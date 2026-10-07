"""Trilateration: corrected range triplets -> 3D points (CLAUDE.md section 8.3).

Per triplet of centre ranges (already temperature-, radius- and time-aligned
by corrections.py):
  - 2x2 linear solve A @ [x, z] = b in the horizontal plane, with A and the
    constant offsets prebuilt by geometry.ArrayGeometry.trilateration_system().
    The sphere subtraction cancels the sensor-height terms EXACTLY only
    because all three sensors share the same height S_height_m — an
    assumption surveyed to +/-3 mm in Phase 2 (R4) and stated in the report;
    unequal heights would leave residual linear-y terms and invalidate the
    2x2 reduction.
  - Height above the SENSOR plane from ALL THREE spheres (R10a):
    y_k = sqrt(d_k^2 - (x-X_k)^2 - (z-Z_k)^2). Any negative radicand means
    geometrically impossible ranges: the triplet is flagged invalid and
    discarded — NEVER clamped to zero, never abs()'d (NaN guard).
  - y_plane = mean(y_1, y_2, y_3); consistency residual q = max|y_k - y_plane|
    stored per triplet (R10a schema). **Implementation finding, for the
    report:** q is IDENTICALLY ZERO by construction, noise or no noise. The
    2x2 system is precisely the pair of equations "radicand_1 = radicand_k"
    (k = 2, 3), so the solved (x, z) forces all three radicands equal for ANY
    input ranges: the three y_k are not merely correlated (the spec's
    "below sqrt(3)" caveat) but identical — three ranges, three unknowns,
    zero redundancy. q is computed and stored for schema compatibility and as
    a numerical-sanity check (~1e-16), but it carries no information about
    measurement consistency; a genuine per-triplet consistency check would
    require a fourth sensor. Verified empirically in test_trilateration.py.
  - Floor frame (R4): y_floor = y_plane + S_height_m.
  - Per-triplet vertical noise (R6): sigma_y = (d_mean / y_plane) * sigma_pos_m
    (error propagation of y = sqrt(d^2 - rho^2); the overlap floor keeps
    y_plane >~ 0.5 m so d/y <~ 3.5 in practice — the y -> 0 divergence is
    never visited; y_plane == 0 yields inf rather than an exception).

Pure logic, no I/O. Invalid triplets are flagged, never deleted (section 0.4).
"""

from dataclasses import dataclass, field

import numpy as np

from pipeline.geometry import ArrayGeometry


@dataclass(frozen=True)
class TrilaterationResult:
    """Per-triplet outputs; invalid rows are all-NaN with valid=False."""
    x: np.ndarray            # (N,) horizontal position [m]
    z: np.ndarray            # (N,)
    y_plane: np.ndarray      # (N,) height above the SENSOR plane [m]
    y_floor: np.ndarray      # (N,) floor-frame height (R4) [m]
    sigma_y: np.ndarray      # (N,) per-triplet vertical noise (R6) [m]
    q: np.ndarray            # (N,) 3-sphere consistency residual (R10a) [m]
    valid: np.ndarray = field(repr=False)   # (N,) bool


def trilaterate(d_centre, geometry: ArrayGeometry,
                sigma_pos_m: float) -> TrilaterationResult:
    """Solve all N triplets of centre ranges into 3D floor-frame points.

    d_centre : (N, 3) ranges sensor acoustic centre -> ball centre [m],
               time-aligned to a common instant (NaN where invalid upstream).
    """
    d = np.asarray(d_centre, dtype=float)
    if d.ndim != 2 or d.shape[1] != 3:
        raise ValueError(f"expected (N, 3) range array, got {d.shape}")
    n = d.shape[0]

    A, c = geometry.trilateration_system()
    vx = geometry.vertices_xz[:, 0]          # (3,) sensor X_k
    vz = geometry.vertices_xz[:, 1]          # (3,) sensor Z_k

    finite_in = np.all(np.isfinite(d), axis=1)

    # Horizontal solve for every row at once (A is constant and well-
    # conditioned for the equilateral array; invalid rows produce NaN).
    with np.errstate(invalid="ignore", divide="ignore"):
        b = c[None, :] - (d[:, 1:] ** 2 - d[:, [0]] ** 2)
        xz = np.linalg.solve(A, b.T).T       # (N, 2)
        x, z = xz[:, 0], xz[:, 1]

        # Heights above the sensor plane from all three spheres (R10a).
        radicand = d**2 - (x[:, None] - vx[None, :])**2 - (z[:, None] - vz[None, :])**2

        # NaN guard: ANY negative radicand -> impossible geometry -> discard.
        guard_ok = np.all(radicand >= 0.0, axis=1) & finite_in
        y_k = np.sqrt(np.where(radicand >= 0.0, radicand, np.nan))

        y_plane = y_k.mean(axis=1)
        q = np.max(np.abs(y_k - y_plane[:, None]), axis=1)
        y_floor = y_plane + geometry.s_height_m
        sigma_y = np.divide(d.mean(axis=1), y_plane) * sigma_pos_m

    # A ball exactly on the sensor plane gives radicand == 0 -> y_plane == 0 ->
    # sigma_y == inf; such a row must NOT be reported valid (the finite-sigma_y
    # requirement of filter_trajectory would otherwise choke on it). Healthy rows
    # have y_plane > 0 and finite sigma_y, so this only flips the degenerate case.
    valid = guard_ok & np.isfinite(sigma_y)
    nanfill = np.where(valid, 0.0, np.nan)
    return TrilaterationResult(
        x=x + nanfill, z=z + nanfill,
        y_plane=y_plane + nanfill, y_floor=y_floor + nanfill,
        sigma_y=sigma_y + nanfill, q=q + nanfill,
        valid=valid,
    )
