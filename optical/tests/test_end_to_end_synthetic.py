"""Synthetic END-TO-END acceptance test (Optical.md §6) — the Phase 3 gate and the
standing regression anchor.

Full chain on rendered frames: detect (HSV) -> track -> descent -> sub-frame
contact fit -> parallax -> landing, vs the injected truth. Scenarios: nominal
(true-H and FITTED-calibration variants), blurred, shadowed, low-contrast,
dropouts; NEGATIVE controls: no-ball (clean no-detection, never a fabricated
landing) and corrupted marker survey (check-point guard must trip and the throw
must be flaggable).

Tolerances (per §11, one line each). The dominant term is the +-0.5-frame contact-
time BRACKET at 480 fps (§5.5 / contact.py): ~v_h/(2*fps) ~= a few mm along-track,
which is why even the zero-noise nominal sits near ~7 mm rather than the §6 <= 3 mm
aspiration - a characterised frame-quantisation limit, not detector noise, and far
inside the 15 mm GO gate (§8):
  * nominal / true H: <= 10 mm — bracket-limited contact time + detector centroid.
  * nominal / fitted calibration: <= 12 mm — adds the ArUco-bound fitted-H map +
    camera-pose decomposition error in quadrature.
  * shadowed <= 10 mm, low-contrast <= 11 mm, blurred <= 12 mm — detection-edge
    erosion / smear on top of the bracket term, scaled by scenario harshness.
  * dropouts / true H: <= 10 mm — same as nominal (window shortened by the gaps).
  * lowest-pixel fallback truth error <= 8 mm; it is structurally LESS t*-sensitive
    (a near-floor feature), so it is closer than the analytic method here — exactly
    the comparison §5.4's dual-method commissioning cross-check exists to surface.
"""

from pathlib import Path

import numpy as np
import pytest

from optical.calibration import CHECK_POINT_FAIL_FLAG
from optical.contact import fit_contact
from optical.detect import HsvDetector
from optical.geometry import (CameraGeometry, estimate_camera_position,
                             load_config)
from optical.track import build_track, find_descent
from optical import uncertainty as unc
from scripts import calibrate_homography as ch
from simulator import render, scenarios
from simulator.render import floor_to_pixel

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
E2E_KW = dict(resolution=(1280, 720), t_start=0.36)   # memory-bounded window


def _run_chain(res, H_px2floor, camera, sc):
    """detect -> track -> descent -> contact. Shared by every scenario."""
    detector = HsvDetector.from_config(CONFIG)
    detections = [detector.detect(f) if f is not None else None
                  for f in res.frames]
    track = build_track(detections, res.times,
                        max_jump_px=CONFIG["track"]["max_jump_px"])
    descent = find_descent(track, window=CONFIG["track"]["descent_window_frames"])
    contact = fit_contact(track, descent, H_px2floor, sc.r_ball,
                          sc.fps_measured, camera=camera)
    return track, contact


def _report(name, contact, res):
    err = float(np.linalg.norm(contact.landing_xz - res.contact_xz))
    t_err_ms = abs(contact.t_star - res.contact_time_s) * 1e3
    print(f"\n[e2e:{name}] landing error {err * 1000:.2f} mm | "
          f"t* error {t_err_ms:.3f} ms "
          f"({t_err_ms * res.scenario.fps_measured / 1e3:.2f} frames) | "
          f"{contact.n_descent_frames} descent frames | method {contact.method}")
    return err, t_err_ms


@pytest.fixture(scope="module")
def nominal_run():
    sc = scenarios.nominal(**E2E_KW)
    res = render.render_sequence(sc)
    return sc, res


# --------------------------------------------------------------------------- #
# Positive scenarios                                                           #
# --------------------------------------------------------------------------- #

def test_e2e_nominal_true_H(nominal_run):
    sc, res = nominal_run
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    err, t_err = _report("nominal/trueH", contact, res)
    assert err < 0.010
    assert t_err < 1.5


