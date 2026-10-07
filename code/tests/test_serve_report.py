"""Tests for scripts/serve_report.py + the section 6.3 solve refactor (Stage 3).

Tests 5-10 of website.md section 10. Sessions are REAL (generate_session ->
process_session) so they carry a prediction + trajectory.csv and render as input.
The POST core (handle_ground_truth) and helpers are driven directly for
determinism; one test stands up the real ThreadingHTTPServer to prove the HTTP
plumbing.
"""

import json
import re
import sys
import threading
import http.client
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.geometry import recommend_reference_sensors
from pipeline.process_throw import process_session
from pipeline.simulator import ThrowParams, generate_session
from pipeline.web_report import render_session_report
from tests.session_factory import write_session_dir

# scripts/ is not a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_campaign  # noqa: E402
import append_ground_truth  # noqa: E402
import demo_web_reports  # noqa: E402
import run_session  # noqa: E402
import serve_report  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _processed(config, root, name, seed):
    """A real processed session under root/name (prediction + trajectory.csv)."""
    root.mkdir(parents=True, exist_ok=True)
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(seed),
                               background_distance_m=1.95)
    folder = write_session_dir(root / name, session, 20.0)
    process_session(folder, config)
    return folder


def _pred_xz(folder):
    raw = json.loads((folder / "session.json").read_text(
        encoding="utf-8"))["prediction"]["raw"]
    return (raw["x_m"], raw["z_m"])


def _gt_inputs(config, pred_xz, mark=None):
    """(v2.3 G1) (L_centroid, sensors, L_a, L_b) for the two sensors RECOMMENDED
    by the predicted landing, with the three tape distances from a chosen mark
    (default = the prediction, i.e. a small error)."""
    a, b = recommend_reference_sensors(pred_xz, config)
    mark = np.array(pred_xz if mark is None else mark, dtype=float)
    pa = np.array(config["array"][a + "_xz"])
    pb = np.array(config["array"][b + "_xz"])
    return (float(np.hypot(*mark)), [a, b],
            float(np.hypot(*(mark - pa))), float(np.hypot(*(mark - pb))))


def _refs(sensors, L_a, L_b):
    return [{"name": sensors[0], "L": L_a}, {"name": sensors[1], "L": L_b}]


def _extract_data(html: str) -> dict:
    m = re.search(r"window\.__DATA__\s*=\s*(\{.*?\});</script>", html, re.S)
    assert m, "window.__DATA__ not found"
    return json.loads(m.group(1).replace("<\\/", "</"))


def _inputs(values):
    it = iter(values)
    return lambda *a, **k: next(it)


# -- Test 5 -----------------------------------------------------------------

def test_web_block_equals_terminal_and_append(config, tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))

    status, body = serve_report.handle_ground_truth(
        root, "S0", Lc, sensors, La, Lb, config)
    assert status == 200 and body["persisted"] is True
    web_block = json.loads((f / "session.json").read_text(
        encoding="utf-8"))["ground_truth"]

    solve_block = run_session.solve_ground_truth(Lc, _refs(sensors, La, Lb), config)
    assert web_block == solve_block

    # terminal append path: accept the recommendation ("") + 3 tapes -> identical
    f2 = _processed(config, root, "S1", 0)            # seed 0 => same prediction
    monkeypatch.setattr("builtins.input",
                        _inputs(["", str(Lc), str(La), str(Lb)]))
    append_block = append_ground_truth.append_to_session(config, f2 / "session.json")
    assert append_block == solve_block


# -- Test 6 -----------------------------------------------------------------

def test_write_back_freezes_and_updates_campaign(config, tmp_path):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))

    status, _ = serve_report.handle_ground_truth(
        root, "S0", Lc, sensors, La, Lb, config)
    assert status == 200
    gt = json.loads((f / "session.json").read_text(encoding="utf-8")).get("ground_truth")
    assert gt is not None and gt["sensors_used"] == sensors

    data = _extract_data((f / "report.html").read_text(encoding="utf-8"))
    assert data["state"] == "frozen"
    assert (root / "campaign.html").is_file()
    cdata = _extract_data((root / "campaign.html").read_text(encoding="utf-8"))
    assert cdata["n"] >= 1


