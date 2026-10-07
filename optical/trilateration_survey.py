"""trilateration_survey.py -- standalone field helper for landing/marker surveying.

Not part of the Optical Verification pipeline (no import of the `optical` package or
`config.yaml` -- deliberately decoupled, per Optical.md sec 12 "duplication over
coupling"). Measure the tape distance from a point on the floor (a landing point or a
floor marker) to the array centroid and/or the three ultrasonic sensor floor marks
(S1, S2, S3), enter ANY THREE of those four distances -- whichever three are practical
to measure given where the point falls -- and this tool solves the point's array-frame
Cartesian (x, z) and polar (r, theta_deg) coordinates by least-squares multilateration.

Array-frame convention (Optical.md / CLAUDE.md sec 2): origin = triangle centroid, on
the floor; +x toward S1 (theta = 0 axis); +z completes a right-handed frame (theta
measured CCW from above, +x -> +z); theta = atan2(z, x) in degrees, folded to
(-180, 180].

Reference point positions below are the IDEAL/design values for the equilateral array
(side s = 1.0 m, circumradius R_c = s/sqrt(3) ~= 0.5774 m), per Optical.md sec 2 /
config.yaml. If the array is later physically surveyed and these are superseded, edit
the constants below by hand -- this script never reads config.yaml.

Usage:
    .\\venv\\Scripts\\python.exe trilateration_survey.py

Each solved point is printed and appended to trilateration_log.csv (created alongside
this script if it doesn't already exist).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Reference points (array frame, metres) -- EDIT HERE if superseded by a real survey.
# ---------------------------------------------------------------------------
CENTROID = (0.0, 0.0)
S1 = (0.5774, 0.0)
S2 = (-0.2887, 0.5)
S3 = (-0.2887, -0.5)

REFERENCE_POINTS = {"centroid": CENTROID, "S1": S1, "S2": S2, "S3": S3}

COND_WARN_THRESHOLD = 1.0e4  # near-collinear reference-choice flag (informational only)

LOG_FILE = Path(__file__).resolve().parent / "trilateration_log.csv"
LOG_FIELDS = [
    "timestamp", "label",
    "ref1_name", "ref1_dist_m", "ref2_name", "ref2_dist_m", "ref3_name", "ref3_dist_m",
    "x_m", "z_m", "r_m", "theta_deg", "ls_residual_m", "cond_number", "cond_warn",
]


def cart_to_polar(x: float, z: float) -> tuple[float, float]:
    """(x, z) [m] -> (r [m], theta [deg]) in (-180, 180], theta CCW from +x toward +z."""
    r = float(np.hypot(x, z))
    theta = float(np.degrees(np.arctan2(z, x)))
    if theta <= -180.0:
        theta += 360.0
    return r, theta


def solve_trilateration(refs: list[tuple[str, tuple[float, float], float]]) -> dict:
    """Least-squares multilateration from exactly 3 (name, (x, z), distance) references.

    Anchors the linearization at refs[0], solves the resulting 2x2 system for an initial
    estimate, then refines over all 3 distance residuals with Gauss-Newton steps -- the
    same pattern as the main project's reference solve (Code/pipeline/geometry.py
    ::ground_truth_landing), generalized here so any of the 4 candidate points, not just
    the centroid, may anchor (the user may omit the centroid entirely).

    Returns {x, z, r, theta_deg, ls_residual_m, cond_number, cond_warn}.
    """
    if len(refs) != 3:
        raise ValueError(f"need exactly 3 references, got {len(refs)}")

    p = [np.asarray(pos, dtype=float) for _, pos, _ in refs]
    d = [float(dist) for _, _, dist in refs]

    # Linearize by subtracting reference 0's sphere equation from 1 and 2:
    #   2*(p_k - p_0).q = |p_k|^2 - |p_0|^2 - d_k^2 + d_0^2
    P = np.array([p[1] - p[0], p[2] - p[0]])  # (2, 2)
    M = 2.0 * P
    b = np.array([
        (p[k] @ p[k] - p[0] @ p[0]) - (d[k] ** 2 - d[0] ** 2)
        for k in (1, 2)
    ])
    q, *_ = np.linalg.lstsq(M, b, rcond=None)  # never raises

    # Refine over all 3 distance residuals (Gauss-Newton, 2 steps) so the reported
    # point/residual reflect the full over-determined fit.
    for _ in range(2):
        rows, rhs = [], []
        for k in range(3):
            diff = q - p[k]
            dist = float(np.hypot(*diff))
            if dist < 1e-12:
                continue
            rows.append(diff / dist)
            rhs.append(d[k] - dist)
        if len(rows) < 2:
            break
        step, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        q = q + step

    # 3-distance RMS residual: an integrity guard, large => mistyped/mis-taped distance
    # or wrong reference point.
    misfit = [float(np.hypot(*(q - p[k]))) - d[k] for k in range(3)]
    ls_residual_m = float(np.sqrt(np.mean(np.square(misfit))))

    # Condition number of the differenced reference-position matrix: flags a
    # near-collinear choice of 3 references. Scale-invariant, so using P (not M) is
    # equivalent. Informational only -- never blocks.
    cond_number = float(np.linalg.cond(P))
    cond_warn = bool(cond_number > COND_WARN_THRESHOLD)

    r, theta_deg = cart_to_polar(q[0], q[1])
    return {
        "x": float(q[0]), "z": float(q[1]), "r": r, "theta_deg": theta_deg,
        "ls_residual_m": ls_residual_m, "cond_number": cond_number, "cond_warn": cond_warn,
    }


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def _prompt_distances() -> list[tuple[str, tuple[float, float], float]]:
    """Prompt for a distance to each of the 4 reference points; Enter skips one.
    Re-prompts the whole set until exactly 3 valid distances have been given."""
    while True:
        refs = []
        for name, pos in REFERENCE_POINTS.items():
            while True:
                raw = input(f"  Distance to {name} [m] (Enter to skip): ").strip()
                if raw == "":
                    break
                try:
                    value = float(raw)
                except ValueError:
                    print("    not a number, try again.")
                    continue
                if value <= 0:
                    print("    distance must be positive, try again.")
                    continue
                refs.append((name, pos, value))
                break
        if len(refs) == 3:
            return refs
        print(f"  Got {len(refs)} distances (need exactly 3) -- re-enter this point.\n")


def _append_log(label: str, refs: list[tuple[str, tuple[float, float], float]],
                 result: dict) -> None:
    is_new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        row = {"timestamp": datetime.now().isoformat(timespec="seconds"), "label": label}
        for i, (name, _, dist) in enumerate(refs, start=1):
            row[f"ref{i}_name"] = name
            row[f"ref{i}_dist_m"] = dist
        row["x_m"] = f"{result['x']:.4f}"
        row["z_m"] = f"{result['z']:.4f}"
        row["r_m"] = f"{result['r']:.4f}"
        row["theta_deg"] = f"{result['theta_deg']:.2f}"
        row["ls_residual_m"] = f"{result['ls_residual_m']:.5f}"
        row["cond_number"] = f"{result['cond_number']:.2f}"
        row["cond_warn"] = result["cond_warn"]
        writer.writerow(row)


def main() -> None:
    print("Trilateration survey helper -- array-frame (x,z)/(r,theta) from tape distances.")
    print("Reference points (array frame, metres):")
    for name, (x, z) in REFERENCE_POINTS.items():
        print(f"  {name:9s} x={x:+.4f}  z={z:+.4f}")
    print(f"Log file: {LOG_FILE}")
    print()

    while True:
        label = input("Point label (Enter/'q' to quit): ").strip()
        if label == "" or label.lower() == "q":
            break

        refs = _prompt_distances()
        result = solve_trilateration(refs)

        chosen = ", ".join(f"{n}={dist:.3f}m" for n, _, dist in refs)
        print(f"\n  refs used: {chosen}")
        print(f"  x = {result['x']:+.4f} m   z = {result['z']:+.4f} m")
        print(f"  r = {result['r']:.4f} m    theta = {result['theta_deg']:+.2f} deg")
        print(f"  ls_residual = {result['ls_residual_m'] * 1000:.2f} mm  "
              f"(RMS misfit of the 3 tape distances against the solved point)")
        if result["cond_warn"]:
            print(f"  WARNING: near-collinear reference choice (cond={result['cond_number']:.1f})"
                  f" -- consider a different 3 references if available.")
        print()

        _append_log(label, refs, result)

    print(f"Session ended. Results logged to {LOG_FILE}")


if __name__ == "__main__":
    main()
