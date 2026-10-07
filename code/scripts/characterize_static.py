"""Static target characterization (CLAUDE.md section 7; build item 14).

Wraps run_session.py --raw-log: it reuses the serial-reading machinery
(acquisition.open_serial / serial_byte_lines / raw_capture) and the canonical
parser (process_throw.parse_serial_lines), adding a per-sensor statistics layer.
The operator places ONE stationary target at a tape-measured distance; this tool
collects >= n_readings per sensor and reports mean, sigma, offset, and timeout
fraction. The outputs feed kalman.sigma_pos_m (noise), the per-sensor electronic
offset decision, and simulator.beam_half_angle_deg via analyze_static.py.

TAPE-TO-CENTRE CONVENTION (section 7, R2) — the one place it must be visible:
  --target board : tape reads the board face; reference = tape (no radius).
  --target ball  : tape reads the nearest SURFACE point; reference = tape +
                   ball.radius_m (the centre). Both numbers are printed so the
                   operator can confirm the convention is the right way round —
                   reversing it corrupts every downstream offset.
  For a ball the reported mean and offset are ALSO lifted to the centre (the
  radius is added to every reading, exactly as the pipeline's R2 add_ball_radius
  does before trilateration), so the printed offset is the true electronic bias,
  directly comparable to the board's — not the surface-vs-centre mix (offset low
  by one radius) that a raw surface mean against a centre reference would give.

This produces NUMBERS, not a final answer: run it on hardware (flat board first
to prove the electronics, then the ball at ~1.0/1.3/1.7 m and several --angle-deg
values) and feed the reports to analyze_static.py.

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\characterize_static.py ^
        --target board --reference-m 1.000 --port COM5
    .\\venv\\Scripts\\python.exe scripts\\characterize_static.py ^
        --target ball --reference-m 0.967 --angle-deg 5 --port COM5
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.acquisition import open_serial, raw_capture, serial_byte_lines
from pipeline.corrections import echo_us_to_m
from pipeline.process_throw import parse_serial_lines


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def centre_reference_m(target: str, raw_tape_m: float, radius_m: float) -> float:
    """(section 7, R2) The tape-to-centre convention, in ONE place.

    board: the tape already reads the reflecting face -> reference = tape.
    ball : the tape reads the nearest surface point -> reference = tape + radius
           (the sensor ranges to the surface; the centre is one radius further).
    """
    if target == "ball":
        return raw_tape_m + radius_m
    return raw_tape_m


class _Collector:
    """Accumulate per-sensor echo_us from raw lines (reuses parse_serial_lines)."""

    def __init__(self):
        self.echoes = {1: [], 2: [], 3: []}

    def feed(self, line: str) -> None:
        _, rows, _ = parse_serial_lines([line])      # header/garbage -> no rows
        for sid, echo, _t in rows:
            self.echoes[sid].append(echo)

    def min_count(self) -> int:
        return min(len(v) for v in self.echoes.values())


def _sensor_stats(echoes, temperature_c: float, reference_m: float,
                  radius_correction_m: float = 0.0) -> dict:
    """Per-sensor mean/sigma/offset/timeout in the distance domain (NaN-safe).

    radius_correction_m (R2) is added to every reading so a ball's mean/offset are
    reported at the ball CENTRE, matching the centre reference (the pipeline applies
    the same add_ball_radius before trilateration). It is 0 for a board (the tape
    already reads the reflecting face). sigma is a pure constant shift, so it is
    unchanged by the correction.
    """
    echo = np.asarray(echoes, dtype=float)
    n = int(echo.size)
    n_timeout = int(np.count_nonzero(echo == 0))
    timeout_fraction = (n_timeout / n) if n else float("nan")
    d = echo_us_to_m(echo, temperature_c) + radius_correction_m  # surface->centre; timeout 0 -> NaN
    finite = d[np.isfinite(d)]
    mean = float(np.mean(finite)) if finite.size >= 1 else float("nan")
    sigma = float(np.std(finite, ddof=1)) if finite.size >= 2 else float("nan")
    offset = (mean - reference_m) if np.isfinite(mean) else float("nan")
    return {"n": n, "n_timeout": n_timeout, "timeout_fraction": timeout_fraction,
            "mean_m": mean, "sigma_m": sigma, "offset_m": offset}


def _json_safe(x):
    """NaN -> None so the report is valid JSON (json allows NaN, readers may not)."""
    return None if (isinstance(x, float) and not np.isfinite(x)) else x


def characterize_core(byte_lines, log_fh, *, target, raw_tape_m, radius_m,
                      temperature_c, n_readings, angle_off_axis_deg=None) -> dict:
    """Collect >= n_readings per sensor off a raw-line stream and report stats.

    Injectable byte_lines + log handle make this callable without hardware. The
    capture stops once every sensor has n_readings (even an all-timeout sensor
    still counts readings), or when the source is exhausted.
    """
    reference = centre_reference_m(target, raw_tape_m, radius_m)
    # (R2) ball ranges point at the surface; lift mean/offset to the CENTRE so they
    # match the centre reference. Board tape already reads the face -> no correction.
    radius_correction = radius_m if target == "ball" else 0.0
    collector = _Collector()
    raw_capture(byte_lines, log_fh, on_line=collector.feed,
                stop=lambda: collector.min_count() >= n_readings)

    sensors = {str(sid): _sensor_stats(collector.echoes[sid], temperature_c,
                                       reference, radius_correction)
               for sid in (1, 2, 3)}
    return {
        "kind": "static_characterization",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "raw_tape_m": raw_tape_m,
        "centre_reference_m": reference,
        "ball_radius_m": radius_m if target == "ball" else None,
        "temperature_c": temperature_c,
        "angle_off_axis_deg": angle_off_axis_deg,
        "n_readings_target": n_readings,
        "sensors": sensors,
    }


def _report_to_json(report: dict) -> dict:
    out = {k: v for k, v in report.items() if k != "sensors"}
    out["sensors"] = {sid: {k: _json_safe(v) for k, v in s.items()}
                      for sid, s in report["sensors"].items()}
    return out


def print_report(report: dict) -> None:
    print(f"\ntarget={report['target']}  tape={report['raw_tape_m']:.4f} m  "
          f"centre_reference={report['centre_reference_m']:.4f} m  "
          f"T={report['temperature_c']} C  "
          f"angle={report['angle_off_axis_deg']}")
    print(f"{'sensor':>6} {'n':>5} {'timeout%':>9} {'mean [m]':>10} "
          f"{'sigma [mm]':>11} {'offset [mm]':>12}")
    for sid in ("1", "2", "3"):
        s = report["sensors"][sid]
        mean = "   nan" if not np.isfinite(s["mean_m"]) else f"{s['mean_m']:.4f}"
        sigma = "  nan" if not np.isfinite(s["sigma_m"]) else f"{s['sigma_m'] * 1e3:.2f}"
        off = "   nan" if not np.isfinite(s["offset_m"]) else f"{s['offset_m'] * 1e3:+.2f}"
        print(f"{'S' + sid:>6} {s['n']:>5} {s['timeout_fraction'] * 100:>8.1f}% "
              f"{mean:>10} {sigma:>11} {off:>12}")


def static_session_dir(out_dir: Path, when: datetime.datetime) -> Path:
    folder = Path(out_dir) / f"{when.strftime('%Y-%m-%d_%H%M%S')}_static"
    if folder.exists():
        raise RuntimeError(f"session directory already exists: {folder}")
    folder.mkdir(parents=True)
    return folder


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", choices=["board", "ball"], required=True)
    p.add_argument("--reference-m", type=float, required=True,
                   help="tape distance [m]: to the board FACE, or to the ball SURFACE")
    p.add_argument("--n-readings", type=int, default=200,
                   help="readings to collect PER SENSOR (default 200)")
    p.add_argument("--temperature-c", type=float, default=20.0)
    p.add_argument("--angle-deg", type=float, default=None,
                   help="target angle off the sensor aim axis [deg] (beam sweep)")
    p.add_argument("--ball-radius-m", type=float, default=None,
                   help="override ball.radius_m [m] for a pending-approval target "
                        "substitution (e.g. a football) WITHOUT editing the committed "
                        "physics value; ignored for --target board (A5, section 11)")
    p.add_argument("--port", default=None,
                   help="serial port (default: acquisition.port from config)")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--out-dir", type=Path, default=Path("data") / "sessions")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    # A CLI override lets a pending-approval bench target (e.g. a football) be
    # characterized without mutating the committed ball.radius_m (which would break
    # the section-9 acceptance gate). Config value is the default.
    radius = args.ball_radius_m if args.ball_radius_m is not None \
        else config["ball"]["radius_m"]
    if args.ball_radius_m is not None:
        print(f"NOTE: ball radius overridden to {radius:.4f} m via --ball-radius-m "
              f"(config value {config['ball']['radius_m']:.4f} m unchanged)")

    # Make the tape-to-centre convention visible BEFORE collecting (section 7).
    ref = centre_reference_m(args.target, args.reference_m, radius)
    if args.target == "ball":
        print(f"ball: tape-to-surface {args.reference_m:.4f} m + radius "
              f"{radius:.4f} m = centre reference {ref:.4f} m")
    else:
        print(f"board: tape-to-face {args.reference_m:.4f} m = reference {ref:.4f} m")

    session_dir = static_session_dir(args.out_dir, datetime.datetime.now())
    log_path = session_dir / "raw_serial.log"
    print(f"session: {session_dir}")
    print(f"collecting >= {args.n_readings} readings/sensor; Ctrl-C to stop early")

    ser = open_serial(config, args.port)
    try:
        with open(log_path, "wb") as log_fh:
            report = characterize_core(
                serial_byte_lines(ser), log_fh,
                target=args.target, raw_tape_m=args.reference_m, radius_m=radius,
                temperature_c=args.temperature_c, n_readings=args.n_readings,
                angle_off_axis_deg=args.angle_deg)
    finally:
        ser.close()

    with open(session_dir / "static_report.json", "w", newline="",
              encoding="utf-8") as f:
        json.dump(_report_to_json(report), f, indent=2)
    print_report(report)
    print(f"\nwrote {session_dir / 'static_report.json'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted - raw_serial.log was flushed; exiting cleanly")
