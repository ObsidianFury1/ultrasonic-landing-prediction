"""Homography calibration CLI (Optical.md §5.1).

Usage (typical):
  .\\venv\\Scripts\\python.exe scripts\\calibrate_homography.py ^
      --frame data\\optical\\2026-07-18_T01\\calib_frame.png --config config.yaml ^
      --calib-id 2026-07-18_A [--intrinsics calib\\intrinsics_720p480.yaml] [--click]

Flow: load frame (image, or temporal-median of a video) -> undistort -> auto-detect
ArUco -> optional manual clicks for the pod/centroid reference marks -> merge with the
surveyed positions from config -> plain-LS fit (held-out excluded) -> report -> write
calib/homography_<calib_id>.yaml.

The testable core is `run_calibration` (headless, arrays in / calibration out);
`main` is a thin argument-parsing wrapper around it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical import calibration as cal  # noqa: E402
from optical.geometry import decompose_camera, load_config  # noqa: E402


def survey_from_config(config: dict) -> tuple[dict, object]:
    """Extract {marker_id: floor_xz} and the held-out id from config markers.fit_points."""
    surveyed: dict = {}
    held_out = None
    for entry in config["markers"]["fit_points"]:
        surveyed[entry["id"]] = np.asarray(entry["xz"], dtype=float)
        if entry.get("held_out"):
            if held_out is not None:
                raise ValueError("config lists more than one held-out marker")
            held_out = entry["id"]
    if not surveyed:
        raise ValueError("config markers.fit_points is empty - survey the markers "
                         "first (Optical.md checklist C4)")
    if held_out is None:
        raise ValueError("config designates no held-out check point (Optical.md section 3.3)")
    return surveyed, held_out


def run_calibration(frame: np.ndarray, surveyed: dict, held_out_id, calib_id: str,
                    tol_m: float, out_dir: str | Path,
                    intrinsics: dict | None = None,
                    intrinsics_file: str | None = None,
                    manual_points: dict | None = None,
                    camera_measured=None,
                    ) -> tuple[cal.HomographyCalibration, Path]:
    """Headless calibration core (fully unit-tested on synthetic frames).

    manual_points: {label: pixel (2,)} for reference marks whose survey positions are
    in `surveyed` under the same (string) ids — the click UI supplies these
    interactively; tests supply them directly.

    camera_measured: optional (X, Y, Z) tape-measured camera centre in the §2 array frame
    (WO-OPT-3 Stage 4 / D13). When given AND intrinsics are available, records
    camera_{measured,decomposed,delta}_m in the calibration YAML for review — INFORMATIONAL
    only (no threshold, no flag, no abort). When None, the YAML is unchanged (additive-only).
    """
    frame_u = cal.undistort_frame(frame, intrinsics)

    detected_px = cal.aruco_centres(cal.detect_aruco_markers(frame_u))
    if manual_points:
        detected_px.update({k: np.asarray(v, dtype=float)
                            for k, v in manual_points.items()})

    correspondences = {}
    missing = []
    for mid, floor_xz in surveyed.items():
        if mid in detected_px:
            correspondences[mid] = (detected_px[mid], np.asarray(floor_xz, dtype=float))
        else:
            missing.append(mid)
    if missing:
        print(f"WARNING: surveyed markers not found in frame: {missing}")
    extra = sorted((set(detected_px) - set(surveyed)), key=str)
    if extra:
        print(f"NOTE: detected but unsurveyed markers ignored: {extra}")

    calib = cal.calibrate(correspondences, held_out_id, calib_id, tol_m,
                          intrinsics_file=intrinsics_file)

    # WO-OPT-3 Stage 4 (D13): optional tape cross-check of the camera position. Decomposing the
    # pose from H needs K (intrinsics); when absent, skip with a note (never abort). The delta is
    # recorded for a human to review against the §5.4 "record both" sanity check — no threshold,
    # no flag, no abort tied to its magnitude.
    if camera_measured is not None:
        if intrinsics is None:
            print("NOTE: --camera-measured supplied but no intrinsics; the decomposed pose "
                  "needs K, so the camera cross-check is skipped (calibration still written).")
        else:
            C_dec = decompose_camera(calib.H,
                                     np.asarray(intrinsics["camera_matrix"], dtype=float))[0]
            cm = np.asarray(camera_measured, dtype=float)
            delta = cm - C_dec
            calib.camera_measured_m = {"x": float(cm[0]), "y": float(cm[1]), "z": float(cm[2])}
            calib.camera_decomposed_m = {"x": float(C_dec[0]), "y": float(C_dec[1]),
                                         "z": float(C_dec[2])}
            calib.camera_delta_m = {"dx": float(delta[0]), "dy": float(delta[1]),
                                    "dz": float(delta[2]), "norm": float(np.linalg.norm(delta))}
            print(f"camera measured    : x={cm[0]:.3f} y={cm[1]:.3f} z={cm[2]:.3f} m")
            print(f"camera decomposed  : x={C_dec[0]:.3f} y={C_dec[1]:.3f} z={C_dec[2]:.3f} m")
            print(f"camera delta       : {calib.camera_delta_m['norm'] * 1000:.1f} mm "
                  f"(dx {delta[0] * 1000:.1f}, dy {delta[1] * 1000:.1f}, "
                  f"dz {delta[2] * 1000:.1f} mm) - informational only, no gate")

    path = cal.save_homography_yaml(calib, out_dir)

    print(f"calib_id           : {calib.calib_id}")
    print(f"fit markers        : {len(calib.fit_ids)} {sorted(calib.fit_ids, key=str)}")
    print(f"reproj RMS         : {calib.reproj_rms_px:.3f} px")
    print(f"check point {str(calib.check_point_id):<6} : "
          f"{calib.check_point_err_m * 1000:.1f} mm "
          f"(tol {tol_m * 1000:.1f} mm) -> {'OK' if calib.check_point_ok else 'FAIL'}")
    if calib.flags:
        print(f"FLAGS              : {calib.flags}")
    print(f"written            : {path}")
    return calib, path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frame", required=True,
                    help="calibration image, or video (temporal-median frame is used)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--calib-id", required=True)
    ap.add_argument("--intrinsics", default=None,
                    help="calib/intrinsics_<mode>.yaml for undistortion (section 3.4)")
    ap.add_argument("--out", default=str(ROOT / "calib"))
    ap.add_argument("--click", action="store_true",
                    help="manually click the pod/centroid reference marks")
    ap.add_argument("--camera-measured", dest="camera_measured", nargs=3, type=float,
                    default=None, metavar=("X", "Y", "Z"),
                    help="optional tape-measured camera centre (metres, section-2 array frame: "
                         "origin at centroid, +x toward S1, +y up). Records "
                         "camera_{measured,decomposed,delta}_m in the calib YAML for review "
                         "(informational only, no gate; needs --intrinsics to decompose).")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    surveyed, held_out = survey_from_config(config)
    tol_m = float(config["tolerances"]["check_point_tol_m"])

    frame = cal.load_calibration_frame(args.frame)
    intr = cal.load_intrinsics(args.intrinsics) if args.intrinsics else None

    manual = None
    if args.click:
        marks = config["markers"]["reference_marks"]
        labels = list(marks.keys())
        clicked = cal.manual_click_points(cal.undistort_frame(frame, intr), labels)
        manual = clicked
        for label in labels:                       # clicked marks join the survey
            surveyed.setdefault(label, np.asarray(marks[label], dtype=float))

    calib, _ = run_calibration(frame, surveyed, held_out, args.calib_id, tol_m,
                               args.out, intrinsics=intr,
                               intrinsics_file=args.intrinsics, manual_points=manual,
                               camera_measured=args.camera_measured)
    return 0 if calib.check_point_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