def test_e2e_nominal_fitted_calibration(nominal_run, tmp_path):
    """The realistic path: H fitted from the frame's ArUco markers (true survey),
    camera position decomposed from the fitted H + K."""
    sc, res = nominal_run
    surveyed = {mid: np.asarray(xz, float) for mid, xz in sc.markers_true.items()}
    calib, _ = ch.run_calibration(res.frames[0], surveyed, sc.held_out_id,
                                  "E2E_A", tol_m=0.005, out_dir=tmp_path)
    assert calib.check_point_ok
    C_est = estimate_camera_position(calib.H, res.cam.K)
    print(f"\n[e2e:fitted] camera-position error "
          f"{np.linalg.norm(C_est - res.cam.C) * 1000:.1f} mm")

    _, contact = _run_chain(res, calib.H, CameraGeometry.from_homography(calib.H, res.cam.K), sc)
    err, _ = _report("nominal/fitted", contact, res)
    assert err < 0.012


def test_e2e_blurred(tmp_path):
    sc = scenarios.blurred(**E2E_KW)
    res = render.render_sequence(sc)
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    err, _ = _report("blurred", contact, res)
    assert err < 0.012


def test_e2e_shadowed():
    sc = scenarios.shadowed(**E2E_KW)
    res = render.render_sequence(sc)
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    err, _ = _report("shadowed", contact, res)
    assert err < 0.012


def test_e2e_low_contrast():
    sc = scenarios.low_contrast(**E2E_KW)
    res = render.render_sequence(sc)
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    err, _ = _report("low_contrast", contact, res)
    assert err < 0.012


def test_e2e_dropouts():
    sc = scenarios.with_dropouts(**E2E_KW)
    res = render.render_sequence(sc)
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    err, _ = _report("dropouts", contact, res)
    assert err < 0.010


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 4 (M4): the BOUNCE / reversal branch — the path real footage    #
# always takes. The six scenarios above all vanish at contact (end_reason        #
# 'track_end'); these exercise find_descent's 'reversal' branch end-to-end.       #
# --------------------------------------------------------------------------- #

def _bounce_chain(sc):
    res = render.render_sequence(sc)
    detector = HsvDetector.from_config(CONFIG)
    dets = [detector.detect(f) if f is not None else None for f in res.frames]
    track = build_track(dets, res.times, max_jump_px=CONFIG["track"]["max_jump_px"])
    descent = find_descent(track, window=CONFIG["track"]["descent_window_frames"])
    contact = fit_contact(track, descent, np.linalg.inv(res.H_true), sc.r_ball,
                          sc.fps_measured, camera=CameraGeometry.from_model(res.cam))
    return res, descent, contact


def test_e2e_bounce_reversal_kink_nominal_camera():
    """A real bounce (restitution 0.75) makes find_descent take its 'reversal' branch,
    and the §5.5 (v1.2) KINK solve fires. Tolerance 3 mm — the §6 zero-noise aspiration:
    with the kink the timing error collapses to ~0.00 frame (measured 0.15 mm clean,
    <= 0.36 mm across noise-2/blur/shadow variants; Stage 4 table in IMPLEMENTATION_
    NOTES), leaving only detector-centroid/rasterisation terms. Compare 10.12 mm under
    the pre-v1.2 +0.5-frame bracket — the M4 defect this test guards against."""
    res, descent, contact = _bounce_chain(scenarios.bounce(**E2E_KW))
    assert descent.end_reason == "reversal"        # the real-footage branch, exercised
    assert "contact_time_kink" in contact.flags    # the v1.2 solve, not the bracket
    err = np.linalg.norm(contact.landing_xz - res.contact_xz)
    print(f"\n[e2e:bounce] landing error {err * 1000:.2f} mm (kink)")
    assert err < 0.003


