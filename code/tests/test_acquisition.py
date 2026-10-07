"""Tests for the live acquisition layer (pipeline/acquisition.py) and the
one-throw program core (scripts/run_session.capture_session).

The headline test is live==offline: a mocked serial stream pushed through
capture_session must yield the SAME prediction that process_throw.process_session
produces directly on the captured log — proving the live path reuses the offline
chain instead of duplicating it.
"""

import io
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.acquisition import Triplet, stream_triplets
from pipeline.process_throw import MICROS_ROLLOVER, process_session, unwrap_micros
from pipeline.simulator import ThrowParams, generate_session

# scripts/ is not a package; put it on the path to import the one-throw program.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_session  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(sid, echo, t):
    return f"{sid},{echo},{t}".encode("ascii") + b"\r\n"


HEADER = b"# fw=05,slot_ms=18,timeout_us=12500\r\n"


def _collect(byte_lines, **kw):
    warns = []
    sink = io.BytesIO()
    triplets = list(stream_triplets(byte_lines, sink,
                                    warn=lambda m: warns.append(m), **kw))
    return triplets, warns, sink


# ---------------------------------------------------------------------------
# 1. Assembly, t_sample, and resync after a corrupted line
# ---------------------------------------------------------------------------

class TestStreamTriplets:
    def test_assembly_t_sample_and_resync(self):
        byte_lines = [
            HEADER,
            _line(1, 5000, 0), _line(2, 5100, 18000), _line(3, 5200, 36000),  # T0
            _line(1, 6000, 54000), _line(3, 6200, 90000),   # missing S2 -> resync
            _line(1, 7000, 108000), _line(2, 7100, 126000), _line(3, 7200, 144000),  # T1
            _line(1, 0, 162000), _line(2, 0, 180000), _line(3, 8200, 198000),  # T2 timeouts
        ]
        triplets, warns, _ = _collect(byte_lines,
                                      expected_header="slot_ms=18,timeout_us=12500")

        assert [t.index for t in triplets] == [0, 1, 2]
        assert triplets[0].echo_us.tolist() == [5000, 5100, 5200]
        assert triplets[0].t_trig_us.tolist() == [0, 18000, 36000]
        # t_sample = t_trig + echo/2 for every reading (R3)
        for t in triplets:
            assert np.allclose(t.t_sample_us, t.t_trig_us + t.echo_us / 2.0)
        # resync skipped the stray S1 + S3; T1 still assembles correctly
        assert triplets[1].echo_us.tolist() == [7000, 7100, 7200]
        assert any("order violation" in w for w in warns)
        # timeouts (echo 0): t_sample collapses to t_trig
        t2 = triplets[2]
        assert t2.echo_us.tolist() == [0, 0, 8200]
        assert t2.t_sample_us[0] == t2.t_trig_us[0] == 162000
        assert t2.t_sample_us[2] == 198000 + 8200 / 2.0

    def test_header_mismatch_warns_not_fatal(self):
        byte_lines = [b"# fw=99,slot_ms=7,timeout_us=999\r\n",
                      _line(1, 100, 0), _line(2, 110, 18000), _line(3, 120, 36000)]
        triplets, warns, _ = _collect(byte_lines,
                                      expected_header="slot_ms=18,timeout_us=12500")
        assert len(triplets) == 1                       # parsing still proceeds
        assert any("header mismatch" in w for w in warns)

    def test_auto_reset_garbage_discarded_before_header(self):
        byte_lines = [b"\x00\xff garbage\r\n", b"Rebooting...\r\n", HEADER,
                      _line(1, 100, 0), _line(2, 110, 18000), _line(3, 120, 36000)]
        triplets, warns, _ = _collect(byte_lines)
        assert len(triplets) == 1
        assert warns == []                              # clean: garbage then header


# ---------------------------------------------------------------------------
# 2. micros() rollover unwrap (R10c) — oracle is the reused unwrap_micros
# ---------------------------------------------------------------------------

class TestRolloverUnwrap:
    def test_yielded_t_trig_matches_unwrap_micros(self):
        # Raw (wrapped) S1/S2/S3 timestamps with a first rollover between T0 and
        # T1 and a second (double rollover) between T2 and T3. The fixture mirrors
        # test_process_throw's rollover values (6000, 24000 post-wrap); the oracle
        # is the reused unwrap_micros, not hand-computed expectations.
        raw_t = [4294900000, 4294918000, 4294936000,   # T0 (pre-wrap)
                 6000, 24000, 42000,                    # T1 (wrap #1)
                 100000, 118000, 136000,                # T2
                 50, 18050, 36050]                      # T3 (wrap #2 = double)
        byte_lines = [HEADER]
        for k in range(0, len(raw_t), 3):
            for j in range(3):
                byte_lines.append(_line(j + 1, 5000, raw_t[k + j]))

        triplets, _, _ = _collect(byte_lines)
        assert len(triplets) == 4
        flat = np.concatenate([t.t_trig_us for t in triplets])
        assert np.array_equal(flat, unwrap_micros(raw_t))     # reuse is consistent
        assert np.all(np.diff(flat) > 0)                      # strictly monotonic
        assert triplets[1].t_trig_us[0] == MICROS_ROLLOVER + 6000
        assert triplets[3].t_trig_us[0] == 2 * MICROS_ROLLOVER + 50


