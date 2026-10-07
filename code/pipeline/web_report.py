"""Browser report generators (CLAUDE.md section 1 spirit; website.md Stage 1).

PURE PLOTTING / I-O, no physics. Like reporting.py, this module only visualizes
what process_throw.py already wrote to a session directory (session.json,
trajectory.csv, triplets_raw.csv). Every authoritative number -- the landing
(r, theta), (x, z), the sigmas, the 2-D error -- is read VERBATIM from
session.json; nothing is recomputed. The only arithmetic here is display
arithmetic on on-disk values (e.g. the 2-D Euclidean error in mm), exactly the
pattern analyze_campaign already uses.

It is the plotting/I-O member of pipeline/ (NOT one of the pure computational
modules of section 0.5): it reads the session's CSV/JSON and writes report.html
into the session directory.

Self-containment: the generated report.html inlines all data as
window.__DATA__; the static template carries all CSS + JS inline. No CDN, no
runtime fetch of any pipeline file (website.md section 1, section 6.1).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.corrections import echo_us_to_m, speed_of_sound
from pipeline.geometry import recommend_reference_sensors

_ASSETS = Path(__file__).resolve().parent / "web_assets"
_SESSION_TEMPLATE = _ASSETS / "session_report.html"
_CAMPAIGN_TEMPLATE = _ASSETS / "campaign_report.html"
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_MARKER = "<!--__DATA__-->"


# ---------------------------------------------------------------------------
# (v2.4 D5) Session-detection predicate -- the SINGLE separation mechanism.
# A directory is a session iff it contains session.json. This is what makes a
# live campaign builder scanning data/sessions/ skip the demo/ container (it
# holds no top-level session.json) with NO name matching on "demo" or "sim_".
# It supersedes the v2.2 §VV-1 "directories-only" filter (a dir alone no longer
# suffices). Routed through web_report.build_campaign_data,
# analyze_campaign.load_campaign, and the calibrate_bias per-path loader (CLAUDE
# §8.7, §12.2). Home note (D5): it lives here because web_report already owned
# the §VV-1 filter; web_report imports analyze_campaign only lazily
# (_campaign_modules), so scripts/ importing it at module level forms no cycle.
# ---------------------------------------------------------------------------

def is_session_dir(p) -> bool:
    """True iff p is a directory containing a session.json (CLAUDE §8.7, §12.2)."""
    p = Path(p)
    return p.is_dir() and (p / "session.json").exists()


# ---------------------------------------------------------------------------
# Small display helpers (ported from reporting.py; display-only, no physics)
# ---------------------------------------------------------------------------

def _ground_truth(meta: dict):
    """The ENTERED ground-truth block, or None.

    The per-throw input/frozen state keys on the real `ground_truth` block ONLY
    (the surveyed two-tape entry). The simulated `truth.landing` fallback that
    reporting.py / calibrate_bias apply is deliberately NOT used here: it is the
    campaign's error-stat concern (Stage 2, via summary_stats/load_record), and
    treating it as entered ground truth would render every simulated session
    'frozen', so the input form could never appear (website.md sections 5.A/5.B
    define frozen = ground_truth PRESENT, i.e. tapes entered)."""
    gt = meta.get("ground_truth")
    if gt and gt.get("x_m") is not None and gt.get("z_m") is not None:
        return gt
    return None


def _f(v):
    """JSON/JS-safe python float (drops numpy types); None passes through."""
    return None if v is None else float(v)


def _flist(series):
    return [float(v) for v in series]


# ---------------------------------------------------------------------------
# __DATA__ assembly
# ---------------------------------------------------------------------------

def _trajectory_arrays(session_dir: Path, min_fit_points: int):
    """Read trajectory.csv -> dict of display arrays, or None when too short."""
    path = session_dir / "trajectory.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    if len(df) < min_fit_points:
        return None
    t = df["t_sample_s"].to_numpy(dtype=float)
    return {
        "t": _flist(t - t[0]),
        "xr": _flist(df["x_raw_m"]), "yr": _flist(df["y_raw_m"]),
        "zr": _flist(df["z_raw_m"]),
        "xk": _flist(df["x_kalman_m"]), "yk": _flist(df["y_kalman_m"]),
        "zk": _flist(df["z_kalman_m"]),
    }, len(df)


def _range_vs_time(session_dir: Path, meta: dict):
    """Read triplets_raw.csv -> per-sensor range-vs-time arrays (mirrors
    reporting._plot_range_vs_time: range from echo_us, timeouts dropped, the
    in-throw window as a shaded span). Returns None when the file is absent."""
    path = session_dir / "triplets_raw.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    temperature = float(meta["temperature_c"])
    t_us = df["t_sample_us"].to_numpy(dtype=float)
    t0 = (t_us - t_us.min()) * 1e-6
    rng = echo_us_to_m(df["echo_us"].to_numpy(dtype=float), temperature)
    df = df.assign(_t_s=t0, _range_m=rng)

    sensors = []
    for sid in (1, 2, 3):
        sub = df[(df["sensor"] == sid) & np.isfinite(df["_range_m"])]
        sensors.append({
            "sid": sid,
            "t": _flist(sub["_t_s"]),
            "range": _flist(sub["_range_m"]),
            "valid": [int(v) for v in sub["reading_valid"]],
        })
    throw = df[df["in_throw"] == 1]
    window = None
    if not throw.empty:
        window = [float(throw["_t_s"].min()), float(throw["_t_s"].max())]
    return {"sensors": sensors, "window": window}


def _error_mm(pred_block, gt):
    """2-D Euclidean error in mm from on-disk values (display arithmetic)."""
    if gt is None or pred_block is None:
        return None
    if pred_block.get("x_m") is None or pred_block.get("z_m") is None:
        return None
    return 1000.0 * math.hypot(pred_block["x_m"] - gt["x_m"],
                               pred_block["z_m"] - gt["z_m"])


def build_session_data(session_dir: Path, config: dict) -> dict:
    """Assemble the single window.__DATA__ object for one session (no I/O beyond
    reading the session dir; returns a JSON-serializable dict)."""
    session_dir = Path(session_dir)
    with open(session_dir / "session.json", encoding="utf-8") as f:
        meta = json.load(f)

    min_fit = int(config["landing"]["min_fit_points"])
    temperature = _f(meta.get("temperature_c"))
    sound = speed_of_sound(temperature) if temperature is not None else None

    prediction = meta.get("prediction") or {}
    raw = prediction.get("raw")
    corrected = prediction.get("corrected")
    has_landing = bool(raw) and raw.get("x_m") is not None

    traj = _trajectory_arrays(session_dir, min_fit)
    traj_arrays, traj_rows = (traj if traj is not None else (None, 0))

    gt = _ground_truth(meta)
    gate = meta.get("gate_summary") or {}

    # ---- state selection (website.md section 5) ----
    if has_landing and traj_arrays is not None:
        state = "frozen" if gt is not None else "input"
    else:
        state = "failure"

    # detection yield (section 4.1): used / in-window, with the >= min status
    used = gate.get("n_triplets_used")
    in_window = gate.get("n_triplets_in_throw")
    yield_block = None
    if used is not None:
        yield_block = {
            "used": int(used),
            "in_window": None if in_window is None else int(in_window),
            "min_fit_points": min_fit,
            "pass": int(used) >= min_fit,
        }

    # failure-mode empty-state line (section 5.C). N from the best available
    # source; gate_summary/CSVs are absent when process_session raised pre-write.
    failure_used = (int(used) if used is not None
                    else (traj_rows if traj_rows else None))
    failure_message = None
    if state == "failure":
        n_txt = str(failure_used) if failure_used is not None else "Too few"
        failure_message = (
            f"No valid prediction. {n_txt} triplets used (need >= {min_fit} "
            f"for a degree-2 fit). Ground truth cannot be attached to a throw "
            f"without a prediction.")

    array = config["array"]
    # (v2.3 G1) sensor positions for the chips/scope, and the recommended pair
    # nearest the predicted landing -- the two-sensor multilateration references.
    sensors_xz = [{"name": n, "x": _f(array[n + "_xz"][0]),
                   "z": _f(array[n + "_xz"][1])} for n in ("S1", "S2", "S3")]
    recommended = (list(recommend_reference_sensors((raw["x_m"], raw["z_m"]), config))
                   if has_landing else None)

    data = {
        "state": state,
        "session_id": meta.get("session_id", session_dir.name),
        "timestamp": meta.get("timestamp"),               # often absent
        "temperature_c": temperature,
        "sound_speed_m_s": _f(sound),
        "ball_radius_m": _f(config["ball"]["radius_m"]),
        "min_fit_points": min_fit,
        "sensors": sensors_xz,
        "recommended": recommended,
        "residual_warn_m": _f(config["ground_truth"].get("residual_warn_m", 0.05)),
        "geometry": {
            "vertices_xz": [
                [_f(array["S1_xz"][0]), _f(array["S1_xz"][1])],
                [_f(array["S2_xz"][0]), _f(array["S2_xz"][1])],
                [_f(array["S3_xz"][0]), _f(array["S3_xz"][1])],
            ],
            "s_height_m": _f(array.get("S_height_m")),
            "tilt_deg": _f(array.get("tilt_deg")),
        },
        "prediction": {
            "raw": raw if has_landing else None,
            "corrected": corrected,
            "model_id": prediction.get("model_id"),
        },
        "yield": yield_block,
        "stats": {
            "heading_deg": _f(raw.get("heading_deg")) if has_landing else None,
            "v_h_m_s": _f(raw.get("v_h_m_s")) if has_landing else None,
            "temperature_c": temperature,
            "sound_speed_m_s": _f(sound),
            "dof": raw.get("dof") if has_landing else None,
            "n_points": raw.get("n_points") if has_landing else None,
            "malformed": gate.get("malformed_lines"),
        },
        "caveat": meta.get("small_sample_caveat"),
        "trajectory": traj_arrays,
        "range_vs_time": _range_vs_time(session_dir, meta),
        "ground_truth": gt,
        "error_mm": {
            "raw": _error_mm(raw if has_landing else None, gt),
            "corrected": _error_mm(corrected, gt),
        } if gt is not None else None,
        # Relative server endpoints (section 6.2). The input page health-checks
        # /api/health on load and POSTs to /api/ground-truth -- both RELATIVE, so
        # they target the serving origin when a server is up and simply fail
        # (-> "start the server" direction) when opened from file://. No absolute
        # http(s):// URL is ever baked in, so the frozen file stays self-contained.
        "awaiting_ground_truth": state == "input",
        "server": {"health": "/api/health", "ground_truth": "/api/ground-truth",
                   "session_id": meta.get("session_id", session_dir.name)},
        "failure_used": failure_used,
        "failure_message": failure_message,
    }
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _inject(template_path: Path, data: dict) -> str:
    html = template_path.read_text(encoding="utf-8")
    if _MARKER not in html:
        raise ValueError(f"template {template_path} missing {_MARKER} marker")
    blob = json.dumps(data).replace("</", "<\\/")   # safe inside <script>
    script = f"<script>window.__DATA__ = {blob};</script>"
    return html.replace(_MARKER, script)


def render_session_report(session_dir, config) -> Path:
    """Render <session_dir>/report.html (input / frozen / failure) from disk.

    Self-contained: all data inlined as window.__DATA__, all CSS+JS inline in
    the template. Returns the written path. Never recomputes pipeline numbers.
    """
    session_dir = Path(session_dir)
    data = build_session_data(session_dir, config)
    out = session_dir / "report.html"
    out.write_text(_inject(_SESSION_TEMPLATE, data), encoding="utf-8")
    print(f"  web report ({data['state']}): {out.name}")
    return out


# ---------------------------------------------------------------------------
# Campaign dashboard (website.md section 6.5/7/8; Stage 2)
#
# All statistics are REUSED, never recomputed: scripts/analyze_campaign
# (load_campaign + summary_stats), scripts/calibrate_bias (load_record + power_n,
# pulled in transitively), pipeline.bias (evaluate, CorrectionModel). web_report
# lives in pipeline/ but the spec mandates reuse of the scripts/ analysis code;
# the import is lazy + path-injected (mirroring tests/test_analyze_campaign.py)
# so the Stage-1 session renderer never pulls matplotlib.
# ---------------------------------------------------------------------------

def _campaign_modules():
    """Lazily import the (script-level) campaign analysis code + reuse helpers."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import analyze_campaign            # noqa: E402  (scripts/, not a package)
    from pipeline.bias import CorrectionModel, evaluate
    from pipeline.geometry import cart_to_polar
    return analyze_campaign, CorrectionModel, evaluate, cart_to_polar


