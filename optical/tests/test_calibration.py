"""Phase 2 tests: calibration chain against Phase-1 synthetic truth (Optical.md §5.1).

Tolerance rationale (per §11):
  * Exact-correspondence fits: < 1e-6 m — pure linear algebra on noise-free points.
  * Full synthetic ArUco calibration: reproj RMS < 1.0 px and mapped-grid error
    < 5 mm — bounded by the ~0.9 px worst-case ArUco corner error measured in Phase 1
    (~3 mm at the ~330 px/m nominal floor scale), averaged down by the 7-marker fit.
  * Intrinsics, corner level (exact synthetic corners): fx/fy within 0.1%, k1 within
    1e-3 — calibrateCamera is iterative but converges essentially exactly on clean
    data with 12 well-spread views.
  * Intrinsics, image level (zero-distortion rendered boards): fx/fy within 2%,
    principal point within 15 px — bounded by cornerSubPix accuracy on warped
    checkerboards, not by our code.
"""

import cv2
import numpy as np
import pytest
import yaml

from optical import calibration as cal
from scripts import calibrate_homography as ch
from scripts import calibrate_intrinsics as ci
from simulator import render, scenarios
from simulator.render import floor_to_pixel


# --------------------------------------------------------------------------- #
# Shared synthetic fixtures                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def nominal_scene():
    """One full-res nominal ArUco calibration frame + exact truth."""
    sc = scenarios.nominal(traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0)
    res = render.render_sequence(sc)
    return sc, res, res.frames[0]


def _grid_floor_points():
    xs = np.linspace(-0.4, 1.4, 10)
    zs = np.linspace(-0.7, 1.0, 10)
    return np.array([(x, z) for x in xs for z in zs])


# --------------------------------------------------------------------------- #
# Fit core                                                                     #
# --------------------------------------------------------------------------- #

def test_fit_recovers_known_H_from_exact_points(nominal_scene):
    sc, res, _ = nominal_scene
    floor = np.array(list(sc.markers_true.values()), dtype=float)
    pixels = floor_to_pixel(res.H_true, floor)          # exact correspondences
    H, rms = cal.fit_homography(pixels, floor)
    # cv2.findHomography works in float32 internally: ~1e-4 px is its precision
    # floor on kilopixel coordinates, NOT a fit error. 1e-3 px ~= 3e-7 m here.
    assert rms < 1e-3
    grid = _grid_floor_points()
    mapped = cal.apply_homography(H, floor_to_pixel(res.H_true, grid))
    assert np.max(np.linalg.norm(mapped - grid, axis=1)) < 1e-6


def test_fit_requires_four_points():
    with pytest.raises(ValueError, match=">= 4"):
        cal.fit_homography(np.zeros((3, 2)), np.zeros((3, 2)))


def test_degenerate_collinear_markers_raise(nominal_scene):
    _, res, _ = nominal_scene
    floor = np.array([(t, 0.5 * t) for t in np.linspace(0, 1.2, 6)])  # a line
    pixels = floor_to_pixel(res.H_true, floor)
    with pytest.raises(ValueError, match="degenerate"):
        cal.fit_homography(pixels, floor)


# --------------------------------------------------------------------------- #
# Full synthetic calibration - nominal (positive control)                      #
# --------------------------------------------------------------------------- #