# ---------------------------------------------------------------------------
# 3. Live == offline: capture_session reuses process_session, no divergence
# ---------------------------------------------------------------------------

def _to_byte_lines(raw_bytes: bytes) -> list:
    return [ln + b"\r\n" for ln in raw_bytes.split(b"\r\n") if ln]


class TestLiveEqualsOffline:
    def test_capture_session_matches_direct_process_session(self, config, tmp_path):
        session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                                   rng=np.random.default_rng(0))
        byte_lines = _to_byte_lines(session.serial_bytes())

        # live path: mocked stream -> capture_session -> process_session inside
        dir_a = tmp_path / "live"
        res_a = run_session.capture_session(dir_a, config, byte_lines, 20.0)

        # offline twin: same captured raw_serial.log, process_session directly.
        # capture_session applies the per-sensor offset by DEFAULT (Phase 5, S4D),
        # so the offline twin must match it (apply_offset=True) for a like-for-like
        # parity check — the point of this test is "live == offline, same settings".
        dir_b = tmp_path / "offline"
        dir_b.mkdir()
        shutil.copy(dir_a / "raw_serial.log", dir_b / "raw_serial.log")
        (dir_b / "session.json").write_text(
            json.dumps({"session_id": "offline", "temperature_c": 20.0}),
            encoding="utf-8")
        res_b = process_session(dir_b, config, apply_offset=True)

        meta_a = json.loads((dir_a / "session.json").read_text(encoding="utf-8"))
        meta_b = json.loads((dir_b / "session.json").read_text(encoding="utf-8"))
        raw_a, raw_b = meta_a["prediction"]["raw"], meta_b["prediction"]["raw"]
        for k in ("x_m", "z_m", "r_m", "theta_deg", "sigma_r_m", "sigma_theta_deg",
                  "heading_deg", "v_h_m_s"):
            assert raw_a[k] == pytest.approx(raw_b[k], abs=1e-9, rel=1e-9), k
        assert np.allclose(raw_a["cov_xz_m2"], raw_b["cov_xz_m2"], atol=1e-12)
        assert raw_a["n_points"] == raw_b["n_points"]
        assert raw_a["dof"] == raw_b["dof"]
        # gate summaries (counts, segmentation indices, header) identical too
        assert meta_a["gate_summary"] == meta_b["gate_summary"]
        # the returned objects agree with what was written
        assert res_a.prediction["raw"]["r_m"] == pytest.approx(
            res_b.prediction["raw"]["r_m"], abs=1e-9)

    def test_capture_session_writes_expected_artifacts(self, config, tmp_path):
        session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                                   rng=np.random.default_rng(1))
        byte_lines = _to_byte_lines(session.serial_bytes())
        sdir = tmp_path / "S"
        res = run_session.capture_session(sdir, config, byte_lines, 20.0)
        for name in ("raw_serial.log", "background.json", "triplets_raw.csv",
                     "trajectory.csv", "session.json"):
            assert (sdir / name).is_file()
        # one throw segmented and a usable landing produced
        assert res.gate_summary["n_triplets_used"] >= config["landing"]["min_fit_points"]
        truth = session.truth["landing"]
        raw = res.prediction["raw"]
        assert np.hypot(raw["x_m"] - truth["x_m"], raw["z_m"] - truth["z_m"]) < 0.10

    def test_capture_session_skip_background(self, config, tmp_path):
        """--no-background: no calibration, all bands disabled, throw still found.

        The open-air padding (timeouts) does not arm, so the throw segments the
        same and a usable landing is produced -- but the persisted background has
        every band disabled, matching the R1 open-air state."""
        session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                                   rng=np.random.default_rng(1))
        byte_lines = _to_byte_lines(session.serial_bytes())
        sdir = tmp_path / "S_nobg"
        res = run_session.capture_session(sdir, config, byte_lines, 20.0,
                                          skip_background=True)
        bg = json.loads((sdir / "background.json").read_text(encoding="utf-8"))
        assert all(not s["enabled"] for s in bg["sensors"])    # all bands disabled
        assert res.gate_summary["n_triplets_used"] >= config["landing"]["min_fit_points"]
        truth = session.truth["landing"]
        raw = res.prediction["raw"]
        assert np.hypot(raw["x_m"] - truth["x_m"], raw["z_m"] - truth["z_m"]) < 0.10
