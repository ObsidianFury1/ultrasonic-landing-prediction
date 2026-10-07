"""Array-frame geometry and polar <-> Cartesian conversions.

Coordinate contract (Optical.md/CLAUDE.md §2, mirroring main CLAUDE.md §0.1):

  * Origin: the ultrasonic triangle's centroid, on the floor plane.
  * +x: horizontal, toward the S1 floor mark. This is the theta = 0 reference axis.
  * +y: vertical, up.
  * +z: horizontal, perpendicular to x, completing a right-handed frame; theta is
    measured counter-clockwise viewed from above, going from +x toward +z.

  * Polar output: r = sqrt(x^2 + z^2) [m]; theta = atan2(z, x) in DEGREES, CCW from
    above, in the half-open range (-180, 180].  In particular a point on +x is 0 deg,
    on +z is +90 deg, and on -x is +180 deg (never -180).

All conversion math lives here locally; nothing is imported from the main project
(Optical.md §12: deliberate duplication over coupling). Functions accept Python
scalars or array-likes and preserve that distinction on return.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from optical.errors import OpticalConfigError

__all__ = [
    "cart_to_polar",
    "polar_to_cart",
    "load_config",
    "sensor_positions",
    "centroid_position",
    "CameraGeometry",
    "decompose_camera",
    "estimate_camera_position",
    "parallax_correct",
    "reconstruct_world_point",
]


def _is_scalar(value: Any) -> bool:
    """True if `value` is a plain scalar (so results are returned as Python floats)."""
    return np.isscalar(value) or (isinstance(value, np.ndarray) and value.ndim == 0)


def cart_to_polar(x, z):
    """Convert Cartesian floor coordinates (x, z) [m] to polar (r [m], theta [deg]).

    theta = atan2(z, x) in degrees, normalised to the half-open range (-180, 180]:
    the sole boundary case atan2 can emit as exactly -180 (a point on the -x axis
    reached from the -z side, i.e. z is negative zero) is mapped to +180 so that the
    -x axis is unambiguously +180 deg per the §2 contract.

    Accepts scalars or array-likes; returns (float, float) for scalar input and
    (ndarray, ndarray) for array input.
    """
    scalar = _is_scalar(x) and _is_scalar(z)
    xa = np.asarray(x, dtype=float)
    za = np.asarray(z, dtype=float)

    r = np.hypot(xa, za)
    theta = np.degrees(np.arctan2(za, xa))
    # arctan2 yields (-180, 180] except it can return exactly -180 for z == -0.0.
    # Fold that single value onto +180 to honour the (-180, 180] convention.
    theta = np.where(theta == -180.0, 180.0, theta)

    if scalar:
        return float(r), float(theta)
    return r, theta


def polar_to_cart(r, theta_deg):
    """Convert polar (r [m], theta [deg]) to Cartesian floor coordinates (x, z) [m].

    x = r * cos(theta), z = r * sin(theta), theta in degrees (CCW from +x toward +z).
    Accepts scalars or array-likes; returns (float, float) for scalar input and
    (ndarray, ndarray) for array input.
    """
    scalar = _is_scalar(r) and _is_scalar(theta_deg)
    ra = np.asarray(r, dtype=float)
    ta = np.radians(np.asarray(theta_deg, dtype=float))

    x = ra * np.cos(ta)
    z = ra * np.sin(ta)

    if scalar:
        return float(x), float(z)
    return x, z


def load_config(path: str | Path = "config.yaml") -> dict:
    """Load the project config.yaml as a dict."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sensor_positions(config: dict) -> dict[str, np.ndarray]:
    """Return the surveyed sensor floor positions {S1,S2,S3} as (x, z) arrays [m]."""
    arr = config["array"]
    return {name: np.asarray(arr[f"{name}_xz"], dtype=float) for name in ("S1", "S2", "S3")}


def centroid_position(config: dict) -> np.ndarray:
    """Return the array centroid floor position as an (x, z) array [m] (origin = [0,0])."""
    return np.asarray(config["array"].get("centroid_xz", [0.0, 0.0]), dtype=float)


# --------------------------------------------------------------------------- #
# Parallax correction (Optical.md §5.4) — closed-form floor-plane geometry.    #
# Lives here (not in a dedicated module) because §5's module list has no       #
# parallax module and the correction is pure projective floor geometry.        #
# --------------------------------------------------------------------------- #

@dataclass
class CameraGeometry:
    """Minimal camera pose used by the parallax + size-height math (§5.4, §5.5).
    K: 3x3 intrinsics; R: 3x3 world->camera rotation; C: (3,) camera centre in the
    array frame. Matches the simulator's CameraModel fields (K, R, C)."""
    K: np.ndarray
    R: np.ndarray
    C: np.ndarray

    @classmethod
    def from_homography(cls, H_px2floor: np.ndarray, K: np.ndarray) -> "CameraGeometry":
        C, R = decompose_camera(H_px2floor, K)
        return cls(K=np.asarray(K, dtype=float), R=R, C=C)

    @classmethod
    def from_model(cls, cam) -> "CameraGeometry":
        return cls(K=np.asarray(cam.K, float), R=np.asarray(cam.R, float),
                   C=np.asarray(cam.C, float))