def test_full_synthetic_calibration_nominal(nominal_scene, tmp_path):
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}

    calib, path = ch.run_calibration(frame, surveyed, sc.held_out_id, "TEST_A",
                                     tol_m=0.005, out_dir=tmp_path)

    print(f"\n[gate] nominal calibration: reproj_rms={calib.reproj_rms_px:.4f} px, "
          f"check_point_err={calib.check_point_err_m * 1000:.2f} mm")
    assert calib.check_point_ok
    assert calib.reproj_rms_px < 1.0
    assert calib.check_point_err_m < 0.005
    assert calib.flags == []
    assert len(calib.fit_ids) == len(surveyed) - 1
    assert sc.held_out_id not in calib.fit_ids

    # H recovery: map a dense pixel grid through the FITTED H, compare with truth.
    grid = _grid_floor_points()
    mapped = cal.apply_homography(calib.H, floor_to_pixel(res.H_true, grid))
    max_err = float(np.max(np.linalg.norm(mapped - grid, axis=1)))
    print(f"[gate] fitted-H max floor-map error over grid: {max_err * 1000:.2f} mm")
    assert max_err < 0.005

    # yaml written with the §5.6 key names, loadable, faithful
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("calib_id", "reproj_rms_px", "check_point_err_m", "intrinsics"):
        assert key in data
    loaded = cal.load_homography_yaml(path)
    assert np.allclose(loaded.H, calib.H)
    assert loaded.check_point_ok == calib.check_point_ok


def test_manual_reference_marks_join_the_fit(nominal_scene, tmp_path):
    """String-id manual points (pod/centroid clicks) merge with ArUco detections."""
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    surveyed["centroid"] = np.array([0.0, 0.0])
    manual = {"centroid": floor_to_pixel(res.H_true, np.array([0.0, 0.0]))[0]}

    calib, _ = ch.run_calibration(frame, surveyed, sc.held_out_id, "TEST_B",
                                  tol_m=0.005, out_dir=tmp_path,
                                  manual_points=manual)
    assert "centroid" in calib.fit_ids
    assert calib.check_point_ok


# --------------------------------------------------------------------------- #
# NEGATIVE CONTROL: corrupted survey must trip the check-point guard, loudly    #
# --------------------------------------------------------------------------- #

def test_negative_control_corrupted_survey_trips_guard(tmp_path):
    sc = scenarios.survey_perturbed(traj=None, resolution=(1280, 720),
                                    t_start=0.0, t_end=0.0)
    res = render.render_sequence(sc)
    corrupted_survey = sc.markers_surveyed()        # scene stays TRUE; survey lies

    with pytest.warns(UserWarning, match="CHECK-POINT GUARD TRIPPED"):
        calib, _ = ch.run_calibration(res.frames[0], corrupted_survey,
                                      sc.held_out_id, "TEST_NEG", tol_m=0.005,
                                      out_dir=tmp_path)
    print(f"\n[gate] negative control: check_point_err="
          f"{calib.check_point_err_m * 1000:.1f} mm (tol 5.0 mm) "
          f"flags={calib.flags}")
    assert not calib.check_point_ok
    assert calib.check_point_err_m > 0.005
    assert cal.CHECK_POINT_FAIL_FLAG in calib.flags


# --------------------------------------------------------------------------- #
# Stability re-check (§5.1 step 5)                                             #
# --------------------------------------------------------------------------- #

def test_stability_check_flags_camera_bump(nominal_scene):
    sc, res, _ = nominal_scene
    check_xz = np.asarray(sc.markers_true[sc.held_out_id], float)

    floor = np.array([xz for mid, xz in sc.markers_true.items()
                      if mid != sc.held_out_id])
    H_fit, _ = cal.fit_homography(floor_to_pixel(res.H_true, floor), floor)

    uv_start = floor_to_pixel(res.H_true, check_xz)[0]

    # camera bumped between start and end: same scene, slightly rotated camera
    cam_bumped = render.make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.06),
                                    sc.resolution, sc.hfov_deg)
    uv_end = floor_to_pixel(render.floor_homography(cam_bumped), check_xz)[0]

    with pytest.warns(UserWarning, match="HOMOGRAPHY DRIFT"):
        result = cal.stability_check(H_fit, uv_start, uv_end, check_xz, tol_m=0.005)
    print(f"\n[gate] stability: drift={result.drift_m * 1000:.1f} mm -> flagged")
    assert result.drifted
    assert result.drift_m > 0.005
    assert result.err_start_m < 0.001               # start frame maps true


