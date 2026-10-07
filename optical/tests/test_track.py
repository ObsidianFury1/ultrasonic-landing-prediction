"""Phase 3 tests: association + descent segmentation (§5.3).

These tests fabricate Detection sequences directly (no rendering): association and
segmentation are pure logic on point sequences, and exactness matters more than
photorealism here. Rendered-frame integration is covered by the end-to-end test.
"""

import numpy as np
import pytest

from optical.detect import Detection
from optical.track import DescentSegment, Track, build_track, find_descent


def _det(u, v, n_candidates=1):
    c = np.array([float(u), float(v)])
    return Detection(centroid_px=c, bbox=(int(u) - 5, int(v) - 5, 10, 10),
                     lowest_px=c + [0.0, 5.0], radius_px=5.0, area_px=80.0,
                     circularity=0.9, n_candidates=n_candidates)


def _times(n, fps=480.0):
    return np.arange(n) / fps


def test_clean_association():
    dets = [_det(100 + 2 * i, 200 + 3 * i) for i in range(20)]
    tr = build_track(dets, _times(20), max_jump_px=150)
    assert tr.n_valid == 20
    assert all(s == "ok" for s in tr.status)
    assert np.allclose(tr.centroid_px[5], [110, 215])


def test_gaps_recorded_not_dropped():
    dets = [_det(100 + 2 * i, 200 + 3 * i) for i in range(10)]
    dets[3] = None
    dets[4] = None
    tr = build_track(dets, _times(10), max_jump_px=150)
    assert tr.status[3] == "none" and tr.status[4] == "none"
    assert tr.n_valid == 8
    assert np.all(np.isnan(tr.centroid_px[3]))


def test_jump_gate_rejects_teleport_keeps_track():
    dets = [_det(100 + 2 * i, 200 + 3 * i) for i in range(10)]
    dets[5] = _det(900, 900)                       # decoy teleport
    tr = build_track(dets, _times(10), max_jump_px=150)
    assert tr.status[5] == "jump_rejected"
    assert tr.status[6] == "ok"                    # anchor survived the flier
    assert tr.n_valid == 9


def test_jump_gate_scales_with_gap_length():
    """After g missed frames the ball may have moved ~g frames' worth; the gate
    must not reject legitimate re-acquisition."""
    dets = [_det(100 + 40 * i, 200) for i in range(8)]   # 40 px/frame
    dets[3] = None
    dets[4] = None                                  # re-acquired 120 px away
    tr = build_track(dets, _times(8), max_jump_px=50)    # 50 < 120 < 3*50
    assert tr.status[5] == "ok"
    assert tr.n_valid == 6


def test_ambiguous_detections_flagged():
    dets = [_det(100, 200 + i, n_candidates=2 if i == 4 else 1) for i in range(8)]
    tr = build_track(dets, _times(8), max_jump_px=150)
    assert tr.status[4] == "ambiguous"
    assert tr.valid[4]                              # flagged but USED


def test_descent_track_end():
    """Ball descends (v increasing) then vanishes: descent = last `window` frames,
    reason 'track_end'."""
    v = 200 + 4 * np.arange(30)
    dets = [_det(100 + i, vi) for i, vi in enumerate(v)] + [None] * 5
    tr = build_track(dets, _times(35), max_jump_px=150)
    seg = find_descent(tr, window=10)
    assert seg.end_reason == "track_end"
    assert len(seg.indices) == 10
    assert seg.indices[-1] == 29


def test_descent_first_reversal_is_taken():
    """v rises (descent), reverses (contact/bounce), rises again (second descent):
    §5.3 takes the FIRST reversal, not the last."""
    v_down1 = 200 + 5 * np.arange(15)          # descent to first touchdown
    v_up = v_down1[-1] - 4 * np.arange(1, 8)   # bounce going up
    v_down2 = v_up[-1] + 4 * np.arange(1, 10)  # falling again
    v = np.concatenate([v_down1, v_up, v_down2])
    dets = [_det(100 + i, vi) for i, vi in enumerate(v)]
    tr = build_track(dets, _times(len(v)), max_jump_px=150)
    seg = find_descent(tr, window=10)
    assert seg.end_reason == "reversal"
    assert seg.indices[-1] == 14               # peak of the FIRST descent


