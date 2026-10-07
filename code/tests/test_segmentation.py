"""Tests for pipeline.segmentation (CLAUDE.md section 5.5, R5).

Config defaults: arm_M = 2, close_K = 3 (read from config.yaml so the tests
track the real thresholds).
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.segmentation import ThrowDetector, segment_throw

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def gates():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["gates"]


def flags(pattern: str) -> list:
    """'..VVVV..' -> [False, False, True, True, True, True, False, False]"""
    return [c == "V" for c in pattern]


class TestOneThrowIsolation:
    def test_throw_surrounded_by_background(self, gates):
        seg = segment_throw(flags("....VVVVVV...."), gates["arm_M"], gates["close_K"])
        assert seg is not None
        assert seg.start == 4 and seg.end == 9
        assert seg.in_throw.sum() == 6

    def test_no_throw_returns_none(self, gates):
        assert segment_throw(flags("..........."), gates["arm_M"],
                             gates["close_K"]) is None

    def test_single_valid_triplet_never_arms(self, gates):
        # arm_M = 2: isolated valid triplets (noise blips) must not open a throw.
        assert segment_throw(flags("...V...V...V..."), gates["arm_M"],
                             gates["close_K"]) is None

    def test_second_throw_ignored(self, gates):
        # One session = one throw (section 0.3): only the first is returned.
        seg = segment_throw(flags("..VVVV.....VVVV.."), gates["arm_M"],
                            gates["close_K"])
        assert seg.start == 2 and seg.end == 5
        assert not seg.in_throw[11:].any()


class TestHysteresis:
    def test_short_invalid_runs_do_not_close(self, gates):
        # close_K = 3: runs of 1-2 invalid triplets inside the throw are
        # dropouts/rejections, not the end of the throw.
        seg = segment_throw(flags("..VVV.VV..VVV..."), gates["arm_M"],
                            gates["close_K"])
        assert seg.start == 2 and seg.end == 12
        # The mid-throw invalid triplets are INSIDE the buffer, flagged by
        # their validity (never deleted) — in_throw covers them.
        assert seg.in_throw[5] and seg.in_throw[8:10].all()

    def test_exactly_close_K_invalid_closes(self, gates):
        seg = segment_throw(flags("..VVVV...VV..."), gates["arm_M"],
                            gates["close_K"])
        assert seg.end == 5                     # closed by the 3-run; VV after
        assert not seg.in_throw[9:11].any()     # ... is a second throw, ignored

    def test_trailing_K_stripped(self, gates):
        seg = segment_throw(flags("..VVVVV..."), gates["arm_M"], gates["close_K"])
        assert seg.end == 6                     # the closing run is not in-throw
        assert seg.in_throw[7:].sum() == 0


class TestArmingTripletsR5:
    def test_arming_triplets_in_buffer(self, gates):
        """R5: the arm_M arming triplets are retroactively part of the throw."""
        valid = flags("....VVVVVV....")
        seg = segment_throw(valid, gates["arm_M"], gates["close_K"])
        first_valid = valid.index(True)
        assert seg.start == first_valid          # not first_valid + arm_M
        assert seg.in_throw[first_valid:first_valid + gates["arm_M"]].all()

    def test_arming_after_false_start(self, gates):
        # A single valid triplet, a gap, then the real throw: arming counts
        # restart, and the throw starts at ITS first arming triplet.
        seg = segment_throw(flags("..V..VVVVV..."), gates["arm_M"],
                            gates["close_K"])
        assert seg.start == 5


class TestStreamEnd:
    def test_stream_ends_while_active(self, gates):
        seg = segment_throw(flags("....VVVVVV"), gates["arm_M"], gates["close_K"])
        assert seg is not None
        assert seg.end == 9

    def test_stream_ends_with_short_invalid_tail(self, gates):
        # Tail of 2 invalid (< close_K): stripped by flush, throw still closes.
        seg = segment_throw(flags("....VVVVVV.."), gates["arm_M"],
                            gates["close_K"])
        assert seg.end == 9


class TestDetectorClass:
    def test_incremental_matches_batch(self, gates):
        pattern = flags("..VVV.VV..VVV......")
        det = ThrowDetector(gates["arm_M"], gates["close_K"])
        for v in pattern:
            det.update(v)
        det.flush()
        seg = segment_throw(pattern, gates["arm_M"], gates["close_K"])
        assert (det.start, det.end) == (seg.start, seg.end)

    def test_bad_params_raise(self):
        with pytest.raises(ValueError):
            ThrowDetector(0, 3)

    def test_updates_after_close_ignored(self, gates):
        det = ThrowDetector(gates["arm_M"], gates["close_K"])
        for v in flags("..VVVV...VVVV"):
            det.update(v)
        assert det.state == "CLOSED"
        assert det.end == 5
