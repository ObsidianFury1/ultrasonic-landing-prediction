"""Phase 4 tests: static-point validation runner + GO/NO-GO summary (§8).

Tolerance: a resting synthetic ball is recovered within ~5 mm (detector centroid +
parallax with r_ball; no contact-timing term since it is static), comfortably inside
the 15 mm gate. The GO/NO-GO logic itself is tested exactly.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from optical.detect import HsvDetector
from optical.geometry import CameraGeometry, load_config
from optical.uncertainty import read_uncertainty_config
from scripts import calibrate_homography as ch
from scripts import validate_static as vs
from simulator import render, scenarios

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
CONFIG = load_config(CONFIG_PATH)
R_BALL = CONFIG["ball"]["radius_m"]
UNCFG = read_uncertainty_config(CONFIG)
CAM = dict(cam_pos=(3.5, 1.5, 0.0), cam_target=(0.4, 0.0, 0.0),
           resolution=(1280, 720), hfov_deg=62.0)
MARKERS = scenarios.BASE_MARKERS


def _static_point(xz, seed=0):
    frames, H_px2floor, cam, _ = render.render_static_scene(
        **CAM, ball_xz=xz, r_ball=R_BALL, markers=MARKERS, n_frames=12,
        noise_sigma=2.0, seed=seed)
    return frames, H_px2floor, CameraGeometry.from_model(cam)


def test_static_landing_recovers_resting_ball():
    xz = np.array([0.6, -0.3])
    frames, H_px2floor, camera = _static_point(xz)
    detector = HsvDetector.from_config(CONFIG)
    measured, sigma_xz, stats = vs.static_landing(
        frames, H_px2floor, camera, detector, R_BALL, uncertainty_cfg=UNCFG)
    err = np.linalg.norm(measured - xz)
    print(f"\n[static] recovered {measured} vs {xz}, err {err * 1000:.2f} mm")
    assert err < 0.005
    assert stats["n_detected"] == stats["n_frames"]
    assert np.all(sigma_xz > 0)


def test_static_landing_no_ball_raises():
    frames, H_px2floor, cam, _ = render.render_static_scene(
        **CAM, ball_xz=(0.5, 0.0), r_ball=R_BALL, markers=MARKERS, n_frames=3)
    # blank the ball out: feed marker-only frames (paint over with floor gray)
    blank = [np.full_like(f, 110) for f in frames]
    with pytest.raises(ValueError, match="no ball detected"):
        vs.static_landing(blank, H_px2floor, CameraGeometry.from_model(cam),
                          HsvDetector.from_config(CONFIG), R_BALL,
                          uncertainty_cfg=UNCFG)


def test_measure_points_and_go_verdict():
    """8 surveyed points spread across the FOV -> GO (RMS <= gate)."""
    surveyed = [(0.6, -0.3), (0.9, 0.4), (0.3, -0.7), (1.2, 0.2),
                (0.0, 0.5), (-0.3, -0.2), (1.4, -0.4), (0.5, 0.8)]
    detector = HsvDetector.from_config(CONFIG)
    # one shared calibration geometry for all points
    _, H_px2floor, camera = _static_point(surveyed[0])
    points = []
    for i, xz in enumerate(surveyed):
        frames, _, _ = _static_point(xz, seed=i)
        points.append((f"P{i}", np.array(xz), frames))
    results = vs.measure_points(points, H_px2floor, camera, detector, R_BALL,
                                uncertainty_cfg=UNCFG,
                                marker_survey_m=CONFIG["markers"]["survey_sigma_m"]["value"])
    summary = vs.summarize(results, CONFIG["tolerances"]["rms_gate_m"])
    print(f"\n[static] RMS {summary['rms_m'] * 1000:.2f} mm over "
          f"{summary['n_points']} points -> {'GO' if summary['go'] else 'NO-GO'}")
    assert summary["n_points"] == 8 and summary["enough_points"]
    assert summary["rms_m"] < CONFIG["tolerances"]["rms_gate_m"]
    assert summary["go"] is True


def test_summarize_no_go_below_eight_points():
    """< 8 points is INSUFFICIENT even at zero error (the gate demands >= 8, §8)."""
    r = vs.StaticResult("P0", np.zeros(2), np.zeros(2), 0.0, np.array([1e-3, 1e-3]),
                        0.1, 12, 12)
    summary = vs.summarize([r] * 5, 0.015)
    assert not summary["enough_points"]
    assert summary["go"] is False


def test_summarize_no_go_when_rms_exceeds_gate():
    results = [vs.StaticResult(f"P{i}", np.zeros(2), np.array([0.03, 0.0]), 0.03,
                               np.array([1e-3, 1e-3]), 0.1, 12, 12) for i in range(8)]
    summary = vs.summarize(results, 0.015)
    assert summary["enough_points"]
    assert summary["rms_m"] == pytest.approx(0.03)
    assert summary["go"] is False


def test_comparison_table_reports_verdict_and_budget():
    results = [vs.StaticResult(f"P{i}", np.array([0.5, 0.0]),
                               np.array([0.503, 0.001]), 0.00316,
                               np.array([0.004, 0.005]), 0.12, 12, 12)
               for i in range(8)]
    summary = vs.summarize(results, 0.015)
    table = vs.comparison_table(results, summary)
    assert "VERDICT         : GO" in table
    assert "budget-vs-measured" in table
    assert "RMS disagreement" in table


def test_static_landing_records_unmeasured_components():
    """WO-OPT-1 Stage 1: placeholder (measured: false) config components surface in
    stats['unmeasured_components']. pixel_sigma_px is measured LIVE from the static
    frames here, so it is NOT in the list.

    [C6 UPDATE 2026-07-11] The live config's `sigma_h_m` was flipped to measured: true this
    session (a physics-model estimate from real ultrasonic velocity data + a literature
    contact-duration figure, per checklist C6 -- see config.yaml's own comment trail and
    IMPLEMENTATION_NOTES_OPTICAL.md). Only `sigma_C_m` and `rolling_shutter_m` remain
    placeholders (neither attempted this session: repeated-C5-calibration+tape, and a
    falling-ball/plumb-line film, respectively) -- was {sigma_h_m, sigma_C_m,
    rolling_shutter_m} before this stage."""
    frames, H_px2floor, camera = _static_point(np.array([0.6, -0.3]))
    detector = HsvDetector.from_config(CONFIG)
    _, _, stats = vs.static_landing(frames, H_px2floor, camera, detector, R_BALL,
                                    uncertainty_cfg=UNCFG)
    um = stats["unmeasured_components"]
    assert "pixel_sigma_px" not in um            # measured live from the static frames
    assert set(um) == {"sigma_C_m", "rolling_shutter_m"}


def test_session_stability_span(tmp_path):
    """WO-OPT-1 Stage 3 task 4: the §8 gate span check catches a bump between the first
    point's clip and the last point's clip; a still session is clean; missing survey is
    reported (-> stability_unchecked in the Stage 5 report)."""
    cam_a = dict(cam_pos=(3.5, 1.5, 0.0), cam_target=(0.4, 0.0, 0.0),
                 resolution=(1280, 720), hfov_deg=62.0)
    cam_b = dict(cam_a, cam_target=(0.4, 0.0, 0.06))
    # [WO-OPT-4 Stage 3] draw_ball=False: these are STABILITY frames — §5.1 maps the held-out
    # check point through H in them, so the check point must be VISIBLE. The basketball resting
    # at (0.5, 0.0) occludes marker 6 (= HELD_OUT_ID), which made session_stability report
    # "unavailable" rather than detect the drift this test exists to detect. The ball plays no
    # part in a drift check, so it is not drawn.
    frames_a, Hpf, _, _ = render.render_static_scene(
        **cam_a, ball_xz=(0.5, 0.0), r_ball=R_BALL, markers=MARKERS, n_frames=4,
        noise_sigma=2.0, seed=0, draw_ball=False)
    frames_b, _, _, _ = render.render_static_scene(
        **cam_b, ball_xz=(0.5, 0.0), r_ball=R_BALL, markers=MARKERS, n_frames=4,
        noise_sigma=2.0, seed=1, draw_ball=False)
    cp_xz = np.asarray(MARKERS[scenarios.HELD_OUT_ID], float)

    with pytest.warns(UserWarning, match="HOMOGRAPHY DRIFT"):
        res, reason = vs.session_stability([frames_a, frames_b], Hpf,
                                           scenarios.HELD_OUT_ID, cp_xz, tol_m=0.005)
    assert reason is None and res.drifted            # bump across the span is caught

    res2, reason2 = vs.session_stability([frames_a, frames_a], Hpf,
                                         scenarios.HELD_OUT_ID, cp_xz, tol_m=0.005)
    assert reason2 is None and not res2.drifted       # still session -> clean

    res3, reason3 = vs.session_stability([frames_a], Hpf, scenarios.HELD_OUT_ID, None, 0.005)
    assert res3 is None and "unavailable" in reason3  # missing survey -> reported


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 5.3 — the real validate_static CLI over an on-disk gate tree   #
# --------------------------------------------------------------------------- #

def _write_intrinsics(tmp_path):
    """True K of the CAM render camera + zero distortion, as an intrinsics_<mode>.yaml."""
    cam = render.make_camera(CAM["cam_pos"], CAM["cam_target"], CAM["resolution"],
                             CAM["hfov_deg"])
    p = tmp_path / "intr.yaml"
    p.write_text(yaml.safe_dump({
        "mode": "720p480", "image_size": [1280, 720],
        "camera_matrix": [[float(v) for v in r] for r in cam.K],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0]}), encoding="utf-8")
    return p


def _build_gate_tree(tmp_path, xzs):
    """A calib yaml + a root of per-point subdirs (PNG frames + point.yaml). Returns
    (root, calib_path, intr_path)."""
    # [WO-OPT-4 Stage 3 — Hari-approved 2026-07-10.] The homography calibration frame is
    # rendered BALL-FREE. It previously contained the ball resting at xzs[0]; at the
    # basketball's ~40 px radius that ball OCCLUDES ArUco marker 6 — which is HELD_OUT_ID,
    # the check point — so calibrate() raised "held-out check point id 6 not among
    # correspondences". §5.1 never required a ball in the calibration frame; removing it
    # kills the whole occlusion failure class instead of dodging one instance.
    frame0 = render.render_static_scene(**CAM, ball_xz=xzs[0], r_ball=R_BALL,
                                        markers=MARKERS, n_frames=1, noise_sigma=2.0,
                                        draw_ball=False)[0][0]
    surveyed = {mid: np.asarray(xz, float) for mid, xz in MARKERS.items()}
    _, calib_path = ch.run_calibration(frame0, surveyed, scenarios.HELD_OUT_ID, "GATE",
                                       tol_m=0.005, out_dir=tmp_path)
    root = tmp_path / "static"
    root.mkdir()
    for i, xz in enumerate(xzs):
        d = root / f"point_{i:02d}"
        d.mkdir()
        frames, _, _, _ = render.render_static_scene(
            **CAM, ball_xz=xz, r_ball=R_BALL, markers=MARKERS, n_frames=3,
            noise_sigma=2.0, seed=i)
        for j, f in enumerate(frames):
            cv2.imwrite(str(d / f"{j:03d}.png"), f)
        (d / "point.yaml").write_text(yaml.safe_dump({"id": f"P{i}", "xz": list(xz)}),
                                      encoding="utf-8")
    return root, calib_path, _write_intrinsics(tmp_path)


def test_validate_static_cli_go(tmp_path):
    """8 spread points, accurate intrinsics -> GO, exit 0, report + verdict written."""
    xzs = [(0.6, -0.3), (0.9, 0.4), (0.3, -0.7), (1.2, 0.2),
           (0.0, 0.5), (-0.3, -0.2), (1.4, -0.4), (0.5, 0.8)]
    root, calib_path, intr_path = _build_gate_tree(tmp_path, xzs)
    out = tmp_path / "report.txt"
    rc = vs.main(["--root", str(root), "--calib", str(calib_path),
                  "--config", str(CONFIG_PATH), "--intrinsics", str(intr_path),
                  "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "VERDICT         : GO" in text
    assert "session stability" in text          # span check is in the report


def test_validate_static_cli_nogo_insufficient_points(tmp_path):
    """< 8 points -> INSUFFICIENT -> NO-GO, exit 1 (the §8 pre-registered gate)."""
    xzs = [(0.6, -0.3), (0.9, 0.4), (0.3, -0.7), (1.2, 0.2), (0.0, 0.5)]   # only 5
    root, calib_path, intr_path = _build_gate_tree(tmp_path, xzs)
    out = tmp_path / "report.txt"
    rc = vs.main(["--root", str(root), "--calib", str(calib_path),
                  "--config", str(CONFIG_PATH), "--intrinsics", str(intr_path),
                  "--out", str(out)])
    assert rc == 1
    assert "VERDICT         : NO-GO" in out.read_text(encoding="utf-8")


def test_validate_static_cli_requires_intrinsics(tmp_path):
    """Omitting --intrinsics without the opt-in fallback is a hard config error."""
    from optical.errors import OpticalConfigError
    root, calib_path, _ = _build_gate_tree(tmp_path, [(0.6, -0.3), (0.9, 0.4)])
    with pytest.raises(OpticalConfigError, match="no --intrinsics"):
        vs.main(["--root", str(root), "--calib", str(calib_path),
                 "--config", str(CONFIG_PATH), "--out", str(tmp_path / "r.txt")])


def test_write_report_atomic(tmp_path):
    results = [vs.StaticResult("P0", np.zeros(2), np.array([0.002, 0.0]), 0.002,
                               np.array([1e-3, 1e-3]), 0.1, 12, 12)]
    summary = vs.summarize(results, 0.015)
    p = vs.write_report(tmp_path / "static_validation.txt", results, summary)
    assert p.exists()
    assert "STATIC-POINT VALIDATION" in p.read_text(encoding="utf-8")
