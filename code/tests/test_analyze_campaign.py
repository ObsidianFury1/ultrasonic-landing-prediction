"""Tests for scripts/analyze_campaign.py and scripts/append_ground_truth.py.

Fixtures reuse tests/session_factory.write_session_dir (no new helper); each
session.json is then patched with KNOWN predictions + ground truth so the 2D
errors and along-track residuals are exact and the summary stats can be checked
against an independent numpy/scipy computation.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy import stats

from pipeline.bias import AxisStats, CorrectionModel
from pipeline.geometry import recommend_reference_sensors
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

# scripts/ is not a package; put it on the path to import the campaign tools.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_campaign  # noqa: E402
import append_ground_truth  # noqa: E402
import calibrate_bias  # noqa: E402
import run_session  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
ALPHA = 0.05


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _make_session(folder, config, *, pred_xz, actual_xz, heading_deg,
                  n_used=6, with_gt=True):
    """write_session_dir, then inject a known prediction / ground truth / gate."""
    throw = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.0, vy=4.0, vz=0.0)
    session = generate_session(config, throw, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(0), n_bg_pre=2, n_bg_post=2)
    write_session_dir(folder, session, 20.0)
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    meta["prediction"] = {
        "raw": {
            "x_m": pred_xz[0], "z_m": pred_xz[1],
            "r_m": float(np.hypot(*pred_xz)),
            "theta_deg": float(np.degrees(np.arctan2(pred_xz[1], pred_xz[0]))),
            "sigma_r_m": 0.02, "sigma_theta_deg": 1.0,
            "heading_deg": heading_deg, "v_h_m_s": 3.5,
            "n_points": 6, "dof": 3, "cov_xz_m2": [[4e-4, 0.0], [0.0, 9e-4]],
        },
        "corrected": None, "model_id": None,
    }
    meta["gate_summary"] = {"n_triplets_used": n_used}
    if with_gt:
        meta["ground_truth"] = {"x_m": actual_xz[0], "z_m": actual_xz[1],
                                "r_m": 0.0, "theta_deg": 0.0,
                                "sigma_x_m": 0.005, "sigma_z_m": 0.005}
    (folder / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder


# Four throws (heading 0 => along-track residual == x residual): errors chosen
# so raw 2D error and along-track residual are both exactly [20, 40, 40, 60] mm.
ERRORS_M = [0.02, 0.04, 0.04, 0.06]


def _campaign(tmp_path, config):
    for i, e in enumerate(ERRORS_M):
        _make_session(tmp_path / f"S{i}", config,
                      pred_xz=(1.0, 0.0), actual_xz=(1.0 - e, 0.0), heading_deg=0.0)
    return analyze_campaign.load_campaign([str(tmp_path / "S*")])


class TestSummaryStats:
    def test_loads_all_four(self, tmp_path, config):
        assert len(_campaign(tmp_path, config)) == 4

    def test_raw_stats_hand_computed(self, tmp_path, config):
        throws = _campaign(tmp_path, config)
        s = analyze_campaign.summary_stats(throws, model=None, alpha=ALPHA)

        e = np.array(ERRORS_M)
        exp_mean, exp_std = e.mean(), e.std(ddof=1)
        t_crit = float(stats.t.ppf(1 - ALPHA / 2, len(e) - 1))
        sem = exp_std / np.sqrt(len(e))
        assert s["n"] == 4
        assert s["raw_mean_m"] == pytest.approx(exp_mean)
        assert s["raw_std_m"] == pytest.approx(exp_std)
        assert s["raw_ci_m"][0] == pytest.approx(exp_mean - t_crit * sem)
        assert s["raw_ci_m"][1] == pytest.approx(exp_mean + t_crit * sem)
        # along-track residual == x residual at heading 0
        assert s["along_bias_m"] == pytest.approx(exp_mean)
        assert s["along_scatter_m"] == pytest.approx(exp_std)
        # power_n wired to the reused calibrate_bias.power_n
        import calibrate_bias
        assert s["power_n"] == calibrate_bias.power_n(exp_std, exp_mean, 4, ALPHA)
        assert s["mode"] == "none"

    def test_power_note_confidence_level_from_alpha(self, tmp_path, config):
        """(Minor-9) the power-note confidence level is derived from alpha, not a
        hardcoded 95%. The _campaign bias is non-zero, so power_n is finite and the
        percentage branch fires."""
        throws = _campaign(tmp_path, config)
        s = analyze_campaign.summary_stats(throws, model=None, alpha=0.10)
        assert "90%" in s["power_note"]
        assert "95%" not in s["power_note"]

    def test_none_model_corrected_equals_raw(self, tmp_path, config):
        throws = _campaign(tmp_path, config)
        dummy = AxisStats(0.0, 0.0, 0.0, 0.0, 0.0, False)
        none_model = CorrectionModel(
            mode="none", frame="track", offset_along_m=0.0, offset_cross_m=0.0,
            linear_slope=0.0, linear_intercept=0.0, n_throws=4, alpha=ALPHA,
            along=dummy, cross=dummy)
        s = analyze_campaign.summary_stats(throws, model=none_model, alpha=ALPHA)
        assert s["corrected_mean_m"] == pytest.approx(np.mean(ERRORS_M))
        assert s["corrected_ci_m"][0] == pytest.approx(s["raw_ci_m"][0])
        assert s["mode"] == "none"


class TestAppendGroundTruth:
    def test_updates_only_ground_truth(self, tmp_path, config):
        folder = _make_session(tmp_path / "S", config, pred_xz=(1.0, 0.0),
                               actual_xz=(0, 0), heading_deg=0.0, with_gt=False)
        path = folder / "session.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        assert "ground_truth" not in old

        gt_block = {"x_m": 0.8, "z_m": 0.3, "r_m": 0.854, "theta_deg": 20.6,
                    "sigma_x_m": 0.005, "sigma_z_m": 0.005}
        append_ground_truth.update_session_ground_truth(path, gt_block)

        new = json.loads(path.read_text(encoding="utf-8"))
        assert new["ground_truth"] == gt_block
        new.pop("ground_truth")
        assert new == old                    # everything else unchanged

    def test_end_to_end_via_prompt(self, tmp_path, config, monkeypatch):
        # v2.3 G1: centroid + 2-recommended-sensor multilateration via the prompt.
        folder = _make_session(tmp_path / "S", config, pred_xz=(0.8, 0.3),
                               actual_xz=(0, 0), heading_deg=20.0, with_gt=False)
        path = folder / "session.json"

        mark = np.array([0.8, 0.3])          # the true first-contact mark
        names = recommend_reference_sensors((0.8, 0.3), config)   # default pair
        pa = np.array(config["array"][names[0] + "_xz"])
        pb = np.array(config["array"][names[1] + "_xz"])
        L_c = float(np.hypot(*mark))
        L_a = float(np.hypot(*(mark - pa)))
        L_b = float(np.hypot(*(mark - pb)))
        # accept the recommendation (empty), then the three tapes
        inputs = iter(["", str(L_c), str(L_a), str(L_b)])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))

        gt = append_ground_truth.append_to_session(config, path)
        assert gt is not None

        # terminal/append == direct solve_ground_truth (byte-equality, anti-divergence)
        expected = run_session.solve_ground_truth(
            L_c, [{"name": names[0], "L": L_a}, {"name": names[1], "L": L_b}], config)
        assert gt == expected
        assert gt["sensors_used"] == [names[0], names[1]]
        assert gt["x_m"] == pytest.approx(0.8, abs=1e-6)
        assert gt["z_m"] == pytest.approx(0.3, abs=1e-6)
        # written into the file
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["ground_truth"]["x_m"] == pytest.approx(0.8, abs=1e-6)
        assert meta["ground_truth"]["sensors_used"] == [names[0], names[1]]


def test_load_campaign_skips_non_session_paths(tmp_path, config):
    """(D5) load_campaign routes through is_session_dir: a root/* glob that also
    matches a demo/ container (no top-level session.json) and a stray
    campaign.html loads ONLY the live session dirs (CLAUDE section 8.7 / 12.2)."""
    # 3 live sessions directly under tmp_path
    for i, e in enumerate(ERRORS_M[:3]):
        _make_session(tmp_path / f"L{i}", config, pred_xz=(1.0, 0.0),
                      actual_xz=(1.0 - e, 0.0), heading_deg=0.0)
    # a demo/ container holding a session (no demo/session.json itself)
    demo = tmp_path / "demo"
    demo.mkdir()
    _make_session(demo / "D0", config, pred_xz=(1.0, 0.0),
                  actual_xz=(0.96, 0.0), heading_deg=0.0)
    # a stray campaign.html beside the live sessions
    (tmp_path / "campaign.html").write_text("<html></html>", encoding="utf-8")

    throws = analyze_campaign.load_campaign([str(tmp_path / "*")])
    assert sorted(t.session_dir.name for t in throws) == ["L0", "L1", "L2"]


def test_load_record_ingests_new_format_ground_truth(tmp_path, config):
    """calibrate_bias.load_record reads the preserved DERIVED keys from a new-format
    (multilateration) ground_truth block with references/sensors_used/integrity fields."""
    folder = _make_session(tmp_path / "S", config, pred_xz=(1.0, 0.2),
                           actual_xz=(0, 0), heading_deg=0.0, with_gt=False)
    path = folder / "session.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["ground_truth"] = {
        "x_m": 0.95, "z_m": 0.18, "r_m": 0.967, "theta_deg": 10.7,
        "sigma_x_m": 0.005, "sigma_z_m": 0.005,
        "cov_xz_m2": [[2.5e-5, 0.0], [0.0, 2.5e-5]],
        "L_centroid_m": 0.967,
        "references": [{"name": "S1", "L_m": 0.4}, {"name": "S2", "L_m": 1.3}],
        "sensors_used": ["S1", "S2"], "sigma_tape_m": 0.005,
        "ls_residual_m": 0.001, "cond_number": 3.2, "cond_warn": False,
    }
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    rec, reason = calibrate_bias.load_record(path)
    assert rec is not None, reason
    assert rec.x_actual == pytest.approx(0.95)
    assert rec.z_actual == pytest.approx(0.18)
