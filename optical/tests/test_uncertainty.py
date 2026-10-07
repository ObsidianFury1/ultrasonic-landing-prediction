"""Phase 3 tests: uncertainty budget (§7).

Tolerances: analytic propagation vs Monte-Carlo references within 5% (standard
check for first-order propagation at these small relative sigmas); hand-computed
nadir pixel scale to 1e-9 (pure algebra).
"""

import numpy as np
import pytest

from optical import uncertainty as unc
from simulator import render, scenarios
from simulator.render import floor_to_pixel, make_camera

# [WO-OPT-4 Stage 3 hardcode audit] Config-driven, never a literal 0.0335.
R_BALL = render.config_r_ball()


def test_local_pixel_scale_nadir_hand_computed():
    """Nadir camera at height h: the pixel->floor map is a pure scaling h/fx, so
    both singular values of the Jacobian must equal h/fx exactly."""
    h, w, hh, hfov = 2.0, 640, 360, 60.0
    cam = make_camera((0.0, h, 0.0), (0.0, 0.0, 0.0), (w, hh), hfov)
    H_px2floor = np.linalg.inv(render.floor_homography(cam))
    fx = cam.K[0, 0]
    J = unc.local_floor_jacobian(H_px2floor, (w / 2 + 40, hh / 2 - 25))
    s = np.linalg.svd(J, compute_uv=False)
    assert np.allclose(s, h / fx, atol=1e-9)


def test_pixel_sigma_through_diagonal_jacobian():
    J = np.diag([0.003, 0.005])
    sx, sz = unc.pixel_sigma_to_floor(J, sigma_px=2.0)
    assert np.isclose(sx, 0.006) and np.isclose(sz, 0.010)


def test_grazing_view_inflates_far_field_scale():
    """§3.1 constraint (b): grazing views compress the far field and blow up
    per-pixel uncertainty. The far-field m/px at the grazing camera must exceed
    the nominal camera's at the same floor point."""
    far_xz = np.array([-0.5, 0.0])                # far side from both cameras
    scales = {}
    for name, factory in (("nominal", scenarios.nominal),
                          ("grazing", scenarios.grazing)):
        sc = factory(resolution=(1280, 720))
        cam = make_camera(sc.cam_pos, sc.cam_target, sc.resolution, sc.hfov_deg)
        H_f2p = render.floor_homography(cam)
        uv = floor_to_pixel(H_f2p, far_xz)[0]
        J = unc.local_floor_jacobian(np.linalg.inv(H_f2p), uv)
        scales[name] = np.linalg.svd(J, compute_uv=False)[0]
    print(f"\n[unc] far-field worst scale: nominal={scales['nominal'] * 1000:.2f} "
          f"mm/px, grazing={scales['grazing'] * 1000:.2f} mm/px")
    assert scales["grazing"] > 2.0 * scales["nominal"]


def test_parallax_sigma_vs_monte_carlo():
    from optical.geometry import parallax_correct
    P, h = np.array([0.7, -0.3]), R_BALL
    C = np.array([3.5, 1.5, 0.0])
    sh, sC = 0.004, (0.02, 0.015, 0.02)
    analytic = unc.parallax_sigma(P, h, C, sh, sC)

    rng = np.random.default_rng(5)
    samples = []
    for _ in range(20000):
        hi = h + rng.normal(0, sh)
        Ci = C + rng.normal(0, sC)
        samples.append(parallax_correct(P, hi, Ci))
    mc = np.std(np.array(samples), axis=0, ddof=1)
    assert np.all(np.abs(analytic - mc) / mc < 0.05)


def test_polar_sigma_vs_monte_carlo():
    x, z, sx, sz = 0.9, -0.6, 0.006, 0.009
    sr, st_deg = unc.polar_sigma(x, z, sx, sz)
    rng = np.random.default_rng(6)
    xs = x + rng.normal(0, sx, 200000)
    zs = z + rng.normal(0, sz, 200000)
    r_mc = np.std(np.hypot(xs, zs), ddof=1)
    t_mc = np.degrees(np.std(np.arctan2(zs, xs), ddof=1))
    assert abs(sr - r_mc) / r_mc < 0.05
    assert abs(st_deg - t_mc) / t_mc < 0.05


def test_polar_sigma_rejects_origin():
    with pytest.raises(ValueError, match="r = 0"):
        unc.polar_sigma(0.0, 0.0, 0.01, 0.01)


