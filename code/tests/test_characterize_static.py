"""Tests for the static characterization tools (scripts/characterize_static.py and
scripts/analyze_static.py). Mirrors test_acquisition.py: a mocked raw-line stream
and an io.BytesIO log handle, no hardware.

The load-bearing test is test_radius_applied_ball_not_board — it would fail loudly
if the section-7 tape-to-centre convention (R2) were ever reversed.
"""

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.corrections import echo_us_to_m

# scripts/ is not a package; put it on the path to import the tools.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_static  # noqa: E402
import characterize_static  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
HEADER = b"# fw=05,slot_ms=18,timeout_us=12500\r\n"

# Known synthetic sample: S1 clean, S2 with one timeout, S3 all timeouts.
E1 = [5800, 5820, 5790, 5810]
E2 = [7700, 7720, 0, 7710]
E3 = [0, 0, 0, 0]
TEMP_C = 20.0


@pytest.fixture(scope="module")
def radius():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["ball"]["radius_m"]


def _line(sid, echo, t):
    return f"{sid},{echo},{t}".encode("ascii") + b"\r\n"


def _build_stream(e1, e2, e3):
    lines = [HEADER]
    t = 0
    for i in range(len(e1)):
        for sid, e in ((1, e1[i]), (2, e2[i]), (3, e3[i])):
            lines.append(_line(sid, e, t))
            t += 18000
    return lines


def _expected(echoes, reference_m, radius_correction_m=0.0):
    d = echo_us_to_m(np.asarray(echoes, dtype=float), TEMP_C) + radius_correction_m
    finite = d[np.isfinite(d)]
    mean = float(np.mean(finite)) if finite.size else float("nan")
    sigma = float(np.std(finite, ddof=1)) if finite.size >= 2 else float("nan")
    n_to = int(np.count_nonzero(np.asarray(echoes) == 0))
    return mean, sigma, mean - reference_m, n_to / len(echoes)


class TestCharacterizeStats:
    def test_stats_board(self, radius):
        ref = 1.000
        report = characterize_static.characterize_core(
            _build_stream(E1, E2, E3), io.BytesIO(),
            target="board", raw_tape_m=ref, radius_m=radius,
            temperature_c=TEMP_C, n_readings=4)

        assert report["centre_reference_m"] == ref          # board: no radius
        assert report["ball_radius_m"] is None

        for echoes, sid in ((E1, "1"), (E2, "2")):
            mean, sigma, offset, to = _expected(echoes, ref)
            s = report["sensors"][sid]
            assert s["mean_m"] == pytest.approx(mean)
            assert s["sigma_m"] == pytest.approx(sigma)
            assert s["offset_m"] == pytest.approx(offset)
            assert s["timeout_fraction"] == pytest.approx(to)
            assert s["n"] == len(echoes)

        s3 = report["sensors"]["3"]                          # all timeouts
        assert s3["timeout_fraction"] == 1.0
        assert not np.isfinite(s3["mean_m"])
        assert not np.isfinite(s3["offset_m"])
        assert s3["n_timeout"] == len(E3)

    def test_radius_applied_ball_not_board(self, radius):
        tape = 0.967
        board = characterize_static.characterize_core(
            _build_stream(E1, E2, E3), io.BytesIO(), target="board",
            raw_tape_m=tape, radius_m=radius, temperature_c=TEMP_C, n_readings=4)
        ball = characterize_static.characterize_core(
            _build_stream(E1, E2, E3), io.BytesIO(), target="ball",
            raw_tape_m=tape, radius_m=radius, temperature_c=TEMP_C, n_readings=4)

        # The convention: ball reference is one radius further than the tape.
        assert board["centre_reference_m"] == pytest.approx(tape)
        assert ball["centre_reference_m"] == pytest.approx(tape + radius)
        assert ball["ball_radius_m"] == pytest.approx(radius)

        # ...and the ball mean/offset are reported at the CENTRE (R2): the mean is
        # one radius further than the board (surface) mean, and the offset — the
        # electronic bias — MATCHES the board because the radius cancels
        # (centre_mean - centre_ref == surface_mean - tape).
        for sid in ("1", "2"):
            assert ball["sensors"][sid]["mean_m"] == pytest.approx(
                board["sensors"][sid]["mean_m"] + radius)
            assert ball["sensors"][sid]["offset_m"] == pytest.approx(
                board["sensors"][sid]["offset_m"])

    def test_convention_helper(self, radius):
        assert characterize_static.centre_reference_m("board", 1.0, radius) == 1.0
        assert characterize_static.centre_reference_m("ball", 1.0, radius) == \
            pytest.approx(1.0 + radius)

    def test_ball_radius_override_flag(self, monkeypatch):
        # A pending-approval target (e.g. a football) is characterized via the CLI
        # override, NOT by editing config.ball.radius_m (which breaks the gate).
        monkeypatch.setattr(sys, "argv", [
            "characterize_static.py", "--target", "ball", "--reference-m", "1.0",
            "--ball-radius-m", "0.11"])
        assert characterize_static.parse_args().ball_radius_m == pytest.approx(0.11)
        # absent flag -> None, so main() falls back to the config value
        monkeypatch.setattr(sys, "argv", [
            "characterize_static.py", "--target", "board", "--reference-m", "1.0"])
        assert characterize_static.parse_args().ball_radius_m is None

    def test_overridden_radius_lifts_ball_mean_to_centre(self, radius):
        # characterize_core with an explicit (overridden) radius reports the ball
        # centre reference and centre-lifted mean at that radius, not the config one.
        r_override = 0.11
        assert r_override != radius                       # genuinely different
        report = characterize_static.characterize_core(
            _build_stream(E1, E2, E3), io.BytesIO(), target="ball",
            raw_tape_m=1.0, radius_m=r_override, temperature_c=TEMP_C, n_readings=4)
        assert report["centre_reference_m"] == pytest.approx(1.0 + r_override)
        mean, _, offset, _ = _expected(E1, 1.0 + r_override, r_override)
        assert report["sensors"]["1"]["mean_m"] == pytest.approx(mean)
        assert report["sensors"]["1"]["offset_m"] == pytest.approx(offset)


class TestBeamHalfAngle:
    def test_crossing_interpolated(self):
        pts = [(4.0, 0.1), (6.0, 0.4), (8.0, 0.7)]
        # 0.5 lies between (6, 0.4) and (8, 0.7): 6 + 0.1/0.3 * 2 = 6.667
        assert analyze_static.beam_half_angle(pts) == pytest.approx(6.667, abs=1e-3)

    def test_not_bracketed_returns_none(self):
        assert analyze_static.beam_half_angle([(4.0, 0.1), (6.0, 0.2)]) is None

    def test_unsorted_input_and_early_saturation(self):
        # input out of order; smallest angle already past 0.5 -> that angle (bound)
        assert analyze_static.beam_half_angle([(8.0, 0.9), (4.0, 0.6)]) == 4.0