def test_stability_check_passes_when_camera_still(nominal_scene):
    sc, res, _ = nominal_scene
    check_xz = np.asarray(sc.markers_true[sc.held_out_id], float)
    floor = np.array([xz for mid, xz in sc.markers_true.items()
                      if mid != sc.held_out_id])
    H_fit, _ = cal.fit_homography(floor_to_pixel(res.H_true, floor), floor)
    uv = floor_to_pixel(res.H_true, check_xz)[0]
    result = cal.stability_check(H_fit, uv, uv + [0.2, -0.1], check_xz, tol_m=0.005)
    assert not result.drifted
    assert result.drift_m < 0.002


# --------------------------------------------------------------------------- #
# Stage 3 (M3): stability_between_frames reusable core (re-detect + re-map)     #
# --------------------------------------------------------------------------- #

def test_stability_between_frames_still_and_drift(nominal_scene):
    """Re-detect the ArUco check point in two frames and re-map: same camera -> no drift;
    a bumped-camera end frame -> drift flagged (tol 5 mm, the config check_point_tol_m)."""
    sc, res, frame = nominal_scene
    floor = np.array([xz for mid, xz in sc.markers_true.items() if mid != sc.held_out_id])
    H_fit, _ = cal.fit_homography(floor_to_pixel(res.H_true, floor), floor)
    cp_xz = np.asarray(sc.markers_true[sc.held_out_id], float)

    result, reason = cal.stability_between_frames(H_fit, frame, frame, sc.held_out_id,
                                                  cp_xz, tol_m=0.005)
    assert reason is None and not result.drifted        # same frame -> zero drift

    bumped = render.render_sequence(scenarios.nominal(
        traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0,
        cam_target=(0.4, 0.0, 0.06))).frames[0]
    with pytest.warns(UserWarning, match="HOMOGRAPHY DRIFT"):
        result2, reason2 = cal.stability_between_frames(H_fit, frame, bumped,
                                                        sc.held_out_id, cp_xz, tol_m=0.005)
    assert reason2 is None and result2.drifted


def test_cond_warn_soft_band_flags_not_raises():
    """WO-OPT-1 Stage 5.4: a poorly-spread (near-collinear, ratio ~0.006) but non-degenerate
    marker cloud sets `cond_warn` and warns — it does NOT hard-fail (that stays reserved for
    the ~1e-8 collinear floor). Exact correspondences isolate conditioning from fit error."""
    from simulator.render import floor_to_pixel, floor_homography, make_camera
    cam = make_camera((3.5, 1.5, 0.0), (0.4, 0.0, 0.0), (1280, 720), 62.0)
    Hf2p = floor_homography(cam)
    floor = {0: (0.0, 0.0), 1: (0.8, 0.01), 2: (1.6, 0.0), 3: (2.4, 0.015),
             4: (0.4, 0.005), 5: (2.0, 0.008)}          # wide x, ~0.015 z -> ratio ~0.006
    corr = {mid: (floor_to_pixel(Hf2p, np.array(xz))[0], np.array(xz, float))
            for mid, xz in floor.items()}
    with pytest.warns(UserWarning, match="MARKER CONDITIONING"):
        calib = cal.calibrate(corr, held_out_id=4, calib_id="COND", tol_m=0.05)
    assert cal.COND_WARN_FLAG in calib.flags
    assert cal.conditioning_ratio(np.array(list(floor.values()))) < cal.COND_WARN_RATIO


def test_well_spread_markers_no_cond_warn(nominal_scene, tmp_path):
    """The nominal near/far/left/right field is well-conditioned -> no cond_warn."""
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    calib, _ = ch.run_calibration(frame, surveyed, sc.held_out_id, "WS", tol_m=0.005,
                                  out_dir=tmp_path)
    assert cal.COND_WARN_FLAG not in calib.flags
    assert cal.conditioning_ratio(np.array(list(sc.markers_true.values()))) >= cal.COND_WARN_RATIO


