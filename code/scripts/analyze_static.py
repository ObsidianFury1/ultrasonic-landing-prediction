"""Aggregate static_report.json files into hardware numbers (CLAUDE.md section 7).

Two outputs from a set of reports produced by characterize_static.py:

  1. Beam half-angle (D2): per sensor, the angle off the aim axis at which the
     timeout fraction crosses ~50% — the empirical simulator.beam_half_angle_deg
     that replaces the UNVERIFIED 7.0 estimate. Needs reports tagged with
     --angle-deg at a fixed distance (the ball beam sweep).
  2. Electronic offset: per sensor, the mean - reference offset and its
     sigma/sqrt(N), with a recommendation on subtracting a CONSTANT offset at the
     acquisition layer. This is a measurement-layer correction, deliberately kept
     OUTSIDE bias.py (which handles only the throw-aligned drag residual).

Assumption: --angle-deg is the operator's recorded off-axis angle for the sensor
being swept; the geometric per-sensor angle is not reconstructed from tape
distance. This produces NUMBERS for a joint config.yaml update, not a final answer.

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\analyze_static.py ^
        data\\sessions\\*_static\\static_report.json
"""

import argparse
import glob
import json
import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SENSORS = ("1", "2", "3")


def beam_half_angle(points):
    """First angle where timeout fraction crosses 0.5 (linear interp), or None.

    points: iterable of (angle_deg, timeout_fraction). Returns None when the
    fraction never reaches 0.5 (sweep too narrow — widen it).
    """
    pts = sorted((float(a), float(f)) for a, f in points)
    for (a0, f0), (a1, f1) in zip(pts, pts[1:]):
        if f0 < 0.5 <= f1:
            return a0 + (0.5 - f0) * (a1 - a0) / (f1 - f0)
    # No clean rising crossing: if the smallest measured angle is already past
    # 0.5, the half-angle is at or below it (an upper bound, still informative).
    crossed = [a for a, f in pts if f >= 0.5]
    return min(crossed) if crossed else None


def load_reports(paths):
    reports = []
    for p in paths:
        for match in sorted(glob.glob(p)):
            with open(match, encoding="utf-8") as f:
                r = json.load(f)
            r["_path"] = match
            reports.append(r)
    return reports


def analyze_beam(reports, config_value):
    print("=== Beam half-angle (D2) ===")
    crossings = []
    for sid in SENSORS:
        pts = [(r["angle_off_axis_deg"], r["sensors"][sid]["timeout_fraction"])
               for r in reports
               if r.get("angle_off_axis_deg") is not None
               and r["sensors"][sid]["timeout_fraction"] is not None]
        if len(pts) < 2:
            print(f"  S{sid}: need >= 2 angle-tagged reports (got {len(pts)})")
            continue
        a = beam_half_angle(pts)
        if a is None:
            hi = max(f for _, f in pts)
            print(f"  S{sid}: timeout never reaches 50% (max {hi * 100:.0f}%) "
                  "- widen the angle sweep")
        else:
            crossings.append(a)
            print(f"  S{sid}: 50% timeout crossing at {a:.1f} deg "
                  f"({len(pts)} points)")
    if crossings:
        crossings.sort()
        mid = crossings[len(crossings) // 2]            # median of bracketed sensors
        print(f"\nSuggested beam_half_angle_deg: {mid:.1f} "
              f"(vs current config value {config_value})")
    else:
        print("\nSuggested beam_half_angle_deg: (none — no bracketed sensor; "
              f"current config value {config_value})")


def analyze_offset(reports):
    print("\n=== Electronic offset (acquisition-layer correction, OUTSIDE bias.py) ===")
    board = [r for r in reports if r.get("target") == "board"]
    src = board or reports
    print(f"  source: {'flat-board reports' if board else 'all reports'} "
          f"({len(src)})")
    for sid in SENSORS:
        offs, sems = [], []
        for r in src:
            s = r["sensors"][sid]
            if s["offset_m"] is None or s["sigma_m"] is None or s["n"] < 2:
                continue
            offs.append(s["offset_m"])
            sems.append(s["sigma_m"] / math.sqrt(s["n"]))
        if not offs:
            print(f"  S{sid}: no valid offset (target undetected / all timeouts)")
            continue
        mean_off = sum(offs) / len(offs)
        mean_sem = sum(sems) / len(sems)
        verdict = ("SIGNIFICANT -> subtract a constant offset at acquisition"
                   if abs(mean_off) > 3 * mean_sem else "within noise, leave uncorrected")
        print(f"  S{sid}: offset = {mean_off * 1e3:+.2f} mm, "
              f"sigma/sqrt(N) = {mean_sem * 1e3:.2f} mm -> {verdict}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report_paths", nargs="+",
                   help="static_report.json files (globs ok)")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config_value = config["simulator"]["beam_half_angle_deg"]

    reports = load_reports(args.report_paths)
    if not reports:
        sys.exit("no static_report.json files matched the given paths")
    print(f"loaded {len(reports)} report(s)\n")
    analyze_beam(reports, config_value)
    analyze_offset(reports)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
