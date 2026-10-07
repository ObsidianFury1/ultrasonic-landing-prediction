"""Range corrections (CLAUDE.md section 8.2): temperature, ball radius, temporal.

Order of application (correct_triplets):
  (a) temperature: echo microseconds -> metres at the session temperature;
  (b) ball radius (R2): measured ranges point at the ball SURFACE; add
      ball.radius_m so trilateration sees the centre;
  (c) temporal, Option A (R3): same-sensor forward difference on mid-echo
      t_sample timestamps, extrapolating S2/S3 back to the triplet's S1
      sample instant. Optional central-difference upgrade (A4).

Also provides the A4 zenith-curvature characterization
(temporal_residual_vs_speed) for the report's error budget.

Pure arrays in / arrays out; no I/O. Triplet data is (N, 3) arrays
(rows = triplets, columns = S1, S2, S3).
"""

from dataclasses import dataclass, field

import numpy as np


def speed_of_sound(t_celsius: float) -> float:
    """v = 331.4 + 0.606*T [m/s] (section 5.2; coefficients per course notes)."""
    return 331.4 + 0.606 * t_celsius


def echo_us_to_m(echo_us, t_celsius: float):
    """(a) Round-trip echo time [us] -> one-way distance [m]; timeout 0 -> NaN."""
    echo = np.asarray(echo_us, dtype=float)
    d = speed_of_sound(t_celsius) * echo * 1e-6 / 2.0
    d = np.where(echo == 0, np.nan, d)
    return float(d) if np.isscalar(echo_us) else d


def mid_echo_sample_time_us(t_trig_us, echo_us):
    """(R3) Physical sampling instant: t_sample = t_trig + echo/2 [us, float].

    The ball is interrogated when the pulse reaches it (one-way time =
    echo/2), not at TRIG. Timeouts have echo == 0, so t_sample = t_trig,
    which is fine — they are flagged invalid downstream anyway.
    """
    return np.asarray(t_trig_us, dtype=float) + np.asarray(echo_us, dtype=float) / 2.0


def add_ball_radius(d_surface_m, radius_m: float):
    """(R2) Surface range -> centre range. NaN-transparent."""
    return np.asarray(d_surface_m, dtype=float) + radius_m


def apply_sensor_offset(d_m, offset_m):
    """(Phase 5, CLAUDE.md S4D) Per-sensor electronic-offset subtraction.

    corrected = measured - offset, where offset_m is a (3,) sequence [m]
    (S1, S2, S3) = analyze_static's mean-minus-reference from the flat-board
    characterization. A NEGATIVE offset (sensor reads short) therefore ADDS
    distance. This is a MEASUREMENT-layer correction, deliberately OUTSIDE
    bias.py (which handles only the throw-aligned drag residual).

    NaN-transparent; broadcasts the (3,) offset across (N, 3) triplet arrays.
    offset_m None (or an all-zero vector) -> the input is returned unchanged.
    """
    if offset_m is None:
        return np.asarray(d_m, dtype=float)
    off = np.asarray(offset_m, dtype=float)
    if off.shape[-1] != 3:
        raise ValueError(f"sensor_offset_m must have 3 entries (S1,S2,S3), got {off.shape}")
    return np.asarray(d_m, dtype=float) - off


