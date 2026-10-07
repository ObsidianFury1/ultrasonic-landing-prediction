"""Phase 3 tests: parallax correction (§5.4) and sub-frame contact fit (§5.5)
against EXACT synthetic geometry from the Phase-1 simulator.

Tolerances:
  * Parallax closed form on exact geometry: < 1e-9 m (pure algebra).
  * Camera-position decomposition from exact H + K: < 1e-6 m (one SVD polar snap).
  * Contact fit on EXACT truth tracks: landing < 5 mm, |t* - t_true| < 0.6 ms. With
    zero detection noise the residual is the +-0.5-frame contact-time BRACKET (the
    last tracked frame sits just before touchdown; contact is bracketed to the next
    inter-frame interval): here ~0.16 frame -> ~3 mm along-track via v_h * dt. Sub-
    frame refinement was investigated and not adopted - the size-height cue is signal-
    starved over this short window and the oblique image-v reversal apex is ~1 frame
    offset from world contact (IMPLEMENTATION_NOTES Phase 3). The bound is far inside
    the 15 mm GO gate; landing is dominated by the clean centroid track, not t*.
"""

import numpy as np
import pytest

from optical.calibration import apply_homography
from optical.contact import fit_contact
from optical.geometry import (CameraGeometry, estimate_camera_position,
                             parallax_correct)
from optical.track import Track, find_descent
from simulator import render, scenarios
from simulator.render import floor_to_pixel, make_camera, project_points

# [WO-OPT-4 Stage 3 hardcode audit] Config-driven, never a literal 0.0335.
R_BALL = render.config_r_ball()


@pytest.fixture(scope="module")
def scene():
    sc = scenarios.nominal()          # 640x360 is fine: no rendering used here
    res = render.render_sequence(sc)
    return sc, res


# --------------------------------------------------------------------------- #
# Parallax (§5.4)                                                              #
# --------------------------------------------------------------------------- #

def test_parallax_correction_exact_geometry(scene):
    """A point at height h above P_true, mapped through the FLOOR homography, then
    corrected with the exact camera centre, must return P_true exactly."""
    sc, res = scene
    H_px2floor = np.linalg.inv(res.H_true)
    rng = np.random.default_rng(11)
    for _ in range(50):
        P_true = rng.uniform([-0.5, -0.8], [1.5, 1.0])
        h = rng.uniform(0.01, 0.6)
        world = np.array([P_true[0], h, P_true[1]])
        uv = project_points(res.cam, world)[0]
        P_mapped = apply_homography(H_px2floor, uv)[0]
        recovered = parallax_correct(P_mapped, h, res.cam.C)
        assert np.linalg.norm(recovered - P_true) < 1e-9


def test_parallax_zero_height_is_identity(scene):
    _, res = scene
    P = np.array([0.7, -0.2])
    assert np.allclose(parallax_correct(P, 0.0, res.cam.C), P)


def test_parallax_rejects_camera_below_point(scene):
    _, res = scene
    with pytest.raises(ValueError, match="camera height"):
        parallax_correct(np.array([0.5, 0.0]), h=2.0, C=np.array([3.5, 1.5, 0.0]))


def test_camera_position_decomposition(scene):
    """§5.4: C 'decomposed from H + intrinsics' — recover the exact simulator
    camera centre from the pixel->floor homography and K."""
    _, res = scene
    H_px2floor = np.linalg.inv(res.H_true)
    C_est = estimate_camera_position(H_px2floor, res.cam.K)
    err = np.linalg.norm(C_est - res.cam.C)
    print(f"\n[parallax] camera-position decomposition error: {err:.2e} m")
    assert err < 1e-6


def test_camera_position_from_fitted_H(scene):
    """Same decomposition through a FITTED H (exact correspondences): survives the
    float32 fit noise at the mm level."""
    sc, res = scene
    from optical.calibration import fit_homography
    floor = np.array(list(sc.markers_true.values()), dtype=float)
    pixels = floor_to_pixel(res.H_true, floor)
    H_fit, _ = fit_homography(pixels, floor)
    C_est = estimate_camera_position(H_fit, res.cam.K)
    assert np.linalg.norm(C_est - res.cam.C) < 0.005


