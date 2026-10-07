"""Phase 1 tests: the simulator against ANALYTIC projections (Optical.md §6, §14).

The phase gate is test_rendered_disc_fiducials_match_projection_subpixel plus
test_nadir_projection_hand_computed: rendered fiducial pixel positions must match
the analytic projection to sub-pixel.

Tolerance rationale (per §11, stated per test):
  * Hand-computed analytic checks: 1e-9 px / 1e-12 m — pure float algebra, no
    rasterisation, so machine precision applies.
  * Rendered-and-recovered disc centroids: < 0.3 px — the only error sources are
    LINE_AA rasterisation at 1/16-px fixed point and uint8 quantisation; measured
    well below this in practice, 0.3 px is a stable ceiling.
  * ArUco detected corners: < 1.0 px — bounded by cv2.aruco's corner refinement on a
    clean synthetic oblique view, not by our projection math (which the disc test
    isolates); 1 px is the documented practical accuracy class of the detector.
"""

import cv2
import numpy as np
import pytest

from simulator import render, scenarios

# [WO-OPT-4 Stage 3 hardcode audit] Ball radius and the HSV band are read from config, never
# duplicated as literals here: a literal would keep asserting against the retired tennis ball.
R_BALL = render.config_r_ball()
_BAND = render._config()["detect"]
HSV_LOWER, HSV_UPPER = tuple(_BAND["hsv_lower"]), tuple(_BAND["hsv_upper"])
from simulator.render import (Trajectory, floor_homography, floor_to_pixel,
                              make_camera, pixel_to_floor, point_depth,
                              project_points)


# --------------------------------------------------------------------------- #
# Analytic camera / homography checks                                          #
# --------------------------------------------------------------------------- #

def test_rotation_is_orthonormal_right_handed():
    cam = make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.0), (640, 360), 62.0)
    R = cam.R
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-12)
    # y_cam (image-down) must point downward in the world (negative world-y component)
    assert R[1, 1] < 0


def test_nadir_projection_hand_computed():
    """Fully hand-derived case. Camera at (0, h, 0) looking straight down; the
    look-at fallback picks world +z as up reference, giving x_cam = (-1,0,0),
    y_cam = (0,0,-1), z_cam = (0,-1,0). For a floor point (x, 0, z):
        depth = h,  u = cx - fx*x/h,  v = cy - fx*z/h.
    Compare that closed form against BOTH code paths (3D projection and the floor
    homography). Tolerance 1e-9 px: pure algebra, no rasterisation."""
    h_cam = 2.0
    w, hh = 640, 360
    hfov = 60.0
    fx = (w / 2.0) / np.tan(np.radians(hfov / 2.0))
    cx, cy = w / 2.0, hh / 2.0
    cam = make_camera((0.0, h_cam, 0.0), (0.0, 0.0, 0.0), (w, hh), hfov)
    H = floor_homography(cam)

    for (x, z) in [(0.4, -0.3), (-0.7, 0.55), (0.0, 0.0), (1.1, 1.0)]:
        u_hand = cx - fx * x / h_cam
        v_hand = cy - fx * z / h_cam
        uv_proj = project_points(cam, np.array([[x, 0.0, z]]))[0]
        uv_homo = floor_to_pixel(H, np.array([[x, z]]))[0]
        assert abs(uv_proj[0] - u_hand) < 1e-9 and abs(uv_proj[1] - v_hand) < 1e-9
        assert abs(uv_homo[0] - u_hand) < 1e-9 and abs(uv_homo[1] - v_hand) < 1e-9


def test_homography_agrees_with_3d_projection_oblique():
    """The floor homography and the general 3D projection are independent code paths;
    they must agree to machine precision for arbitrary floor points."""
    cam = make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.0), (1280, 720), 62.0)
    H = floor_homography(cam)
    rng = np.random.default_rng(3)
    xz = rng.uniform(-1.0, 1.7, size=(200, 2))
    uv_h = floor_to_pixel(H, xz)
    pts3 = np.column_stack([xz[:, 0], np.zeros(len(xz)), xz[:, 1]])
    uv_p = project_points(cam, pts3)
    assert np.max(np.abs(uv_h - uv_p)) < 1e-9


def test_pixel_floor_roundtrip():
    cam = make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.0), (1280, 720), 62.0)
    H = floor_homography(cam)
    rng = np.random.default_rng(4)
    xz = rng.uniform(-1.0, 1.7, size=(200, 2))
    back = pixel_to_floor(H, floor_to_pixel(H, xz))
    assert np.max(np.abs(back - xz)) < 1e-9   # pure algebra tolerance


