"""The live one-throw session program (CLAUDE.md sections 5.5, 5.7; build item 13).

One session = one throw (section 0.3). This script is GLUE: it captures the live
serial stream, runs background calibration, drives the throw with
segmentation.ThrowDetector, and then hands ALL post-CLOSING work
(corrections -> trilateration -> Kalman -> landing -> optional bias) to
process_throw.process_session. None of that chain is re-implemented here.

Modes (section 5.7):
  default            full one-throw session: temperature prompt -> background cal
                     -> detect throw -> process_session -> report (r, theta,
                     sigma_r, sigma_theta) -> ground-truth protocol -> write outputs.
  --raw-log          no state machine, no gating: stream + log raw lines until
                     Ctrl-C (what characterize_static.py will wrap).
  --background-only  background cal only: print + persist background.json, predict
                     the A2 ceiling wrap-around ghost when ceiling_height_m is set.
  --no-correction    force raw-only output (skip loading the bias model).
  --no-offset-correction
                     disable the acquisition-layer per-sensor electronic-offset
                     subtraction (config acquisition.sensor_offset_m; on by default).
  --no-background    skip the ~11 s background calibration (open-ground use; all
                     bands disabled, gate on d_max + timeout only).

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\run_session.py --port COM5
"""

import argparse
import datetime
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import acquisition, reporting
from pipeline.web_report import render_campaign_report, render_session_report
from pipeline.background import (
    calibrate_background,
    ceiling_ghost_apparent_range,
    disabled_background,
    sanity_warnings,
    triplet_valid,
)
from pipeline.bias import CorrectionModel
from pipeline.corrections import echo_us_to_m
from pipeline.geometry import (
    ArrayGeometry,
    ground_truth_landing,
    recommend_reference_sensors,
)
from pipeline.process_throw import process_session
from pipeline.segmentation import ACTIVE, CLOSED, ThrowDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def expected_header(config: dict) -> str:
    acq = config["acquisition"]
    return f"slot_ms={acq['slot_ms']},timeout_us={acq['pulse_timeout_us']}"


def next_session_dir(out_dir: Path, when: datetime.datetime) -> Path:
    """Create data/sessions/<YYYY-MM-DD>_T## (next free counter; never overwrite)."""
    out_dir = Path(out_dir)
    date = when.strftime("%Y-%m-%d")
    for i in range(1, 100):
        cand = out_dir / f"{date}_T{i:02d}"
        if not cand.exists():
            cand.mkdir(parents=True)
            return cand
    raise RuntimeError(f"more than 99 sessions for {date}; clean up data/sessions")


