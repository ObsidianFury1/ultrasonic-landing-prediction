"""Tests for pipeline.web_report.render_session_report (website.md Stage 1).

Fixtures follow test_reporting.py: tests/session_factory.write_session_dir +
process_session populate the session dir; the renderer is then run over it. The
renderer does NO physics -- these tests prove state selection, self-containment,
and that every authoritative number is the on-disk session.json value verbatim.
"""

import copy
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline import web_report
from pipeline.bias import AxisStats, CorrectionModel
from pipeline.process_throw import process_session
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

# scripts/ is not a package; needed to reuse the campaign loader/stats as oracle.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_campaign  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
# A throw proven detectable in test_process_throw / test_reporting (static
# reflector at 1.95 m so the throw closes cleanly).
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _make_processed(config, tmp_path, name, seed):
    """A fully processed session (input mode: prediction present, no GT)."""
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(seed),
                               background_distance_m=1.95)
    folder = write_session_dir(tmp_path / name, session, 20.0)
    process_session(folder, config)
    return folder


def _extract_data(html: str) -> dict:
    """Pull the inlined window.__DATA__ JSON object back out of report.html."""
    m = re.search(r"window\.__DATA__\s*=\s*(\{.*?\});</script>", html, re.S)
    assert m, "window.__DATA__ assignment not found"
    return json.loads(m.group(1).replace("<\\/", "</"))


# --------------------------------------------------------------------------
# Test 1 -- self-containment
# --------------------------------------------------------------------------

def test_self_contained(config, tmp_path):
    folder = _make_processed(config, tmp_path, "S1", 0)
    out = web_report.render_session_report(folder, config)
    html = out.read_text(encoding="utf-8")

    assert "window.__DATA__" in html
    # no external origins / resources of any kind
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html.lower()
    assert "<link href=" not in html.lower()
    assert "//cdn" not in html.lower()


# --------------------------------------------------------------------------
# Test 2 -- state selection (input / frozen / failure)
# --------------------------------------------------------------------------

def test_state_input(config, tmp_path):
    folder = _make_processed(config, tmp_path, "Sin", 1)
    data = _extract_data(web_report.render_session_report(folder, config)
                         .read_text(encoding="utf-8"))
    assert data["state"] == "input"
    assert data["awaiting_ground_truth"] is True
    assert data["ground_truth"] is None
    assert data["prediction"]["raw"]["x_m"] is not None
    # (v2.3 G1) sensors + recommended pair for the chip/scope UI
    assert [s["name"] for s in data["sensors"]] == ["S1", "S2", "S3"]
    assert all("x" in s and "z" in s for s in data["sensors"])
    assert len(data["recommended"]) == 2
    assert set(data["recommended"]) <= {"S1", "S2", "S3"}
    assert data["recommended"][0] != data["recommended"][1]


def test_state_frozen(config, tmp_path):
    folder = _make_processed(config, tmp_path, "Sfr", 2)
    # enter ground truth (the block run_session/append_ground_truth would write)
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    raw = meta["prediction"]["raw"]
    meta["ground_truth"] = {     # new-format (v2.3 G1) multilateration block
        "x_m": raw["x_m"] + 0.05, "z_m": raw["z_m"] - 0.03,
        "r_m": raw["r_m"], "theta_deg": raw["theta_deg"],
        "sigma_x_m": 0.005, "sigma_z_m": 0.005,
        "cov_xz_m2": [[2.5e-5, 0.0], [0.0, 2.5e-5]],
        "L_centroid_m": 1.2,
        "references": [{"name": "S1", "L_m": 0.4}, {"name": "S2", "L_m": 1.3}],
        "sensors_used": ["S1", "S2"], "sigma_tape_m": 0.005,
        "ls_residual_m": 0.001, "cond_number": 3.2, "cond_warn": False,
    }
    (folder / "session.json").write_text(json.dumps(meta, indent=2),
                                         encoding="utf-8")

    data = _extract_data(web_report.render_session_report(folder, config)
                         .read_text(encoding="utf-8"))
    assert data["state"] == "frozen"
    assert data["ground_truth"] is not None
    assert data["ground_truth"]["sensors_used"] == ["S1", "S2"]
    assert data["awaiting_ground_truth"] is False
    # 2-D error is display arithmetic on the on-disk raw + GT: hypot(0.05, 0.03)
    expect_mm = 1000.0 * (0.05**2 + 0.03**2) ** 0.5
    assert data["error_mm"]["raw"] == pytest.approx(expect_mm, abs=1e-6)