def temporal_correction(d_centre, t_sample_s, central_difference: bool = False):
    """(c) Align S2/S3 ranges to the triplet's S1 sample instant (Option A).

    d_centre    : (N, 3) centre ranges [m] (NaN where invalid)
    t_sample_s  : (N, 3) mid-echo sample times [s]
    Returns (d_aligned (N, 3), usable (N,) bool). S1 passes through unchanged.

    central_difference=False (legacy forward): v_i[n] from triplets (n, n+1);
    the last triplet has no successor and is flagged unusable (keeps N-1).

    central_difference=True (D1 HYBRID stencil, production default): forward
    difference at the first triplet, central difference (n-1, n+1) for every
    interior triplet, backward difference at the last triplet. Keeps ALL N
    triplets (the old pure-central path dropped both endpoints; forward kept
    N-1). Central cancels the leading curvature-bias term on the interior;
    the endpoints retain their one-sided estimate. NaN fallback (hybrid only):
    if a needed neighbour is a timeout/NaN, the triplet falls back to whichever
    ONE-SIDED difference is still available (forward or backward); if neither
    neighbour is valid it is flagged unusable — never a velocity from a single
    point.
    In both modes a NaN in the triplet's OWN reading propagates to its
    d_aligned and flags it unusable (flags, never deletions).
    """
    d = np.asarray(d_centre, dtype=float)
    t = np.asarray(t_sample_s, dtype=float)
    if d.shape != t.shape or d.ndim != 2 or d.shape[1] != 3:
        raise ValueError(f"expected matching (N, 3) arrays, got {d.shape} and {t.shape}")

    n = len(d)
    v = np.full_like(d, np.nan)
    with np.errstate(invalid="ignore"):
        if central_difference:
            # (D1) HYBRID stencil: forward @ first, central @ interior,
            # backward @ last — keeps ALL N triplets (forward mode keeps N-1).
            v_fwd = np.full_like(d, np.nan)    # needs n+1
            v_bwd = np.full_like(d, np.nan)    # needs n-1
            v_cen = np.full_like(d, np.nan)    # needs n-1 and n+1
            if n >= 2:
                step = (d[1:] - d[:-1]) / (t[1:] - t[:-1])
                v_fwd[:-1] = step
                v_bwd[1:] = step
            if n >= 3:
                v_cen[1:-1] = (d[2:] - d[:-2]) / (t[2:] - t[:-2])
            # Preferred stencil per row: central interior, forward first,
            # backward last.
            v = v_cen.copy()
            if n >= 1:
                v[0] = v_fwd[0]
                v[-1] = v_bwd[-1]
            # NaN fallback: where the preferred stencil is NaN (a needed
            # neighbour was a timeout), fall back to whichever ONE-SIDED
            # difference is still available; if neither is, the row stays NaN
            # (unusable). Never a velocity from a single point. The endpoints'
            # unavailable one-sided difference is already NaN, so this cannot
            # invent a value there.
            fallback = np.where(np.isfinite(v_fwd), v_fwd, v_bwd)
            v = np.where(np.isfinite(v), v, fallback)
        else:
            # Legacy forward-only (unchanged): last triplet has no successor
            # and stays NaN -> flagged unusable (keeps N-1).
            if n >= 2:
                v[:-1] = (d[1:] - d[:-1]) / (t[1:] - t[:-1])
        dt_back = t[:, [0]] - t                # 0 for S1, ~-18/-36 ms for S2/S3
        d_aligned = d + v * dt_back
    d_aligned[:, 0] = d[:, 0]                  # S1 needs no correction
    usable = np.all(np.isfinite(d_aligned), axis=1)
    return d_aligned, usable


@dataclass(frozen=True)
class CorrectedTriplets:
    """Output of the full correction chain for one session's triplets."""
    d_centre: np.ndarray      # (N, 3) centre ranges at each sensor's own instant
    d_aligned: np.ndarray     # (N, 3) ranges aligned to the S1 sample instant
    t_sample_us: np.ndarray   # (N, 3) mid-echo sample times [us, float]
    usable: np.ndarray = field(repr=False)  # (N,) bool


def correct_triplets(echo_us, t_trig_us, t_celsius: float, radius_m: float,
                     central_difference: bool = False) -> CorrectedTriplets:
    """Full chain (a) -> (b) -> t_sample -> (c) on (N, 3) raw triplet arrays."""
    d_surface = echo_us_to_m(echo_us, t_celsius)
    d_centre = add_ball_radius(d_surface, radius_m)
    t_sample_us = mid_echo_sample_time_us(t_trig_us, echo_us)
    d_aligned, usable = temporal_correction(
        d_centre, t_sample_us * 1e-6, central_difference=central_difference)
    return CorrectedTriplets(d_centre=d_centre, d_aligned=d_aligned,
                             t_sample_us=t_sample_us, usable=usable)