def _nearest_rotation(A: np.ndarray) -> np.ndarray:
    """Nearest proper rotation to a 3x3 matrix via the SVD polar factor, REFLECTION-SAFE
    (WO-OPT-3 Stage 5): R = U diag(1, 1, det(U Vt)) Vt forces det(R) = +1, so a noisy
    near-reflection input can never snap to an improper (mirrored) rotation. For a
    well-conditioned near-rotation input det(U Vt) = +1, so this is identical to U Vt — no
    change to any existing well-conditioned decomposition result."""
    U, _, Vt = np.linalg.svd(np.asarray(A, dtype=float))
    D = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(U @ Vt)))])
    return U @ D @ Vt


def decompose_camera(H_px2floor: np.ndarray, K: np.ndarray
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Recover (C, R): camera centre and world->camera rotation from the calibrated
    pixel->floor homography and intrinsics (§5.4).

    The floor->pixel homography factors as H_f2p = K [c1 | c3 | t] where c1, c3 are
    the first and third COLUMNS of R (world y is the floor normal) and t the
    world->camera translation. M = K^-1 H_f2p, normalised by the mean length of its
    first two columns, recovers (c1, c3, t) up to sign; the sign is fixed by the
    camera being above the floor (C_y > 0). c2 = c3 x c1 completes R (SVD-snapped to
    a true rotation); C = -R^T t.
    """
    H_f2p = np.linalg.inv(np.asarray(H_px2floor, dtype=float))
    M = np.linalg.inv(np.asarray(K, dtype=float)) @ H_f2p
    lam = 0.5 * (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
    if lam < 1e-12:
        raise OpticalConfigError("degenerate homography - cannot decompose camera pose")

    for sign in (1.0, -1.0):
        c1 = sign * M[:, 0] / lam
        c3 = sign * M[:, 1] / lam
        t = sign * M[:, 2] / lam
        c2 = np.cross(c3, c1)
        R = _nearest_rotation(np.column_stack([c1, c2, c3]))   # reflection-safe snap
        C = -R.T @ t
        if C[1] > 0:
            return C, R
    raise OpticalConfigError("camera pose decomposition failed (below-floor solutions for "
                     "both signs - homography or intrinsics inconsistent)")


def estimate_camera_position(H_px2floor: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Camera centre C only (back-compat wrapper over decompose_camera, §5.4)."""
    return decompose_camera(H_px2floor, K)[0]


def reconstruct_world_point(u: float, v: float, r_px: float, r_ball: float,
                            cam: "CameraGeometry") -> np.ndarray:
    """Recover a ball's 3D centre in the array frame from its image centre (u, v) and
    apparent pixel radius r_px, using the size range cue r_px = fx * r_ball / Z_cam
    (§5.5: the ball-bottom/centre height is read from the ball's calibrated apparent
    size, robust to the detector's silhouette-bottom morphology bias).

    Z_cam = fx * r_ball / r_px (camera-axis depth); back-project the centre pixel to
    that depth and rotate into the world:  P_world = R^T (Z_cam * K^-1 [u,v,1]) + C.
    Returns (x, y, z); the height above the floor is P_world[1].
    """
    if r_px <= 1e-6:
        raise ValueError("non-positive ball pixel radius - cannot range by size")
    fx = float(cam.K[0, 0])
    Z_cam = fx * r_ball / r_px
    ray = np.linalg.inv(cam.K) @ np.array([u, v, 1.0])
    ray = ray / ray[2]
    P_cam = Z_cam * ray
    return cam.R.T @ P_cam + cam.C


def parallax_correct(P_mapped, h: float, C) -> np.ndarray:
    """Analytic centroid parallax correction (§5.4, primary method).

    A point physically at height h above floor position P_floor, mapped through the
    FLOOR homography, lands at P_mapped — shifted along the camera-ray ground
    projection. Closed-form inverse:

        P_floor = P_mapped - (h / C_y) * (P_mapped - C_ground),  C_ground = (C_x, C_z)

    P_mapped: (2,) or (N,2) floor coords [m]; h: height above floor [m] (= r_ball at
    contact); C: camera centre (3,) in the array frame. Requires C_y > h.
    """
    P = np.atleast_2d(np.asarray(P_mapped, dtype=float))
    C = np.asarray(C, dtype=float)
    if C[1] <= h:
        raise OpticalConfigError(f"camera height C_y={C[1]:.3f} m must exceed the point "
                         f"height h={h:.3f} m")
    C_ground = np.array([C[0], C[2]])
    out = P - (h / C[1]) * (P - C_ground)
    return out[0] if np.asarray(P_mapped).ndim == 1 else out
