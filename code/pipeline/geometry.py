"""Coordinate frame, sensor-array geometry and ground-truth triangulation.

Implements CLAUDE.md (v2.1) section 8.1, in the frame of section 0.1:
  - origin at the array centroid, ON THE FLOOR (y = 0 is the floor plane)
  - +x horizontal toward sensor S1 (the theta = 0 reference axis)
  - +y vertical, up
  - +z horizontal, right-handed; theta (CCW viewed from above) runs +x -> +z
  - polar output: r [m], theta [deg] in (-180, 180]

All physical values (vertex coordinates, sensor height) come from an
already-parsed config dict; this module performs no I/O.
"""

from dataclasses import dataclass, field

import numpy as np

# Tolerances are numerical (floating-point) guards, not physical constants,
# so they may live here rather than in config.yaml.
_COLLINEAR_TOL = 1e-9        # m^2; twice the triangle area below this -> degenerate


# ---------------------------------------------------------------------------
# Array geometry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArrayGeometry:
    """Sensor-array geometry: horizontal vertices + common acoustic-centre height.

    vertices_xz : (3, 2) array, rows S1, S2, S3, columns (x, z) [m]
    s_height_m  : acoustic-centre height above the floor [m] (R4)
    """

    vertices_xz: np.ndarray = field()
    s_height_m: float = field()

    def __post_init__(self):
        vertices = np.asarray(self.vertices_xz, dtype=float)
        if vertices.shape != (3, 2):
            raise ValueError(
                f"vertices_xz must have shape (3, 2), got {vertices.shape}"
            )
        # Twice the signed triangle area; ~0 means collinear vertices, which
        # makes the trilateration matrix A singular.
        v1, v2, v3 = vertices
        e1, e2 = v2 - v1, v3 - v1
        area2 = abs(e1[0] * e2[1] - e1[1] * e2[0])
        if area2 < _COLLINEAR_TOL:
            raise ValueError(
                "sensor vertices are collinear (or coincident); "
                "trilateration matrix would be singular"
            )
        object.__setattr__(self, "vertices_xz", vertices)
        object.__setattr__(self, "s_height_m", float(self.s_height_m))

    @classmethod
    def from_config(cls, config: dict) -> "ArrayGeometry":
        """Build from a parsed config dict (the config.yaml `array` schema)."""
        array_cfg = config["array"]
        vertices = np.array(
            [array_cfg["S1_xz"], array_cfg["S2_xz"], array_cfg["S3_xz"]],
            dtype=float,
        )
        return cls(vertices_xz=vertices, s_height_m=array_cfg["S_height_m"])

    @property
    def vertices_3d(self) -> np.ndarray:
        """(3, 3) array of acoustic-centre positions (x, y, z) in the floor frame."""
        x = self.vertices_xz[:, 0]
        z = self.vertices_xz[:, 1]
        y = np.full(3, self.s_height_m)
        return np.column_stack([x, y, z])

    def trilateration_system(self) -> tuple[np.ndarray, np.ndarray]:
        """Constant parts of the trilateration linear system (general A^-1 b form).

        Subtracting the S1 sphere equation from S2/S3 (equal sensor heights make
        the y-terms cancel exactly, section 8.3) gives  A @ [x, z] = b  with

            A = 2 * [[X2-X1, Z2-Z1], [X3-X1, Z3-Z1]]
            b = c - [d2^2 - d1^2, d3^2 - d1^2]
            c = [|p2|^2 - |p1|^2, |p3|^2 - |p1|^2],  p_i = (X_i, Z_i)

        Returns (A, c); the per-triplet b and solve belong to trilateration.py.
        """
        p = self.vertices_xz
        A = 2.0 * (p[1:] - p[0])
        norms = np.sum(p**2, axis=1)
        c = norms[1:] - norms[0]
        return A, c


# ---------------------------------------------------------------------------
# Polar <-> Cartesian (degrees at the interface, CCW from +x toward +z)
# ---------------------------------------------------------------------------

def polar_to_cart(r: float, theta_deg: float) -> tuple[float, float]:
    """(r, theta [deg]) -> (x, z)."""
    theta = np.radians(theta_deg)
    return float(r * np.cos(theta)), float(r * np.sin(theta))


def cart_to_polar(x: float, z: float) -> tuple[float, float]:
    """(x, z) -> (r, theta [deg]), theta in (-180, 180]."""
    r = float(np.hypot(x, z))
    theta = float(np.degrees(np.arctan2(z, x)))
    if theta <= -180.0:
        theta += 360.0
    return r, theta


# ---------------------------------------------------------------------------
# Multilateration ground-truth solve (CLAUDE.md v2.3 section 5.5/8.1, G1)
#
# (The old two_circle_intersection two-tape solver was retired with the G1
# migration: multilateration over centroid + 2 sensors is unique, so the mirror
# ambiguity it resolved no longer exists. Its last caller was the old
# ground-truth path; see CHANGES.md §1.4.)
# ---------------------------------------------------------------------------