def test_budget_block_matches_frozen_schema():
    """The §5.6 uncertainty block: exact key names, quadrature behaviour."""
    sc = scenarios.nominal(resolution=(1280, 720))
    cam = make_camera(sc.cam_pos, sc.cam_target, sc.resolution, sc.hfov_deg)
    H_px2floor = np.linalg.inv(render.floor_homography(cam))
    landing = np.array([0.664, -0.127])
    uv = floor_to_pixel(render.floor_homography(cam), landing)[0]

    budget = unc.build_budget(
        landing_xz=landing, landing_uv=uv, H_px2floor=H_px2floor,
        marker_survey_m=0.0025, reproj_rms_px=0.2, check_point_err_m=0.004,
        sigma_px=0.5, parallax_P_mapped=landing, r_ball=R_BALL, camera_C=cam.C,
        sigma_h_m=0.004, sigma_C_m=(0.02, 0.015, 0.02),
        vel_xz=np.array([1.4, -0.9]), sigma_t_s=3e-4)

    assert set(budget) == {"sigma_x_m", "sigma_z_m", "sigma_r_m",
                           "sigma_theta_deg", "components"}
    assert set(budget["components"]) == {"marker_survey_m", "homography_m",
                                         "pixel_localisation_m",
                                         "parallax_residual_m", "temporal_m"}
    # quadrature: total per-axis sigma >= every single component, < their plain sum
    comps = budget["components"]
    total = max(budget["sigma_x_m"], budget["sigma_z_m"])
    assert total >= max(comps.values()) - 1e-9
    assert total < sum(comps.values())
    print(f"\n[unc] budget: sigma_x={budget['sigma_x_m'] * 1000:.2f} mm, "
          f"sigma_z={budget['sigma_z_m'] * 1000:.2f} mm, "
          f"sigma_r={budget['sigma_r_m'] * 1000:.2f} mm, "
          f"sigma_theta={budget['sigma_theta_deg']:.3f} deg")
    print(f"[unc] components (mm): "
          + ", ".join(f"{k.replace('_m', '')}={v * 1000:.2f}"
                      for k, v in comps.items()))


def test_read_uncertainty_config_parses_and_flags_unmeasured():
    """WO-OPT-1 Stage 1: the parser returns values + the list of unmeasured components."""
    cfg = {"uncertainty": {
        "pixel_sigma_px": {"value": 0.5, "measured": True},
        "sigma_h_m": {"value": 0.004, "measured": False},
        "sigma_C_m": {"value": [0.0, 0.0, 0.0], "measured": False},
        "rolling_shutter_m": {"value": 0.0, "measured": False}}}
    out = unc.read_uncertainty_config(cfg)
    assert out["pixel_sigma_px"] == 0.5
    assert out["sigma_C_m"] == [0.0, 0.0, 0.0]
    assert set(out["unmeasured"]) == {"sigma_h_m", "sigma_C_m", "rolling_shutter_m"}


def test_read_uncertainty_config_hard_errors():
    """Missing block, missing key, and malformed entry each raise (never a silent default)."""
    with pytest.raises(ValueError, match="uncertainty"):
        unc.read_uncertainty_config({})
    with pytest.raises(ValueError, match="missing required key"):
        unc.read_uncertainty_config({"uncertainty": {
            "pixel_sigma_px": {"value": 0.5, "measured": True}}})
    with pytest.raises(ValueError, match="value, measured"):
        unc.read_uncertainty_config({"uncertainty": {
            "pixel_sigma_px": 0.5, "sigma_h_m": {"value": 0.004, "measured": True},
            "sigma_C_m": {"value": [0, 0, 0], "measured": True},
            "rolling_shutter_m": {"value": 0.0, "measured": True}}})


def test_read_survey_sigma_parses_and_flags():
    """WO-OPT-3 Stage 3 (Moderate 5.2 / D11): the sibling reader parses markers.survey_sigma_m
    as {value, measured}; a placeholder surfaces via `unmeasured`, a measured entry does not."""
    out = unc.read_survey_sigma(
        {"markers": {"survey_sigma_m": {"value": 0.0025, "measured": False}}})
    assert out["value"] == 0.0025 and out["measured"] is False
    assert out["unmeasured"] == [unc.SURVEY_SIGMA_COMPONENT]
    out2 = unc.read_survey_sigma(
        {"markers": {"survey_sigma_m": {"value": 0.003, "measured": True}}})
    assert out2["value"] == 0.003 and out2["measured"] is True and out2["unmeasured"] == []


def test_read_survey_sigma_hard_errors():
    """Missing key and malformed shape (e.g. the pre-WO-OPT-3 bare number) each hard-error —
    no silent default, matching read_uncertainty_config's posture."""
    with pytest.raises(ValueError, match="survey_sigma_m"):
        unc.read_survey_sigma({"markers": {}})
    with pytest.raises(ValueError, match="value, measured"):
        unc.read_survey_sigma({"markers": {"survey_sigma_m": 0.0025}})   # old bare-number shape


def test_budget_rolling_shutter_term_enters():
    """§7 item 5: the rolling-shutter term must not be assumable-away silently —
    when supplied it must grow the temporal component."""
    sc = scenarios.nominal(resolution=(1280, 720))
    cam = make_camera(sc.cam_pos, sc.cam_target, sc.resolution, sc.hfov_deg)
    H_px2floor = np.linalg.inv(render.floor_homography(cam))
    landing = np.array([0.664, -0.127])
    uv = floor_to_pixel(render.floor_homography(cam), landing)[0]
    kw = dict(landing_xz=landing, landing_uv=uv, H_px2floor=H_px2floor,
              marker_survey_m=0.0025, reproj_rms_px=0.2, check_point_err_m=0.004,
              sigma_px=0.5, parallax_P_mapped=landing, r_ball=R_BALL,
              camera_C=cam.C, sigma_h_m=0.004, vel_xz=np.array([1.4, -0.9]),
              sigma_t_s=3e-4)
    without = unc.build_budget(**kw)
    with_rs = unc.build_budget(**kw, rolling_shutter_m=0.005)
    assert (with_rs["components"]["temporal_m"]
            > without["components"]["temporal_m"])
    assert with_rs["sigma_x_m"] > without["sigma_x_m"]
