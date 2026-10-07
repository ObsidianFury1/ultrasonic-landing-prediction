"""optical_gt.json reader/writer — FROZEN schema (Optical.md §5.6, O7).

The key names are frozen at schema_version 1.0: additive extension is allowed,
renames are forbidden (future integration, §12, is a pure consumer-side change).
Writes are atomic (temp file + fsync + os.replace) so a crash never leaves a
half-written or corrupted optical_gt.json (§5, §11).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from optical.geometry import cart_to_polar

SCHEMA_VERSION = "1.0"

# quality.flags vocabulary (Optical.md §5.6; extend additively, never rename).
FLAG_VOCAB = {
    "homography_drift", "low_frame_count", "detection_gaps", "blur_suspected",
    "parallax_fallback_used", "cond_warn",
    # additive extensions introduced by the as-built pipeline (Phase 3/4):
    "contact_time_bracket", "contact_time_coarse", "no_prediction",
    # v1.2 (WO-OPT-1 Stage 4): sub-frame kink solve at a bounce reversal (§5.5).
    "contact_time_kink",
    # reserved by the Optical.md v1.1 §5.6 amendment (WO-OPT-1); producers wired
    # across Stages 1-5. Synced into the code vocabulary in Stage 1 because Stage 0
    # was documentation-only (spec) by design.
    "fallback_intrinsics", "fps_mismatch", "unmeasured_uncertainty_components",
    "stability_unchecked",
    # v1.4 (WO-OPT-3 Stage 1): additive under O7 (FLAG_VOCAB 14 -> 16).
    # check_point_fail: the section-5.1 step-4 held-out check-point guard tripped for the
    #   calibration this throw used. Its PRODUCER has existed in optical/calibration.py
    #   (CHECK_POINT_FAIL_FLAG) since Phase 2, but the flag was never in this vocabulary, so
    #   process_clip's `[f for f in calib.flags if f in FLAG_VOCAB]` filter silently dropped
    #   it and it never reached any per-throw optical_gt.json (audit Moderate 5.1).
    # stability_abs_fail: the section-5.1 step-5 ABSOLUTE check-point error exceeded
    #   check_point_tol_m at the session start and/or end frame (stale/bumped calibration).
    #   Distinct from check_point_fail (Decision D10) and from homography_drift.
    "check_point_fail", "stability_abs_fail",
}

# Top-level keys that MUST be present (schema contract).
_REQUIRED_TOP = {"schema_version", "session_id", "clip", "calibration", "method",
                 "landing", "uncertainty", "contact", "quality", "notes"}

# Nested keys that MUST be present under each parent (frozen §5.6 schema; WO-OPT-3 Stage 5).
# `landing` is validated separately because it is null in the failure mode.
_REQUIRED_NESTED = {
    "clip": {"file", "mode", "fps_nominal", "fps_measured"},
    "calibration": {"calib_id", "reproj_rms_px", "check_point_err_m", "intrinsics"},
    "method": {"detector", "parallax"},
    "uncertainty": {"sigma_x_m", "sigma_z_m", "sigma_r_m", "sigma_theta_deg", "components"},
    "contact": {"t_frame", "t_subframe", "n_descent_frames"},
    "quality": {"flags", "n_tracked_frames"},
}
_REQUIRED_LANDING = {"x_m", "z_m", "r_m", "theta_deg"}   # only when landing is non-null


def build_optical_gt(*, session_id: str, clip: dict, calibration: dict, method: dict,
                     landing_xz, uncertainty: dict, contact: dict,
                     n_tracked_frames: int, flags: list, notes: str = "") -> dict:
    """Assemble a schema-1.0 optical_gt dict (pure; no I/O).

    landing_xz: (x, z) in array metres, or None for the failure mode (no valid
    prediction) — then landing is null and 'no_prediction' should be in flags.
    """
    if landing_xz is None:
        landing = None
    else:
        x, z = float(landing_xz[0]), float(landing_xz[1])
        r, theta = cart_to_polar(x, z)
        landing = {"x_m": round(x, 6), "z_m": round(z, 6),
                   "r_m": round(r, 6), "theta_deg": round(theta, 4)}

    unknown = set(flags) - FLAG_VOCAB
    if unknown:
        raise ValueError(f"unknown quality.flags {sorted(unknown)} - extend "
                         f"FLAG_VOCAB (section 5.6) before using new flags")

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "clip": dict(clip),
        "calibration": dict(calibration),
        "method": dict(method),
        "landing": landing,
        "uncertainty": uncertainty,
        "contact": dict(contact),
        "quality": {"flags": list(flags), "n_tracked_frames": int(n_tracked_frames)},
        "notes": notes,
    }


def validate_schema(data: dict) -> None:
    """Raise ValueError if `data` violates the frozen schema (top-level AND nested keys).

    Nested-key presence is enforced (WO-OPT-3 Stage 5) so a malformed dict fails HERE with a
    clear key-path, rather than surfacing later as a KeyError from e.g. overlay.summary_text."""
    missing = _REQUIRED_TOP - set(data)
    if missing:
        raise ValueError(f"optical_gt missing required keys: {sorted(missing)}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version {data['schema_version']!r} != "
                         f"{SCHEMA_VERSION!r}")
    for parent, keys in _REQUIRED_NESTED.items():
        sub = data[parent]
        if not isinstance(sub, dict):
            raise ValueError(f"optical_gt '{parent}' must be a mapping, got {type(sub).__name__}")
        miss = keys - set(sub)
        if miss:
            raise ValueError(f"optical_gt missing nested keys: "
                             f"{sorted(parent + '.' + k for k in miss)}")
    landing = data["landing"]
    if landing is not None:
        miss = _REQUIRED_LANDING - set(landing)
        if miss:
            raise ValueError(f"optical_gt missing nested keys: "
                             f"{sorted('landing.' + k for k in miss)}")
    bad = set(data["quality"]["flags"]) - FLAG_VOCAB
    if bad:
        raise ValueError(f"quality.flags contains non-vocabulary entries {sorted(bad)}")


def _serialise(data: dict) -> str:
    """Canonical serialisation: fixed indent, ASCII, keys in insertion order. Reading
    then re-serialising this string reproduces it byte-for-byte (round-trip stable)."""
    return json.dumps(data, indent=2, ensure_ascii=True, sort_keys=False) + "\n"


def write_optical_gt(path: str | Path, data: dict) -> Path:
    """Atomically write optical_gt.json (temp + fsync + os.replace). Validates first,
    so a malformed dict never reaches disk."""
    validate_schema(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(_serialise(data))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def read_optical_gt(path: str | Path) -> dict:
    """Read + validate an optical_gt.json."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    validate_schema(data)
    return data
