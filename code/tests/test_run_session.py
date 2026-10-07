"""Tests for the terminal-defaults path of the one-throw program
(scripts/run_session.py).

capture_session's live==offline equality is covered in test_acquisition.py; this
module holds the terminal-path guards and rendering behaviour added by the audit
remediation (raw-data overwrite guard, atomic ground-truth write, terminal-mode
report/campaign rendering, failure-path robustness).
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from pipeline.process_throw import process_session
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

# scripts/ is not a package; put it on the path to import the one-throw program.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_session  # noqa: E402
import append_ground_truth  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _processed(config, root, name, seed):
    """A real processed session under root/name (prediction + trajectory.csv),
    mirroring test_serve_report._processed."""
    root.mkdir(parents=True, exist_ok=True)
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(seed),
                               background_distance_m=1.95)
    folder = write_session_dir(root / name, session, 20.0)
    process_session(folder, config)
    return folder


def _to_byte_lines(raw_bytes: bytes) -> list:
    """Split a serial byte stream into raw byte-lines (mirrors test_acquisition)."""
    return raw_bytes.splitlines(keepends=True)


class _StubSerial:
    def close(self):
        pass


def test_capture_session_refuses_to_overwrite_raw_log(config, tmp_path):
    """capture_session must REFUSE (not silently clobber) a directory that already
    holds a raw_serial.log -- raw data is sacred (section 0.4)."""
    session_dir = tmp_path / "2026-07-02_T01"
    session_dir.mkdir(parents=True)
    original = b"# fw=05,slot_ms=18,timeout_us=12500\r\n1,5000,1000\r\n"
    (session_dir / "raw_serial.log").write_bytes(original)

    # byte_lines is never consumed: the guard raises before the capture starts.
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        run_session.capture_session(session_dir, config, [], 20.0)

    # The pre-existing raw log is untouched (refused, not overwritten).
    assert (session_dir / "raw_serial.log").read_bytes() == original


# ---------------------------------------------------------------------------
# M-1: terminal ground-truth write goes through the atomic writer
# ---------------------------------------------------------------------------

_GT_BLOCK = {"x_m": 0.12, "z_m": 0.34, "r_m": 0.361, "theta_deg": 70.6,
             "sigma_x_m": 0.004, "sigma_z_m": 0.004, "sensors_used": ["S1", "S2"]}


def test_terminal_gt_write_atomic_no_residue(config, tmp_path, monkeypatch):
    """run_default must persist ground truth via the atomic writer (temp +
    os.replace), leaving no .session-* residue -- not the plain _write_json --
    and (M-3) render the per-throw report + the campaign page."""
    root = tmp_path / "sessions"
    folder = _processed(config, root, "2026-07-02_T01", 0)

    # result must be non-None (None is the M-4 "no prediction" signal that would
    # route run_default to the failure path); its value is unused because
    # prompt_ground_truth is monkeypatched.
    monkeypatch.setattr(run_session, "_capture_default",
                        lambda config, args: (folder, object()))
    monkeypatch.setattr(run_session, "prompt_ground_truth",
                        lambda config, result: dict(_GT_BLOCK))

    run_session.run_default(config, SimpleNamespace(plot=False, out_dir=root))

    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert meta["ground_truth"] == _GT_BLOCK
    assert list(folder.glob(".session-*")) == []             # no temp residue
    assert (folder / "report.html").is_file()                # (M-3) per-throw page
    assert (root / "campaign.html").is_file()                # (M-3) campaign page


def test_terminal_gt_write_failure_preserves_original(config, tmp_path, monkeypatch):
    """An injected write failure during the terminal GT write leaves the original
    session.json byte-for-byte intact and no temp residue (atomic guarantee)."""
    folder = _processed(config, tmp_path / "sessions", "2026-07-02_T02", 0)
    sj = folder / "session.json"
    original = sj.read_text(encoding="utf-8")

    monkeypatch.setattr(run_session, "_capture_default",
                        lambda config, args: (folder, object()))  # non-None: not the failure path
    monkeypatch.setattr(run_session, "prompt_ground_truth",
                        lambda config, result: dict(_GT_BLOCK))

    def boom(*a, **k):
        raise OSError("simulated disk-full")
    monkeypatch.setattr(append_ground_truth.json, "dump", boom)

    with pytest.raises(OSError):
        run_session.run_default(config, SimpleNamespace(plot=False))

    assert sj.read_text(encoding="utf-8") == original        # original intact
    assert "ground_truth" not in json.loads(original)        # sanity: was absent
    assert list(folder.glob(".session-*")) == []             # temp cleaned up


# ---------------------------------------------------------------------------
# M-3: terminal-mode ground-truth entry (append) renders report + campaign
# ---------------------------------------------------------------------------

def test_terminal_append_renders_report_and_campaign(config, tmp_path, monkeypatch):
    """append_ground_truth.append_to_session must write the GT AND refresh the
    per-throw report.html (frozen) + the subtree campaign.html (M-3)."""
    root = tmp_path / "sessions"
    folder = _processed(config, root, "2026-07-02_T03", 0)

    monkeypatch.setattr(run_session, "prompt_ground_truth",
                        lambda config, result: dict(_GT_BLOCK))

    gt = append_ground_truth.append_to_session(config, folder / "session.json")

    assert gt == _GT_BLOCK
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert meta["ground_truth"] == _GT_BLOCK
    assert (folder / "report.html").is_file()                # frozen per-throw page
    assert (root / "campaign.html").is_file()                # subtree campaign page


# ---------------------------------------------------------------------------
# M-4: live failure path -- clean message, gating evidence preserved, failure
#      report renders the range-vs-time panel
# ---------------------------------------------------------------------------

def test_run_default_failure_path_preserves_evidence_and_renders(
        config, tmp_path, monkeypatch, capsys):
    """A throw that segments but fails the fit must NOT crash run_default: it
    prints a clean message, leaves triplets_raw.csv + the gate summary on disk
    (Part 2), and the rendered failure report carries the range-vs-time panel."""
    root = tmp_path / "sessions"
    root.mkdir()
    # Detectable throw, but demand an impossible fit-point count so the fit stage
    # (not segmentation) fails -- the substantive M-4 case.
    cfg = {**config, "landing": {**config["landing"], "min_fit_points": 999}}
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(0),
                               background_distance_m=1.95)
    byte_lines = _to_byte_lines(session.serial_bytes())

    monkeypatch.setattr("builtins.input", lambda *a, **k: "20")
    monkeypatch.setattr(run_session.acquisition, "open_serial",
                        lambda *a, **k: _StubSerial())
    monkeypatch.setattr(run_session.acquisition, "serial_byte_lines",
                        lambda ser: byte_lines)

    args = SimpleNamespace(no_correction=True, no_offset_correction=False,
                           no_background=False, port=None, out_dir=root, plot=False)
    run_session.run_default(cfg, args)                       # (a) must not raise

    assert "no prediction" in capsys.readouterr().out        # (b) clean message

    sessions = [p for p in root.iterdir() if p.is_dir()]
    assert len(sessions) == 1
    folder = sessions[0]
    assert (folder / "triplets_raw.csv").is_file()           # (c) evidence kept
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert "gate_summary" in meta and "prediction" not in meta

    # (d) rendered failure report has a populated range-vs-time panel
    from pipeline.web_report import build_session_data
    data = build_session_data(folder, cfg)
    assert data["state"] == "failure"
    assert data["range_vs_time"] is not None
    assert data["range_vs_time"]["sensors"]
    assert (folder / "report.html").is_file()