def test_stability_between_frames_reports_unrunnable():
    """Cannot-run cases return (None, reason) — never raise, never a silent skip."""
    frame = np.zeros((100, 100, 3), np.uint8)
    res, reason = cal.stability_between_frames(np.eye(3), frame, frame, "centroid",
                                               np.array([0.0, 0.0]), 0.005)
    assert res is None and "manual" in reason            # non-ArUco check point
    res2, reason2 = cal.stability_between_frames(np.eye(3), frame, frame, 6, None, 0.005)
    assert res2 is None and "unavailable" in reason2     # no surveyed position
    res3, reason3 = cal.stability_between_frames(np.eye(3), frame, frame, 6,
                                                 np.array([0.0, 0.0]), 0.005)
    assert res3 is None and "not detected" in reason3    # ArUco id but no marker in frame


# --------------------------------------------------------------------------- #
# Config survey extraction guards                                              #
# --------------------------------------------------------------------------- #

def test_survey_from_config_rejects_placeholder_config():
    """An EMPTY survey (markers.fit_points == []) - running calibration against it must
    fail with an actionable message, not fit garbage.

    Uses a synthetic empty-survey dict rather than loading the live project config.yaml:
    Phase 5 fieldwork (2026-07-11) populated the real config's marker survey with actual
    surveyed positions, so the live file no longer models the "nobody has surveyed markers
    yet" state this test exists to guard -- that state is now constructed directly."""
    cfg = {"markers": {"fit_points": []}}
    with pytest.raises(ValueError, match="fit_points is empty"):
        ch.survey_from_config(cfg)


def test_survey_from_config_requires_held_out():
    cfg = {"markers": {"fit_points": [
        {"id": 0, "xz": [0.5, 0.5]}, {"id": 1, "xz": [1.0, -0.5]}]}}
    with pytest.raises(ValueError, match="held-out"):
        ch.survey_from_config(cfg)


# --------------------------------------------------------------------------- #
# Intrinsics (§3.4) - unit-tested scope per the script docstring                #
# --------------------------------------------------------------------------- #

K_TRUE = np.array([[1100.0, 0.0, 640.0], [0.0, 1100.0, 360.0], [0.0, 0.0, 1.0]])
DIST_TRUE = np.array([-0.12, 0.03, 0.001, -0.001, 0.0])
PATTERN = (9, 6)
IMAGE_SIZE = (1280, 720)


def _poses(n=12):
    """Deterministic spread of board poses filling the frame."""
    rng = np.random.default_rng(7)
    poses = []
    for _ in range(n):
        rvec = rng.uniform(-0.35, 0.35, 3)
        tvec = np.array([rng.uniform(-0.16, 0.04),
                         rng.uniform(-0.12, 0.02),
                         rng.uniform(0.5, 0.9)])
        poses.append((rvec, tvec))
    return poses


def test_intrinsics_corner_level_recovers_K_and_distortion():
    """Corner-level core: EXACT projected corners under known K + distortion."""
    objp = ci.board_object_points(PATTERN, 0.03)
    objpoints, imgpoints = [], []
    for rvec, tvec in _poses():
        img, _ = cv2.projectPoints(objp, rvec, tvec, K_TRUE, DIST_TRUE)
        img = img.reshape(-1, 2)
        if (img.min() < 0 or img[:, 0].max() >= IMAGE_SIZE[0]
                or img[:, 1].max() >= IMAGE_SIZE[1]):
            continue                                   # keep only fully-visible views
        objpoints.append(objp)
        imgpoints.append(img)
    assert len(objpoints) >= 8

    result = ci.calibrate_from_corners(objpoints, imgpoints, IMAGE_SIZE)
    K = result["camera_matrix"]
    fx_err = abs(K[0, 0] - K_TRUE[0, 0]) / K_TRUE[0, 0]
    k1_err = abs(result["dist_coeffs"][0] - DIST_TRUE[0])
    print(f"\n[gate] intrinsics corner-level: fx rel err={fx_err:.2e}, "
          f"k1 abs err={k1_err:.2e}, rms={result['rms_reproj_px']:.2e} px")
    assert fx_err < 1e-3
    assert abs(K[0, 2] - 640.0) < 0.5 and abs(K[1, 2] - 360.0) < 0.5
    assert k1_err < 1e-3
    assert result["rms_reproj_px"] < 0.01


