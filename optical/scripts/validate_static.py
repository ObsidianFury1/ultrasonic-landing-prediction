"""Static-point validation — the §8 acceptance-gate runner (GO/NO-GO).

Places the ball statically at >= 8 surveyed floor points, runs each through the
optical pipeline (a static ball rests on the floor, so its centre is r_ball above its
floor position — detect -> map -> parallax-correct with r_ball), and compares the
recovered (x, z) with the surveyed reference. Produces the comparison table and the
budget-vs-measured page (§7: the propagated budget next to the MEASURED spread).

GO if RMS disagreement <= config tolerances.rms_gate_m (default 0.015 m), else NO-GO.
The criterion is fixed BEFORE data (Optical.md §8, O9); this script only reports it.

The testable core is `static_landing` and `summarize`; `main` is the CLI wrapper.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2                                        # noqa: E402
import yaml                                       # noqa: E402

from optical import calibration as cal           # noqa: E402
from optical import io_session                    # noqa: E402
from optical import uncertainty as unc           # noqa: E402
from optical.calibration import (apply_homography, atomic_write_text,  # noqa: E402
                                 stability_between_frames)
from optical.detect import HsvDetector, localisation_scatter          # noqa: E402
from optical.errors import OpticalConfigError, OpticalDataError        # noqa: E402
from optical.geometry import CameraGeometry, load_config, parallax_correct  # noqa: E402
from scripts.process_clip import check_point_xz                        # noqa: E402


@dataclass
class StaticResult:
    point_id: object
    surveyed_xz: np.ndarray
    measured_xz: np.ndarray
    error_m: float
    sigma_xz: np.ndarray
    sigma_px: float
    n_detected: int
    n_frames: int


def static_landing(frames, H_px2floor, camera: CameraGeometry, detector: HsvDetector,
                   r_ball: float, *, uncertainty_cfg: dict, marker_survey_m=0.0025,
                   marker_survey_measured: bool = True,
                   reproj_rms_px=0.0, check_point_err_m=0.0
                   ) -> tuple[np.ndarray, np.ndarray, dict]:
    """Recover a resting ball's floor (x, z) from a static clip: median detected
    centroid -> floor map -> parallax-correct with r_ball. Returns (xz, sigma_xz, stats)
    with sigma propagated through the §7 budget.

    uncertainty_cfg: the parsed uncertainty block from
    `optical.uncertainty.read_uncertainty_config(config)`. `sigma_h_m`, `sigma_C_m` and
    `rolling_shutter_m` are taken from it with NO silent default (WO-OPT-1 Stage 1 / audit
    M1). `pixel_sigma_px` prefers the LIVE measured scatter over the config placeholder;
    it falls back to the config value only when live scatter is unavailable, and that
    fallback is recorded in `stats['unmeasured_components']`."""
    dets = [detector.detect(f) for f in frames]
    centroids = np.array([d.centroid_px for d in dets if d is not None])
    if len(centroids) == 0:
        raise OpticalDataError("no ball detected in the static clip")
    uv = np.median(centroids, axis=0)
    M_c = apply_homography(H_px2floor, uv)[0]
    xz = parallax_correct(M_c, r_ball, camera.C)

    unmeasured = list(uncertainty_cfg["unmeasured"])
    scat = localisation_scatter(frames, detector)
    if np.isfinite(scat["sigma_px"]):
        sigma_px = float(scat["sigma_px"])          # live measurement overrides placeholder
        if "pixel_sigma_px" in unmeasured:
            unmeasured.remove("pixel_sigma_px")
    else:
        sigma_px = float(uncertainty_cfg["pixel_sigma_px"])
        if "pixel_sigma_px" not in unmeasured:
            unmeasured.append("pixel_sigma_px")
    # WO-OPT-3 Stage 3 (D11): the survey sigma placeholder, when unmeasured, joins the report's
    # unmeasured-component list (defaults measured -> not added, so callers that don't pass the
    # status are unaffected).
    if not marker_survey_measured and unc.SURVEY_SIGMA_COMPONENT not in unmeasured:
        unmeasured.append(unc.SURVEY_SIGMA_COMPONENT)
    budget = unc.build_budget(
        landing_xz=xz, landing_uv=uv, H_px2floor=H_px2floor,
        marker_survey_m=marker_survey_m, reproj_rms_px=reproj_rms_px,
        check_point_err_m=check_point_err_m, sigma_px=sigma_px,
        parallax_P_mapped=M_c, r_ball=r_ball, camera_C=camera.C,
        sigma_h_m=float(uncertainty_cfg["sigma_h_m"]),
        sigma_C_m=tuple(float(v) for v in uncertainty_cfg["sigma_C_m"]),
        vel_xz=np.array([0.0, 0.0]), sigma_t_s=0.0,
        rolling_shutter_m=float(uncertainty_cfg["rolling_shutter_m"]))
    sigma_xz = np.array([budget["sigma_x_m"], budget["sigma_z_m"]])
    return xz, sigma_xz, {"sigma_px": sigma_px, "n_detected": len(centroids),
                          "n_frames": len(frames), "budget": budget,
                          "unmeasured_components": unmeasured}


def measure_points(points, H_px2floor, camera, detector, r_ball, **kw) -> list:
    """points: list of (point_id, surveyed_xz, frames). Returns [StaticResult]."""
    results = []
    for pid, surveyed, frames in points:
        xz, sigma_xz, stats = static_landing(frames, H_px2floor, camera, detector,
                                              r_ball, **kw)
        surveyed = np.asarray(surveyed, float)
        results.append(StaticResult(
            point_id=pid, surveyed_xz=surveyed, measured_xz=xz,
            error_m=float(np.linalg.norm(xz - surveyed)), sigma_xz=sigma_xz,
            sigma_px=stats["sigma_px"], n_detected=stats["n_detected"],
            n_frames=stats["n_frames"]))
    return results


def session_stability(point_clips, H_px2floor, check_point_id, check_point_xz, tol_m,
                      dict_name="DICT_4X4_50"):
    """§5.1/§8 drift re-check spanning the FULL static-gate session: the first frame of the
    first point's clip vs the last frame of the last point's clip. A tripod bump partway
    through the C7 session is the audit's flagged false-GO path (M3), so the gate report
    must run this across the whole span, not per point. `point_clips`: list of frame-lists
    in acquisition order. Returns (StabilityResult | None, reason) — reason is None on a
    clean run, else the string to surface as `stability_unchecked` in the report.

    Wired into the Stage 5 validate_static CLI; provided now (WO-OPT-1 Stage 3 task 4) so
    it is ready to call."""
    clips = [c for c in point_clips if c]
    if not clips:
        return None, "no clips for the session stability span"
    first = next((f for f in clips[0] if f is not None), None)
    last = next((f for f in reversed(clips[-1]) if f is not None), None)
    if first is None or last is None:
        return None, "no usable start/end frame for the session stability span"
    return stability_between_frames(H_px2floor, first, last, check_point_id,
                                    check_point_xz, tol_m, dict_name)


def summarize(results, rms_gate_m: float) -> dict:
    """RMS of the 2-D disagreement over all points + the GO/NO-GO verdict (§8)."""
    errs = np.array([r.error_m for r in results])
    rms = float(np.sqrt(np.mean(errs ** 2))) if len(errs) else float("nan")
    return {"n_points": len(results), "rms_m": rms, "max_m": float(errs.max())
            if len(errs) else float("nan"), "rms_gate_m": rms_gate_m,
            "go": bool(len(errs) >= 8 and rms <= rms_gate_m),
            "enough_points": len(errs) >= 8}


def comparison_table(results, summary) -> str:
    """The §8 comparison table + the budget-vs-measured page, as text."""
    lines = ["STATIC-POINT VALIDATION (Optical.md section 8)",
             "=" * 64,
             f"{'id':>4} {'surv_x':>8} {'surv_z':>8} {'meas_x':>8} {'meas_z':>8} "
             f"{'err_mm':>7} {'sig_mm':>7} {'det':>5}",
             "-" * 64]
    for r in results:
        sig = float(np.linalg.norm(r.sigma_xz))
        lines.append(
            f"{str(r.point_id):>4} {r.surveyed_xz[0]:8.3f} {r.surveyed_xz[1]:8.3f} "
            f"{r.measured_xz[0]:8.3f} {r.measured_xz[1]:8.3f} "
            f"{r.error_m * 1000:7.1f} {sig * 1000:7.1f} "
            f"{r.n_detected:3d}/{r.n_frames}")
    lines += ["-" * 64,
              f"n points        : {summary['n_points']} "
              f"({'>= 8 OK' if summary['enough_points'] else '< 8 INSUFFICIENT'})",
              f"RMS disagreement: {summary['rms_m'] * 1000:.1f} mm",
              f"max error       : {summary['max_m'] * 1000:.1f} mm",
              f"gate            : <= {summary['rms_gate_m'] * 1000:.1f} mm",
              f"VERDICT         : {'GO' if summary['go'] else 'NO-GO'}",
              "",
              "budget-vs-measured (mm): per-point propagated sigma above should be",
              "commensurate with the point's error; a budget far below the spread",
              "means an unmodelled error source (section 7).",
              f"  mean propagated sigma : "
              f"{np.mean([np.linalg.norm(r.sigma_xz) for r in results]) * 1000:.1f} mm",
              f"  measured RMS spread   : {summary['rms_m'] * 1000:.1f} mm"]
    return "\n".join(lines)


def write_report(path, results, summary) -> Path:
    path = Path(path)
    atomic_write_text(path, comparison_table(results, summary) + "\n")
    return path


# --------------------------------------------------------------------------- #
# On-disk gate session (Stage 5.3) — per §9 layout                            #
# --------------------------------------------------------------------------- #

def load_point_frames(point_dir) -> list:
    """Frames for one static point: raw.mp4 if present (§9), else a sorted *.png sequence
    (a codec-free path for capture and testing)."""
    point_dir = Path(point_dir)
    raw = point_dir / "raw.mp4"
    if raw.exists():
        cap = cv2.VideoCapture(str(raw))
        frames = []
        try:
            while True:
                ok, f = cap.read()
                if not ok:
                    break
                frames.append(f)
        finally:
            cap.release()
        if frames:
            return frames
    pngs = sorted(point_dir.glob("*.png"))
    if pngs:
        return [cv2.imread(str(p)) for p in pngs]
    raise OpticalDataError(f"no raw.mp4 or *.png frames in static point dir {point_dir}")


def enumerate_static_points(root) -> list:
    """Sorted [(id, surveyed_xz, frames)] from per-point subdirs of `root`, each holding a
    `point.yaml` ({id, xz: [x, z]}) plus raw.mp4 or *.png frames. Subdirs without a
    point.yaml are skipped (Stage 5.3)."""
    root = Path(root)
    if not root.is_dir():
        raise OpticalConfigError(f"static-validation root {root} is not a directory")
    points = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = d / "point.yaml"
        if not meta.exists():
            continue
        with meta.open("r", encoding="utf-8") as fh:
            m = yaml.safe_load(fh)
        points.append((m["id"], np.asarray(m["xz"], dtype=float), load_point_frames(d)))
    if not points:
        raise OpticalConfigError(f"no static-point subdirs (each with point.yaml) under "
                                 f"{root}")
    return points


def _stability_line(stab, reason) -> tuple[str, list]:
    """One report line + the LIST of stability flags. Evaluates BOTH guards (WO-OPT-3 Stage 1):
    'homography_drift' (start-vs-end drift) and/or 'stability_abs_fail' (absolute check-point
    error at either frame). ['stability_unchecked'] when the check could not run; [] clean."""
    if reason is not None:
        return f"session stability : UNCHECKED - {reason}", ["stability_unchecked"]
    flags = []
    if stab.drifted:
        flags.append("homography_drift")
    if stab.abs_fail:
        flags.append("stability_abs_fail")
    if not flags:
        return (f"session stability : OK (drift {stab.drift_m * 1000:.1f} mm, abs err "
                f"start {stab.err_start_m * 1000:.1f} / end {stab.err_end_m * 1000:.1f} mm "
                f"across the session)"), []
    parts = []
    if stab.drifted:
        parts.append(f"DRIFT {stab.drift_m * 1000:.1f} mm")
    if stab.abs_fail:
        parts.append(f"ABS ERR start {stab.err_start_m * 1000:.1f} / "
                     f"end {stab.err_end_m * 1000:.1f} mm")
    return (f"session stability : {' + '.join(parts)} across the gate session -> results "
            f"NOT trustworthy (section 5.1)"), flags


def _fallback_K(config, mode):
    w, h = config["capture"]["modes"][mode]["resolution"]
    fx = (w / 2.0) / np.tan(np.radians(60.0) / 2.0)
    return np.array([[fx, 0, w / 2.0], [0, fx, h / 2.0], [0, 0, 1.0]])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True,
                    help="dir of per-point subdirs (each: point.yaml + raw.mp4 or *.png)")
    ap.add_argument("--calib", required=True, help="homography_<id>.yaml")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--intrinsics", default=None,
                    help="intrinsics_<mode>.yaml (section 3.4); required unless "
                         "--allow-fallback-intrinsics")
    ap.add_argument("--allow-fallback-intrinsics", dest="allow_fallback",
                    action="store_true", help="smoke-test only: HFOV-guess K")
    ap.add_argument("--mode", default=None)
    ap.add_argument("--out", default=str(ROOT / "data" / "static_validation.txt"))
    args = ap.parse_args(argv)

    config = load_config(args.config)
    mode = args.mode or config["capture"]["default_mode"]
    r_ball = float(config["ball"]["radius_m"])
    rms_gate_m = float(config["tolerances"]["rms_gate_m"])
    ucfg = unc.read_uncertainty_config(config)

    calib = cal.load_homography_yaml(args.calib)
    intr = cal.load_intrinsics(args.intrinsics) if args.intrinsics else None
    if intr is not None:
        K = intr["camera_matrix"]
    elif args.allow_fallback:
        K = _fallback_K(config, mode)
        warnings.warn("FALLBACK INTRINSICS: HFOV-guess K (smoke-test only); supply the "
                      "section-3.4 intrinsics for a real gate run.", UserWarning, stacklevel=2)
    else:
        raise OpticalConfigError("no --intrinsics supplied. Pass the section-3.4 intrinsics, or "
                                 "--allow-fallback-intrinsics for smoke-testing only.")
    camera = CameraGeometry.from_homography(calib.H, K)
    detector = HsvDetector.from_config(config)

    scfg = unc.read_survey_sigma(config)         # WO-OPT-3 Stage 3 / D11: {value, measured}
    points = enumerate_static_points(args.root)
    results = measure_points(
        points, calib.H, camera, detector, r_ball, uncertainty_cfg=ucfg,
        marker_survey_m=scfg["value"], marker_survey_measured=scfg["measured"],
        reproj_rms_px=calib.reproj_rms_px, check_point_err_m=calib.check_point_err_m)
    summary = summarize(results, rms_gate_m)

    # §8/§5.1: drift re-check spanning the WHOLE gate session (first point's clip start ->
    # last point's clip end) — a bump partway through is the audit's false-GO path (M3).
    cp_xz = check_point_xz(config, calib.check_point_id)
    dict_name = (config.get("markers", {}) or {}).get("aruco_dict", "DICT_4X4_50")
    stab, stab_reason = session_stability(
        [frames for _, _, frames in points], calib.H, calib.check_point_id, cp_xz,
        float(calib.tol_m), dict_name)
    stab_line, stab_flags = _stability_line(stab, stab_reason)

    report = comparison_table(results, summary) + "\n" + stab_line + "\n"
    atomic_write_text(Path(args.out), report)
    print(report)

    # GO requires the pre-registered gate AND a trustworthy calibration across the session:
    # a drift (camera moved mid-session) OR a stability_abs_fail (stale/bumped calibration —
    # large absolute check-point error) invalidates the RMS, so either forces NO-GO.
    go = bool(summary["go"] and "homography_drift" not in stab_flags
              and "stability_abs_fail" not in stab_flags)
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
