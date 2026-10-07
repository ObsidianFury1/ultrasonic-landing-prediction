"""Tests for pipeline.process_throw: parsing helpers (section 5.1, R10c) and
the offline orchestrator round-trip on a simulator-written session directory."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.process_throw import (
    MICROS_ROLLOVER,
    assemble_triplets,
    parse_serial_lines,
    process_session,
    unwrap_micros,
)
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

class TestUnwrapMicros:
    def test_rollover_unwrapped_monotonic(self):
        """R10c: micros() wraps at 2^32; the unwrap must restore monotonicity."""
        t = [MICROS_ROLLOVER - 30000, MICROS_ROLLOVER - 12000, 6000, 24000]
        out = unwrap_micros(t)
        assert np.all(np.diff(out) > 0)
        assert out[2] == MICROS_ROLLOVER + 6000
        assert out[3] == MICROS_ROLLOVER + 24000

    def test_double_rollover(self):
        t = [MICROS_ROLLOVER - 10, 5, MICROS_ROLLOVER - 3, 7]
        out = unwrap_micros(t)
        assert np.all(np.diff(out) > 0)
        assert out[3] == 2 * MICROS_ROLLOVER + 7

    def test_no_rollover_untouched(self):
        t = [100, 200, 300]
        assert unwrap_micros(t).tolist() == t


class TestParsing:
    def test_header_and_rows(self):
        lines = ["# fw=05,slot_ms=18,timeout_us=12500",
                 "1,5000,0", "2,5100,18000", "3,5200,36000"]
        header, rows, malformed = parse_serial_lines(lines)
        assert "fw=05" in header
        assert rows == [(1, 5000, 0), (2, 5100, 18000), (3, 5200, 36000)]
        assert malformed == 0

    def test_malformed_lines_counted_not_fatal(self):
        lines = ["# fw=05,slot_ms=18,timeout_us=12500",
                 "1,5000,0", "garbage", "9,1,2", "2,xx,3", "2,5100,18000",
                 "3,5200,36000", "1,2,3,4"]
        header, rows, malformed = parse_serial_lines(lines)
        assert len(rows) == 3
        assert malformed == 4

    def test_assembler_resyncs_on_order_violation(self):
        rows = [(1, 10, 0), (2, 11, 18000), (3, 12, 36000),
                (1, 20, 54000), (3, 22, 90000),          # missing S2 -> resync
                (1, 30, 108000), (2, 31, 126000), (3, 32, 144000)]
        echo, t_trig, dropped = assemble_triplets(rows)
        assert echo.shape == (2, 3)
        assert echo[0].tolist() == [10, 11, 12]
        assert echo[1].tolist() == [30, 31, 32]
        assert dropped == 2                              # stray S1 and S3


# ---------------------------------------------------------------------------
# Orchestrator round-trip on a written session directory
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_dir(config, tmp_path_factory):
    # Static reflector at 1.95 m: near the d_max edge, so the band rule is
    # genuinely active but the ball crosses it fast. A reflector mid-corridor
    # (e.g. 1.55 m) gates >= close_K consecutive flight triplets and CLOSES
    # THE THROW MID-FLIGHT — the section 5.3 "room must change" scenario,
    # which the sanity warning flags (asserted below).
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(0),
                               background_distance_m=1.95)
    return write_session_dir(tmp_path_factory.mktemp("proc") / "S00",
                             session, 20.0), session


class TestProcessSession:
    def test_round_trip_outputs_and_accuracy(self, config, session_dir):
        folder, session = session_dir
        result = process_session(folder, config)
        for name in ("background.json", "triplets_raw.csv", "trajectory.csv"):
            assert (folder / name).is_file()
        meta = json.loads((folder / "session.json").read_text())
        raw = meta["prediction"]["raw"]
        truth = session.truth["landing"]
        err = np.hypot(raw["x_m"] - truth["x_m"], raw["z_m"] - truth["z_m"])
        assert err < 0.08
        assert result.gate_summary["n_triplets_used"] >= 4
        assert result.gate_summary["malformed_lines"] == 0
        assert "degree(s) of freedom" in result.caveat
        # Static 1.55 m background: bands enabled on all sensors, and the
        # section 5.3 overlap warning fires (band inside the ball range).
        assert all(result.gate_summary["background_enabled"])
        assert any("eat real ball readings" in w for w in result.warnings)

    def test_arming_triplets_in_throw_buffer(self, config, session_dir):
        """R5 at the orchestrator level: in_throw covers the arming triplets."""
        folder, _ = session_dir
        rows = (folder / "triplets_raw.csv").read_text().splitlines()[1:]
        cells = [r.split(",") for r in rows[::3]]          # one row per triplet
        t_valid = np.array([int(c[7]) for c in cells], dtype=bool)
        in_throw = np.array([int(c[8]) for c in cells], dtype=bool)
        first_valid = int(np.flatnonzero(t_valid)[0])
        assert in_throw[first_valid]                       # arming included
        arm_m = config["gates"]["arm_M"]
        assert in_throw[first_valid:first_valid + arm_m].all()

    def test_header_mismatch_warned(self, config, session_dir, tmp_path):
        folder, session = session_dir
        clone = tmp_path / "S_badfw"
        clone.mkdir()
        raw = (folder / "raw_serial.log").read_bytes()
        bad = raw.replace(b"timeout_us=12500", b"timeout_us=15000", 1)
        (clone / "raw_serial.log").write_bytes(bad)
        (clone / "session.json").write_text(
            (folder / "session.json").read_text().replace(folder.name, clone.name),
            encoding="utf-8")
        result = process_session(clone, config)
        assert any("fw header mismatch" in w for w in result.warnings)

    def test_background_only_session_raises_no_throw(self, config, tmp_path):
        quiet = generate_session(
            config, THROW, temperature_c=20.0, noise_mm=8.0,
            rng=np.random.default_rng(1), background_distance_m=1.55,
            n_bg_pre=config["gates"]["bg_n_triplets"] + 5, n_bg_post=5)
        # Cut the log off before the throw begins: background only.
        folder = write_session_dir(tmp_path / "S_quiet", quiet, 20.0)
        lines = (folder / "raw_serial.log").read_bytes().splitlines()
        n_keep = 1 + 3 * config["gates"]["bg_n_triplets"]
        (folder / "raw_serial.log").write_bytes(b"\r\n".join(lines[:n_keep]) + b"\r\n")
        with pytest.raises(ValueError, match="no throw"):
            process_session(folder, config)

    def test_unknown_negative_control_rejected(self, config, session_dir):
        folder, _ = session_dir
        with pytest.raises(ValueError, match="negative control"):
            process_session(folder, config, _negative_control="bogus")

    def test_offset_correction_toggle(self, config, session_dir, tmp_path):
        """(Phase 5, S4D) apply_offset subtracts config sensor_offset_m from the
        trilateration-path ranges. Default False leaves synthetic data untouched
        and records nothing; True shifts the reconstructed landing and is logged.
        Same session processed both ways proves the toggle bites and is inert by
        default (guarding the acceptance gate, which never sets apply_offset)."""
        _, session = session_dir
        cfg = copy.deepcopy(config)
        cfg["acquisition"]["sensor_offset_m"] = [-0.03, -0.03, -0.03]

        off_folder = write_session_dir(tmp_path / "S_off", session, 20.0)
        on_folder = write_session_dir(tmp_path / "S_on", session, 20.0)
        r_off = process_session(off_folder, cfg, apply_offset=False)
        r_on = process_session(on_folder, cfg, apply_offset=True)

        assert r_off.gate_summary["sensor_offset_applied"] is False
        assert r_off.gate_summary["sensor_offset_m"] is None
        assert r_on.gate_summary["sensor_offset_applied"] is True
        assert r_on.gate_summary["sensor_offset_m"] == [-0.03, -0.03, -0.03]

        off = json.loads((off_folder / "session.json").read_text())["prediction"]["raw"]
        on = json.loads((on_folder / "session.json").read_text())["prediction"]["raw"]
        assert (off["x_m"], off["z_m"]) != (on["x_m"], on["z_m"])

    def test_offset_default_off_when_config_absent(self, config, session_dir, tmp_path):
        """apply_offset=True is a no-op (and records nothing) when the config has
        no sensor_offset_m key — the correction is opt-in on BOTH the flag and the
        presence of measured offsets."""
        _, session = session_dir
        cfg = copy.deepcopy(config)
        cfg["acquisition"].pop("sensor_offset_m", None)
        folder = write_session_dir(tmp_path / "S_noffs", session, 20.0)
        r = process_session(folder, cfg, apply_offset=True)
        assert r.gate_summary["sensor_offset_applied"] is False
        assert r.gate_summary["sensor_offset_m"] is None

    def test_reprocess_failure_clears_stale_prediction(self, config, tmp_path):
        """(N-1) Re-processing a previously-successful session under a config
        that now fails the fit must leave a CONSISTENT failure state: no stale
        prediction/caveat in session.json, no stale trajectory.csv -- otherwise
        the failed session renders as a valid page with stale data. Own session
        dir (tmp_path): this test mutates it, so the shared fixture is not used."""
        session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                                   rng=np.random.default_rng(0),
                                   background_distance_m=1.95)
        folder = write_session_dir(tmp_path / "S_re", session, 20.0)

        # First pass succeeds: prediction + trajectory.csv on disk.
        process_session(folder, config)
        meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        assert meta["prediction"]["raw"]["x_m"] is not None
        assert (folder / "trajectory.csv").is_file()

        # Second pass with an impossible fit-point demand fails at the fit stage.
        bad = {**config, "landing": {**config["landing"], "min_fit_points": 999}}
        with pytest.raises(ValueError):
            process_session(folder, bad)

        # Consistent failure state: new gate summary, NO stale derived state.
        meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        assert "gate_summary" in meta
        assert "prediction" not in meta
        assert "small_sample_caveat" not in meta
        assert not (folder / "trajectory.csv").exists()
        assert (folder / "triplets_raw.csv").is_file()      # evidence retained
        from pipeline.web_report import build_session_data
        assert build_session_data(folder, config)["state"] == "failure"
