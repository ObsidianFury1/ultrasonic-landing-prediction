"""Phase 4 tests: frozen optical_gt.json schema, atomic + byte-stable I/O (§5.6, §11)."""

import json

import numpy as np
import pytest

from optical import io_session as io


def _budget():
    return {"sigma_x_m": 0.006, "sigma_z_m": 0.009, "sigma_r_m": 0.008,
            "sigma_theta_deg": 0.4,
            "components": {"marker_survey_m": 0.003, "homography_m": 0.004,
                           "pixel_localisation_m": 0.003, "parallax_residual_m": 0.002,
                           "temporal_m": 0.004}}


def _valid_gt(landing_xz=(0.412, -1.103), flags=None):
    return io.build_optical_gt(
        session_id="2026-07-18_T03",
        clip={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480,
              "fps_measured": 479.82},
        calibration={"calib_id": "2026-07-18_A", "reproj_rms_px": 0.7,
                     "check_point_err_m": 0.004, "intrinsics": "intrinsics_720p480.yaml"},
        method={"detector": "hsv", "parallax": "analytic_centroid"},
        landing_xz=landing_xz, uncertainty=_budget(),
        contact={"t_frame": 143, "t_subframe": 143.38, "n_descent_frames": 10},
        n_tracked_frames=47, flags=flags or [], notes="")


def test_schema_has_exact_frozen_top_level_keys():
    gt = _valid_gt()
    assert set(gt) == io._REQUIRED_TOP
    # §5.6 nested key names verbatim
    assert set(gt["landing"]) == {"x_m", "z_m", "r_m", "theta_deg"}
    assert set(gt["uncertainty"]) >= {"sigma_x_m", "sigma_z_m", "sigma_r_m",
                                      "sigma_theta_deg", "components"}
    assert set(gt["contact"]) == {"t_frame", "t_subframe", "n_descent_frames"}
    assert set(gt["quality"]) == {"flags", "n_tracked_frames"}


def test_landing_polar_matches_cartesian():
    from optical.geometry import cart_to_polar
    gt = _valid_gt(landing_xz=(0.412, -1.103))
    r, theta = cart_to_polar(0.412, -1.103)
    assert gt["landing"]["r_m"] == pytest.approx(r, abs=1e-6)
    assert gt["landing"]["theta_deg"] == pytest.approx(theta, abs=1e-4)


def test_roundtrip_byte_stable(tmp_path):
    """write -> read -> re-write must be byte-for-byte identical (§11)."""
    gt = _valid_gt(flags=["detection_gaps"])
    p = tmp_path / "optical_gt.json"
    io.write_optical_gt(p, gt)
    first = p.read_bytes()
    reread = io.read_optical_gt(p)
    io.write_optical_gt(p, reread)
    assert p.read_bytes() == first
    assert reread == gt


def test_atomic_write_leaves_no_partial_and_no_temp(tmp_path):
    p = tmp_path / "optical_gt.json"
    io.write_optical_gt(p, _valid_gt())
    assert p.exists()
    assert not (tmp_path / "optical_gt.json.tmp").exists()   # temp cleaned by replace
    # file is complete, parseable JSON (not a partial write)
    json.loads(p.read_text(encoding="utf-8"))


def test_crash_leftover_temp_does_not_corrupt_real_file(tmp_path):
    """A stale .tmp from a previous interrupted write must not affect the real file."""
    p = tmp_path / "optical_gt.json"
    io.write_optical_gt(p, _valid_gt(landing_xz=(0.1, 0.2)))
    good = p.read_bytes()
    (tmp_path / "optical_gt.json.tmp").write_text("GARBAGE PARTIAL {", encoding="utf-8")
    # the real file is still valid and unchanged
    assert p.read_bytes() == good
    assert io.read_optical_gt(p)["landing"]["x_m"] == pytest.approx(0.1)
    # a new write still succeeds and overwrites the stale temp
    io.write_optical_gt(p, _valid_gt(landing_xz=(0.3, 0.4)))
    assert io.read_optical_gt(p)["landing"]["x_m"] == pytest.approx(0.3)


def test_failure_mode_landing_null(tmp_path):
    # A real failure-mode artifact carries full clip/calibration/method sub-dicts (main()
    # provides them); only `landing` is null. Schema-complete so it passes validate_schema
    # (WO-OPT-3 Stage 5 nested-key validation).
    gt = io.build_optical_gt(
        session_id="s",
        clip={"file": "raw.mp4", "mode": "720p480", "fps_nominal": 480, "fps_measured": 479.82},
        calibration={"calib_id": "T", "reproj_rms_px": 0.2, "check_point_err_m": 0.004,
                     "intrinsics": None},
        method={"detector": "hsv", "parallax": "analytic_centroid"},
        landing_xz=None,
        uncertainty={"sigma_x_m": None, "sigma_z_m": None, "sigma_r_m": None,
                     "sigma_theta_deg": None, "components": {}},
        contact={"t_frame": None, "t_subframe": None, "n_descent_frames": 0},
        n_tracked_frames=2, flags=["no_prediction"], notes="no descent")
    assert gt["landing"] is None
    p = io.write_optical_gt(tmp_path / "optical_gt.json", gt)
    assert io.read_optical_gt(p)["landing"] is None


def test_unknown_flag_rejected():
    with pytest.raises(ValueError, match="unknown quality.flags"):
        _valid_gt(flags=["totally_made_up_flag"])


def test_validate_schema_rejects_missing_key_and_wrong_version():
    gt = _valid_gt()
    del gt["landing"]
    with pytest.raises(ValueError, match="missing required keys"):
        io.validate_schema(gt)
    gt2 = _valid_gt()
    gt2["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="schema_version"):
        io.validate_schema(gt2)


def test_validate_schema_rejects_missing_nested_key():
    """WO-OPT-3 Stage 5: nested-key presence is enforced, so a malformed dict raises a clear
    schema error naming the missing key PATH (e.g. 'clip.mode') instead of a later KeyError
    from a downstream consumer such as overlay.summary_text."""
    gt = _valid_gt()
    del gt["clip"]["mode"]
    with pytest.raises(ValueError, match=r"clip\.mode"):
        io.validate_schema(gt)

    gt2 = _valid_gt()
    del gt2["contact"]["t_frame"]
    with pytest.raises(ValueError, match=r"contact\.t_frame"):
        io.validate_schema(gt2)

    gt3 = _valid_gt(landing_xz=(0.4, -1.1))          # non-null landing -> its keys required
    del gt3["landing"]["x_m"]
    with pytest.raises(ValueError, match=r"landing\.x_m"):
        io.validate_schema(gt3)


def test_flag_vocab_includes_wo_opt_3_additions():
    """WO-OPT-3 Stage 1: FLAG_VOCAB grew 14 -> 16 with the two additive flags (O7 preserved —
    no renames/removals). check_point_fail closes the Moderate-5.1 vocabulary gap;
    stability_abs_fail is the new section-5.1 absolute-error flag (Major 4.1)."""
    assert "check_point_fail" in io.FLAG_VOCAB
    assert "stability_abs_fail" in io.FLAG_VOCAB
    assert len(io.FLAG_VOCAB) == 16
    # both must be accepted by build_optical_gt now (were rejected as unknown before)
    gt = _valid_gt(flags=["check_point_fail", "stability_abs_fail"])
    assert set(gt["quality"]["flags"]) == {"check_point_fail", "stability_abs_fail"}