_SENSOR_NAMES = ("S1", "S2", "S3")
# Default near-collinear flag threshold (CLAUDE.md §2 / CHANGES §4). Used when
# config.ground_truth.cond_warn is absent -- the explicit config key is added in
# the G1 migration's Stage 2; geometry stays robust whether or not it is present.
_DEFAULT_COND_WARN = 1.0e4


def recommend_reference_sensors(landing_xz, config: dict) -> tuple[str, str]:
    """The two sensors (of S1/S2/S3) whose surveyed floor positions are nearest
    the predicted landing, nearest first (CLAUDE.md v2.3 G1).

    Pure and deterministic: ties break by sensor index (S1 < S2 < S3) so the
    recommendation is stable. One home for the default pair (terminal prompt,
    web __DATA__ builder, append_ground_truth all call this).
    """
    geom = ArrayGeometry.from_config(config)
    q = np.asarray(landing_xz, dtype=float)
    dists = [(float(np.hypot(*(geom.vertices_xz[i] - q))), i)
             for i in range(3)]
    dists.sort(key=lambda t: (t[0], t[1]))          # distance, then index
    return _SENSOR_NAMES[dists[0][1]], _SENSOR_NAMES[dists[1][1]]


def ground_truth_landing(L_centroid: float, refs, config: dict) -> dict:
    """Least-squares multilateration ground-truth landing (CLAUDE.md v2.3 G1).

    References are the centroid (origin, distance L_centroid) plus the two chosen
    sensors. `refs` is an ordered list of two dicts, each
    {"name": str, "pos": (px, pz), "L": float}. Three distance constraints, two
    unknowns -> the solution is UNIQUE: the second sensor breaks the reflection
    symmetry of the old two-circle case, so there is no mirror ambiguity and no
    `pick`/`pred_z` argument.

    Returns dict with x, z, r, theta_deg, sigma_x, sigma_z, cov_xz (2x2),
    ls_residual_m (3-distance misfit, an integrity guard), cond_number and
    cond_warn (near-collinear references flag -- NEVER raises, no NaNs; §8.1 G1).
    """
    if len(refs) != 2:
        raise ValueError(f"need exactly two sensor references, got {len(refs)}")
    p = [np.zeros(2)] + [np.asarray(r["pos"], dtype=float) for r in refs]   # centroid + 2
    d = [float(L_centroid)] + [float(r["L"]) for r in refs]

    # Linearise by subtracting the centroid equation (p0 = 0, d0 = L_centroid)
    # from each sensor equation:  2 * p_i . q = |p_i|^2 - d_i^2 + d0^2.
    P = np.array([p[1], p[2]])                       # (2, 2) sensor positions
    M = 2.0 * P
    b = np.array([P[k] @ P[k] - d[k + 1] ** 2 + d[0] ** 2 for k in range(2)])
    q, *_ = np.linalg.lstsq(M, b, rcond=None)        # best estimate, never raises

    # Refine over ALL THREE distance residuals (1-2 Gauss-Newton steps) so the
    # reported point and residual reflect the full over-determined fit.
    for _ in range(2):
        rows, rhs = [], []
        for k in range(3):
            diff = q - p[k]
            dist = float(np.hypot(*diff))
            if dist < 1e-12:
                continue
            u = diff / dist
            rows.append(u)
            rhs.append(d[k] - dist)                  # residual to drive to zero
        if len(rows) < 2:
            break
        step, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        q = q + step

    # 3-distance LS residual (integrity guard: large = mis-tape / wrong sensor).
    misfit = [float(np.hypot(*(q - p[k]))) - d[k] for k in range(3)]
    ls_residual_m = float(np.sqrt(np.mean(np.square(misfit))))

    # Condition number of the 2x2 sensor-reference matrix (a property of WHICH
    # two sensors were chosen). Above cond_warn -> near-collinear references:
    # flag it, do not raise (§8.1 G1). Well-conditioned for the equilateral array.
    cond_number = float(np.linalg.cond(P))
    cond_warn = bool(cond_number
                     > config["ground_truth"].get("cond_warn", _DEFAULT_COND_WARN))

    # Uncertainty: the existing delta-method generalised from two to three refs.
    # G rows = unit vectors from each reference to q; least-squares pseudo-inverse
    # J = (G^T G)^-1 G^T maps tape errors to (x, z).
    sigma_tape_m = config["ground_truth"]["sigma_tape_m"]
    G = np.array([(q - p[k]) / max(float(np.hypot(*(q - p[k]))), 1e-12)
                  for k in range(3)])
    J = np.linalg.pinv(G)
    cov = sigma_tape_m**2 * (J @ J.T)

    r, theta_deg = cart_to_polar(q[0], q[1])
    return {
        "x": float(q[0]),
        "z": float(q[1]),
        "r": r,
        "theta_deg": theta_deg,
        "sigma_x": float(np.sqrt(cov[0, 0])),
        "sigma_z": float(np.sqrt(cov[1, 1])),
        "cov_xz": cov,
        "ls_residual_m": ls_residual_m,
        "cond_number": cond_number,
        "cond_warn": cond_warn,
    }
