"""Homography calibration chain (Optical.md §5.1, §3.3, §3.4).

Responsibilities:
  * ArUco fiducial detection (DICT_4X4_50) on an undistorted calibration frame.
  * Manual-click UI for the surveyed pod/centroid reference marks (interactive,
    matplotlib; deliberately NOT unit-tested — everything downstream of the clicked
    pixels is).
  * Plain least-squares homography fit (cv2.findHomography, method=0 — the marker set
    is trusted and small; RANSAC only if an outlier is ever proven, per §5.1).
  * Reprojection RMS (px) over the fit markers, held-out check-point error (m), and
    the session stability re-check (start vs end frame drift).
  * homography_<calib_id>.yaml persistence with atomic writes.

Direction convention: the CALIBRATED homography `H` maps image pixels -> floor-plane
(x, z) in array metres (§2: "the homography maps image pixels -> floor-plane (x, z)").
The simulator's H_true is the floor->pixel direction; they are inverses.

The check-point guard philosophy mirrors the main project's `ls_residual_m` integrity
guard: a tripped check point WARNS loudly and flags the calibration; it does not
silently pass, and it does not abort (the operator decides).
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from optical.errors import OpticalConfigError

ARUCO_DICT_NAME = "DICT_4X4_50"          # Optical.md §3.3
CHECK_POINT_FAIL_FLAG = "check_point_fail"
DRIFT_FLAG = "homography_drift"
ABS_FAIL_FLAG = "stability_abs_fail"     # WO-OPT-3 Stage 1 (section 5.1 absolute-error guard)
COND_WARN_FLAG = "cond_warn"
# Soft marker-conditioning threshold (WO-OPT-1 Stage 5.4). The point-cloud singular-value
# ratio s1/s0 measures 2-D spread anisotropy (1.0 = isotropic, 0 = collinear).
# `_assert_noncollinear` HARD-fails below 1e-8 (essentially a line). This soft band flags a
# poorly-spread cloud that still fits but is ill-conditioned in its thin direction: 0.05 =
# a >20:1 elongated field, ~6-7 orders above the hard floor — 're-spread the markers (§3.3)'
# without blocking the run.
COND_WARN_RATIO = 0.05


# --------------------------------------------------------------------------- #
# Small shared helpers                                                         #
# --------------------------------------------------------------------------- #

def apply_homography(H: np.ndarray, pts) -> np.ndarray:
    """Apply a 3x3 homography to (N,2) points; returns (N,2)."""
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    ones = np.ones((pts.shape[0], 1))
    out = np.hstack([pts, ones]) @ np.asarray(H, dtype=float).T
    w = out[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise OpticalConfigError("homography maps a point to infinity")
    return out[:, :2] / w


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically: temp file in the same directory + os.replace (§5)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Intrinsics / undistortion                                                    #
# --------------------------------------------------------------------------- #

def load_intrinsics(path: str | Path) -> dict:
    """Load an intrinsics_<mode>.yaml written by scripts/calibrate_intrinsics.py."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["camera_matrix"] = np.asarray(data["camera_matrix"], dtype=float)
    data["dist_coeffs"] = np.asarray(data["dist_coeffs"], dtype=float)
    return data


def undistort_frame(frame: np.ndarray, intrinsics: dict | None) -> np.ndarray:
    """Undistort per §3.4. intrinsics=None is a documented passthrough (synthetic
    frames are rendered distortion-free)."""
    if intrinsics is None:
        return frame
    return cv2.undistort(frame, intrinsics["camera_matrix"], intrinsics["dist_coeffs"])


# --------------------------------------------------------------------------- #
# Detection + manual clicks                                                    #
# --------------------------------------------------------------------------- #

def detect_aruco_markers(frame: np.ndarray,
                         dict_name: str = ARUCO_DICT_NAME) -> dict[int, np.ndarray]:
    """Detect ArUco markers; returns {id: (4,2) corner array}. Empty dict if none."""
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name)),
        cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(frame)
    if ids is None:
        return {}
    return {int(mid): quad.reshape(4, 2).astype(float)
            for quad, mid in zip(corners, ids.flatten())}