# -- Test 7 -----------------------------------------------------------------

def test_invalid_sensors_422_nothing_written(config, tmp_path):
    # Multilateration never "fails to intersect"; the 422 path is now an invalid
    # sensor selection (not exactly two distinct of S1/S2/S3).
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    for bad in (["S1", "S1"], ["S1"], ["S1", "S4"], ["S1", "S2", "S3"]):
        status, body = serve_report.handle_ground_truth(
            root, "S0", 0.9, bad, 0.4, 1.1, config)
        assert status == 422 and "error" in body
    assert "ground_truth" not in json.loads((f / "session.json").read_text(encoding="utf-8"))


# -- Test 8 -----------------------------------------------------------------

def test_read_back_round_trip(config, tmp_path):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))
    status, body = serve_report.handle_ground_truth(
        root, "S0", Lc, sensors, La, Lb, config)
    assert status == 200

    meta = json.loads((f / "session.json").read_text(encoding="utf-8"))
    gt, raw = meta["ground_truth"], meta["prediction"]["raw"]
    assert body["r"] == gt["r_m"] and body["theta"] == gt["theta_deg"]
    assert body["x"] == gt["x_m"] and body["z"] == gt["z_m"]
    exp = 1000.0 * np.hypot(raw["x_m"] - gt["x_m"], raw["z_m"] - gt["z_m"])
    assert body["error_mm_raw"] == pytest.approx(exp)
    # integrity fields surfaced from the re-read block (section 5.1)
    assert body["residual_m"] == pytest.approx(gt["ls_residual_m"])
    assert body["cond_warn"] == gt["cond_warn"]


# -- Test 9 -----------------------------------------------------------------

def test_atomic_only_ground_truth_added(config, tmp_path):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    sj = f / "session.json"
    before = json.loads(sj.read_text(encoding="utf-8"))
    block = {"x_m": 0.1, "z_m": 0.2, "r_m": 0.22, "theta_deg": 63.0}

    append_ground_truth.update_session_ground_truth(sj, block)

    after = json.loads(sj.read_text(encoding="utf-8"))
    assert after["ground_truth"] == block
    after.pop("ground_truth")
    assert after == before                                  # nothing else changed
    assert list(f.glob(".session-*")) == []                 # no temp residue


def test_atomic_uses_os_replace(config, tmp_path, monkeypatch):
    f = _processed(config, tmp_path / "sessions", "S0", 0)
    used = {}
    real_replace = append_ground_truth.os.replace
    monkeypatch.setattr(append_ground_truth.os, "replace",
                        lambda a, b: (used.setdefault("yes", True), real_replace(a, b))[1])
    append_ground_truth.update_session_ground_truth(f / "session.json", {"x_m": 0, "z_m": 0})
    assert used.get("yes") is True


def test_atomic_write_failure_preserves_original(config, tmp_path, monkeypatch):
    f = _processed(config, tmp_path / "sessions", "S0", 0)
    sj = f / "session.json"
    original = sj.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise OSError("simulated disk-full")
    monkeypatch.setattr(append_ground_truth.json, "dump", boom)

    with pytest.raises(OSError):
        append_ground_truth.update_session_ground_truth(sj, {"x_m": 0, "z_m": 0})
    assert sj.read_text(encoding="utf-8") == original        # original intact
    assert list(f.glob(".session-*")) == []                  # temp cleaned up


# -- Test 10 ----------------------------------------------------------------

def test_session_input_page_then_post(config, tmp_path):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)

    data = _extract_data(render_session_report(f, config).read_text(encoding="utf-8"))
    assert data["state"] == "input"
    assert data["server"]["health"] == "/api/health"
    assert data["server"]["ground_truth"] == "/api/ground-truth"

    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))
    status, _ = serve_report.handle_ground_truth(
        root, "S0", Lc, sensors, La, Lb, config)
    assert status == 200
    web_block = json.loads((f / "session.json").read_text(encoding="utf-8"))["ground_truth"]
    assert web_block == run_session.solve_ground_truth(Lc, _refs(sensors, La, Lb), config)


