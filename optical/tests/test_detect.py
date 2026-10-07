"""Phase 3 tests: HSV detector (§5.2), including the shadowed scenario — not just
clean frames.

Tolerances: detected centroid vs drawn truth < 0.5 px on clean frames (Phase-1
rasterisation bound); < 2 px under shadow/low-contrast/blur (morphology + edge
erosion effects, still ~6 mm at the ~330 px/m floor scale — far under the noise
these scenarios are meant to stress).
"""

import numpy as np
import pytest

from optical.detect import Detection, HsvDetector, localisation_scatter
from optical.geometry import load_config
from simulator import render, scenarios

from pathlib import Path

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")

# [WO-OPT-4 Stage 3 hardcode audit] The "near floor" sample instant used to be the literal
# t = 0.46 s, which was one frame before the TENNIS ball's contact (t* = 0.4744 s). A bigger
# ball touches down EARLIER (basketball t* = 0.4531 s), so 0.46 s now lands PAST contact,
# where the simulator stops drawing the ball — the test failed with "no detection" for a
# reason that had nothing to do with shadows. Derive the instant from contact time instead.
R_BALL = render.config_r_ball()
_T_CONTACT = scenarios.BASE_TRAJ.contact_time(R_BALL)
T_NEAR_FLOOR = _T_CONTACT - 2.0 / 480.0        # two frames @480 fps before touchdown


@pytest.fixture(scope="module")
def detector():
    return HsvDetector.from_config(CONFIG)


def _one_frame(factory, t=0.42, **kw):
    sc = factory(resolution=(1280, 720), t_start=t, t_end=t, **kw)
    res = render.render_sequence(sc)
    return res.frames[0], res.ball_center_px[0], res.ball_radius_px[0]


def test_detects_ball_on_nominal_frame(detector):
    frame, truth_uv, r_px = _one_frame(scenarios.nominal)
    det = detector.detect(frame)
    assert det is not None
    err = np.linalg.norm(det.centroid_px - truth_uv)
    print(f"\n[detect] nominal centroid error: {err:.3f} px")
    assert err < 0.5
    # lowest point sits ~one radius below the centre (drawn-disc geometry)
    assert abs(det.lowest_px[1] - (truth_uv[1] + r_px)) < 1.5
    assert det.n_candidates == 1
    assert det.circularity > 0.8


def test_detects_ball_under_shadow(detector):
    """§5.2: must be tested WITH shadows present. The shadow ellipse is adjacent to
    (and below) the ball in the image; low saturation must exclude it from the mask
    so neither the centroid nor the lowest point is contaminated."""
    frame, truth_uv, r_px = _one_frame(scenarios.shadowed, t=T_NEAR_FLOOR)  # near floor
    det = detector.detect(frame)
    assert det is not None
    err = np.linalg.norm(det.centroid_px - truth_uv)
    print(f"\n[detect] shadowed centroid error: {err:.3f} px")
    assert err < 2.0
    assert abs(det.lowest_px[1] - (truth_uv[1] + r_px)) < 2.5   # bottom not stolen


def test_detects_ball_low_contrast(detector):
    frame, truth_uv, _ = _one_frame(scenarios.low_contrast)
    det = detector.detect(frame)
    assert det is not None
    assert np.linalg.norm(det.centroid_px - truth_uv) < 2.0


def test_detects_ball_blurred(detector):
    frame, truth_uv, _ = _one_frame(scenarios.blurred)
    det = detector.detect(frame)
    assert det is not None
    # motion smear is symmetric about the centre: centroid stays near truth
    assert np.linalg.norm(det.centroid_px - truth_uv) < 2.5


def test_no_ball_returns_none(detector):
    frame, _, _ = _one_frame(scenarios.no_ball)
    assert detector.detect(frame) is None      # markers/floor never fake a ball


def test_area_band_rejects_speck(detector):
    frame, _, _ = _one_frame(scenarios.no_ball)
    render._draw_disc(frame, (300.0, 200.0), 2.0, render.basketball_bgr())
    assert detector.detect(frame) is None      # ~12 px^2 < min_area_px


def test_ambiguous_scene_flagged_largest_wins(detector):
    frame, truth_uv, r_px = _one_frame(scenarios.nominal)
    render._draw_disc(frame, (200.0, 150.0), r_px * 0.7,
                      render.basketball_bgr())          # smaller decoy ball
    det = detector.detect(frame)
    assert det is not None
    assert det.n_candidates == 2                          # ambiguity recorded
    assert np.linalg.norm(det.centroid_px - truth_uv) < 0.5   # largest blob wins


def test_localisation_scatter_on_noisy_static_frames(detector):
    """Detector characterisation (§7 item 3): scatter of the centroid over repeated
    noisy renders of the SAME ball position. This is the measured pixel-localisation
    sigma the uncertainty budget consumes."""
    frames = []
    for seed in range(25):
        sc = scenarios.nominal(resolution=(1280, 720), t_start=0.42, t_end=0.42,
                               noise_sigma=3.0, seed=seed)
        frames.append(render.render_sequence(sc).frames[0])
    stats = localisation_scatter(frames, detector)
    print(f"\n[detect] localisation scatter: sigma_px={stats['sigma_px']:.4f} "
          f"({stats['n_detected']}/{stats['n_frames']} detected)")
    assert stats["n_detected"] == stats["n_frames"]
    assert 0.0 < stats["sigma_px"] < 0.5


def test_scatter_handles_no_detections(detector):
    frame, _, _ = _one_frame(scenarios.no_ball)
    stats = localisation_scatter([frame] * 3, detector)
    assert stats["n_detected"] == 0
    assert np.isnan(stats["sigma_px"])