def temporal_residual_vs_speed(config: dict, speeds_m_s=(1.0, 2.0, 3.0, 4.0),
                               temperature_c: float = 20.0) -> dict:
    """(A4) Characterize the Option-A zenith curvature residual vs transverse speed.

    For each speed v, a noise-free throw crosses horizontally over sensor S1
    with closest approach d = 1 m (apex exactly above S1), and the maximum
    |d_aligned - d_true(at the S1 sample instant)| over S2/S3 of all usable
    in-flight triplets is reported, for both forward and central-difference
    modes. Note: the curvature d-dot-dot includes a gravity term -g*(y-h)/d
    of the same order as the v_perp^2/d geometric term the audit cited, so
    the residual is NOT monotonic in v — it is bounded, cm-scale, and the
    central-difference mode reduces it (report material).

    Returns per-speed lists for `forward_m` / `central_m` (worst residual over
    ALL usable in-flight triplets) and `forward_interior_m` /
    `central_interior_m` (worst over INTERIOR triplets only, excluding the
    first and last in-flight triplet). The endpoints use the same one-sided
    stencil in both modes (hybrid: forward@first/backward@last; forward mode:
    forward), so they tie; the hybrid gain is on the interior, where it
    replaces forward with central — hence the interior split.
    """
    # Local import: simulator imports this module at module level.
    from pipeline.simulator import G, ThrowParams, generate_session

    from pipeline.geometry import ArrayGeometry

    geom = ArrayGeometry.from_config(config)
    s1 = geom.vertices_3d[0]
    radius = config["ball"]["radius_m"]
    rng = np.random.default_rng(0)             # unused (noise-free) but required

    out = {"speeds_m_s": list(speeds_m_s), "forward_m": [], "central_m": [],
           "forward_interior_m": [], "central_interior_m": []}
    for v in speeds_m_s:
        # Lofted throw whose apex (zenith, fully transverse motion) is exactly
        # 1 m above S1's acoustic centre, reached 0.3 s after release.
        t_up = 0.3
        vy = G * t_up
        throw = ThrowParams(
            x0=float(s1[0]) - v * t_up, y0=float(s1[1]) + 1.0 - 0.5 * G * t_up**2,
            z0=float(s1[2]), vx=v, vy=vy, vz=0.0,
        )
        session = generate_session(config, throw, temperature_c=temperature_c,
                                   noise_mm=0.0, rng=rng, n_bg_pre=2, n_bg_post=2)
        echo, t_trig, target = session.triplet_arrays()
        t_launch = session.truth["t_launch_s"]
        sensors = geom.vertices_3d

        # Interior = in-flight triplets excluding the first and last, where
        # both modes use the same one-sided stencil. Defined on the flight
        # window so the two modes compare the same triplets.
        flight = np.flatnonzero(target)
        interior = set(flight[1:-1].tolist()) if len(flight) >= 3 else set()
        for mode, key, ikey in ((False, "forward_m", "forward_interior_m"),
                                (True, "central_m", "central_interior_m")):
            res = correct_triplets(echo, t_trig, temperature_c, radius,
                                   central_difference=mode)
            worst = worst_interior = 0.0
            for n in np.flatnonzero(res.usable & target):
                t_s1 = res.t_sample_us[n, 0] * 1e-6
                pos = session.trajectory.position(t_s1 - t_launch)
                d_true = np.linalg.norm(sensors - pos, axis=1)
                resid = float(np.max(np.abs(res.d_aligned[n, 1:] - d_true[1:])))
                worst = max(worst, resid)
                if n in interior:
                    worst_interior = max(worst_interior, resid)
            out[key].append(worst)
            out[ikey].append(worst_interior)
    return out