def test_nearest_rotation_is_reflection_safe():
    """WO-OPT-3 Stage 5: the SVD snap in decompose_camera forces a PROPER rotation (det +1)
    even on a near-reflection input, so a noisy decomposition can never yield an improper
    (mirrored) pose; a well-conditioned rotation is left unchanged."""
    from optical.geometry import _nearest_rotation
    from simulator.render import make_camera
    rng = np.random.default_rng(0)
    A = np.diag([1.0, 1.0, -1.0]) + 1e-3 * rng.standard_normal((3, 3))   # ~improper frame
    R = _nearest_rotation(A)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)              # proper rotation
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)                    # orthonormal
    R_good = make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.0), (1280, 720), 62.0).R
    assert np.allclose(_nearest_rotation(R_good), R_good, atol=1e-9)     # unchanged (det +1)


# --------------------------------------------------------------------------- #
# Contact fit (§5.5) on exact truth tracks                                     #
# --------------------------------------------------------------------------- #

def _truth_track(res) -> Track:
    """Track built from simulator TRUTH arrays: centroid = projected centre, lowest =
    projected 3D bottom pole, radius = exact ball_radius_px (the size range cue).
    Isolates the fit from detection noise; the size-height solve is exact at contact."""
    n = len(res.times)
    return Track(times=res.times, centroid_px=res.ball_center_px.copy(),
                 lowest_px=res.ball_bottom_px.copy(), status=["ok"] * n,
                 radius_px=res.ball_radius_px.copy())


def test_contact_fit_recovers_truth(scene):
    sc, res = scene
    track = _truth_track(res)
    descent = find_descent(track, window=10)
    H_px2floor = np.linalg.inv(res.H_true)

    result = fit_contact(track, descent, H_px2floor, sc.r_ball,
                         sc.fps_measured, camera=CameraGeometry.from_model(res.cam))

    t_err_ms = abs(result.t_star - res.contact_time_s) * 1e3
    land_err = np.linalg.norm(result.landing_xz - res.contact_xz)
    low_err = np.linalg.norm(result.landing_lowest_xz - res.contact_xz)
    print(f"\n[contact] t* error: {t_err_ms:.3f} ms "
          f"({t_err_ms * sc.fps_measured / 1e3:.3f} frames)")
    print(f"[contact] landing error analytic: {land_err * 1000:.2f} mm, "
          f"lowest-pixel fallback: {low_err * 1000:.2f} mm")
    assert result.method == "analytic_centroid"
    assert t_err_ms < 0.6
    assert land_err < 0.005          # +-0.5-frame bracket -> ~3 mm along-track here
    assert low_err < 0.005
    assert result.sigma_t_s < 2e-3
    assert result.n_descent_frames == 10


def test_contact_prefer_lowest_is_the_deliberate_fallback(scene):
    """§5.4: the lowest-pixel method selected deliberately (cross-check arm) keeps
    the same t* machinery, flags itself, and lands close to the analytic method."""
    sc, res = scene
    track = _truth_track(res)
    descent = find_descent(track, window=10)
    result = fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                         sc.fps_measured, camera=CameraGeometry.from_model(res.cam),
                         prefer_lowest=True)
    assert result.method == "lowest_pixel"
    assert "parallax_fallback_used" in result.flags
    assert np.allclose(result.landing_xz, result.landing_lowest_xz)
    assert np.linalg.norm(result.landing_xz - res.contact_xz) < 0.004


def test_contact_coarse_mode_without_camera_position(scene):
    """No camera position at all: contact bounded to half a frame, landing from the
    mapped-bottom fit, loudly flagged. Sanity-bounded, deliberately not precise."""
    sc, res = scene
    track = _truth_track(res)
    descent = find_descent(track, window=10)
    result = fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                         sc.fps_measured, camera=None)
    assert result.method == "lowest_pixel"
    assert "parallax_fallback_used" in result.flags
    assert "contact_time_coarse" in result.flags
    assert result.sigma_t_s == pytest.approx(0.5 / sc.fps_measured)
    err = np.linalg.norm(result.landing_xz - res.contact_xz)
    print(f"\n[contact] coarse-mode landing error: {err * 1000:.1f} mm")
    assert err < 0.030


def test_contact_fit_small_window_uses_linear(scene):
    """N=5 descent frames -> degree-1 fits still produce a sane landing."""
    sc, res = scene
    track = _truth_track(res)
    descent = find_descent(track, window=5)
    result = fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                         sc.fps_measured, camera=CameraGeometry.from_model(res.cam))
    assert np.linalg.norm(result.landing_xz - res.contact_xz) < 0.006


def test_contact_requires_four_frames(scene):
    sc, res = scene
    track = _truth_track(res)
    descent = find_descent(track, window=10)
    descent.indices = descent.indices[-3:]
    with pytest.raises(ValueError, match=">= 4"):
        fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                    sc.fps_measured, camera=CameraGeometry.from_model(res.cam))