def _load_correction_model(config, CorrectionModel):
    """Load the existing correction_model.json (display only), or None."""
    mp = Path(config["bias"]["model_path"])
    if not mp.is_file():
        return None
    with open(mp, encoding="utf-8") as f:
        return CorrectionModel.from_dict(json.load(f))


def _mm(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) \
        else float(v) * 1000.0


def build_campaign_data(sessions_root, config) -> dict:
    """Assemble the campaign window.__DATA__ from every ground-truthed throw under
    sessions_root. Numbers come straight from analyze_campaign.summary_stats; this
    function only reshapes and converts to mm for display."""
    analyze_campaign, CorrectionModel, evaluate, cart_to_polar = _campaign_modules()
    sessions_root = Path(sessions_root)

    # (v2.4 D5) Enumerate by the session-detection predicate: a directory is a
    # session iff it holds session.json. This skips our own campaign.html (a
    # file) AND the demo/ container (a dir with no top-level session.json) with
    # no name matching -- the live builder scanning data/sessions/ therefore
    # excludes data/sessions/demo automatically (CLAUDE §8.7, §12.2). Supersedes
    # the §VV-1 directories-only filter.
    session_dirs = []
    for p in sorted(sessions_root.iterdir()):
        if is_session_dir(p):
            session_dirs.append(str(p))
        elif p.is_dir():
            print(f"  skip {p.name}: no session.json")
    throws = analyze_campaign.load_campaign(session_dirs)
    model = _load_correction_model(config, CorrectionModel)
    alpha = config["bias"]["alpha"]
    stats = analyze_campaign.summary_stats(throws, model, alpha)

    # per-throw corrected error (reuse bias.evaluate; never re-derive)
    after = (evaluate(model, [t.to_record() for t in throws])["after"]
             if model is not None and throws else None)

    rows = []
    for i, t in enumerate(throws):
        r, theta = cart_to_polar(t.x_pred, t.z_pred)
        rows.append({
            "session_id": t.session_id,
            "r": _f(r), "theta": _f(theta),
            "x_pred": _f(t.x_pred), "z_pred": _f(t.z_pred),
            "x_actual": _f(t.x_actual), "z_actual": _f(t.z_actual),
            "heading_deg": _f(t.heading_deg),
            "used": t.n_triplets_used,
            "err_raw_mm": _mm(t.error_2d),
            "err_corr_mm": _mm(float(after[i])) if after is not None else None,
        })

    raw_ci = stats["raw_ci_m"]
    corr_present = stats["corrected_mean_m"] is not None
    corr_ci = stats["corrected_ci_m"] if corr_present else (None, None)
    array = config["array"]
    bm = None
    if model is not None:
        bm = {
            "present": True, "mode": model.mode,
            "along_mean_mm": _mm(model.along.mean),
            "along_ci_mm": [_mm(model.along.ci_low), _mm(model.along.ci_high)],
            "significant": bool(model.along.significant),
            "verdict": model.diagnostics.get("verdict", ""),
            "created": model.created,
        }

    return {
        "n": stats["n"],
        "awaiting": stats["n"] == 0,
        "raw": {"mean_mm": _mm(stats["raw_mean_m"]),
                "std_mm": _mm(stats["raw_std_m"]),
                "ci_mm": [_mm(raw_ci[0]), _mm(raw_ci[1])]},
        "corrected": ({"mean_mm": _mm(stats["corrected_mean_m"]),
                       "std_mm": _mm(stats["corrected_std_m"]),
                       "ci_mm": [_mm(corr_ci[0]), _mm(corr_ci[1])]}
                      if corr_present else None),
        "along_bias_mm": _mm(stats["along_bias_m"]),
        "along_scatter_mm": _mm(stats["along_scatter_m"]),
        "mode": stats["mode"],
        "power_note": stats["power_note"],
        "underpowered_null_note": stats["underpowered_null_note"],
        "bias_model": bm if bm is not None else {"present": False},
        "geometry": {"vertices_xz": [
            [_f(array["S1_xz"][0]), _f(array["S1_xz"][1])],
            [_f(array["S2_xz"][0]), _f(array["S2_xz"][1])],
            [_f(array["S3_xz"][0]), _f(array["S3_xz"][1])],
        ]},
        "throws": rows,
    }


def render_campaign_report(sessions_root, config) -> Path:
    """Render <sessions_root>/campaign.html over all sessions. Full overwrite
    every call (never frozen). Returns the written path."""
    sessions_root = Path(sessions_root)
    data = build_campaign_data(sessions_root, config)
    out = sessions_root / "campaign.html"
    out.write_text(_inject(_CAMPAIGN_TEMPLATE, data), encoding="utf-8")
    print(f"  campaign report ({data['n']} throws): {out.name}")
    return out
