"""Phase 4 tests: process_clip orchestrator + overlay + manifest, on synthetic clips.

Also carries the WO-OPT-1 Stage 1 orchestrator-level tests for uncertainty inputs wired
from config (audit finding M1): missing block hard-errors, placeholder components raise
the `unmeasured_uncertainty_components` flag, and config `sigma_C_m` / `rolling_shutter_m`
demonstrably enter the final budget.
"""

import copy
from pathlib import Path

import cv2
import numpy as np
import pytest

from optical import io_session, overlay
from optical.geometry import CameraGeometry, load_config
from scripts import calibrate_homography as ch
from scripts import process_clip as pc
from simulator import render, scenarios

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")


def _synthetic_clip(factory=scenarios.nominal):
    sc = factory(resolution=(1280, 720), t_start=0.36)
    res = render.render_sequence(sc)
    frames = [f for f in res.frames if f is not None]
    times = np.arange(len(frames)) / sc.fps_measured
    clip_meta = {"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
                 "fps_measured": sc.fps_measured}
    calib_meta = {"calib_id": "TEST", "reproj_rms_px": 0.2,
                  "check_point_err_m": 0.004, "intrinsics": None}
    camera = CameraGeometry.from_model(res.cam)
    return sc, res, frames, times, clip_meta, calib_meta, camera


def test_run_clip_pipeline_produces_valid_gt():
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, track, contact = pc.run_clip_pipeline(
        frames, times, CONFIG, np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="2026-07-18_T01")

    io_session.validate_schema(gt)               # frozen schema respected
    assert gt["landing"] is not None
    assert contact is not None and contact.method == "analytic_centroid"
    # landing agrees with the pipeline's own contact result
    assert gt["landing"]["x_m"] == pytest.approx(contact.landing_xz[0], abs=1e-6)
    # and is close to injected truth (Phase-3 bracket-limited tolerance)
    err = np.linalg.norm(np.array([gt["landing"]["x_m"], gt["landing"]["z_m"]])
                         - res.contact_xz)
    assert err < 0.010
    assert gt["quality"]["n_tracked_frames"] >= 4      # >= the contact-fit minimum


def test_no_ball_clip_writes_failure_gt():
    sc = scenarios.no_ball(resolution=(1280, 720), t_start=0.36, t_end=0.40)
    res = render.render_sequence(sc)
    frames = [f for f in res.frames if f is not None]
    times = np.arange(len(frames)) / sc.fps_measured
    gt, track, contact = pc.run_clip_pipeline(
        frames, times, CONFIG, np.linalg.inv(res.H_true),
        CameraGeometry.from_model(res.cam),
        clip_meta={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
                   "fps_measured": sc.fps_measured},
        calib_meta={"calib_id": "TEST", "reproj_rms_px": 0.2,
                    "check_point_err_m": 0.004, "intrinsics": None},
        session_id="fail")
    io_session.validate_schema(gt)
    assert gt["landing"] is None                 # never fabricates a landing
    assert "no_prediction" in gt["quality"]["flags"]
    assert contact is None