def test_reversal_kink_recovers_exact_contact():
    """§5.5 (v1.2) kink solve on a FABRICATED piecewise-linear image-v track: rising at
    +8 px/frame, kink at a known sub-frame instant, falling at -6 px/frame. The
    intersection of the two branches must recover the kink to << 0.1 frame (tolerance
    0.02 frame: two exact linear fits intersecting — pure algebra, slack only for the
    peak-sample exclusion). Position tracks are linear so the landing maths stays sane."""
    from optical.track import DescentSegment
    fps = 480.0
    t_true = 13.62                     # kink between samples 13 and 14, sub-frame
    n = 18
    frames = np.arange(n, dtype=float)
    v = np.where(frames <= t_true, 300.0 + 8.0 * frames,
                 300.0 + 8.0 * t_true - 6.0 * (frames - t_true))
    centroid = np.column_stack([600.0 + 2.0 * frames, v])
    track = Track(times=frames / fps, centroid_px=centroid,
                  lowest_px=centroid + [0.0, 8.0], status=["ok"] * n,
                  radius_px=np.full(n, 5.0))
    seg = find_descent(track, window=10)
    assert seg.end_reason == "reversal"
    H = np.eye(3) * 0.01; H[2, 2] = 1.0          # trivial px->floor scaling map
    res = fit_contact(track, seg, H, R_BALL, fps,
                      camera=CameraGeometry(K=np.eye(3), R=np.eye(3),
                                            C=np.array([0.0, 2.0, 0.0])))
    assert "contact_time_kink" in res.flags
    assert abs(res.t_subframe - t_true) < 0.02


def test_reversal_without_rebound_frames_anchors_at_peak():
    """When the kink cannot be solved (apex window carries < 2 post-peak frames), t*
    anchors AT the peak frame (no +0.5 — the peak IS touchdown up to sampling), with
    the widened sigma (one frame/sqrt(3), uniform over +-1 frame) and the bracket flag."""
    from optical.track import DescentSegment
    fps = 480.0
    n = 12
    frames = np.arange(n, dtype=float)
    centroid = np.column_stack([600.0 + 2.0 * frames, 300.0 + 8.0 * frames])
    track = Track(times=frames / fps, centroid_px=centroid,
                  lowest_px=centroid + [0.0, 8.0], status=["ok"] * n,
                  radius_px=np.full(n, 5.0))
    seg = DescentSegment(indices=np.arange(n), end_reason="reversal", flags=[],
                         reversal_index=n - 1, apex_indices=np.arange(n - 2, n))
    H = np.eye(3) * 0.01; H[2, 2] = 1.0
    res = fit_contact(track, seg, H, R_BALL, fps,
                      camera=CameraGeometry(K=np.eye(3), R=np.eye(3),
                                            C=np.array([0.0, 2.0, 0.0])))
    assert "contact_time_bracket" in res.flags and "contact_time_kink" not in res.flags
    assert res.t_subframe == pytest.approx(n - 1, abs=1e-6)      # AT the peak, no +0.5
    assert res.sigma_t_s == pytest.approx((1.0 / fps) / np.sqrt(3.0))


def test_contact_size_refinement_declines_falls_back_to_bracket(scene):
    """When the apparent-size height reconstruction gives no usable r_ball crossing
    (here: constant radius => no height signal), the fit does NOT fail or fabricate a
    size-driven answer — it falls back to the robust bracket t* and flags it. (The
    genuine 'no contact at all' case is caught UPSTREAM by find_descent, tested in
    test_track.py::test_no_descending_run_raises_cleanly.)"""
    sc, res = scene
    n = 12
    times = np.arange(n) / sc.fps_measured
    centroid = np.tile([600.0, 300.0], (n, 1))
    centroid[:, 1] += np.linspace(0, 10.0, n)     # descending in image
    lowest = centroid + [0.0, 10.0]
    radius = np.full(n, 4.0)                        # constant => no height signal
    track = Track(times=times, centroid_px=centroid, lowest_px=lowest,
                  status=["ok"] * n, radius_px=radius)
    from optical.track import DescentSegment
    descent = DescentSegment(indices=np.arange(n), end_reason="track_end", flags=[])
    result = fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                         sc.fps_measured, camera=CameraGeometry.from_model(res.cam))
    assert "contact_time_bracket" in result.flags
    assert result.t_subframe == pytest.approx(n - 1 + 0.5, abs=1e-6)