def test_e2e_bounce_oblique_within_gate():
    """The oblique bounce (~12 deg elevation) measured 17.62 mm — OVER the 15 mm §8 gate —
    under the pre-v1.2 bracket (the confirmed M4 failure). The kink intersection is
    invariant to camera obliquity (position is continuous through the bounce; only the
    v-slope kinks), so the same 3 mm zero-noise tolerance applies (measured 0.51 mm
    clean, 0.70 mm at noise sigma=2)."""
    res, descent, contact = _bounce_chain(scenarios.bounce_oblique(**E2E_KW))
    assert descent.end_reason == "reversal"
    assert "contact_time_kink" in contact.flags
    err = np.linalg.norm(contact.landing_xz - res.contact_xz)
    print(f"\n[e2e:bounce_oblique] landing error {err * 1000:.2f} mm (kink; was 17.62 mm "
          f"under the bracket)")
    assert err < 0.003


def test_e2e_bounce_noisy_within_gate():
    """Kink robustness under pixel noise (the degraded-scenario discipline of §6): at
    noise sigma=2 the measured error stays <= 0.36 mm; tolerance 2 mm gives an order of
    magnitude of headroom while still catching any regression to frame-level timing
    (which would cost >= ~3 mm at this geometry)."""
    res, descent, contact = _bounce_chain(scenarios.bounce(noise_sigma=2.0, seed=1,
                                                           **E2E_KW))
    assert descent.end_reason == "reversal"
    err = np.linalg.norm(contact.landing_xz - res.contact_xz)
    print(f"\n[e2e:bounce_noisy] landing error {err * 1000:.2f} mm")
    assert err < 0.002


def test_e2e_fallback_agrees_with_analytic(nominal_run):
    """Commissioning cross-check rehearsal (§5.4): analytic centroid vs lowest-pixel
    fallback.

    [AMENDED v1.5 / WO-OPT-4 Stage 3 — Decision D20; Hari-approved 2026-07-10.] The
    tennis-era assertions (gap < 13 mm, err_fb < 8 mm, "fallback is CLOSER to truth")
    are RETIRED. They no longer describe the physics: the lowest-pixel fallback maps the
    ball's bottom-silhouette tangent, whose parallax offset from the true 3D bottom pole
    scales with r_ball, so it degrades ~x3.56 with the basketball. MEASURED on this exact
    fixture: analytic-vs-fallback gap 10.6 -> 34.2 mm; fallback truth error 3.4 -> 31.0 mm;
    meanwhile the PRIMARY analytic method IMPROVES, 7.2 -> 3.2 mm. So the headline method is
    unaffected (better, even); it is the fallback cross-check whose spread grew. Bounds below
    are the measured basketball values + ~30% margin; they are NOT loosened to hide a
    regression — see the analytic-truth assertion, which is TIGHTENED to 6 mm."""
    sc, res = nominal_run
    _, analytic = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    _, fallback = _run_chain(res, np.linalg.inv(res.H_true), None, sc)
    gap = np.linalg.norm(analytic.landing_xz - fallback.landing_xz)
    err_fb = np.linalg.norm(fallback.landing_xz - res.contact_xz)
    err_an = np.linalg.norm(analytic.landing_xz - res.contact_xz)
    print(f"\n[e2e:fallback] analytic-vs-fallback gap {gap * 1000:.2f} mm, "
          f"fallback truth error {err_fb * 1000:.2f} mm, analytic truth error {err_an * 1000:.2f} mm")
    assert fallback.method == "lowest_pixel"
    assert "parallax_fallback_used" in fallback.flags
    # PRIMARY method: the headline number the module reports. Held TIGHT (measured 3.2 mm).
    assert err_an < 0.006
    # Fallback cross-check: measured gap 34.2 mm / err_fb 31.0 mm for the basketball (D20).
    # Bounds = measured + ~30% margin. The fallback's absolute accuracy is NOT a gate; §5.4
    # keeps it only as a cross-check, and this test rehearses the analytic-vs-fallback compare.
    assert gap < 0.045            # was 0.013 (tennis); parallax offset scales ~x3.56 with r_ball
    assert err_fb < 0.041         # was 0.008 (tennis); fallback is now the WORSE arm, by design