# --------------------------------------------------------------------------- #
# THE PHASE GATE: rendered fiducials vs analytic projection, sub-pixel          #
# --------------------------------------------------------------------------- #

def test_rendered_disc_fiducials_match_projection_subpixel():
    """Render symmetric disc fiducials, recover their centroids from the image, and
    compare with the analytic H projection of the marker floor positions.
    Tolerance 0.3 px (rasterisation + uint8 quantisation only; see module docstring)."""
    sc = scenarios.nominal(fiducial_style="disc", traj=None,
                           resolution=(1280, 720))
    res = render.render_sequence(
        scenarios.nominal(fiducial_style="disc", traj=None, resolution=(1280, 720),
                          t_start=0.0, t_end=0.0))
    frame = res.frames[0]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    n, _, _, centroids = cv2.connectedComponentsWithStats(binary)
    detected = centroids[1:]                       # drop background component
    assert len(detected) == len(sc.markers_true)

    expected = floor_to_pixel(res.H_true,
                              np.array(list(sc.markers_true.values())))
    errors = []
    for exp in expected:
        d = np.linalg.norm(detected - exp, axis=1)
        errors.append(d.min())
    max_err = max(errors)
    print(f"\n[gate] disc fiducial max centroid error: {max_err:.4f} px "
          f"(mean {np.mean(errors):.4f} px)")
    assert max_err < 0.3


def test_aruco_markers_render_and_detect_subpixel():
    """Real DICT_4X4_50 bitmaps warped onto the floor must be detected by cv2.aruco,
    all eight ids, with refined corners within 1.0 px of the analytic projection of
    the marker corners (detector-accuracy-bound tolerance; see module docstring)."""
    sc = scenarios.nominal(traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0)
    res = render.render_sequence(sc)
    frame = res.frames[0]

    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(frame)
    assert ids is not None
    found = set(int(i) for i in ids.flatten())
    assert found == set(sc.markers_true.keys())

    max_err = 0.0
    for quad, mid in zip(corners, ids.flatten()):
        floor_corners = render._marker_floor_corners(sc.markers_true[int(mid)],
                                                     sc.marker_size_m)
        expected = floor_to_pixel(res.H_true, floor_corners)
        for det_corner in quad.reshape(-1, 2):
            d = np.linalg.norm(expected - det_corner, axis=1).min()
            max_err = max(max_err, float(d))
    print(f"\n[gate] aruco corner max error: {max_err:.4f} px")
    assert max_err < 1.0


# --------------------------------------------------------------------------- #
# Ball trajectory + rendered ball position                                      #
# --------------------------------------------------------------------------- #

def test_contact_time_and_point():
    traj = scenarios.BASE_TRAJ
    r_ball = R_BALL                             # config-driven (was hardcoded 0.0335)
    t_star = traj.contact_time(r_ball)
    p = traj.pos(t_star)
    assert abs(p[1] - r_ball) < 1e-12          # centre height = r_ball, exact algebra
    v_y = traj.v0[1] - render.GRAVITY * t_star
    assert v_y < 0                              # descending branch
    xz = traj.contact_point_xz(r_ball)
    assert np.allclose(xz, [p[0], p[2]], atol=1e-12)


def test_contact_unreachable_raises():
    # thrown upward from y=1 with huge speed never sampled below... use a trajectory
    # whose apex stays above contact height reversed: start BELOW contact height going up
    # is fine; truly unreachable = discriminant < 0 is impossible for downward gravity,
    # so test the past-contact branch instead: p0 below floor moving down.
    with pytest.raises(ValueError):
        Trajectory(p0=(0, -1.0, 0), v0=(0, -5.0, 0)).contact_time(R_BALL)


def test_rendered_ball_center_matches_truth():
    """Colour-mask centroid of the drawn ball vs the recorded truth centre.
    Tolerance 0.5 px: disc rasterisation as above plus anti-aliased edge on a
    textured-free background."""
    sc = scenarios.nominal(resolution=(1280, 720))
    res = render.render_sequence(sc)
    idx = 20                                    # mid-descent, well before contact
    frame = res.frames[idx]
    truth_uv = res.ball_center_px[idx]
    assert np.all(np.isfinite(truth_uv))

    # [AMENDED v1.5 / WO-OPT-4 Stage 2 — D18; was: a hardcoded (25,60,60)-(45,255,255),
    # i.e. the old tennis yellow-green band duplicated into the test.] Read the band from
    # config so this test cannot silently mask against a band the detector no longer uses.
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)
    m = cv2.moments(mask, binaryImage=True)
    assert m["m00"] > 0
    centroid = np.array([m["m10"] / m["m00"], m["m01"] / m["m00"]])
    err = np.linalg.norm(centroid - truth_uv)
    print(f"\n[gate] ball centroid error: {err:.4f} px")
    assert err < 0.5


