"""Offline processing orchestrator: one session directory -> landing prediction.

This is the "same code path as post-CLOSING in run_session.py" that section 9
refers to: parse raw_serial.log -> background calibration -> validity gate ->
one-throw segmentation -> corrections -> trilateration -> Kalman -> landing ->
optional bias correction -> session-folder outputs (sections 5.4-5.6).

Deliberate deviation from the pipeline/ no-I/O rule, stated openly: this
module reads and writes the SESSION DIRECTORY (that is its job — both the
section 9 acceptance test and run_session.py call process_session). It
contains no serial-port code; the live reader (Step 9 acquisition.py) reuses
the pure parsing helpers below on the byte stream it captures.

Raw data is sacred (section 0.4): raw_serial.log is read, never modified;
gating writes flags, never deletes rows.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipeline.background import (
    BackgroundModel,
    calibrate_background,
    reading_valid as bg_reading_valid,
    sanity_warnings,
)
from pipeline.bias import CorrectionModel, apply_correction
from pipeline.corrections import (
    add_ball_radius,
    apply_sensor_offset,
    echo_us_to_m,
    mid_echo_sample_time_us,
    temporal_correction,
)
from pipeline.geometry import ArrayGeometry
from pipeline.kalman import filter_trajectory
from pipeline.landing import predict_landing
from pipeline.segmentation import segment_throw
from pipeline.trilateration import trilaterate

MICROS_ROLLOVER = 2**32   # Arduino micros() wraps every ~71.6 min (R10c)

NEGATIVE_CONTROLS = (None, "ball_radius", "mid_echo", "sensor_height")


# ---------------------------------------------------------------------------
# Pure parsing helpers (section 5.1; reused by the live acquisition layer)
# ---------------------------------------------------------------------------

def parse_serial_lines(lines):
    """Parse decoded serial lines -> (header|None, (n,3) int rows, n_malformed).

    Rows are (sensor_id, echo_us, t_trig_us). Comment lines (#...) beyond the
    first header and malformed lines are counted, never fatal.
    """
    header = None
    rows, malformed = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if header is None and "fw=" in line:
                header = line
            continue
        parts = line.split(",")
        try:
            sid, echo, t = int(parts[0]), int(parts[1]), int(parts[2])
            if len(parts) != 3 or sid not in (1, 2, 3) or echo < 0 or t < 0:
                raise ValueError
        except (ValueError, IndexError):
            malformed += 1
            continue
        rows.append((sid, echo, t))
    return header, rows, malformed


def unwrap_micros(t_us):
    """Unwrap the 2^32-us micros() rollover: t[n] < t[n-1] -> add 2^32 (R10c)."""
    t = np.asarray(t_us, dtype=np.int64)
    wraps = np.cumsum(np.diff(t, prepend=t[:1]) < 0)
    return t + wraps * MICROS_ROLLOVER


def assemble_triplets(rows):
    """Assemble S1->S2->S3 triplets keyed on each S1 reading (section 5.1).

    rows: (sensor_id, echo_us, t_trig_us_unwrapped). Order violation makes
    the triplet malformed; resynchronize on the next S1. Returns
    (echo (N,3), t_trig (N,3), n_dropped_readings).
    """
    echo, t_trig, dropped = [], [], 0
    i, n = 0, len(rows)
    while i < n:
        if rows[i][0] != 1:
            dropped += 1
            i += 1
            continue
        if i + 2 < n and rows[i + 1][0] == 2 and rows[i + 2][0] == 3:
            echo.append([rows[i][1], rows[i + 1][1], rows[i + 2][1]])
            t_trig.append([rows[i][2], rows[i + 1][2], rows[i + 2][2]])
            i += 3
        else:                       # order violation: drop the S1, resync
            dropped += 1
            i += 1
    return (np.array(echo, dtype=np.int64).reshape(-1, 3),
            np.array(t_trig, dtype=np.int64).reshape(-1, 3), dropped)


# ---------------------------------------------------------------------------
# Session processing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcessedSession:
    prediction: dict          # raw (+ corrected when a model is applied)
    gate_summary: dict
    warnings: list
    caveat: str


def _write_triplets_csv(path, echo, t_trig, t_sample, d_centre, r_valid,
                        t_valid, in_throw):
    with open(path, "w", newline="", encoding="utf-8") as f:    # W2
        wr = csv.writer(f)
        wr.writerow(["triplet", "sensor", "echo_us", "t_trig_us", "t_sample_us",
                     "d_centre_m", "reading_valid", "triplet_valid", "in_throw"])
        for nrow in range(len(echo)):
            for s in range(3):
                wr.writerow([nrow, s + 1, int(echo[nrow, s]),
                             int(t_trig[nrow, s]), f"{t_sample[nrow, s]:.1f}",
                             "" if np.isnan(d_centre[nrow, s])
                             else f"{d_centre[nrow, s]:.6f}",
                             int(r_valid[nrow, s]), int(t_valid[nrow]),
                             int(in_throw[nrow])])


def _write_trajectory_csv(path, t_s, xyz_raw, filt, sigma_y, q):
    with open(path, "w", newline="", encoding="utf-8") as f:    # W2
        wr = csv.writer(f)
        wr.writerow(["t_sample_s", "x_raw_m", "y_raw_m", "z_raw_m",
                     "x_kalman_m", "y_kalman_m", "z_kalman_m",
                     "sigma_y_m", "height_consistency_q_m"])
        for k in range(len(t_s)):
            wr.writerow([f"{t_s[k]:.6f}",
                         *(f"{v:.6f}" for v in xyz_raw[k]),
                         *(f"{v:.6f}" for v in filt.pos[k]),
                         f"{sigma_y[k]:.6f}", f"{q[k]:.2e}"])


def process_session(session_dir: Path, config: dict, *,
                    model: CorrectionModel | None = None,
                    apply_offset: bool = False,
                    _negative_control: str | None = None) -> ProcessedSession:
    """Run the full offline pipeline over one recorded session directory.

    apply_offset (Phase 5, CLAUDE.md S4D) enables the acquisition-layer per-sensor
    electronic-offset subtraction from config['acquisition']['sensor_offset_m'].
    It defaults to False so synthetic callers (the section-9 acceptance gate,
    simulator-written sessions) are unaffected — synthetic data carries no
    electronic offset. run_session.py enables it by DEFAULT for real hardware
    (disable with --no-offset-correction). The correction touches only the
    distances that feed trilateration; the background gate uses raw distances (a
    constant per-sensor shift cancels in the band rule, so gating is unchanged).

    _negative_control is a TEST-ONLY hook for the section 9 acceptance gate:
    'ball_radius' skips R2, 'mid_echo' uses t_trig instead of t_sample (R3),
    'sensor_height' forces S_height_m = 0 (R4). Never set in production.
    """
    if _negative_control not in NEGATIVE_CONTROLS:
        raise ValueError(f"unknown negative control {_negative_control!r}")
    session_dir = Path(session_dir)
    warnings = []

    # ---- session metadata (temperature is per-session, section 5.2) ----
    with open(session_dir / "session.json", encoding="utf-8") as f:
        meta = json.load(f)
    t_celsius = meta["temperature_c"]

    # ---- raw bytes -> triplets (section 5.1) ----
    raw = (session_dir / "raw_serial.log").read_bytes()
    lines = raw.decode("ascii", errors="replace").splitlines()
    header, rows, malformed = parse_serial_lines(lines)
    acq = config["acquisition"]
    expected = f"slot_ms={acq['slot_ms']},timeout_us={acq['pulse_timeout_us']}"
    if header is None or expected not in header:
        warnings.append(f"fw header mismatch: got {header!r}, expected "
                        f"'... {expected}' — check the flashed firmware")
    if not rows:
        raise ValueError("raw_serial.log contains no parseable readings")
    t_unwrapped = unwrap_micros([r[2] for r in rows])
    rows = [(sid, e, int(t)) for (sid, e, _), t in zip(rows, t_unwrapped)]
    echo, t_trig, dropped = assemble_triplets(rows)
    if len(echo) == 0:
        raise ValueError("no complete triplets could be assembled")

    # ---- distances and gating (sections 5.2-5.4) ----
    d_surface = echo_us_to_m(echo, t_celsius)
    gates = config["gates"]
    bg_path = session_dir / "background.json"
    if bg_path.is_file():
        with open(bg_path, encoding="utf-8") as f:
            bg = BackgroundModel.from_dict(json.load(f))
    else:
        n_bg = min(gates["bg_n_triplets"], len(d_surface))
        bg = calibrate_background(d_surface[:n_bg], gates)
        with open(bg_path, "w", newline="", encoding="utf-8") as f:
            json.dump(bg.to_dict(), f, indent=2)
    warnings.extend(sanity_warnings(bg))

    r_valid = bg_reading_valid(d_surface, bg)
    t_valid = r_valid.all(axis=1)

    # ---- one-throw segmentation (section 5.5) ----
    seg = segment_throw(t_valid, gates["arm_M"], gates["close_K"])
    if seg is None:
        raise ValueError("no throw detected in this session "
                         f"({int(t_valid.sum())} valid triplets)")

    # ---- corrections (section 8.2) ----
    radius = config["ball"]["radius_m"]
    # (Phase 5, S4D) acquisition-layer per-sensor electronic-offset correction,
    # opt-in. Applied to the distances feeding trilateration; the background gate
    # above used RAW d_surface (a constant per-sensor shift cancels in the band
    # rule, so gating is unchanged). Synthetic callers leave apply_offset False.
    sensor_offset = config.get("acquisition", {}).get("sensor_offset_m")
    offset_on = bool(apply_offset and sensor_offset is not None)
    d_meas = apply_sensor_offset(d_surface, sensor_offset) if offset_on \
        else np.asarray(d_surface, dtype=float)
    if _negative_control == "ball_radius":
        d_centre = np.asarray(d_meas, dtype=float)             # R2 disabled
    else:
        d_centre = add_ball_radius(d_meas, radius)
    d_centre = np.where(r_valid, d_centre, np.nan)             # gate as flags
    t_sample_us = mid_echo_sample_time_us(t_trig, echo)
    if _negative_control == "mid_echo":
        t_used_us = np.asarray(t_trig, dtype=float)            # R3 disabled
    else:
        t_used_us = t_sample_us
    central = bool(config.get("corrections", {}).get("central_difference", False))
    d_aligned, usable = temporal_correction(d_centre, t_used_us * 1e-6,
                                            central_difference=central)

    # ---- trilateration (section 8.3) ----
    geom = ArrayGeometry.from_config(config)
    if _negative_control == "sensor_height":
        geom = ArrayGeometry(vertices_xz=geom.vertices_xz, s_height_m=0.0)  # R4
    kal = config["kalman"]
    tri = trilaterate(d_aligned, geom, kal["sigma_pos_m"])

    used = usable & t_valid & tri.valid & seg.in_throw
    idx = np.flatnonzero(used)
    t_s = t_used_us[idx, 0] * 1e-6
    xyz_raw = np.column_stack([tri.x[idx], tri.y_floor[idx], tri.z[idx]])

    # ---- gate summary + gating evidence, persisted BEFORE the fit (M-4) ----
    # The Kalman/landing stage below may raise ValueError (< min_fit_points,
    # < 2 used triplets, or a non-concave fit). Writing triplets_raw.csv and the
    # gate summary now means a failed session still carries the range-vs-time
    # diagnostic the section 12.1 failure-mode report renders, instead of leaving
    # nothing on disk.
    gate_summary = {
        "n_triplets_total": int(len(echo)),
        "n_triplets_valid": int(t_valid.sum()),
        "n_triplets_in_throw": int(seg.in_throw.sum()),
        "n_triplets_used": int(used.sum()),
        "throw_start": int(seg.start), "throw_end": int(seg.end),
        "malformed_lines": int(malformed), "dropped_readings": int(dropped),
        "background_enabled": [bool(s.enabled) for s in bg.sensors],
        "sensor_offset_applied": offset_on,
        "sensor_offset_m": list(sensor_offset) if offset_on else None,
        "fw_header": header,
    }
    _write_triplets_csv(session_dir / "triplets_raw.csv", echo, t_trig,
                        t_sample_us, d_centre, r_valid, t_valid, seg.in_throw)
    # A REPROCESSED session may carry derived state from a previous run; if the
    # fit stage below fails, a stale prediction/trajectory must not survive next
    # to the new gate summary (the session would render as a valid page instead
    # of the failure state, and calibrate_bias would ingest the stale
    # prediction). Raw data is sacred; DERIVED artifacts are overwritten by
    # design on every run. ground_truth is kept: it is operator-measured and
    # independent of processing.
    meta.pop("prediction", None)
    meta.pop("small_sample_caveat", None)
    (session_dir / "trajectory.csv").unlink(missing_ok=True)
    meta["gate_summary"] = gate_summary
    meta["processing_warnings"] = warnings
    with open(session_dir / "session.json", "w", newline="",
              encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # ---- Kalman + landing (sections 8.4-8.5) ----
    filt = filter_trajectory(t_s, xyz_raw, tri.sigma_y[idx],
                             sigma_pos_m=kal["sigma_pos_m"],
                             q_scale=kal["q_scale"], hetero_R=kal["hetero_R"])
    pred = predict_landing(filt, ball_radius_m=radius,
                           min_fit_points=config["landing"]["min_fit_points"])

    prediction = {
        "raw": {
            "x_m": pred.x, "z_m": pred.z,
            "r_m": pred.r, "theta_deg": pred.theta_deg,
            "sigma_r_m": pred.sigma_r, "sigma_theta_deg": pred.sigma_theta_deg,
            "heading_deg": pred.heading_deg, "v_h_m_s": pred.v_h_m_s,
            "n_points": pred.n_points, "dof": pred.dof,
            "cov_xz_m2": pred.cov_xz.tolist(),
        },
        "corrected": None,
        "model_id": None,
    }
    if model is not None and model.mode != "none":
        corr = apply_correction(model, pred.x, pred.z, pred.heading_deg,
                                pred.v_h_m_s)
        prediction["corrected"] = corr
        prediction["model_id"] = model.created

    # ---- trajectory + finalized session.json (prediction added; section 5.6) ----
    _write_trajectory_csv(session_dir / "trajectory.csv", t_s, xyz_raw, filt,
                          tri.sigma_y[idx], tri.q[idx])
    meta["prediction"] = prediction
    meta["small_sample_caveat"] = pred.caveat
    with open(session_dir / "session.json", "w", newline="",
              encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return ProcessedSession(prediction=prediction, gate_summary=gate_summary,
                            warnings=warnings, caveat=pred.caveat)
