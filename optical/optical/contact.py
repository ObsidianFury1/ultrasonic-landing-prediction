"""Sub-frame first contact (Optical.md §5.5, as amended v1.2) — physics-based, no ML (Zone 3).

Design, and why (all MEASURED; IMPLEMENTATION_NOTES Phase 3 + WO-OPT-1 Stage 4):

  Over the short near-contact window the ball's monocular height is only weakly
  observable. Two literal sub-frame designs were built, measured, and REJECTED (not wired
  in): (1) an image-vertical crossing fit, defeated by a ~1 px systematic between the
  detected silhouette bottom (mask-morphology inflated) and the true 3D bottom pole; and
  (2) an apparent-size height reconstruction — exact on noise-free truth but signal-starved
  here (the ball's pixel radius changes only ~0.05 px over the ~10-frame window while the
  detector radius carries a ~0.9 px bias). The size-reconstruction geometry
  (`geometry.reconstruct_world_point`, and the local `_root_near` helper) is retained
  DORMANT-BY-DESIGN for reporting / re-evaluation on real footage — it is on no default path.

  t* by descent end:
    * 'track_end' (ball vanishes / leaves frame): the +0.5-frame BRACKET — the last
      airborne frame is strictly pre-contact, so contact is bracketed to the next
      inter-frame interval; sigma_t = one frame / sqrt(12). Flag 'contact_time_bracket'.
    * 'reversal' (real bounce): the KINK intersection (`_reversal_kink_offset`) — the ball's
      image position is CONTINUOUS through the bounce and only the vertical-velocity sign
      flips, so the pre-contact and post-peak image-v fits meet in a kink exactly at contact,
      invariant to camera obliquity. Flag 'contact_time_kink'. Peak-anchor fallback when
      unsolvable (t* AT the peak, no +0.5, sigma_t = one frame / sqrt(3),
      'contact_time_bracket'). This replaced the pre-v1.2 bracket, which ran ~0.6 frame late
      on a bounce (10-18 mm landing error, over the §8 gate at an oblique camera).

  landing (analytic_centroid, primary, §5.4): the parallax-corrected CENTROID floor-track at
  t*; lowest_pixel fallback/cross-check = mapped bottom track. Landing accuracy is dominated
  by the clean, sub-pixel, morphology-unbiased centroid track, not by t* resolution.

Contact duration for a basketball has NOT been verified against a primary source and may
span more frames at 480 fps than the tennis ball did; confirm it empirically at
commissioning, do not assume it (Optical.md §5.5). [AMENDED v1.5 / WO-OPT-4 — Decision D21;
was: "for a tennis ball is a few ms — possibly zero true contact frames even at 480 fps".]
The reasoning is unchanged either way: first contact falls BETWEEN samples whatever the
contact span, which is why the fit/bracket, not a single frame, defines the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from optical.calibration import apply_homography
from optical.errors import OpticalDataError
from optical.geometry import CameraGeometry, parallax_correct
from optical.track import DescentSegment, Track

COARSE_FLAG = "contact_time_coarse"
BRACKET_FLAG = "contact_time_bracket"
KINK_FLAG = "contact_time_kink"
FALLBACK_FLAG = "parallax_fallback_used"


@dataclass
class ContactResult:
    t_star: float                 # contact time [s], same base as track.times
    t_frame: int                  # index of the last descent frame (integer anchor)
    t_subframe: float             # t_star expressed in frame units (t_star * fps)
    landing_xz: np.ndarray        # (2,) headline landing (method below)
    landing_lowest_xz: np.ndarray # (2,) lowest-pixel fallback landing
    method: str                   # 'analytic_centroid' | 'lowest_pixel'
    vel_xz: np.ndarray            # (2,) fitted landing-track velocity at t* [m/s]
    sigma_t_s: float              # 1-sigma of t* (uniform-window assignment, §5.5)
    n_descent_frames: int
    flags: list = field(default_factory=list)


def _polyfit(t, y, deg):
    coeffs = np.polyfit(t, y, deg)
    resid = y - np.polyval(coeffs, t)
    dof = max(len(t) - (deg + 1), 1)
    rms = float(np.sqrt(np.sum(resid ** 2) / dof))
    return coeffs, rms


def _root_near(coeffs, target, t_near):
    """Real root of polyval(coeffs, t) == target nearest t_near; clean error if none."""
    c = np.array(coeffs, dtype=float)
    c[-1] -= target
    roots = np.roots(c)
    real = roots[np.abs(roots.imag) < 1e-9].real
    if len(real) == 0:
        raise ValueError("reconstructed height never reaches r_ball on the descent - "
                         "no contact geometry (clean failure, nothing reported)")
    return float(real[np.argmin(np.abs(real - t_near))])


def _reversal_kink_offset(track: Track, descent: DescentSegment, cV_pre,
                          t0: float, fps_measured: float) -> float | None:
    """Sub-frame contact instant for a REVERSAL end (WO-OPT-1 Stage 4 / audit M4).

    Physics: the ball's image position is CONTINUOUS through the bounce; only the
    vertical velocity flips sign at touchdown. Image-v(t) is therefore a rising branch
    (descent) meeting a falling branch (rebound) in a KINK exactly at contact — under
    ANY camera obliquity, because the horizontal-motion tilt of image-v is continuous
    and cannot move the kink. Solving the intersection of the pre-contact fit `cV_pre`
    and a linear fit of the post-peak rebound frames localises contact to well below
    one frame (this is what the Phase-3 parabola-VERTEX idea got wrong: a smooth
    extremum is shifted by the tilt, an intersection of the two branches is not).

    Returns the time offset (relative to t0 = peak-frame time) of the real intersection
    nearest the peak, sanity-clamped to +-1.5 frames; None when it cannot be solved
    (too few rebound frames, degenerate fits, no root in the clamp) — caller falls back
    to the peak-anchored bracket.
    """
    if descent.apex_indices is None or descent.reversal_index is None:
        return None
    post = descent.apex_indices[descent.apex_indices > descent.reversal_index]
    if len(post) < 2:
        return None
    tp = track.times[post] - t0
    vp = track.centroid_px[post, 1]
    cPost = np.polyfit(tp, vp, 1)         # rebound is ~linear over a few ms
    diff = np.polysub(cV_pre, cPost)
    if np.allclose(diff, 0.0):
        return None
    roots = np.roots(diff)
    real = roots[np.abs(roots.imag) < 1e-9].real
    cand = real[np.abs(real) <= 1.5 / fps_measured]
    if len(cand) == 0:
        return None
    return float(cand[np.argmin(np.abs(cand))])


def fit_contact(track: Track, descent: DescentSegment, H_px2floor: np.ndarray,
                r_ball: float, fps_measured: float,
                camera: CameraGeometry | None = None,
                prefer_lowest: bool = False) -> ContactResult:
    """Fit the descent and solve the first contact t* (§5.5, as amended v1.2).

    t* selection by descent end reason:
      * 'reversal' (real bounce — the path real footage takes): KINK solve — the
        intersection of the pre-contact image-v fit and the post-peak rebound fit
        (`_reversal_kink_offset`); flag 'contact_time_kink'. If unsolvable, fall back
        to anchoring t* AT the peak frame (no +0.5 — the peak IS touchdown up to
        sampling), sigma widened to one frame/sqrt(3) (contact within +-1 frame);
        flag 'contact_time_bracket'. The peak sample itself is excluded from all
        fits (it may be pre- or post-contact — ambiguous side of the kink).
      * 'track_end' (ball vanishes/leaves): the original +0.5-frame bracket, sigma
        one frame/sqrt(12), flag 'contact_time_bracket' — unchanged, and correct
        there (the last frame is strictly pre-contact).

    camera: full camera pose (K, R, C) for the §5.4 parallax correction. None ->
    COARSE fallback: same t* selection, landing from the mapped-bottom fit, flags
    'parallax_fallback_used' + 'contact_time_coarse'.
    prefer_lowest: with a camera present, make the lowest-pixel landing the headline
    (§5.4 fallback chosen deliberately); the t* solve is unchanged.
    """
    idx = descent.indices
    n = len(idx)
    reversal = descent.end_reason == "reversal"
    # For a reversal the LAST descent frame is the image-v peak = the touchdown-adjacent
    # sample; it may sit on either side of the kink, so exclude it from the fits.
    fit_idx = idx[:-1] if reversal else idx
    if len(fit_idx) < 4:
        raise OpticalDataError(f"descent window has {len(fit_idx)} usable fit frames - "
                               f"need >= 4 for a quadratic fit with residual dof")
    t0 = float(track.times[idx[-1]])     # shift origin to the descent end: conditioning
    t = track.times[fit_idx] - t0
    deg = 2 if len(fit_idx) >= 6 else 1

    M_b = apply_homography(H_px2floor, track.lowest_px[fit_idx])
    cBx, _ = _polyfit(t, M_b[:, 0], deg)
    cBz, _ = _polyfit(t, M_b[:, 1], deg)
    cV, _ = _polyfit(t, track.centroid_px[fit_idx, 1], deg)
    flags = list(descent.flags)

    # ---- t* selection (see docstring) ----------------------------------------- #
    if reversal:
        ts = _reversal_kink_offset(track, descent, cV, t0, fps_measured)
        if ts is not None:
            sigma_t = (1.0 / fps_measured) / np.sqrt(12.0)   # conservative: the kink
            # solve is much better than a frame on clean data, but keep the one-frame
            # uniform sigma until real-footage residuals justify shrinking it (§7).
            flags.append(KINK_FLAG)
        else:
            ts = 0.0                                          # anchor AT the peak frame
            sigma_t = (1.0 / fps_measured) / np.sqrt(3.0)     # uniform over +-1 frame
            flags.append(BRACKET_FLAG)
    else:
        ts = 0.5 / fps_measured
        sigma_t = (1.0 / fps_measured) / np.sqrt(12.0)
        flags.append(BRACKET_FLAG)

    if camera is None:
        landing_lowest = np.array([np.polyval(cBx, ts), np.polyval(cBz, ts)])
        vel = np.array([np.polyval(np.polyder(cBx), ts),
                        np.polyval(np.polyder(cBz), ts)])
        flags += [FALLBACK_FLAG, COARSE_FLAG]
        return ContactResult(
            t_star=float(ts + t0), t_frame=int(idx[-1]),
            t_subframe=float((ts + t0) * fps_measured),
            landing_xz=landing_lowest.copy(), landing_lowest_xz=landing_lowest,
            method="lowest_pixel", vel_xz=vel,
            sigma_t_s=float(max(sigma_t, 0.5 / fps_measured)),   # coarse mode stays
            n_descent_frames=n, flags=flags)                     # deliberately imprecise

    # Centroid PIXEL track (clean, near-linear projection of the parabola). The
    # parallax correction is nonlinear and exact only when the ball is at height
    # r_ball (i.e. AT contact), so we fit the raw pixel, evaluate at t*, and apply
    # the parallax ONCE there - rather than fitting the already-corrected track
    # (which is biased off-contact and drags the extrapolation with it). L(t) below
    # is kept only for the floor velocity.
    cU, _ = _polyfit(t, track.centroid_px[fit_idx, 0], deg)
    M_c = apply_homography(H_px2floor, track.centroid_px[fit_idx])
    L = parallax_correct(M_c, r_ball, camera.C)
    cLx, _ = _polyfit(t, L[:, 0], deg)
    cLz, _ = _polyfit(t, L[:, 1], deg)

    uv_star = np.array([np.polyval(cU, ts), np.polyval(cV, ts)])
    M_c_star = apply_homography(H_px2floor, uv_star)[0]
    landing_analytic = parallax_correct(M_c_star, r_ball, camera.C)
    landing_lowest = np.array([np.polyval(cBx, ts), np.polyval(cBz, ts)])
    vel = np.array([np.polyval(np.polyder(cLx), ts),
                    np.polyval(np.polyder(cLz), ts)])

    if prefer_lowest:
        landing, method = landing_lowest, "lowest_pixel"
        flags.append(FALLBACK_FLAG)
    else:
        landing, method = landing_analytic, "analytic_centroid"

    return ContactResult(
        t_star=float(ts + t0), t_frame=int(idx[-1]),
        t_subframe=float((ts + t0) * fps_measured),
        landing_xz=landing, landing_lowest_xz=landing_lowest,
        method=method, vel_xz=vel, sigma_t_s=float(sigma_t),
        n_descent_frames=n, flags=flags)
