"""manual_marker_click.py -- standalone field helper for hand-clicking ArUco markers that
cv2.aruco failed to auto-detect (Optical.md sec 5.1 step 2 extends this idea to the pod/
centroid marks only; this tool applies the same "zoom, then click" interaction to any
marker ID, for the case -- hit twice during this session's [C5] fieldwork -- where specific
printed markers are legible to the eye but the ArUco decoder still misses them).

Reuses the TESTED undistort/click machinery in optical/calibration.py rather than
duplicating it (unlike trilateration_survey.py, which is deliberately decoupled from the
optical package for its own reasons -- this tool is directly extending calibration.py's own
functionality, so reuse is the right call here).

Usage (run interactively -- needs a real display and mouse, not runnable headlessly):
    .\\venv\\Scripts\\python.exe manual_marker_click.py ^
        --frame data\\optical\\homography\\IMG_1878.MOV ^
        --intrinsics calib\\intrinsics_1080p240.yaml ^
        --ids 0 5 6 ^
        --out calib\\manual_clicks_2026-07-11.yaml

For each id: the frame opens in a matplotlib window. Zoom/pan with the toolbar to get a
close, precise view of that marker, then click once on its centre. A verification image
with all clicks marked is saved alongside the output YAML -- check it before trusting the
result (per the field checklist's own caution: no undo, a mis-click means re-running).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical import calibration as cal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frame", required=True, help="calibration image or video")
    ap.add_argument("--intrinsics", default=None, help="calib/intrinsics_<mode>.yaml")
    ap.add_argument("--ids", nargs="+", type=int, required=True,
                    help="marker ids to click, e.g. --ids 0 5 6")
    ap.add_argument("--out", required=True, help="output YAML path")
    args = ap.parse_args()

    frame = cal.load_calibration_frame(args.frame)
    intr = cal.load_intrinsics(args.intrinsics) if args.intrinsics else None
    frame_u = cal.undistort_frame(frame, intr)

    labels = [str(mid) for mid in args.ids]
    print(f"Click {len(labels)} marker(s) in order: {labels}")
    print("Zoom/pan with the matplotlib toolbar FIRST, then click once on each marker's "
          "centre. No undo -- re-run this script if you mis-click.")
    clicked = cal.manual_click_points(frame_u, labels)

    result = {int(label): [float(v) for v in pt] for label, pt in clicked.items()}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cal.atomic_write_text(out_path, yaml.safe_dump(
        {"clicks_px": result, "source_frame": str(args.frame)},
        default_flow_style=False, sort_keys=False))
    print(f"written: {out_path}")

    vis = frame_u.copy()
    for mid, pt in result.items():
        p = (int(pt[0]), int(pt[1]))
        cv2.drawMarker(vis, p, (0, 0, 255), cv2.MARKER_CROSS, 30, 3)
        cv2.putText(vis, str(mid), (p[0] + 15, p[1] - 15),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    vis_path = out_path.with_suffix(".png")
    cv2.imwrite(str(vis_path), vis)
    print(f"verification image: {vis_path}  <- CHECK this before trusting the result")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
