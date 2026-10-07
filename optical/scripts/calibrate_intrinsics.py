"""One-time checkerboard intrinsic calibration (Optical.md §3.4).

Usage:
  .\\venv\\Scripts\\python.exe scripts\\calibrate_intrinsics.py ^
      --images "calib\\raw\\720p480\\*.png" --pattern 9x6 --square-size-m 0.024 ^
      --mode 720p480

Captures ~15-20 stills per video mode (the slow-mo crop differs per mode, so
intrinsics differ), finds chessboard corners, runs cv2.calibrateCamera, and writes
calib/intrinsics_<mode>.yaml with the camera matrix, distortion coefficients and the
RMS reprojection error.

UNIT-TEST SCOPE (stated per §14 Phase 2): the corner-level core
(`calibrate_from_corners`, with synthetic projected corners under a KNOWN camera
matrix + distortion) and the full image path on synthetic zero-distortion
checkerboards are unit-tested. Recovery of NONZERO distortion through the full
image path needs real photographs and is verified at commissioning (checklist C2).
"""

from __future__ import annotations

import argparse
import glob
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical.calibration import atomic_write_text  # noqa: E402


def board_object_points(pattern: tuple[int, int], square_size_m: float) -> np.ndarray:
    """(N,3) board-frame corner coordinates for an (nx, ny) inner-corner pattern."""
    nx, ny = pattern
    objp = np.zeros((nx * ny, 3), np.float32)
    objp[:, :2] = np.mgrid[0:nx, 0:ny].T.reshape(-1, 2) * square_size_m
    return objp


def find_corners(images: list[np.ndarray], pattern: tuple[int, int]
                 ) -> tuple[list[np.ndarray], list[int]]:
    """Find + sub-pixel-refine chessboard corners. Returns (corner sets, used indices)."""
    found, used = [], []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
    for i, img in enumerate(images):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        ok, corners = cv2.findChessboardCorners(gray, pattern)
        if not ok:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        found.append(corners.reshape(-1, 2))
        used.append(i)
    return found, used


def calibrate_from_corners(objpoints: list[np.ndarray], imgpoints: list[np.ndarray],
                           image_size: tuple[int, int]) -> dict:
    """Core cv2.calibrateCamera wrapper. image_size = (width, height)."""
    if len(objpoints) < 3:
        raise ValueError(f"need >= 3 usable views, got {len(objpoints)}")
    obj = [np.asarray(o, np.float32).reshape(-1, 3) for o in objpoints]
    img = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in imgpoints]
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, img, image_size, None, None)
    return {"camera_matrix": K, "dist_coeffs": dist.ravel(),
            "rms_reproj_px": float(rms), "n_views": len(obj),
            "image_size": [int(image_size[0]), int(image_size[1])]}


def calibrate_from_images(images: list[np.ndarray], pattern: tuple[int, int],
                          square_size_m: float) -> dict:
    """Full image path: corner finding + calibration over all usable views."""
    corners, used = find_corners(images, pattern)
    if len(corners) < 3:
        raise ValueError(f"chessboard found in only {len(corners)} of "
                         f"{len(images)} images - need >= 3")
    h, w = images[used[0]].shape[:2]
    objp = board_object_points(pattern, square_size_m)
    result = calibrate_from_corners([objp] * len(corners), corners, (w, h))
    result["n_images_given"] = len(images)
    return result


def save_intrinsics(result: dict, mode: str, out_dir: str | Path,
                    pattern: tuple[int, int], square_size_m: float) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"intrinsics_{mode}.yaml"
    data = {
        "mode": mode,
        "created": datetime.now().isoformat(timespec="seconds"),
        "image_size": result["image_size"],
        "camera_matrix": [[float(v) for v in row] for row in result["camera_matrix"]],
        "dist_coeffs": [float(v) for v in result["dist_coeffs"]],
        "rms_reproj_px": float(result["rms_reproj_px"]),
        "n_views": int(result["n_views"]),
        "pattern": [int(pattern[0]), int(pattern[1])],
        "square_size_m": float(square_size_m),
    }
    atomic_write_text(path, yaml.safe_dump(data, default_flow_style=False,
                                           sort_keys=False))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--images", required=True, help="glob of checkerboard stills")
    ap.add_argument("--pattern", default="9x6", help="INNER corners, e.g. 9x6")
    ap.add_argument("--square-size-m", type=float, required=True,
                    help="measured square side [m] (rule-measured, section 3.4)")
    ap.add_argument("--mode", required=True, help="video mode, e.g. 720p480")
    ap.add_argument("--out", default=str(ROOT / "calib"))
    args = ap.parse_args(argv)

    nx, ny = (int(v) for v in args.pattern.lower().split("x"))
    paths = sorted(glob.glob(args.images))
    if not paths:
        print(f"no images match {args.images}")
        return 1
    images = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            print(f"WARNING: unreadable image skipped: {p}")
        else:
            images.append(img)

    result = calibrate_from_images(images, (nx, ny), args.square_size_m)
    path = save_intrinsics(result, args.mode, args.out, (nx, ny), args.square_size_m)

    K = result["camera_matrix"]
    print(f"views used   : {result['n_views']} / {len(images)}")
    print(f"RMS reproj   : {result['rms_reproj_px']:.4f} px")
    print(f"fx, fy       : {K[0][0]:.2f}, {K[1][1]:.2f}")
    print(f"cx, cy       : {K[0][2]:.2f}, {K[1][2]:.2f}")
    print(f"dist coeffs  : {np.round(result['dist_coeffs'], 5).tolist()}")
    print(f"written      : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