def aruco_centres(markers: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
    """Marker centre = centroid of the 4 detected corners. Under perspective this
    differs from the projected geometric centre by O(0.1 px) at our geometry —
    negligible against the survey sigma (documented judgment call)."""
    return {mid: quad.mean(axis=0) for mid, quad in markers.items()}


def manual_click_points(frame: np.ndarray, labels: list[str]) -> dict[str, np.ndarray]:
    """INTERACTIVE (not unit-tested): click each labelled reference mark in order.

    Zoom/pan first with the matplotlib toolbar, then click once per label; a click
    is taken when the toolbar is idle. Returns {label: (u, v) pixel}."""
    import matplotlib.pyplot as plt

    clicked: dict[str, np.ndarray] = {}
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    for label in labels:
        ax.set_title(f"Zoom as needed, then click: {label}  "
                     f"({len(clicked) + 1}/{len(labels)})")
        fig.canvas.draw()
        pts = plt.ginput(1, timeout=-1)
        if not pts:
            raise RuntimeError(f"no click received for '{label}'")
        clicked[label] = np.array(pts[0], dtype=float)
        ax.plot(*clicked[label], "r+", markersize=12)
    plt.close(fig)
    return clicked


# --------------------------------------------------------------------------- #
# Homography fit + integrity guards                                            #
# --------------------------------------------------------------------------- #

def _assert_noncollinear(pts: np.ndarray, what: str) -> None:
    """A homography fitted through (near-)collinear points is rank-deficient; OpenCV
    still returns a finite H that maps the line correctly and everything else as
    garbage, so this must be caught BEFORE the fit. Criterion: the second singular
    value of the centred point cloud, relative to the first, below 1e-8 (a genuine
    line is ~1e-16; any real 2D marker spread is O(0.1-1))."""
    centred = pts - pts.mean(axis=0)
    s = np.linalg.svd(centred, compute_uv=False)
    if s[0] < 1e-12 or s[1] / s[0] < 1e-8:
        raise OpticalConfigError(f"degenerate marker geometry - {what} points are "
                                 f"(near-)collinear; the homography fit is unusable. "
                                 f"Spread the markers in 2D (Optical.md section 3.3).")


def conditioning_ratio(pts) -> float:
    """2-D spread anisotropy s1/s0 of a point cloud (1.0 isotropic, 0 collinear). Used for
    the soft `cond_warn` band above the `_assert_noncollinear` hard floor (Stage 5.4)."""
    pts = np.asarray(pts, dtype=float)
    centred = pts - pts.mean(axis=0)
    s = np.linalg.svd(centred, compute_uv=False)
    return float(s[1] / s[0]) if s[0] > 0 else 0.0


def fit_homography(pixel_pts, floor_pts) -> tuple[np.ndarray, float]:
    """Plain-LS pixel->floor homography over ALL fit points (§5.1 step 3).

    Returns (H, reprojection RMS in px). The RMS is computed in PIXEL space by
    mapping the surveyed floor points back through H^-1 and comparing with the
    measured pixels (§5.1 step 4 reports px).
    Raises ValueError on degenerate geometry (collinear/insufficient markers).
    """
    pixel_pts = np.asarray(pixel_pts, dtype=np.float64).reshape(-1, 2)
    floor_pts = np.asarray(floor_pts, dtype=np.float64).reshape(-1, 2)
    if len(pixel_pts) < 4:
        raise OpticalConfigError(f"homography needs >= 4 correspondences, got "
                                 f"{len(pixel_pts)}")
    _assert_noncollinear(floor_pts, "surveyed floor")
    _assert_noncollinear(pixel_pts, "detected pixel")

    H, _ = cv2.findHomography(pixel_pts, floor_pts, method=0)
    if H is None or not np.all(np.isfinite(H)):
        raise OpticalConfigError("degenerate marker geometry - homography fit failed "
                                 "(markers collinear or coincident?)")
    # Guard against a numerically garbage (rank-deficient) but finite result.
    if abs(np.linalg.det(H)) < 1e-15:
        raise OpticalConfigError("degenerate marker geometry - homography is singular")

    uv_pred = apply_homography(np.linalg.inv(H), floor_pts)
    rms_px = float(np.sqrt(np.mean(np.sum((uv_pred - pixel_pts) ** 2, axis=1))))
    return H, rms_px


@dataclass
class HomographyCalibration:
    """Result of one calibration; persisted as homography_<calib_id>.yaml."""
    calib_id: str
    H: np.ndarray                      # pixel -> floor (array metres)
    reproj_rms_px: float
    check_point_err_m: float
    check_point_id: object             # int (ArUco) or str (reference mark)
    check_point_ok: bool
    fit_ids: list
    tol_m: float
    intrinsics_file: str | None = None
    created: str = ""
    flags: list = field(default_factory=list)
    notes: str = ""
    # WO-OPT-3 Stage 4 (Moderate 5.5 / D13): optional tape cross-check of the camera position.
    # Populated only when `calibrate_homography.py --camera-measured X Y Z` is supplied; each is
    # a plain dict of floats ready for YAML. Informational only — no threshold, no flag, no
    # abort. When None (the default), the calibration YAML shape is unchanged (additive-only).
    camera_measured_m: dict | None = None      # {x, y, z} tape-measured centre, §2 frame
    camera_decomposed_m: dict | None = None    # {x, y, z} decomposed from H + intrinsics
    camera_delta_m: dict | None = None         # {dx, dy, dz, norm} = measured - decomposed


def calibrate(correspondences: dict, held_out_id, calib_id: str, tol_m: float,
              intrinsics_file: str | None = None) -> HomographyCalibration:
    """Fit H over all correspondences EXCEPT the held-out one; evaluate the guard.

    correspondences: {id: (pixel (2,), floor_xz (2,))}. The held-out id must be
    present (§3.3 mandates a check point). A check-point error above tol_m trips the
    guard: a loud UserWarning plus the 'check_point_fail' flag — never silent.
    """
    if held_out_id not in correspondences:
        raise OpticalConfigError(f"held-out check point id {held_out_id!r} not among "
                                 f"correspondences {sorted(correspondences, key=str)}")
    fit_ids = [k for k in correspondences if k != held_out_id]
    pixels = np.array([correspondences[k][0] for k in fit_ids], dtype=float)
    floors = np.array([correspondences[k][1] for k in fit_ids], dtype=float)

    H, rms_px = fit_homography(pixels, floors)

    chk_px, chk_floor = correspondences[held_out_id]
    mapped = apply_homography(H, chk_px)[0]
    err_m = float(np.linalg.norm(mapped - np.asarray(chk_floor, dtype=float)))

    flags: list[str] = []
    ok = err_m <= tol_m
    if not ok:
        flags.append(CHECK_POINT_FAIL_FLAG)
        warnings.warn(
            f"CHECK-POINT GUARD TRIPPED for calib '{calib_id}': held-out marker "
            f"{held_out_id!r} maps {err_m * 1000:.1f} mm from its surveyed position "
            f"(tolerance {tol_m * 1000:.1f} mm). The marker survey or the frame is "
            f"suspect; do NOT trust this calibration.", UserWarning, stacklevel=2)

    # Soft marker-conditioning check (Stage 5.4): poorly-spread (near-collinear) but not
    # degenerate -> cond_warn (propagated to every throw's quality.flags), not a hard fail.
    ratio = conditioning_ratio(floors)
    if ratio < COND_WARN_RATIO:
        flags.append(COND_WARN_FLAG)
        warnings.warn(
            f"MARKER CONDITIONING for calib '{calib_id}': fit markers are poorly spread "
            f"(spread ratio {ratio:.4f} < {COND_WARN_RATIO}); the homography is "
            f"ill-conditioned in the thin direction. Re-spread the markers near/far and "
            f"left/right (Optical.md section 3.3). Every throw will carry '{COND_WARN_FLAG}'.",
            UserWarning, stacklevel=2)

    return HomographyCalibration(
        calib_id=calib_id, H=H, reproj_rms_px=rms_px, check_point_err_m=err_m,
        check_point_id=held_out_id, check_point_ok=ok, fit_ids=fit_ids, tol_m=tol_m,
        intrinsics_file=intrinsics_file,
        created=datetime.now().isoformat(timespec="seconds"), flags=flags)


@dataclass
class StabilityResult:
    """Session start-vs-end check-point re-mapping (section 5.1 step 5)."""
    err_start_m: float
    err_end_m: float
    drift_m: float
    drifted: bool
    abs_fail: bool = False       # WO-OPT-3 Stage 1: err_start_m and/or err_end_m exceeded
                                 # check_point_tol_m (stale/bumped calibration; distinct from
                                 # drift). Additive/defaulted so any existing construction and
                                 # any test inspecting the prior fields is unaffected.


def stability_check(H: np.ndarray, uv_start, uv_end, floor_xz,
                    tol_m: float) -> StabilityResult:
    """Re-map the check point from a session-START and a session-END frame.

    Two INDEPENDENT guards, both thresholded against `tol_m` (WO-OPT-3 Stage 1, Major 4.1):
      * DRIFT: distance between the two mapped floor positions. Drift beyond tol_m means the
        camera moved DURING the session -> 'homography_drift' (reported but excluded from
        headline statistics, section 5.1). Unchanged from v1.3.
      * ABSOLUTE: each mapped point vs the surveyed check-point position (err_start_m,
        err_end_m). Either beyond tol_m means the calibration is stale, or the camera was
        bumped BETWEEN calibration and the session (near-zero drift, large absolute error —
        drift alone cannot see this) -> 'stability_abs_fail'. Kept a DISTINCT flag from
        homography_drift and check_point_fail (Decision D10): different field remediations.
    Both guards WARN loudly and set their result flag; neither aborts (the operator decides),
    the same posture as the step-4 check-point guard."""
    floor_xz = np.asarray(floor_xz, dtype=float)
    m_start = apply_homography(H, uv_start)[0]
    m_end = apply_homography(H, uv_end)[0]
    drift = float(np.linalg.norm(m_end - m_start))
    err_start = float(np.linalg.norm(m_start - floor_xz))
    err_end = float(np.linalg.norm(m_end - floor_xz))
    drifted = drift > tol_m
    abs_fail = err_start > tol_m or err_end > tol_m
    if drifted:
        warnings.warn(
            f"HOMOGRAPHY DRIFT: check point moved {drift * 1000:.1f} mm between the "
            f"session start and end frames (tolerance {tol_m * 1000:.1f} mm). The "
            f"camera moved; all throws in this session must carry "
            f"'{DRIFT_FLAG}'.", UserWarning, stacklevel=2)
    if abs_fail:
        warnings.warn(
            f"STABILITY ABSOLUTE ERROR: the held-out check point maps "
            f"{err_start * 1000:.1f} mm (start) / {err_end * 1000:.1f} mm (end) from its "
            f"surveyed position (tolerance {tol_m * 1000:.1f} mm). The calibration is stale "
            f"or the camera was bumped between calibration and this session; mapped landings "
            f"are systematically offset. All throws in this session must carry "
            f"'{ABS_FAIL_FLAG}'.", UserWarning, stacklevel=2)
    return StabilityResult(
        err_start_m=err_start, err_end_m=err_end,
        drift_m=drift, drifted=drifted, abs_fail=abs_fail)


def detect_check_point_pixel(frame: np.ndarray, check_point_id,
                             dict_name: str = ARUCO_DICT_NAME):
    """Pixel centre of the held-out check-point ArUco marker in `frame`, or None if it is
    not an ArUco id or is not detected in the frame. (Manual/clicked reference marks cannot
    be auto-detected, so they return None — the caller then reports 'stability_unchecked'.)"""
    if not isinstance(check_point_id, (int, np.integer)):
        return None
    markers = detect_aruco_markers(frame, dict_name)
    cid = int(check_point_id)
    if cid not in markers:
        return None
    return aruco_centres(markers)[cid]


def stability_between_frames(H: np.ndarray, frame_start: np.ndarray, frame_end: np.ndarray,
                             check_point_id, check_point_xz, tol_m: float,
                             dict_name: str = ARUCO_DICT_NAME):
    """§5.1 step-5 drift re-check from two session frames (start & end): re-detect the
    held-out check point in each and run `stability_check`. Reusable core for both
    `process_clip` (throw session) and `validate_static` (the full §8 gate span).

    Returns (StabilityResult, None) on success, or (None, reason) when the check CANNOT be
    run — a non-ArUco check point, no surveyed position, or the marker not visible in a
    frame. NEVER raises for a data problem: a check that cannot run is reported so the
    caller can flag 'stability_unchecked' rather than skip the check silently (§5.1)."""
    if not isinstance(check_point_id, (int, np.integer)):
        return None, (f"check point {check_point_id!r} is a manual (non-ArUco) mark - "
                      f"cannot auto-detect it for the drift re-check")
    if check_point_xz is None:
        return None, (f"surveyed position of check point {check_point_id} is unavailable "
                      f"(not in config markers) - cannot run the drift re-check")
    uv_start = detect_check_point_pixel(frame_start, check_point_id, dict_name)
    uv_end = detect_check_point_pixel(frame_end, check_point_id, dict_name)
    if uv_start is None or uv_end is None:
        where = ("start & end" if uv_start is None and uv_end is None
                 else "start" if uv_start is None else "end")
        return None, (f"check point marker {check_point_id} not detected in the {where} "
                      f"frame(s) - drift re-check skipped")
    result = stability_check(H, uv_start, uv_end, np.asarray(check_point_xz, dtype=float),
                             tol_m)
    return result, None


# --------------------------------------------------------------------------- #
# Persistence                                                                  #
# --------------------------------------------------------------------------- #

def save_homography_yaml(calib: HomographyCalibration, out_dir: str | Path) -> Path:
    """Write homography_<calib_id>.yaml (atomic). Key names match §5.6 verbatim
    where §5.6 names them (calib_id, reproj_rms_px, check_point_err_m, intrinsics)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"homography_{calib.calib_id}.yaml"
    data = {
        "calib_id": calib.calib_id,
        "created": calib.created,
        "direction": "pixel_to_floor",
        "H": [[float(v) for v in row] for row in calib.H],
        "reproj_rms_px": float(calib.reproj_rms_px),
        "check_point_err_m": float(calib.check_point_err_m),
        "check_point_id": calib.check_point_id,
        "check_point_ok": bool(calib.check_point_ok),
        "fit_ids": list(calib.fit_ids),
        "tol_m": float(calib.tol_m),
        "intrinsics": calib.intrinsics_file,
        "flags": list(calib.flags),
        "notes": calib.notes,
    }
    # WO-OPT-3 Stage 4: append the optional camera tape cross-check ONLY when present, at the
    # end, so the absent case is byte-identical to the pre-WO-OPT-3 YAML (additive-only, D13).
    if calib.camera_measured_m is not None:
        data["camera_measured_m"] = {k: float(v) for k, v in calib.camera_measured_m.items()}
        data["camera_decomposed_m"] = {k: float(v) for k, v in calib.camera_decomposed_m.items()}
        data["camera_delta_m"] = {k: float(v) for k, v in calib.camera_delta_m.items()}
    atomic_write_text(path, yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    return path


def load_homography_yaml(path: str | Path) -> HomographyCalibration:
    with Path(path).open("r", encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    return HomographyCalibration(
        calib_id=d["calib_id"], H=np.asarray(d["H"], dtype=float),
        reproj_rms_px=float(d["reproj_rms_px"]),
        check_point_err_m=float(d["check_point_err_m"]),
        check_point_id=d["check_point_id"], check_point_ok=bool(d["check_point_ok"]),
        fit_ids=list(d["fit_ids"]), tol_m=float(d["tol_m"]),
        intrinsics_file=d.get("intrinsics"), created=d.get("created", ""),
        flags=list(d.get("flags", [])), notes=d.get("notes", ""),
        camera_measured_m=d.get("camera_measured_m"),      # WO-OPT-3 Stage 4: optional,
        camera_decomposed_m=d.get("camera_decomposed_m"),  # None when the tape cross-check
        camera_delta_m=d.get("camera_delta_m"))            # was not supplied at calibration


# --------------------------------------------------------------------------- #
# Calibration-frame loading                                                    #
# --------------------------------------------------------------------------- #

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def load_calibration_frame(path: str | Path, max_median_frames: int = 31) -> np.ndarray:
    """Load a calibration frame: an image directly, or the TEMPORAL MEDIAN of up to
    `max_median_frames` evenly-sampled frames of a video (§5.1 'short clip; median
    frame' — the median suppresses transients crossing the scene)."""
    path = Path(path)
    if path.suffix.lower() in _IMAGE_EXTS:
        frame = cv2.imread(str(path))
        if frame is None:
            raise OpticalConfigError(f"could not read image {path}")
        return frame

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise OpticalConfigError(f"could not open video {path}")
    try:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        idxs = np.unique(np.linspace(0, max(n - 1, 0),
                                     min(max_median_frames, max(n, 1))).astype(int))
        frames = []
        for i in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
        if not frames:
            raise OpticalConfigError(f"no readable frames in {path}")
        return np.median(np.stack(frames), axis=0).astype(np.uint8)
    finally:
        cap.release()