def _render_board_view(rvec, tvec, square_px=60, square_m=0.03):
    """Render a checkerboard under a known ZERO-DISTORTION camera via the plane
    homography M = K [r1 r2 t] composed with the board-image-to-metres scaling."""
    nx, ny = PATTERN
    sq_x, sq_y = nx + 1, ny + 1
    margin = square_px
    bw, bh = sq_x * square_px + 2 * margin, sq_y * square_px + 2 * margin
    board = np.full((bh, bw), 255, np.uint8)
    for i in range(sq_x):
        for j in range(sq_y):
            if (i + j) % 2 == 0:
                y0, x0 = margin + j * square_px, margin + i * square_px
                board[y0:y0 + square_px, x0:x0 + square_px] = 0

    R, _ = cv2.Rodrigues(np.asarray(rvec, float))
    Hk = K_TRUE @ np.column_stack([R[:, 0], R[:, 1], np.asarray(tvec, float)])
    # board-image px -> board metres: first INNER corner at (margin+square_px) px = 0 m
    s = square_m / square_px
    off = -(margin + square_px) * s
    S = np.array([[s, 0.0, off], [0.0, s, off], [0.0, 0.0, 1.0]])
    M = Hk @ S
    return cv2.warpPerspective(board, M, IMAGE_SIZE, flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def test_intrinsics_image_level_zero_distortion():
    """Full image path (findChessboardCorners -> calibrateCamera) on rendered
    zero-distortion boards. Distortion recovery through images is commissioning
    scope (C2) - stated in the script docstring."""
    images = [ _render_board_view(rvec, tvec) for rvec, tvec in _poses() ]
    result = ci.calibrate_from_images(images, PATTERN, 0.03)
    K = result["camera_matrix"]
    fx_err = abs(K[0, 0] - 1100.0) / 1100.0
    fy_err = abs(K[1, 1] - 1100.0) / 1100.0
    print(f"\n[gate] intrinsics image-level: views={result['n_views']}, "
          f"fx rel err={fx_err:.4f}, fy rel err={fy_err:.4f}, "
          f"cx={K[0, 2]:.1f}, cy={K[1, 2]:.1f}, rms={result['rms_reproj_px']:.3f} px")
    assert result["n_views"] >= 6
    assert fx_err < 0.02 and fy_err < 0.02
    assert abs(K[0, 2] - 640.0) < 15 and abs(K[1, 2] - 360.0) < 15


def test_intrinsics_yaml_roundtrip(tmp_path):
    result = {"camera_matrix": K_TRUE, "dist_coeffs": DIST_TRUE,
              "rms_reproj_px": 0.123, "n_views": 12, "image_size": [1280, 720]}
    path = ci.save_intrinsics(result, "720p480", tmp_path, PATTERN, 0.03)
    assert path.name == "intrinsics_720p480.yaml"
    loaded = cal.load_intrinsics(path)
    assert np.allclose(loaded["camera_matrix"], K_TRUE)
    assert np.allclose(loaded["dist_coeffs"], DIST_TRUE)
    assert loaded["mode"] == "720p480"


def test_undistort_none_is_passthrough(nominal_scene):
    _, _, frame = nominal_scene
    assert cal.undistort_frame(frame, None) is frame


# --------------------------------------------------------------------------- #
# Calibration-frame loading (temporal median)                                  #
# --------------------------------------------------------------------------- #

def test_median_frame_suppresses_transient(tmp_path):
    """A transient bright frame in a calibration clip must not survive the median."""
    path = tmp_path / "calib.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30,
                             (160, 120))
    if not writer.isOpened():
        pytest.skip("no MJPG VideoWriter available on this system")
    base = np.full((120, 160, 3), 100, np.uint8)
    for i in range(21):
        frame = base.copy()
        if i == 10:
            frame[:] = 255                              # transient
        writer.write(frame)
    writer.release()

    median = cal.load_calibration_frame(path)
    assert median.shape == base.shape
    # MJPG is lossy: allow small compression error, but the transient (155 levels
    # away) must be gone.
    assert abs(int(np.median(median)) - 100) < 10