def test_pending_lists_only_awaiting(config, tmp_path):
    root = tmp_path / "sessions"
    _processed(config, root, "pending", 0)               # prediction, no GT
    done = _processed(config, root, "done", 1)           # prediction + GT
    d_Lc, d_sensors, d_La, d_Lb = _gt_inputs(config, _pred_xz(done))
    serve_report.handle_ground_truth(root, "done", d_Lc, d_sensors, d_La, d_Lb, config)
    # an unprocessed session (no prediction) must NOT be listed
    s = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                         rng=np.random.default_rng(2), background_distance_m=1.95)
    write_session_dir(root / "unprocessed", s, 20.0)

    ids = [sid for sid, _ in serve_report.pending_sessions(root)]
    assert ids == ["pending"]


# -- Stage 3 (D5): the live web path regenerates ONLY the live campaign -------

def test_live_campaign_post_excludes_demo_subtree(config, tmp_path):
    """(D5) A GT POST regenerates root/campaign.html via render_campaign_report
    over the LIVE root. Because of the Stage-1 is_session_dir predicate, a demo/
    subtree under that same root is excluded automatically (no name matching), so
    the live campaign numbers equal summary_stats over the live sessions only."""
    root = tmp_path / "sessions"
    _processed(config, root, "L0", 0)
    _processed(config, root, "L1", 1)
    _processed(config, root / "demo", "D0", 5)     # populated demo/ subtree

    f0 = root / "L0"
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f0))
    status, _ = serve_report.handle_ground_truth(
        root, "L0", Lc, sensors, La, Lb, config)
    assert status == 200

    cdata = _extract_data((root / "campaign.html").read_text(encoding="utf-8"))
    # the campaign sees the two live sessions only -- the demo/ container is gone
    assert {t["session_id"] for t in cdata["throws"]} == {"L0", "L1"}
    # numbers equal summary_stats over JUST the live dirs (the demo throw excluded)
    throws = analyze_campaign.load_campaign([str(root / "L0"), str(root / "L1")])
    stats = analyze_campaign.summary_stats(throws, None, config["bias"]["alpha"])
    assert cdata["n"] == len(throws) == 2
    assert cdata["raw"]["mean_mm"] == pytest.approx(stats["raw_mean_m"] * 1000.0)


# -- demo_web_reports.py is D5-aware (writes under demo/, sim_ names) ---------

def test_demo_web_reports_writes_under_demo_subtree(config, tmp_path, monkeypatch):
    """(D5) The convenience viewer writes synthetic sessions under <root>/demo/
    with sim_ names + per-throw report.html, and regenerates the DEMO campaign --
    it can no longer pollute the live root/campaign."""
    out = tmp_path / "sessions"
    monkeypatch.setattr(sys, "argv", [
        "demo_web_reports.py", "--n-sessions", "2", "--seed", "20260625",
        "--out-dir", str(out)])
    demo_web_reports.main()

    demo = out / "demo"
    session_dirs = sorted(p for p in demo.iterdir() if p.is_dir())
    assert len(session_dirs) == 2
    for p in session_dirs:
        assert p.name.startswith("sim_")           # sim_ naming, not demo_..._T##
        assert (p / "report.html").is_file()        # per-throw HTML present
    assert (demo / "campaign.html").is_file()
    # the live root holds ONLY the demo container -- nothing leaked out
    assert sorted(p.name for p in out.iterdir()) == ["demo"]


# -- real HTTP smoke (health + one POST) ------------------------------------

def test_http_server_health_and_post(config, tmp_path):
    root = tmp_path / "sessions"
    f = _processed(config, root, "S0", 0)
    httpd = serve_report.ReportServer(("127.0.0.1", 0), config, root, "S0")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        port = httpd.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/health")
        r = conn.getresponse()
        assert r.status == 200
        h = json.loads(r.read())
        assert h["ok"] is True and h["session_id"] == "S0"

        Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))
        conn.request("POST", "/api/ground-truth",
                     body=json.dumps({"session_id": "S0", "L_centroid": Lc,
                                      "sensors": sensors, "L_a": La, "L_b": Lb}),
                     headers={"Content-Type": "application/json"})
        r2 = conn.getresponse()
        assert r2.status == 200
        assert json.loads(r2.read())["persisted"] is True
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)
    assert "ground_truth" in json.loads((f / "session.json").read_text(encoding="utf-8"))