def test_state_failure(config, tmp_path):
    # Starve the throw so process_session raises before writing a prediction:
    # truncate raw_serial.log to the header + a couple of triplets (< min_fit).
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(3),
                               background_distance_m=1.95)
    folder = write_session_dir(tmp_path / "Sfa", session, 20.0)
    log = folder / "raw_serial.log"
    lines = log.read_bytes().splitlines()
    log.write_bytes(b"\n".join(lines[:7]) + b"\n")   # header + ~6 readings
    with pytest.raises(ValueError):
        process_session(folder, config)              # no prediction written

    html = web_report.render_session_report(folder, config).read_text(
        encoding="utf-8")
    data = _extract_data(html)
    assert data["state"] == "failure"
    assert data["prediction"]["raw"] is None
    assert data["ground_truth"] is None
    # the "need >= 4" empty-state line is built in Python and inlined
    assert "need >= 4" in html
    assert data["failure_message"] is not None


# --------------------------------------------------------------------------
# Test 3 -- numbers come from disk, not recomputed
# --------------------------------------------------------------------------

def test_numbers_from_disk(config, tmp_path):
    folder = _make_processed(config, tmp_path, "Snum", 4)
    disk = json.loads((folder / "session.json").read_text(
        encoding="utf-8"))["prediction"]["raw"]
    data = _extract_data(web_report.render_session_report(folder, config)
                         .read_text(encoding="utf-8"))
    raw = data["prediction"]["raw"]
    for key in ("x_m", "z_m", "r_m", "theta_deg", "sigma_r_m",
                "sigma_theta_deg", "heading_deg", "v_h_m_s", "dof", "n_points"):
        assert raw[key] == disk[key], key
    assert raw["cov_xz_m2"] == disk["cov_xz_m2"]


# --------------------------------------------------------------------------
# Test 4 -- campaign renderer (numbers == summary_stats; overwrite not append)
# --------------------------------------------------------------------------

# heading 0 => along-track residual == x residual; errors exactly [20,40,40,60] mm
_ERRORS_M = [0.02, 0.04, 0.04, 0.06]