def test_descent_short_run_flagged():
    v = 200 + 5 * np.arange(6)
    dets = [_det(100 + i, vi) for i, vi in enumerate(v)]
    tr = build_track(dets, _times(6), max_jump_px=150)
    seg = find_descent(tr, window=10)
    assert "low_frame_count" in seg.flags
    assert len(seg.indices) == 6


def test_no_track_raises_cleanly():
    tr = build_track([None] * 10, _times(10), max_jump_px=150)
    with pytest.raises(ValueError, match="no ball track"):
        find_descent(tr, window=10)


def test_no_descending_run_raises_cleanly():
    v = 400 - 5 * np.arange(12)                # ball only RISING in the clip
    dets = [_det(100 + i, vi) for i, vi in enumerate(v)]
    tr = build_track(dets, _times(12), max_jump_px=150)
    with pytest.raises(ValueError, match="descent"):
        find_descent(tr, window=10)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="detections vs"):
        build_track([None] * 5, _times(4), max_jump_px=150)


# --------------------------------------------------------------------------- #
# WO-OPT-1 Stage 4.4/4.5 — confirmed reversal (min_rise) + noise robustness    #
# --------------------------------------------------------------------------- #

def test_single_dip_does_not_end_descent():
    """DETERMINISTIC single-frame dip mid-descent (one non-increase, then the rise
    resumes): the confirmed-reversal rule (min_rise=2) must NOT declare a reversal at
    the dip, and the dip-tolerant walk-back must NOT truncate the window there. The
    real reversal (sustained rebound) is still found at the true peak."""
    v_down = 200.0 + 8.0 * np.arange(15)     # descent at 8 px/frame
    v_down[7] = v_down[6] - 1.0              # injected dip: one noisy non-increase
    v_up = v_down[-1] - 7.0 * np.arange(1, 6)
    v = np.concatenate([v_down, v_up])
    dets = [_det(100 + i, vi) for i, vi in enumerate(v)]
    tr = build_track(dets, _times(len(v)), max_jump_px=150)
    seg = find_descent(tr, window=12)
    assert seg.end_reason == "reversal"
    assert seg.indices[-1] == 14             # true peak, not the dip at index 7
    assert len(seg.indices) == 12            # window spans ACROSS the dip, not cut at it
    assert seg.indices[0] == 3               # 14 - 12 + 1: full window survived the dip


@pytest.mark.parametrize("sigma_px", [0.5, 2.0])
def test_reversal_robust_to_pixel_scatter(sigma_px):
    """Injected Gaussian scatter at 0.5 px (the §7 item-3 anticipated detector sigma)
    and 2 px (the Phase-3 shadowed-detection bound) on an 8 px/frame descent + 7 px/frame
    rebound (the near-contact image speeds measured in the e2e scenarios are ~5-15
    px/frame at 480 fps). Requirements: the descent window is not prematurely terminated
    and the confirmed reversal lands within +-1 frame of the true peak. Seeded RNG makes
    each case deterministic; 5 seeds per sigma guard against a lucky draw."""
    for seed in range(5):
        rng = np.random.default_rng(seed)
        v_down = 200.0 + 8.0 * np.arange(15)
        v_up = v_down[-1] - 7.0 * np.arange(1, 8)
        v = np.concatenate([v_down, v_up]) + rng.normal(0.0, sigma_px, 22)
        dets = [_det(100 + i, vi) for i, vi in enumerate(v)]
        tr = build_track(dets, _times(len(v)), max_jump_px=150)
        seg = find_descent(tr, window=10)
        assert seg.end_reason == "reversal", f"seed {seed}: no reversal found"
        assert abs(seg.indices[-1] - 14) <= 1, \
            f"seed {seed}: reversal at {seg.indices[-1]}, true peak 14"
        assert len(seg.indices) >= 8, \
            f"seed {seed}: window prematurely terminated ({len(seg.indices)} frames)"