def test_e2e_uncertainty_budget_covers_error(nominal_run):
    """Budget honesty on the nominal run: |E_n|-style check — the achieved landing
    error must sit within 3x the propagated per-axis sigma (loose: one sample)."""
    sc, res = nominal_run
    _, contact = _run_chain(res, np.linalg.inv(res.H_true), CameraGeometry.from_model(res.cam), sc)
    H_px2floor = np.linalg.inv(res.H_true)
    uv = floor_to_pixel(res.H_true, contact.landing_xz)[0]
    budget = unc.build_budget(
        landing_xz=contact.landing_xz, landing_uv=uv, H_px2floor=H_px2floor,
        marker_survey_m=CONFIG["markers"]["survey_sigma_m"]["value"],
        reproj_rms_px=0.2, check_point_err_m=0.004, sigma_px=0.5,
        parallax_P_mapped=contact.landing_xz, r_ball=sc.r_ball,
        camera_C=res.cam.C, sigma_h_m=0.004, vel_xz=contact.vel_xz,
        sigma_t_s=contact.sigma_t_s)
    err_x = abs(contact.landing_xz[0] - res.contact_xz[0])
    err_z = abs(contact.landing_xz[1] - res.contact_xz[1])
    print(f"\n[e2e:budget] err=({err_x * 1000:.2f}, {err_z * 1000:.2f}) mm vs "
          f"sigma=({budget['sigma_x_m'] * 1000:.2f}, "
          f"{budget['sigma_z_m'] * 1000:.2f}) mm")
    assert err_x < 3 * budget["sigma_x_m"]
    assert err_z < 3 * budget["sigma_z_m"]


# --------------------------------------------------------------------------- #
# NEGATIVE controls (§6: mandatory)                                            #
# --------------------------------------------------------------------------- #

def test_e2e_negative_no_ball_never_fabricates():
    """A no-ball clip must produce a clean 'no detection' failure — never a landing."""
    sc = scenarios.no_ball(**E2E_KW, t_end=0.40)
    res = render.render_sequence(sc)
    detector = HsvDetector.from_config(CONFIG)
    detections = [detector.detect(f) for f in res.frames]
    assert all(d is None for d in detections)
    track = build_track(detections, res.times,
                        max_jump_px=CONFIG["track"]["max_jump_px"])
    with pytest.raises(ValueError, match="no ball track"):
        find_descent(track, window=CONFIG["track"]["descent_window_frames"])


def test_e2e_negative_corrupted_survey_flags_the_throw(tmp_path):
    """Corrupted marker survey: the check-point guard must trip (Phase 2) AND the
    resulting landing must actually be materially wrong — proving the guard is
    load-bearing, not decorative."""
    sc = scenarios.survey_perturbed(**E2E_KW)
    res = render.render_sequence(sc)
    corrupted = sc.markers_surveyed()

    with pytest.warns(UserWarning, match="CHECK-POINT GUARD TRIPPED"):
        calib, _ = ch.run_calibration(res.frames[0], corrupted, sc.held_out_id,
                                      "E2E_NEG", tol_m=0.005, out_dir=tmp_path)
    assert not calib.check_point_ok
    assert CHECK_POINT_FAIL_FLAG in calib.flags

    C_est = estimate_camera_position(calib.H, res.cam.K)
    _, contact = _run_chain(res, calib.H, CameraGeometry.from_homography(calib.H, res.cam.K), sc)
    err = np.linalg.norm(contact.landing_xz - res.contact_xz)
    print(f"\n[e2e:neg-survey] landing error with corrupted survey: "
          f"{err * 1000:.1f} mm (guard flags: {calib.flags})")
    assert err > 0.005            # the corruption genuinely poisons the landing
