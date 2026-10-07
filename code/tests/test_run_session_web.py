"""Stage 4 headless tests for run_session.py --web (website.md section 6.4, 11).

The browser ground-truth loop is driven through run_session.web_finalize with an
injected wait_for_entry seam (no real browser / no real stdin). The reused
serve_report server is exercised over real HTTP. Covers the POST path, the
non-destructive skip + late completion (equality with the live block), and the
Ctrl-C teardown guarantee.
"""

import http.client
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.geometry import recommend_reference_sensors
from pipeline.process_throw import process_session
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_session  # noqa: E402
import serve_report  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _processed(config, root, name, seed):
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
    """(v2.3 G1) (L_centroid, sensors, L_a, L_b) for the recommended pair."""
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


def _post_tapes(url_or_httpd, session_id, Lc, sensors, L_a, L_b):
    port = url_or_httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/api/ground-truth",
                 body=json.dumps({"session_id": session_id, "L_centroid": Lc,
                                  "sensors": sensors, "L_a": L_a, "L_b": L_b}),
                 headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    status = r.status
    r.read()
    conn.close()
    return status


# -- POST path: --web entry freezes the report + updates the campaign ---------

def test_web_post_freezes_and_updates_campaign(config, tmp_path):
    out = tmp_path / "sessions"
    f = _processed(config, out, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))

    def waiter(httpd, url):
        assert _post_tapes(httpd, "S0", Lc, sensors, La, Lb) == 200

    run_session.web_finalize(f, config, out, open_browser=False,
                             wait_for_entry=waiter)

    meta = json.loads((f / "session.json").read_text(encoding="utf-8"))
    assert "ground_truth" in meta
    assert _extract_data((f / "report.html").read_text(encoding="utf-8"))["state"] == "frozen"
    cdata = _extract_data((out / "campaign.html").read_text(encoding="utf-8"))
    assert cdata["n"] >= 1


# -- Skip is non-destructive; late completion equals the live block ----------

def test_web_skip_then_late_complete_equal(config, tmp_path):
    out = tmp_path / "sessions"
    f = _processed(config, out, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))
    expected = run_session.solve_ground_truth(Lc, _refs(sensors, La, Lb), config)

    run_session.web_finalize(f, config, out, open_browser=False,
                             wait_for_entry=lambda httpd, url: None)   # skip

    meta = json.loads((f / "session.json").read_text(encoding="utf-8"))
    assert "ground_truth" not in meta                     # skip wrote nothing
    assert meta["prediction"]["raw"]["x_m"] is not None    # session still valid

    # complete later via the EXISTING Stage-3 path
    status, _ = serve_report.handle_ground_truth(
        out, "S0", Lc, sensors, La, Lb, config)
    assert status == 200
    late = json.loads((f / "session.json").read_text(encoding="utf-8"))["ground_truth"]
    assert late == expected                                # identical to live entry
    assert _extract_data((f / "report.html").read_text(encoding="utf-8"))["state"] == "frozen"


# -- Ctrl-C mid-flow leaves a clean, valid (incomplete) session --------------

def test_web_ctrl_c_leaves_clean_session(config, tmp_path):
    out = tmp_path / "sessions"
    f = _processed(config, out, "S0", 0)

    def boom(httpd, url):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_session.web_finalize(f, config, out, open_browser=False,
                                 wait_for_entry=boom)

    meta = json.loads((f / "session.json").read_text(encoding="utf-8"))   # parseable
    assert meta["prediction"]["raw"]["x_m"] is not None    # fully processed
    assert "ground_truth" not in meta                      # awaiting GT
    assert list(f.glob(".session-*")) == []                # no atomic-write residue


# -- the gt_event signal the console waiter relies on ------------------------

def test_start_background_post_sets_gt_event(config, tmp_path):
    out = tmp_path / "sessions"
    f = _processed(config, out, "S0", 0)
    Lc, sensors, La, Lb = _gt_inputs(config, _pred_xz(f))
    httpd, thread, url = serve_report.start_background(out, config, "S0")
    try:
        assert not httpd.gt_event.is_set()
        assert _post_tapes(httpd, "S0", Lc, sensors, La, Lb) == 200
        assert httpd.gt_event.wait(timeout=2)
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