def test_write_session_and_overlay(tmp_path):
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, track, contact = pc.run_clip_pipeline(
        frames, times, CONFIG, np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    overlay_frame = frames[contact.t_frame]
    json_path, png_path = pc.write_session(tmp_path, gt, overlay_frame, track,
                                           contact, np.linalg.inv(res.H_true))
    assert json_path.exists() and io_session.read_optical_gt(json_path) == gt
    assert png_path.exists() and png_path.stat().st_size > 1000   # real PNG bytes


def test_overlay_failure_mode_renders(tmp_path):
    sc = scenarios.no_ball(resolution=(640, 360), t_start=0.36, t_end=0.38)
    res = render.render_sequence(sc)
    frames = [f for f in res.frames if f is not None]
    gt = io_session.build_optical_gt(
        session_id="fail", clip={"file": "raw.mp4", "mode": "720p480",
                                 "fps_measured": 479.82},
        calibration={"calib_id": "T", "reproj_rms_px": 0.2, "check_point_err_m": 0.004},
        method={"detector": "hsv", "parallax": "analytic_centroid"},
        landing_xz=None,
        uncertainty={"sigma_x_m": None, "sigma_z_m": None, "sigma_r_m": None,
                     "sigma_theta_deg": None, "components": {}},
        contact={"t_frame": None, "t_subframe": None, "n_descent_frames": 0},
        n_tracked_frames=0, flags=["no_prediction"])
    path = overlay.save_overlay(tmp_path / "landing_overlay.png", frames[-1], None,
                                None, gt, np.linalg.inv(res.H_true))
    assert path.exists() and path.stat().st_size > 1000
    assert "NO VALID PREDICTION" in overlay.summary_text(gt)


def test_summary_text_contains_key_fields():
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, CONFIG, np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    text = overlay.summary_text(gt)
    assert "session   : T01" in text
    assert "landing   : r =" in text
    assert "method    : hsv/analytic_centroid" in text


def test_manifest_append_and_replace(tmp_path):
    mpath = tmp_path / "2026-07-18_manifest.yaml"
    pc.append_manifest(mpath, {"session_id": "T01", "mode": "720p480", "notes": "a"})
    pc.append_manifest(mpath, {"session_id": "T02", "mode": "720p480", "notes": "b"})
    pc.append_manifest(mpath, {"session_id": "T01", "mode": "720p480", "notes": "revised"})
    import yaml
    data = yaml.safe_load(mpath.read_text(encoding="utf-8"))
    ids = [c["session_id"] for c in data["clips"]]
    assert ids.count("T01") == 1 and "T02" in ids           # replace, not duplicate
    t01 = next(c for c in data["clips"] if c["session_id"] == "T01")
    assert t01["notes"] == "revised"


def _all_measured(config):
    """A deep copy of config with every placeholder component marked measured (silences the
    placeholder warning; isolates the numeric-effect tests). Covers the four uncertainty-block
    components AND markers.survey_sigma_m (WO-OPT-3 Stage 3 / D11 — now the same shape)."""
    cfg = copy.deepcopy(config)
    for k in ("pixel_sigma_px", "sigma_h_m", "sigma_C_m", "rolling_shutter_m"):
        cfg["uncertainty"][k]["measured"] = True
    cfg["markers"]["survey_sigma_m"]["measured"] = True
    return cfg


def test_missing_uncertainty_block_is_hard_error():
    """WO-OPT-1 Stage 1 / M1: a config with no `uncertainty:` block must raise, never
    silently default the budget inputs."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    cfg = copy.deepcopy(CONFIG)
    cfg.pop("uncertainty", None)
    with pytest.raises(ValueError, match="uncertainty"):
        pc.run_clip_pipeline(frames, times, cfg, np.linalg.inv(res.H_true), camera,
                             clip_meta=clip_meta, calib_meta=calib_meta, session_id="X")


def test_placeholder_components_raise_unmeasured_flag():
    """measured: false on any consumed component -> flag in JSON + UserWarning naming it."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    with pytest.warns(UserWarning, match="UNMEASURED UNCERTAINTY COMPONENTS"):
        gt, _, _ = pc.run_clip_pipeline(
            frames, times, CONFIG, np.linalg.inv(res.H_true), camera,
            clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    assert "unmeasured_uncertainty_components" in gt["quality"]["flags"]
    # the specific offending components are echoed into notes for the record
    assert "unmeasured uncertainty components" in gt["notes"]


def test_no_unmeasured_flag_when_all_measured():
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    assert "unmeasured_uncertainty_components" not in gt["quality"]["flags"]


def test_config_sigma_C_and_rolling_shutter_enter_budget():
    """WO-OPT-1 Stage 1 task (d): sigma_C_m and rolling_shutter_m from config demonstrably
    grow the budget at the ORCHESTRATOR level, not just in the pure build_budget()."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    H = np.linalg.inv(res.H_true)
    base = _all_measured(CONFIG)
    gt0, _, _ = pc.run_clip_pipeline(frames, times, base, H, camera,
                                     clip_meta=clip_meta, calib_meta=calib_meta,
                                     session_id="T0")

    cfg_rs = copy.deepcopy(base)
    cfg_rs["uncertainty"]["rolling_shutter_m"]["value"] = 0.01
    gt_rs, _, _ = pc.run_clip_pipeline(frames, times, cfg_rs, H, camera,
                                       clip_meta=clip_meta, calib_meta=calib_meta,
                                       session_id="Trs")
    assert (gt_rs["uncertainty"]["components"]["temporal_m"]
            > gt0["uncertainty"]["components"]["temporal_m"])
    assert gt_rs["uncertainty"]["sigma_x_m"] >= gt0["uncertainty"]["sigma_x_m"]

    cfg_c = copy.deepcopy(base)
    cfg_c["uncertainty"]["sigma_C_m"]["value"] = [0.05, 0.05, 0.05]
    gt_c, _, _ = pc.run_clip_pipeline(frames, times, cfg_c, H, camera,
                                      clip_meta=clip_meta, calib_meta=calib_meta,
                                      session_id="Tc")
    assert (gt_c["uncertainty"]["components"]["parallax_residual_m"]
            > gt0["uncertainty"]["components"]["parallax_residual_m"])


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 2 — real delivered frame rate (M2)                           #
# --------------------------------------------------------------------------- #

def test_resolve_fps_precedence():
    """--fps-measured wins over container; container used when no arg; refuse if neither.
    tol 5% keeps 480/479/479.82 from tripping mismatch so precedence is isolated."""
    used, _, _ = pc.resolve_fps(480.0, 479.0, 479.82, tol_pct=5.0)
    assert used == 479.82                                   # CLI arg overrides container
    used, _, _ = pc.resolve_fps(480.0, 479.0, None, tol_pct=5.0)
    assert used == 479.0                                    # container used, not nominal
    with pytest.raises(ValueError, match="no usable measured frame rate"):
        pc.resolve_fps(480.0, None, None, tol_pct=5.0)      # nominal never used for timing


def test_resolve_fps_mismatch_within_and_beyond_tol():
    # 479.82 vs 480 -> ~0.038%, within 0.5% -> no mismatch (the simulator's own values)
    _, mm, vals = pc.resolve_fps(480.0, 479.82, None, tol_pct=0.5)
    assert mm is False and set(vals) == {"fps_nominal", "fps_container"}
    # container 470 vs nominal 480 -> ~2.1% -> mismatch
    _, mm, _ = pc.resolve_fps(480.0, 470.0, None, tol_pct=0.5)
    assert mm is True


def test_fps_measured_lands_truthfully_not_nominal():
    """The used (measured) rate lands in the JSON, distinct from nominal — never a copy."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    assert clip_meta["fps_measured"] != clip_meta["fps_nominal"]   # 479.82 vs 480
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    assert gt["clip"]["fps_measured"] == pytest.approx(479.82)
    assert gt["clip"]["fps_nominal"] == 480


def test_fps_mismatch_flag_merges_into_json():
    """main() injects fps_mismatch via extra_flags; it must reach quality.flags."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01",
        extra_flags=["fps_mismatch"])
    assert "fps_mismatch" in gt["quality"]["flags"]
    # and it stays absent when no extra flag is passed
    gt2, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T01")
    assert "fps_mismatch" not in gt2["quality"]["flags"]


def test_read_container_fps_matches_written_rate(tmp_path):
    """WO-OPT-3 Stage 5: de-tautologized. The fixture writes the clip at 120 fps, so
    read_container_fps must return ~120 (not merely 'positive'); container metadata may
    quantize slightly, hence the 1 fps tolerance. A missing file returns None."""
    path = tmp_path / "raw.mp4"
    frames = [np.full((120, 160, 3), i * 8 % 255, np.uint8) for i in range(15)]
    pc.write_trimmed(frames, path, fps=120.0)
    if not path.exists() or path.stat().st_size == 0:
        pytest.skip("mp4v VideoWriter unavailable on this system")
    fps = pc.read_container_fps(path)
    if fps is None:
        pytest.skip("this OpenCV build does not report container fps for mp4v")
    assert fps == pytest.approx(120.0, abs=1.0)      # the actual WRITTEN rate, within quantization
    assert pc.read_container_fps(tmp_path / "nope.mp4") is None   # missing file -> None


# --------------------------------------------------------------------------- #
# WO-OPT-3 Stage 2 — fps hard-refuse band (Major 4.2 / Decision D9)            #
# --------------------------------------------------------------------------- #

def test_resolve_fps_hard_refuse_gross_container_gap():
    """No --fps-measured, container 30 vs nominal 480 (playback-rate container): the used rate
    (= container) is a ~16x-wrong temporal base -> OpticalConfigError, run refused."""
    from optical.errors import OpticalConfigError
    with pytest.raises(OpticalConfigError, match="REFUSING to process"):
        pc.resolve_fps(480.0, 30.0, None, tol_pct=0.5, refuse_pct=20.0)


def test_resolve_fps_typo_measured_is_refused():
    """A mistyped --fps-measured (48 for 480) becomes the used rate and is refused against
    nominal — the refuse also guards the operator-supplied value, not just the container."""
    from optical.errors import OpticalConfigError
    with pytest.raises(OpticalConfigError, match="REFUSING to process"):
        pc.resolve_fps(480.0, 479.82, 48.0, tol_pct=0.5, refuse_pct=20.0)


def test_resolve_fps_two_percent_still_flag_and_continue():
    """D2 UNCHANGED: a ~2% container-vs-nominal gap flags fps_mismatch and does NOT refuse."""
    used, mm, _ = pc.resolve_fps(480.0, 470.0, None, tol_pct=0.5, refuse_pct=20.0)
    assert used == 470.0 and mm is True          # flagged, run continues (no raise)


def test_resolve_fps_refuse_band_boundaries():
    """Just inside 20% -> continue (flagged); just outside -> refuse. No --fps-measured, so
    the used rate is the container and the comparison is container-vs-nominal."""
    from optical.errors import OpticalConfigError
    # 400 vs 480: |400-480| / 440 = 18.18% (< 20) -> no refuse
    used, mm, _ = pc.resolve_fps(480.0, 400.0, None, tol_pct=0.5, refuse_pct=20.0)
    assert used == 400.0 and mm is True
    # 380 vs 480: |380-480| / 430 = 23.26% (> 20) -> refuse
    with pytest.raises(OpticalConfigError):
        pc.resolve_fps(480.0, 380.0, None, tol_pct=0.5, refuse_pct=20.0)


def test_resolve_fps_measured_supersedes_bad_container_no_refuse():
    """WO-OPT-3 Stage 2 judgment call (prompt 5d): --fps-measured=480 (sane, = nominal) WITH a
    playback-rate container (30 fps). Precedence keeps --fps-measured for TIMING; the superseded
    container does NOT force a refuse — that is the EXPECTED slow-mo case that --fps-measured
    exists to remedy (a used-vs-nominal refuse would otherwise fire on every real clip). It does
    still trip the D2 fps_mismatch flag so the container anomaly is surfaced."""
    used, mm, vals = pc.resolve_fps(480.0, 30.0, 480.0, tol_pct=0.5, refuse_pct=20.0)
    assert used == 480.0                          # --fps-measured wins for timing
    assert mm is True                             # container disagreement still flagged (D2)
    assert set(vals) == {"fps_nominal", "fps_container", "fps_measured_arg"}


def test_main_refuses_and_writes_nothing(tmp_path):
    """End-to-end: a gross container-vs-nominal gap makes main() raise OpticalConfigError BEFORE
    any write (resolve_fps is upstream of calib load, frame load, and every output) — so no
    optical_gt.json appears in the session dir. Skips if the local mp4v writer/reader can't
    reproduce a ~30 fps container."""
    from optical.errors import OpticalConfigError
    cfg_path = str(Path(__file__).resolve().parents[1] / "config.yaml")
    session = tmp_path / "2026-07-18_T99"
    session.mkdir()
    frames = [np.full((120, 160, 3), (i * 8) % 255, np.uint8) for i in range(12)]
    pc.write_trimmed(frames, session / "raw.mp4", fps=30.0)
    if not (session / "raw.mp4").exists() or (session / "raw.mp4").stat().st_size == 0:
        pytest.skip("mp4v VideoWriter unavailable on this system")
    container = pc.read_container_fps(session / "raw.mp4")
    if container is None or abs(container - 480.0) / ((container + 480.0) / 2) * 100 <= 20:
        pytest.skip("container fps not read as a gross mismatch on this system")
    with pytest.raises(OpticalConfigError):
        pc.main(["--session", str(session), "--calib", str(tmp_path / "nope.yaml"),
                 "--mode", "720p480", "--config", cfg_path])
    assert not (session / "optical_gt.json").exists()   # refused before any write


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 3 — homography stability re-check wired into production (M3)  #
# --------------------------------------------------------------------------- #

def _stability_setup(tmp_path):
    """Render a nominal session + a camera-bumped variant; calibrate on the nominal frame.
    Returns (calib, still_frames, drift_frames, config_with_survey)."""
    kw = dict(resolution=(1280, 720), t_start=0.36)
    res_nom = render.render_sequence(scenarios.nominal(**kw))
    res_bump = render.render_sequence(scenarios.nominal(cam_target=(0.4, 0.0, 0.06), **kw))
    n = len(res_nom.frames)
    k = n // 2
    still = list(res_nom.frames)
    drift = list(res_nom.frames[:k]) + list(res_bump.frames[k:])   # camera moves mid-session
    surveyed = {mid: np.asarray(xz, float) for mid, xz in scenarios.BASE_MARKERS.items()}
    calib, _ = ch.run_calibration(res_nom.frames[0], surveyed, scenarios.HELD_OUT_ID,
                                  "STAB", tol_m=0.005, out_dir=tmp_path)
    cfg = copy.deepcopy(CONFIG)
    cfg["markers"]["fit_points"] = [
        {"id": scenarios.HELD_OUT_ID,
         "xz": list(scenarios.BASE_MARKERS[scenarios.HELD_OUT_ID]), "held_out": True}]
    return calib, still, drift, cfg


def test_stability_drift_flag_reaches_json(tmp_path):
    """Mid-session camera bump -> evaluate_stability returns a list containing homography_drift
    (and, since the end frame now also maps far in absolute terms, stability_abs_fail), the
    loud warning fires, and the flag reaches the JSON via extra_flags (end-to-end).
    evaluate_stability now returns a LIST of flags (WO-OPT-3 Stage 1)."""
    calib, still, drift, cfg = _stability_setup(tmp_path)
    with pytest.warns(UserWarning, match="HOMOGRAPHY DRIFT"):
        flags, msg = pc.evaluate_stability(drift, calib, cfg)
    assert "homography_drift" in flags

    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(cfg), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="T", extra_flags=flags)
    assert "homography_drift" in gt["quality"]["flags"]


def test_stability_still_camera_no_flag(tmp_path):
    calib, still, drift, cfg = _stability_setup(tmp_path)
    flags, msg = pc.evaluate_stability(still, calib, cfg)
    assert flags == [] and msg is None           # neither guard trips on a still, in-cal clip


def test_stability_unchecked_when_survey_missing(tmp_path):
    """No surveyed check-point position -> the check cannot run -> stability_unchecked,
    never a silent skip."""
    calib, still, drift, cfg = _stability_setup(tmp_path)
    cfg["markers"]["fit_points"] = []            # remove the surveyed check point
    flags, msg = pc.evaluate_stability(still, calib, cfg)
    assert "stability_unchecked" in flags
    assert "unavailable" in msg


# --------------------------------------------------------------------------- #
# WO-OPT-3 Stage 1 — absolute stability guard + check_point_fail plumbing      #
# --------------------------------------------------------------------------- #

def test_bump_between_calibration_and_clip_flags_abs_fail(tmp_path):
    """LOAD-BEARING negative control (WO-OPT-3 Major 4.1): a camera bump BETWEEN calibration
    and the clip — then held still through the clip — yields ~zero start-to-end drift but a
    large ABSOLUTE check-point error, so stability_abs_fail fires (homography_drift does NOT),
    and the landing through the stale calibration is materially wrong. Mirrors the
    corrupted-survey control; it must fail if the absolute guard is ever weakened."""
    kw = dict(resolution=(1280, 720), t_start=0.36)
    cal_frame = render.render_sequence(
        scenarios.nominal(traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0)).frames[0]
    surveyed = {mid: np.asarray(xz, float) for mid, xz in scenarios.BASE_MARKERS.items()}
    calib, _ = ch.run_calibration(cal_frame, surveyed, scenarios.HELD_OUT_ID, "BUMP",
                                  tol_m=0.005, out_dir=tmp_path)
    assert calib.check_point_ok                      # the calibration itself is good

    # Camera bumped between calibration and the clip, then held still THROUGH the clip: an
    # aim nudge (~1 deg, cam_target shifted 6 cm at ~3.5 m) — the whole clip is filmed at the
    # bumped pose, so start-to-end drift is ~0 while the absolute check-point error is large.
    bumped = scenarios.nominal(cam_target=(0.4, 0.0, 0.06), **kw)
    res = render.render_sequence(bumped)
    frames = [f for f in res.frames if f is not None]
    cfg = copy.deepcopy(CONFIG)
    cfg["markers"]["fit_points"] = [
        {"id": scenarios.HELD_OUT_ID,
         "xz": list(scenarios.BASE_MARKERS[scenarios.HELD_OUT_ID]), "held_out": True}]

    with pytest.warns(UserWarning, match="STABILITY ABSOLUTE ERROR"):
        flags, msg = pc.evaluate_stability(frames, calib, cfg)
    assert "stability_abs_fail" in flags
    assert "homography_drift" not in flags           # camera still DURING the clip -> ~0 drift

    times = np.arange(len(frames)) / bumped.fps_measured
    camera = CameraGeometry.from_homography(calib.H, res.cam.K)
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(cfg), calib.H, camera,
        clip_meta={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
                   "fps_measured": bumped.fps_measured},
        calib_meta={"calib_id": calib.calib_id, "reproj_rms_px": calib.reproj_rms_px,
                    "check_point_err_m": calib.check_point_err_m, "intrinsics": None},
        session_id="bump", extra_flags=flags)
    assert gt["landing"] is not None
    land = np.array([gt["landing"]["x_m"], gt["landing"]["z_m"]])
    err = float(np.linalg.norm(land - res.contact_xz))
    print(f"\n[stage1:bump] abs-fail landing error {err * 1000:.1f} mm, "
          f"flags={gt['quality']['flags']}")
    assert err > 0.005                               # the stale calibration poisons the landing
    assert "stability_abs_fail" in gt["quality"]["flags"]


def test_no_bump_no_abs_fail(tmp_path):
    """Control for the above: a clip at the SAME pose as calibration -> neither
    stability_abs_fail nor homography_drift; clean flags."""
    kw = dict(resolution=(1280, 720), t_start=0.36)
    cal_frame = render.render_sequence(
        scenarios.nominal(traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0)).frames[0]
    surveyed = {mid: np.asarray(xz, float) for mid, xz in scenarios.BASE_MARKERS.items()}
    calib, _ = ch.run_calibration(cal_frame, surveyed, scenarios.HELD_OUT_ID, "NOBUMP",
                                  tol_m=0.005, out_dir=tmp_path)
    res = render.render_sequence(scenarios.nominal(**kw))        # same pose as calibration
    frames = [f for f in res.frames if f is not None]
    cfg = copy.deepcopy(CONFIG)
    cfg["markers"]["fit_points"] = [
        {"id": scenarios.HELD_OUT_ID,
         "xz": list(scenarios.BASE_MARKERS[scenarios.HELD_OUT_ID]), "held_out": True}]
    flags, msg = pc.evaluate_stability(frames, calib, cfg)
    assert flags == [] and msg is None


def test_check_point_fail_survives_into_per_throw_json(tmp_path):
    """WO-OPT-3 Moderate 5.1: check_point_fail, produced at calibration time when the held-out
    guard trips, now survives the process_clip FLAG_VOCAB filter into the per-throw JSON.
    Before Stage 1 it was absent from FLAG_VOCAB, so the filter silently dropped it and it
    never reached any output."""
    sc = scenarios.survey_perturbed(traj=None, resolution=(1280, 720), t_start=0.0, t_end=0.0)
    cal_res = render.render_sequence(sc)
    with pytest.warns(UserWarning, match="CHECK-POINT GUARD TRIPPED"):
        calib, _ = ch.run_calibration(cal_res.frames[0], sc.markers_surveyed(),
                                      sc.held_out_id, "CPF", tol_m=0.005, out_dir=tmp_path)
    assert not calib.check_point_ok
    assert "check_point_fail" in calib.flags
    extra = [f for f in calib.flags if f in io_session.FLAG_VOCAB]   # the main() filter step
    assert "check_point_fail" in extra               # NOW kept (was dropped before Stage 1)

    clip = render.render_sequence(scenarios.nominal(resolution=(1280, 720), t_start=0.36))
    frames = [f for f in clip.frames if f is not None]
    times = np.arange(len(frames)) / clip.scenario.fps_measured
    gt, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(clip.H_true),
        CameraGeometry.from_model(clip.cam),
        clip_meta={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
                   "fps_measured": clip.scenario.fps_measured},
        calib_meta={"calib_id": "CPF", "reproj_rms_px": 0.2,
                    "check_point_err_m": 0.02, "intrinsics": None},
        session_id="cpf", extra_flags=extra)
    assert "check_point_fail" in gt["quality"]["flags"]


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 5.1/5.2 — typed errors + fallback-intrinsics gating          #
# --------------------------------------------------------------------------- #

def test_data_error_caught_as_no_prediction():
    """An OpticalDataError (no ball) is caught -> valid failure-mode artifact."""
    from optical.errors import OpticalDataError
    sc = scenarios.no_ball(resolution=(1280, 720), t_start=0.36, t_end=0.40)
    res = render.render_sequence(sc)
    frames = [f for f in res.frames if f is not None]
    times = np.arange(len(frames)) / sc.fps_measured
    gt, _, contact = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true),
        CameraGeometry.from_model(res.cam),
        clip_meta={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
                   "fps_measured": sc.fps_measured},
        calib_meta={"calib_id": "T", "reproj_rms_px": 0.2, "check_point_err_m": 0.004,
                    "intrinsics": None}, session_id="nb")
    assert gt["landing"] is None and "no_prediction" in gt["quality"]["flags"]
    assert contact is None


def test_config_error_propagates_not_swallowed():
    """An OpticalConfigError (camera BELOW the ball) must PROPAGATE out of the pipeline,
    never be reported as an ordinary no-prediction outcome (Stage 5.1)."""
    from optical.errors import OpticalConfigError
    from optical.geometry import CameraGeometry as CG
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    bad = CG(K=res.cam.K, R=res.cam.R,
             C=np.array([res.cam.C[0], 0.01, res.cam.C[2]]))     # C_y < r_ball
    with pytest.raises(OpticalConfigError):
        pc.run_clip_pipeline(frames, times, _all_measured(CONFIG),
                             np.linalg.inv(res.H_true), bad, clip_meta=clip_meta,
                             calib_meta=calib_meta, session_id="cfg")


def test_resolve_camera_K_three_paths():
    from optical.errors import OpticalConfigError
    K_real = np.array([[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1.0]])
    K, flag = pc.resolve_camera_K({"camera_matrix": K_real}, False, CONFIG, "720p480")
    assert np.allclose(K, K_real) and flag is None            # measured -> no flag
    with pytest.warns(UserWarning, match="FALLBACK INTRINSICS"):
        K2, flag2 = pc.resolve_camera_K(None, True, CONFIG, "720p480")
    assert flag2 == "fallback_intrinsics" and K2.shape == (3, 3)   # opt-in fallback -> flag
    with pytest.raises(OpticalConfigError, match="no --intrinsics"):
        pc.resolve_camera_K(None, False, CONFIG, "720p480")       # absent + not allowed -> hard


def test_ambiguous_frames_flag_detection_gaps():
    """Stage 6.3: >= 2 ambiguous frames in the descent window -> detection_gaps; a single
    ambiguous frame (common transient) does not."""
    from optical.track import Track, DescentSegment
    n = 8
    cxy = np.column_stack([np.arange(n) + 1.0, np.arange(n) + 1.0])
    descent = DescentSegment(indices=np.arange(n), end_reason="track_end", flags=[])

    st2 = ["ok"] * n; st2[3] = st2[5] = "ambiguous"
    tr2 = Track(times=np.arange(n) / 480.0, centroid_px=cxy.copy(),
                lowest_px=np.zeros((n, 2)), status=st2)
    assert "detection_gaps" in pc._quality_flags(tr2, descent, None)

    st1 = ["ok"] * n; st1[3] = "ambiguous"
    tr1 = Track(times=np.arange(n) / 480.0, centroid_px=cxy.copy(),
                lowest_px=np.zeros((n, 2)), status=st1)
    assert "detection_gaps" not in pc._quality_flags(tr1, descent, None)


def test_load_clip_frames_trim_roundtrip(tmp_path):
    """write_trimmed -> load_clip_frames slice: exercises the on-disk video path."""
    path = tmp_path / "raw.mp4"
    frames = [np.full((120, 160, 3), i * 8 % 255, np.uint8) for i in range(30)]
    pc.write_trimmed(frames, path, fps=30)
    if not path.exists() or path.stat().st_size == 0:
        pytest.skip("mp4v VideoWriter unavailable on this system")
    got = pc.load_clip_frames(path, in_frame=5, out_frame=15)
    assert len(got) == 10
    assert got[0].shape == (120, 160, 3)


# --------------------------------------------------------------------------- #
# WO-OPT-3 Stage 3 — survey-sigma placeholder (A), main() coverage (B),        #
# fail-loud unknown flags (C)                                                  #
# --------------------------------------------------------------------------- #

_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "config.yaml")


def test_survey_sigma_placeholder_alone_triggers_unmeasured_flag():
    """PART A (Moderate 5.2 / D11): with the four uncertainty-block components all measured,
    an unmeasured markers.survey_sigma_m ALONE still trips unmeasured_uncertainty_components
    (flag + warning + notes echo naming it); a measured survey sigma does not."""
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    gt0, _, _ = pc.run_clip_pipeline(
        frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true), camera,
        clip_meta=clip_meta, calib_meta=calib_meta, session_id="ok")
    assert "unmeasured_uncertainty_components" not in gt0["quality"]["flags"]  # all 5 measured

    cfg = _all_measured(CONFIG)
    cfg["markers"]["survey_sigma_m"]["measured"] = False        # only the survey sigma placeholder
    with pytest.warns(UserWarning, match="UNMEASURED UNCERTAINTY COMPONENTS"):
        gt, _, _ = pc.run_clip_pipeline(
            frames, times, cfg, np.linalg.inv(res.H_true), camera,
            clip_meta=clip_meta, calib_meta=calib_meta, session_id="survey")
    assert "unmeasured_uncertainty_components" in gt["quality"]["flags"]
    assert "markers.survey_sigma_m" in gt["notes"]              # named in the notes echo


def test_malformed_survey_sigma_hard_errors():
    """PART A: a malformed markers.survey_sigma_m (bare number, old shape) hard-errors in
    run_clip_pipeline rather than being silently defaulted."""
    from optical.errors import OpticalConfigError
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    cfg = _all_measured(CONFIG)
    cfg["markers"]["survey_sigma_m"] = 0.0025                    # bare number, not {value, measured}
    with pytest.raises(OpticalConfigError, match="survey_sigma_m"):
        pc.run_clip_pipeline(frames, times, cfg, np.linalg.inv(res.H_true), camera,
                             clip_meta=clip_meta, calib_meta=calib_meta, session_id="bad")


def _main_raw_and_calib(tmp_path, factory, session_name):
    """Render a synthetic clip to <session>/raw.mp4 (480 fps) + a calibration yaml, for main()
    tests. Returns (session_dir, calib_path) or skips if mp4v is unavailable."""
    res = render.render_sequence(factory(resolution=(1280, 720), t_start=0.36))
    frames = [f for f in res.frames if f is not None]
    session = tmp_path / session_name
    session.mkdir()
    pc.write_trimmed(frames, session / "raw.mp4", fps=480.0)
    if not (session / "raw.mp4").exists() or (session / "raw.mp4").stat().st_size == 0:
        pytest.skip("mp4v VideoWriter unavailable on this system")
    surveyed = {mid: np.asarray(xz, float) for mid, xz in scenarios.BASE_MARKERS.items()}
    _, calib_path = ch.run_calibration(frames[0], surveyed, scenarios.HELD_OUT_ID,
                                       session_name, tol_m=0.005, out_dir=tmp_path)
    return session, calib_path


def test_main_end_to_end_artifacts_flags_and_manifest(tmp_path):
    """PART B: main() end-to-end under a --manifest-dir override. Asserts optical_gt.json +
    landing_overlay.png written; a landing recovered (contact branch -> overlay uses
    frames[contact.t_frame]); multi-stage extra_flags accumulate into the JSON
    (fallback_intrinsics from --allow-fallback-intrinsics; stability_unchecked from an EMPTY
    fit_points config; unmeasured_uncertainty_components from the placeholder config); and the
    manifest entry is written under the override with the free-text notes, dedup by session_id
    on a re-run (§9 as-built / WO-OPT-1 Stage 6).

    Uses a TEMP config copy with markers.fit_points forced empty, rather than the live project
    config.yaml (Phase 5 fieldwork, 2026-07-11, populated the real config's marker survey --
    this test's `stability_unchecked` assertion specifically needs the no-survey pathway, which
    is now a deliberately-empty fixture rather than an assumption about the live file)."""
    import yaml as _yaml
    session, calib_path = _main_raw_and_calib(tmp_path, scenarios.nominal, "2026-07-18_M01")
    mdir = tmp_path / "manifests"
    empty_markers_cfg = _yaml.safe_load(Path(_CONFIG_PATH).read_text(encoding="utf-8"))
    empty_markers_cfg["markers"]["fit_points"] = []
    empty_cfg_path = tmp_path / "config_empty_markers.yaml"
    empty_cfg_path.write_text(_yaml.safe_dump(empty_markers_cfg), encoding="utf-8")
    argv = ["--session", str(session), "--calib", str(calib_path), "--config", str(empty_cfg_path),
            "--mode", "720p480", "--fps-measured", "480", "--allow-fallback-intrinsics",
            "--manifest-dir", str(mdir), "--notes", "wind calm; op HK"]
    with pytest.warns(UserWarning):                  # fallback-intrinsics + unmeasured warnings
        assert pc.main(argv) == 0
    gt = io_session.read_optical_gt(session / "optical_gt.json")
    assert (session / "landing_overlay.png").exists()
    assert gt["landing"] is not None                 # contact solve succeeded through raw.mp4
    fl = set(gt["quality"]["flags"])
    assert "fallback_intrinsics" in fl               # accumulation: fps->FALLBACK->calib->stability
    assert "stability_unchecked" in fl               # shipped config has empty fit_points
    assert "unmeasured_uncertainty_components" in fl  # placeholder config
    mfiles = list(mdir.glob("*_manifest.yaml"))
    assert len(mfiles) == 1
    data = _yaml.safe_load(mfiles[0].read_text(encoding="utf-8"))
    assert [c["session_id"] for c in data["clips"]] == ["2026-07-18_M01"]
    assert data["clips"][0]["notes"] == "wind calm; op HK"    # wind/op captured in free-text notes
    with pytest.warns(UserWarning):
        assert pc.main(argv) == 0                    # re-run
    data2 = _yaml.safe_load(mfiles[0].read_text(encoding="utf-8"))
    assert [c["session_id"] for c in data2["clips"]] == ["2026-07-18_M01"]   # dedup: one entry


def test_main_no_ball_overlay_uses_last_frame(tmp_path):
    """PART B: main() on a no-ball clip -> contact is None -> the overlay-frame selection takes
    its else branch (frames[-1], not frames[contact.t_frame]); the JSON has landing null +
    no_prediction and the overlay still renders."""
    session, calib_path = _main_raw_and_calib(tmp_path, scenarios.no_ball, "2026-07-18_M02")
    with pytest.warns(UserWarning):
        assert pc.main(["--session", str(session), "--calib", str(calib_path),
                        "--config", _CONFIG_PATH, "--mode", "720p480", "--fps-measured", "480",
                        "--allow-fallback-intrinsics", "--manifest-dir", str(tmp_path / "m")]) == 0
    gt = io_session.read_optical_gt(session / "optical_gt.json")
    assert gt["landing"] is None and "no_prediction" in gt["quality"]["flags"]
    assert (session / "landing_overlay.png").exists()   # rendered from frames[-1]


def test_unknown_producer_flag_fails_loud(tmp_path):
    """PART C (D12): _quality_flags no longer filters out-of-vocabulary flags, and
    build_optical_gt is the sole authority that rejects them — a producer typo now crashes
    loudly instead of vanishing. Also: run_clip_pipeline raises before reaching any write step,
    so no partial optical_gt.json is produced (build_optical_gt raises inside it, upstream of
    write_session)."""
    from optical.track import Track, DescentSegment
    n = 6
    cxy = np.column_stack([np.arange(n) + 1.0, np.arange(n) + 1.0])
    tr = Track(times=np.arange(n) / 480.0, centroid_px=cxy.copy(),
               lowest_px=np.zeros((n, 2)), status=["ok"] * n)
    descent = DescentSegment(indices=np.arange(n), end_reason="track_end",
                             flags=["totally_bogus_flag"])
    flags = pc._quality_flags(tr, descent, None)
    assert "totally_bogus_flag" in flags             # passed through, NOT dropped (pre-D12 it was)
    with pytest.raises(ValueError, match="totally_bogus_flag"):
        io_session.build_optical_gt(
            session_id="x", clip={}, calibration={}, method={}, landing_xz=(0.5, 0.0),
            uncertainty={"sigma_x_m": 0.0, "sigma_z_m": 0.0, "sigma_r_m": 0.0,
                         "sigma_theta_deg": 0.0, "components": {}},
            contact={"t_frame": 1, "t_subframe": 1.5, "n_descent_frames": 6},
            n_tracked_frames=6, flags=flags)

    # end-to-end: the same bogus flag via run_clip_pipeline raises before any write step
    sc, res, frames, times, clip_meta, calib_meta, camera = _synthetic_clip()
    with pytest.raises(ValueError, match="totally_bogus_flag"):
        pc.run_clip_pipeline(frames, times, _all_measured(CONFIG), np.linalg.inv(res.H_true),
                             camera, clip_meta=clip_meta, calib_meta=calib_meta,
                             session_id="bogus", extra_flags=["totally_bogus_flag"])