def _campaign_session(folder, config, err):
    """A session with an injected KNOWN prediction + ground truth (heading 0),
    mirroring tests/test_analyze_campaign.py._make_session."""
    throw = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.0, vy=4.0, vz=0.0)
    session = generate_session(config, throw, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(0), n_bg_pre=2, n_bg_post=2)
    write_session_dir(folder, session, 20.0)
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    meta["prediction"] = {
        "raw": {"x_m": 1.0, "z_m": 0.0, "r_m": 1.0, "theta_deg": 0.0,
                "sigma_r_m": 0.02, "sigma_theta_deg": 1.0,
                "heading_deg": 0.0, "v_h_m_s": 3.5, "n_points": 6, "dof": 3,
                "cov_xz_m2": [[4e-4, 0.0], [0.0, 9e-4]]},
        "corrected": None, "model_id": None,
    }
    meta["gate_summary"] = {"n_triplets_used": 6}
    meta["ground_truth"] = {"x_m": 1.0 - err, "z_m": 0.0, "r_m": 1.0 - err,
                            "theta_deg": 0.0, "sigma_x_m": 0.005, "sigma_z_m": 0.005}
    (folder / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder


def _campaign_root(tmp_path, config):
    root = tmp_path / "sessions"
    root.mkdir()
    for i, e in enumerate(_ERRORS_M):
        _campaign_session(root / f"S{i}", config, e)
    return root


def test_campaign_numbers_from_summary_stats(config, tmp_path):
    # Isolate bias.model_path to a tmp location that does NOT exist, so this
    # test's "no correction model" assumption cannot collide with a real
    # correction_model.json a live calibrate_bias.py run may have written at the
    # ambient config-relative path (e.g. the project root, after a real campaign).
    cfg = copy.deepcopy(config)
    cfg["bias"]["model_path"] = str(tmp_path / "no_such_correction_model.json")

    root = _campaign_root(tmp_path, cfg)
    out = web_report.render_campaign_report(root, cfg)
    assert out == root / "campaign.html"
    data = _extract_data(out.read_text(encoding="utf-8"))

    throws = analyze_campaign.load_campaign(
        sorted(str(p) for p in root.iterdir() if p.is_dir()))
    stats = analyze_campaign.summary_stats(throws, None, cfg["bias"]["alpha"])
    assert data["n"] == 4
    assert data["raw"]["mean_mm"] == pytest.approx(stats["raw_mean_m"] * 1000.0)
    assert data["raw"]["ci_mm"][0] == pytest.approx(stats["raw_ci_m"][0] * 1000.0)
    assert data["raw"]["ci_mm"][1] == pytest.approx(stats["raw_ci_m"][1] * 1000.0)
    assert data["corrected"] is None          # no correction_model.json present
    assert len(data["throws"]) == 4


def test_campaign_corrected_matches_model(config, tmp_path):
    root = _campaign_root(tmp_path, config)
    # write a 'none' model and point a config copy at it (the real load path)
    model_path = tmp_path / "correction_model.json"
    dummy = AxisStats(0.0, 0.0, 0.0, 0.0, 0.0, False)
    model = CorrectionModel(mode="none", frame="track", offset_along_m=0.0,
                            offset_cross_m=0.0, linear_slope=0.0,
                            linear_intercept=0.0, n_throws=4,
                            alpha=config["bias"]["alpha"], along=dummy, cross=dummy)
    model_path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    cfg = copy.deepcopy(config)
    cfg["bias"]["model_path"] = str(model_path)

    data = _extract_data(web_report.render_campaign_report(root, cfg)
                         .read_text(encoding="utf-8"))
    throws = analyze_campaign.load_campaign(
        sorted(str(p) for p in root.iterdir() if p.is_dir()))
    stats = analyze_campaign.summary_stats(throws, model, cfg["bias"]["alpha"])
    assert data["corrected"]["mean_mm"] == pytest.approx(
        stats["corrected_mean_m"] * 1000.0)
    assert data["bias_model"]["present"] is True
    assert data["bias_model"]["mode"] == "none"


def test_campaign_overwrites_not_appends(config, tmp_path):
    root = _campaign_root(tmp_path, config)
    web_report.render_campaign_report(root, config)
    first = (root / "campaign.html").read_text(encoding="utf-8")
    web_report.render_campaign_report(root, config)
    second = (root / "campaign.html").read_text(encoding="utf-8")
    assert len(list(root.glob("campaign*.html"))) == 1   # one file, overwritten
    assert first == second                                # deterministic regenerate


def test_campaign_empty_awaiting(config, tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    data = _extract_data(web_report.render_campaign_report(root, config)
                         .read_text(encoding="utf-8"))
    assert data["n"] == 0 and data["awaiting"] is True
    assert data["throws"] == []


# --------------------------------------------------------------------------
# Test 5 (D5) -- live/demo separation via the is_session_dir predicate
# --------------------------------------------------------------------------

def test_predicate_is_session_dir(config, tmp_path):
    """is_session_dir is True iff the path is a dir containing session.json."""
    live = tmp_path / "L0"
    _campaign_session(live, config, 0.02)
    assert web_report.is_session_dir(live) is True
    bare = tmp_path / "bare"
    bare.mkdir()
    assert web_report.is_session_dir(bare) is False        # dir, no session.json
    stray = tmp_path / "campaign.html"
    stray.write_text("<html></html>", encoding="utf-8")
    assert web_report.is_session_dir(stray) is False       # a file, not a dir


def test_live_campaign_excludes_demo_subtree_and_stray(config, tmp_path):
    """(D5) The live campaign builder enumerates by is_session_dir, so a demo/
    container (no top-level session.json) and a stray campaign.html are skipped
    with NO name matching; the demo campaign over <root>/demo sees only its own."""
    root = tmp_path / "sessions"
    root.mkdir()
    # N = 3 live sessions directly under root
    for i, e in enumerate(_ERRORS_M[:3]):
        _campaign_session(root / f"L{i}", config, e)
    # demo/ container holding M = 2 sessions (no demo/session.json itself)
    demo = root / "demo"
    demo.mkdir()
    for i, e in enumerate(_ERRORS_M[:2]):
        _campaign_session(demo / f"D{i}", config, e)
    # a stray campaign.html beside the live sessions -- must never load as one
    (root / "campaign.html").write_text("<html>stale</html>", encoding="utf-8")

    live = _extract_data(web_report.render_campaign_report(root, config)
                         .read_text(encoding="utf-8"))
    assert live["n"] == 3                                  # demo/ + stray excluded
    live_ids = {t["session_id"] for t in live["throws"]}
    assert live_ids == {"L0", "L1", "L2"}

    demo_data = _extract_data(web_report.render_campaign_report(demo, config)
                              .read_text(encoding="utf-8"))
    assert demo_data["n"] == 2                             # only the demo subtree
    assert {t["session_id"] for t in demo_data["throws"]} == {"D0", "D1"}