# --------------------------------------------------------------------------- #
# WO-OPT-3 Stage 4 — camera-position tape cross-check hook (Moderate 5.5 / D13) #
# --------------------------------------------------------------------------- #

def test_camera_measured_absent_yaml_shape_unchanged(nominal_scene, tmp_path):
    """Hook absent -> the calibration carries no camera_* fields and the YAML has none of the
    three keys (additive-only; byte-shape identical to the pre-WO-OPT-3 output)."""
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    calib, path = ch.run_calibration(frame, surveyed, sc.held_out_id, "CAM_NONE",
                                     tol_m=0.005, out_dir=tmp_path)
    assert calib.camera_measured_m is None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("camera_measured_m", "camera_decomposed_m", "camera_delta_m"):
        assert key not in data


def test_camera_measured_true_position_small_delta(nominal_scene, tmp_path):
    """Hook present with the scene's TRUE camera centre: the recorded delta is small and
    consistent with the fitted-H decomposition error documented in IMPLEMENTATION_NOTES Phase 3
    (~12 mm from a detected-ArUco fit). Observed value printed. Informational only — the
    calibration is otherwise fine and no flag is raised by the cross-check."""
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    intr = {"camera_matrix": res.cam.K, "dist_coeffs": np.zeros(5)}
    calib, path = ch.run_calibration(frame, surveyed, sc.held_out_id, "CAM_TRUE",
                                     tol_m=0.005, out_dir=tmp_path,
                                     intrinsics=intr, camera_measured=tuple(res.cam.C))
    assert calib.camera_delta_m is not None
    norm = calib.camera_delta_m["norm"]
    print(f"\n[stage4] camera-measured(true) delta norm: {norm * 1000:.1f} mm")
    assert norm < 0.03            # ~12 mm decomposition error; 30 mm ceiling gives headroom
    assert calib.check_point_ok   # the calibration itself is unaffected
    # persisted with the right shape and round-trips through load
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(data["camera_measured_m"]) == {"x", "y", "z"}
    assert set(data["camera_decomposed_m"]) == {"x", "y", "z"}
    assert set(data["camera_delta_m"]) == {"dx", "dy", "dz", "norm"}
    loaded = cal.load_homography_yaml(path)
    assert loaded.camera_delta_m["norm"] == pytest.approx(norm)


def test_camera_measured_wrong_position_large_delta_no_abort(nominal_scene, tmp_path):
    """Hook present with a deliberately wrong measured position (15 cm off in x): a
    correspondingly large delta is recorded and the run COMPLETES normally — confirming the
    cross-check is informational-only (no threshold, no flag, no abort tied to the magnitude)."""
    sc, res, frame = nominal_scene
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    intr = {"camera_matrix": res.cam.K, "dist_coeffs": np.zeros(5)}
    wrong = tuple(np.asarray(res.cam.C, float) + np.array([0.15, 0.0, 0.0]))
    calib, path = ch.run_calibration(frame, surveyed, sc.held_out_id, "CAM_WRONG",
                                     tol_m=0.005, out_dir=tmp_path,
                                     intrinsics=intr, camera_measured=wrong)
    assert calib.camera_delta_m["norm"] > 0.10          # ~15 cm minus the ~12 mm decomp error
    assert calib.camera_delta_m["dx"] == pytest.approx(0.15, abs=0.03)
    assert "check_point_fail" not in calib.flags        # no gate is tied to the delta
    assert path.exists()                                # run completed, YAML written