# --------------------------------------------------------------------------- #
# Scenario library behaviour                                                   #
# --------------------------------------------------------------------------- #

def test_all_scenarios_build():
    for name, factory in scenarios.ALL_SCENARIOS.items():
        sc = factory()
        assert sc.name == name
        assert sc.held_out_id in sc.markers_true


def test_survey_perturbation_negative_control_setup():
    sc = scenarios.survey_perturbed()
    surveyed = sc.markers_surveyed()
    moved = [mid for mid, xz in sc.markers_true.items()
             if not np.allclose(surveyed[mid], xz)]
    assert len(moved) == 3
    # perturbations are cm-scale: big enough to trip check_point_tol_m = 5 mm
    for mid in moved:
        shift = np.linalg.norm(surveyed[mid] - np.asarray(sc.markers_true[mid]))
        assert 0.02 < shift < 0.06
    # the held-out check point itself is NOT perturbed (it must stay honest)
    assert np.allclose(surveyed[sc.held_out_id], sc.markers_true[sc.held_out_id])


def test_no_ball_scenario_renders_no_ball_pixels():
    sc = scenarios.no_ball(resolution=(640, 360), t_start=0.0, t_end=0.01)
    res = render.render_sequence(sc)
    assert res.contact_time_s is None
    for frame in res.frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # [WO-OPT-4 Stage 3 — was a hardcoded (25,60,60)-(45,255,255).] This is a NEGATIVE
        # CONTROL: masked against the retired tennis band it would pass vacuously even if an
        # orange ball WERE drawn. It must test the band the detector actually uses.
        mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)
        assert int(mask.sum()) == 0
    assert np.all(np.isnan(res.ball_center_px))


def test_dropout_frames_are_none_truth_stays_filled():
    sc = scenarios.with_dropouts(frames=frozenset({3, 5}), t_start=0.30, t_end=0.32)
    res = render.render_sequence(sc)
    for i, frame in enumerate(res.frames):
        if i in {3, 5}:
            assert frame is None
            assert np.all(np.isfinite(res.ball_center_px[i]))   # truth unaffected
        else:
            assert isinstance(frame, np.ndarray)


def test_sequence_truth_consistency():
    sc = scenarios.nominal()
    res = render.render_sequence(sc)
    n = int(round((sc.t_end - sc.t_start) * sc.fps_measured)) + 1
    assert len(res.frames) == n and len(res.times) == n
    assert np.allclose(np.diff(res.times), 1.0 / sc.fps_measured)
    # truth contact matches the trajectory's own solution
    assert res.contact_time_s == pytest.approx(sc.traj.contact_time(sc.r_ball))
    assert np.allclose(res.contact_xz, sc.traj.contact_point_xz(sc.r_ball))
    # ball truth present while airborne, NaN after contact
    airborne = res.times <= res.contact_time_s
    assert np.all(np.isfinite(res.ball_center_px[airborne]))
    assert np.all(np.isnan(res.ball_center_px[~airborne]))
    # H_true is exactly the analytic homography of the camera actually used
    assert np.allclose(res.H_true, floor_homography(res.cam))


def test_degraded_scenarios_differ_from_nominal():
    """Smoke check: blur/shadow/low-contrast produce genuinely different frames."""
    kw = dict(t_start=0.40, t_end=0.40, resolution=(640, 360))
    base = render.render_sequence(scenarios.nominal(**kw)).frames[0]
    for factory in (scenarios.blurred, scenarios.shadowed, scenarios.low_contrast):
        frame = render.render_sequence(factory(**kw)).frames[0]
        assert frame.shape == base.shape
        assert not np.array_equal(frame, base)
    # grazing changes the camera, hence the whole geometry
    grz = render.render_sequence(scenarios.grazing(**kw))
    assert not np.allclose(grz.H_true,
                           render.render_sequence(scenarios.nominal(**kw)).H_true)