def _write_json(path: Path, obj: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _read_log_header(log_path: Path) -> str | None:
    raw = log_path.read_bytes().decode("ascii", errors="replace")
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#") and "fw=" in s:
            return s
    return None


def _calibrate_background_phase(triplets, n_bg: int, temperature_c: float,
                                gates: dict):
    """Pull up to n_bg triplets off the live stream and characterize the room.

    Reuses pipeline.background.calibrate_background — no gate logic here.
    """
    bg_echoes = []
    for trip in triplets:
        bg_echoes.append(trip.echo_us)
        if len(bg_echoes) >= n_bg:
            break
    if not bg_echoes:
        raise ValueError("no triplets received during background calibration")
    d_bg = echo_us_to_m(np.array(bg_echoes), temperature_c)
    return calibrate_background(d_bg, gates), len(bg_echoes)


def maybe_load_model(config: dict):
    path = Path(config["bias"]["model_path"])
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        model = CorrectionModel.from_dict(json.load(f))
    print(f"loaded bias correction model (mode={model.mode})")
    return model


# ---------------------------------------------------------------------------
# Core: capture one throw, then delegate processing (testable, no prompts/serial)
# ---------------------------------------------------------------------------

def capture_session(session_dir, config, byte_lines, temperature_c, *, model=None,
                    apply_offset=True, skip_background=False):
    """Capture a live throw into session_dir and process it via process_session.

    Injectable `byte_lines` (an iterable of raw byte-lines) and explicit
    temperature make this callable without hardware or prompts — the live path
    and the offline path therefore share the SAME processing code, which the
    acquisition test asserts.

    apply_offset (Phase 5, S4D) enables the per-sensor electronic-offset
    correction (config acquisition.sensor_offset_m); True by default for real
    hardware, disabled by --no-offset-correction.

    skip_background (--no-background) skips the ~11 s background calibration and
    uses a disabled-band background instead (open-ground use, no static reflector
    to subtract). Every non-timeout echo within d_max is treated as signal, and
    the throw is detected from the very first triplets. The disabled background is
    still persisted so process_session gates identically offline.

    Returns the ProcessedSession from process_throw.process_session.
    """
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    gates = config["gates"]
    log_path = session_dir / "raw_serial.log"
    meta_path = session_dir / "session.json"

    # Raw data is sacred (section 0.4): refuse to capture into a directory that
    # already holds a raw_serial.log rather than silently clobber a recorded
    # session. Mirrors simulate_session.create_session_folder's refusal. Placed
    # before the session.json write so an existing session's metadata is safe too.
    if log_path.exists():
        raise RuntimeError(
            f"session directory already has raw_serial.log: {session_dir} "
            "-- refusing to overwrite recorded session data (section 0.4)")

    # session.json exists from the start (temperature is all process_session
    # needs); so a Ctrl-C mid-throw still leaves a reprocessable session dir.
    _write_json(meta_path, {
        "session_id": session_dir.name,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "temperature_c": temperature_c,
    })

    def warn(msg):
        print(f"  ! {msg}")

    # Verbatim raw_serial.log is flushed per line and closed by the with-block,
    # so the capture survives a Ctrl-C at any point (section 0.4, 5.5).
    with open(log_path, "wb") as log_fh:
        triplets = acquisition.stream_triplets(
            byte_lines, log_fh, expected_header=expected_header(config), warn=warn)

        # ---- background calibration (section 5.3) ----
        if skip_background:
            # Open-ground use: no static reflector to subtract, so skip the ~11 s
            # calibration and gate on d_max + timeout only (all bands disabled).
            bg = disabled_background(gates)
            _write_json(session_dir / "background.json", bg.to_dict())
            print("background calibration SKIPPED (--no-background): all bands "
                  "disabled; every non-timeout echo within "
                  f"{gates['d_max_m']} m treated as signal")
        else:
            bg, n_used = _calibrate_background_phase(
                triplets, gates["bg_n_triplets"], temperature_c, gates)
            _write_json(session_dir / "background.json", bg.to_dict())
            for w in sanity_warnings(bg):
                print(w)
            print(f"background calibrated over {n_used} triplets; "
                  f"bands enabled per sensor: {[s.enabled for s in bg.sensors]}")

        # ---- throw detection (section 5.5): ThrowDetector is the stop-trigger;
        #      process_session re-segments authoritatively offline ----
        det = ThrowDetector(gates["arm_M"], gates["close_K"])
        announced = False
        for trip in triplets:
            d = echo_us_to_m(trip.echo_us.reshape(1, 3), temperature_c)
            valid = bool(triplet_valid(d, bg)[0])
            state = det.update(valid)
            if state == ACTIVE and not announced:
                print("THROW DETECTED")
                announced = True
            if state == CLOSED:
                break

    # record the firmware header (best-effort metadata), then delegate.
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fw_header"] = _read_log_header(log_path)
    _write_json(meta_path, meta)

    return process_session(session_dir, config, model=model, apply_offset=apply_offset)


# ---------------------------------------------------------------------------
# Reporting + ground truth (interactive; default mode only)
# ---------------------------------------------------------------------------

def print_prediction(result) -> None:
    raw = result.prediction["raw"]
    print(f"\nr = {raw['r_m']:.3f} m, theta = {raw['theta_deg']:.1f} deg, "
          f"sigma_r = {raw['sigma_r_m']:.3f} m, "
          f"sigma_theta = {raw['sigma_theta_deg']:.1f} deg")
    corrected = result.prediction.get("corrected")
    if corrected:
        r = corrected.get("r_m")
        if r is not None:
            print(f"corrected: r = {r:.3f} m, "
                  f"theta = {corrected.get('theta_deg', float('nan')):.1f} deg")
        else:
            print(f"corrected: {corrected}")
    if result.caveat:
        print(result.caveat)


_SENSOR_INDEX = {"S1": 0, "S2": 1, "S3": 2}


def _parse_sensor_pair(text: str):
    """Parse an override like 'S2 S3' / 's2,s3' -> ('S2','S3'), or None if it is
    not exactly two distinct sensors of {S1,S2,S3}."""
    parts = [p.strip().upper() for p in text.replace(",", " ").split()]
    if len(parts) != 2 or parts[0] == parts[1]:
        return None
    if any(p not in _SENSOR_INDEX for p in parts):
        return None
    return parts[0], parts[1]


def solve_ground_truth(L_centroid: float, refs, config: dict) -> dict:
    """(section 6.3, v2.3 G1) The PURE multilateration solve (no input()):
    centroid + two chosen sensors -> ground_truth block. `refs` is a list of two
    {"name", "L"} dicts; sensor positions are resolved from config.array.*_xz.
    Unique (no mirror), so there is no pred_z / pick. Shared by the terminal
    prompt, append_ground_truth, and the web POST handler so they cannot diverge.
    """
    geom = ArrayGeometry.from_config(config)
    geom_refs = [{"name": r["name"],
                  "pos": geom.vertices_xz[_SENSOR_INDEX[r["name"]]],
                  "L": float(r["L"])} for r in refs]
    gt = ground_truth_landing(float(L_centroid), geom_refs, config)
    return {
        "x_m": gt["x"], "z_m": gt["z"], "r_m": gt["r"], "theta_deg": gt["theta_deg"],
        "sigma_x_m": gt["sigma_x"], "sigma_z_m": gt["sigma_z"],
        "cov_xz_m2": gt["cov_xz"].tolist(),
        "L_centroid_m": float(L_centroid),
        "references": [{"name": r["name"], "L_m": float(r["L"])} for r in refs],
        "sensors_used": [r["name"] for r in refs],
        "sigma_tape_m": config["ground_truth"]["sigma_tape_m"],
        "ls_residual_m": gt["ls_residual_m"],
        "cond_number": gt["cond_number"],
        "cond_warn": gt["cond_warn"],
    }


def prompt_ground_truth(config: dict, result) -> dict | None:
    """Centroid + 2-recommended-sensor multilateration (section 5.5, v2.3 G1).
    The pipeline recommends the two sensors nearest the predicted landing; the
    operator accepts (Enter) or overrides; tapes to centroid + the two sensors are
    measured; the solve is via solve_ground_truth (unique, no mirror prompt).
    Empty input at L_centroid skips (GT addable later)."""
    raw = result.prediction["raw"]
    rec = recommend_reference_sensors((raw["x_m"], raw["z_m"]), config)
    try:
        ans = input(f"recommend references: centroid + {rec[0]}, {rec[1]} "
                    "(nearest to predicted landing). accept [Enter] / "
                    "override [pick two of S1 S2 S3]: ").strip()
    except EOFError:
        print("  ground truth skipped (no input)")
        return None
    if not ans:
        names = list(rec)
    else:
        names = _parse_sensor_pair(ans)
        if names is None:
            print("  ground truth skipped (need exactly two distinct of S1 S2 S3)")
            return None

    try:
        lc = input("L_centroid [m]: ").strip()
        if not lc:
            return None
        la = input(f"L_{names[0]} [m]: ").strip()
        if not la:
            return None
        lb = input(f"L_{names[1]} [m]: ").strip()
        if not lb:
            return None
        L_centroid, L_a, L_b = float(lc), float(la), float(lb)
    except (EOFError, ValueError):
        print("  ground truth skipped (no/invalid input)")
        return None

    refs = [{"name": names[0], "L": L_a}, {"name": names[1], "L": L_b}]
    try:
        block = solve_ground_truth(L_centroid, refs, config)
    except ValueError as exc:
        print(f"  ground truth skipped: {exc}")
        return None

    print(f"  ground truth: r = {block['r_m']:.3f} m, "
          f"theta = {block['theta_deg']:.1f} deg, "
          f"sensors {','.join(block['sensors_used'])}")
    if block["cond_warn"] or block["ls_residual_m"] > \
            config["ground_truth"].get("residual_warn_m", 0.05):
        print(f"  ! integrity warning: residual "
              f"{block['ls_residual_m'] * 1000:.1f} mm, "
              f"cond {block['cond_number']:.1f}")
    return block


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _capture_default(config: dict, args):
    """Temperature prompt -> live capture -> process -> print. Shared by the
    terminal (run_default) and browser (run_web) flows; returns
    (session_dir, ProcessedSession)."""
    temperature_c = float(input("Ambient temperature [C]: "))
    model = None if args.no_correction else maybe_load_model(config)
    session_dir = next_session_dir(args.out_dir, datetime.datetime.now())
    print(f"session: {session_dir}")

    ser = acquisition.open_serial(config, args.port)
    result = None
    try:
        result = capture_session(session_dir, config,
                                 acquisition.serial_byte_lines(ser),
                                 temperature_c, model=model,
                                 apply_offset=not args.no_offset_correction,
                                 skip_background=args.no_background)
    except ValueError as exc:
        # (M-4) Expected "no prediction" outcomes -- no throw, < min_fit_points,
        # or a non-concave fit -- are reported cleanly, not as a traceback. The
        # session dir already holds raw_serial.log + (for a fit-stage failure)
        # triplets_raw.csv + the gate summary, so the caller can still render the
        # failure-mode report. (RuntimeError from the overwrite guard is NOT
        # caught here -- that refusal stays loud.)
        print(f"\nno prediction: {exc}")
    finally:
        ser.close()

    if result is not None:
        print_prediction(result)
    return session_dir, result


def _render_failure(session_dir, config, args) -> None:
    """(M-4) A session with no usable prediction: render the failure-mode report
    (still shows the range-vs-time panel from the persisted triplets_raw.csv) and
    refresh the campaign. No ground-truth step -- there is no prediction to attach
    a mark to (section 12.1)."""
    render_session_report(session_dir, config)
    render_campaign_report(args.out_dir, config)
    print(f"\nwrote {session_dir} (no prediction)")


def run_default(config: dict, args) -> None:
    session_dir, result = _capture_default(config, args)
    if result is None:
        _render_failure(session_dir, config, args)
        return

    gt = prompt_ground_truth(config, result)
    if gt is not None:
        # Atomic writer, shared with serve_report's POST and append_ground_truth
        # (temp + fsync + os.replace, writes only the ground_truth key). Lazy
        # import: append_ground_truth imports run_session at module top, so a
        # top-level import here would cycle (same reason web_finalize imports
        # serve_report lazily).
        from append_ground_truth import update_session_ground_truth
        update_session_ground_truth(session_dir / "session.json", gt)

    if args.plot:
        for p in reporting.plot_session(session_dir, config):
            print(f"  plot: {p}")

    # Terminal-mode rendering (M-3): the same pages the --web flow produces.
    # Renderers are full-overwrite + import-safe; report.html reflects the GT
    # just written, and the live campaign is regenerated (the demo/ subtree is
    # excluded by the is_session_dir predicate).
    render_session_report(session_dir, config)
    render_campaign_report(args.out_dir, config)
    print(f"\nwrote {session_dir}")


def _wait_console_or_post(httpd, url) -> None:
    """Block with NO timeout until the operator enters ground truth in the browser
    (a successful POST sets httpd.gt_event) OR types anything at the console
    (= skip). The stdin reader is a daemon thread so it dies at process exit."""
    skip = threading.Event()

    def reader():
        try:
            input()                    # any line (incl. empty) means "skip"
        except (EOFError, KeyboardInterrupt):
            pass
        skip.set()

    threading.Thread(target=reader, daemon=True).start()
    while not httpd.gt_event.is_set() and not skip.is_set():
        time.sleep(0.1)


def web_finalize(session_dir, config, out_dir, *, open_browser=True,
                 wait_for_entry=None):
    """(section 6.4) Browser ground-truth loop for an already-processed session.

    Renders the input report + campaign, starts the REUSED serve_report server,
    opens the browser, then blocks (no timeout) until a GT POST arrives or the
    operator skips. The server is always torn down in `finally`, so a Ctrl-C
    propagates cleanly (matching the terminal guarantee) while still stopping the
    server. wait_for_entry is the injectable seam for headless tests.
    """
    import serve_report                 # lazy: serve_report imports run_session

    session_dir = Path(session_dir)
    render_session_report(session_dir, config)          # input mode
    render_campaign_report(out_dir, config)
    httpd, thread, url = serve_report.start_background(
        out_dir, config, session_dir.name)
    try:
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:                            # noqa: BLE001 (headless ok)
                pass
        print(f"\nEnter ground truth in the browser: {url}")
        print("  (or press Enter / type 'skip' here to finalise without it; "
              "you can add it later with serve_report.py --session "
              f"{session_dir.name})")
        (wait_for_entry or _wait_console_or_post)(httpd, url)
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
    render_campaign_report(out_dir, config)              # reflect any entered GT
    return session_dir


def run_web(config: dict, args) -> None:
    session_dir, result = _capture_default(config, args)
    if result is None:
        _render_failure(session_dir, config, args)
        return
    web_finalize(session_dir, config, args.out_dir)
    if args.plot:
        for p in reporting.plot_session(session_dir, config):
            print(f"  plot: {p}")
    print(f"\nwrote {session_dir}")


def run_raw_log(config: dict, args) -> None:
    session_dir = next_session_dir(args.out_dir, datetime.datetime.now())
    log_path = session_dir / "raw_serial.log"
    print(f"--raw-log: streaming to {log_path}; Ctrl-C to stop")
    ser = acquisition.open_serial(config, args.port)
    try:
        with open(log_path, "wb") as log_fh:
            acquisition.raw_capture(acquisition.serial_byte_lines(ser), log_fh,
                                    on_line=print)
    finally:
        ser.close()


def run_background_only(config: dict, args) -> None:
    temperature_c = float(input("Ambient temperature [C]: "))
    gates = config["gates"]
    session_dir = next_session_dir(args.out_dir, datetime.datetime.now())
    log_path = session_dir / "raw_serial.log"

    def warn(msg):
        print(f"  ! {msg}")

    ser = acquisition.open_serial(config, args.port)
    try:
        with open(log_path, "wb") as log_fh:
            triplets = acquisition.stream_triplets(
                acquisition.serial_byte_lines(ser), log_fh,
                expected_header=expected_header(config), warn=warn)
            bg, n_used = _calibrate_background_phase(
                triplets, gates["bg_n_triplets"], temperature_c, gates)
    finally:
        ser.close()

    _write_json(session_dir / "background.json", bg.to_dict())
    _write_json(session_dir / "session.json", {
        "session_id": session_dir.name,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "temperature_c": temperature_c,
        "fw_header": _read_log_header(log_path),
        "background_only": True,
    })

    print(f"\nbackground over {n_used} triplets:")
    for i, s in enumerate(bg.sensors):
        print(f"  S{i + 1}: f0={s.f0:.3f} n_valid={s.n_valid} "
              f"mu={s.mu:.3f} sigma={s.sigma:.4f} w={s.w:.4f} enabled={s.enabled}")
    for w in sanity_warnings(bg):
        print(w)

    ghost = ceiling_ghost_apparent_range(config, temperature_c)
    if ghost is not None:
        flag = " <-- INSIDE BALL GATE WINDOW" if ghost["inside_gate_window"] else ""
        print(f"\nA2 ceiling wrap-around ghost: slant={ghost['slant_m']:.3f} m, "
              f"apparent={ghost['apparent_m']:.3f} m{flag}")
        if ghost["inside_gate_window"]:
            print("  the static ghost lands inside [0.5, d_max]; confirm the band "
                  "rule subtracts it, or reposition/tilt the array.")
    print(f"\nwrote {session_dir}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default=None,
                   help="serial port (default: acquisition.port from config)")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--out-dir", type=Path, default=Path("data") / "sessions")
    p.add_argument("--no-correction", action="store_true",
                   help="report raw landing only; do not load the bias model")
    p.add_argument("--no-offset-correction", action="store_true",
                   help="disable the acquisition-layer per-sensor electronic-offset "
                        "subtraction (config acquisition.sensor_offset_m); applied by "
                        "default. Use to see the uncorrected landing (Phase 5, S4D)")
    p.add_argument("--no-background", action="store_true",
                   help="skip the ~11 s background calibration and gate on d_max + "
                        "timeout only (all bands disabled). For open ground with no "
                        "static reflector to subtract; the throw is detected from the "
                        "first triplets")
    p.add_argument("--plot", action="store_true",
                   help="write per-throw diagnostic plots into the session's plots/")
    web = p.add_mutually_exclusive_group()
    web.add_argument("--web", action="store_true",
                     help="enter ground truth in a browser via the local report "
                          "server (default mode only)")
    web.add_argument("--no-web", action="store_true",
                     help="use the terminal ground-truth prompt (the default)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--raw-log", action="store_true",
                      help="stream + log raw lines until Ctrl-C (no gating)")
    mode.add_argument("--background-only", action="store_true",
                      help="background calibration only; persist + exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.raw_log:
        run_raw_log(config, args)
    elif args.background_only:
        run_background_only(config, args)
    elif args.web:
        run_web(config, args)
    else:
        run_default(config, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted — raw_serial.log was flushed; exiting cleanly")
