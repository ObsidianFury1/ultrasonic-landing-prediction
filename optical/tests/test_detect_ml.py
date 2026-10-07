"""Phase 6a (WO-OPT-2 Stage 1) tests: the zero-shot YOLO ball detector (optical/detect_ml.py),
Zone 2 only, behind the FROZEN §5.2 `Detector` interface.

Skips cleanly if the optional ML stack is not installed, so the CORE suite is unaffected when
`requirements-ml.txt` is absent (the dedicated import-guard test proves this rigorously).

Tolerances (§11 discipline, justified from measured Stage-1 numbers on 1280x720 synthetic
frames): the YOLO box-centre vs the simulator's EXACT analytic ball centre measured 0.8-1.6 px
median across nominal/shadowed/low_contrast; we assert median < 3 px and max < 5 px — a margin
covering the near-contact confidence dip and the box-centre-vs-intensity-centroid difference,
still ~15 mm at the ~330 px/m floor scale, far under the noise these scenarios stress.
Detection rate measured 9-10 of 11 sampled descent frames; we assert >= 8/11. These synthetic
numbers are OPTIMISTIC (the synthetic hue/shape is idealised) and carry no evidentiary weight
for commissioning — that is the whole point of the Phase 6a watermark (§10); this test only
proves the detector honours the Detection contract and plumbs into the pipeline."""

import numpy as np
import pytest

pytest.importorskip("ultralytics",
                    reason="optional ML stack not installed (requirements-ml.txt)")

from pathlib import Path

from optical.detect import HsvDetector
from optical.detect_ml import YoloDetector, MLDetectorUnavailable
from optical.geometry import load_config
from simulator import render, scenarios

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")

# conf=0.02 in the TEST detector (not the config default 0.25): the synthetic ball's zero-shot
# confidence sits low (~0.05-0.72, dipping near contact), so a permissive threshold exercises
# the contract on the most frames. The realistic-threshold exploration is the Phase 6a sweep
# (Stage 2), not this plumbing test.
_TEST_CONF = 0.02


@pytest.fixture(scope="module")
def detector():
    return YoloDetector(model=CONFIG["ml_detector"]["model"],
                        sports_ball_class=CONFIG["ml_detector"]["sports_ball_class"],
                        conf=_TEST_CONF, imgsz=CONFIG["ml_detector"]["imgsz"])


def _scenario_stats(factory, detector, step=8):
    """Detection rate + centroid-error distribution over sampled descent frames, vs the
    simulator's exact analytic ball centre (known because the footage is synthetic)."""
    res = render.render_sequence(factory(resolution=(1280, 720)))
    errs, n_det, n_tot = [], 0, 0
    for i in range(0, len(res.frames), step):
        frame, truth = res.frames[i], res.ball_center_px[i]
        if frame is None or not np.isfinite(truth[0]):
            continue
        n_tot += 1
        det = detector.detect(frame)
        if det is not None:
            n_det += 1
            errs.append(float(np.hypot(*(det.centroid_px - truth))))
    return n_det, n_tot, errs


# [WO-OPT-4 Stage 6 — characterised limitation, §10; do NOT tune the model/threshold to force
# a pass.] These two tests assumed zero-shot YOLO detects the ball at all, true for the tennis
# ball but MEASURED FALSE for the basketball: the pretrained model classifies the flat orange
# disc as COCO class 32... no, as COCO 'orange' (the fruit, a DIFFERENT class), conf 0.25-0.32;
# 'sports ball' itself scores only ~0.05-0.11, below any sane cutoff. Verified down to conf
# 0.005 (near-unfiltered): sports_ball fires on ~1/8 nominal frames. A 2x2 control (colour x
# size) shows this is an INTERACTION — green+basketball and orange+tennis both still detect
# reasonably; only orange+basketball (this project's actual ball) does not. xfail(strict=True)
# so a future model/library change that fixes this shows as an unexpected XPASS, not silence.
_XFAIL_ORANGE_AS_FRUIT = pytest.mark.xfail(
    reason="WO-OPT-4 D22: zero-shot YOLO reads the orange basketball synthetic as COCO "
           "'orange' (fruit), not 'sports ball' (conf ~0.05-0.11, below any cutoff) — "
           "characterised limitation per §10, not tuned away.",
    strict=True)


@_XFAIL_ORANGE_AS_FRUIT
@pytest.mark.parametrize("factory", [scenarios.nominal, scenarios.shadowed,
                                     scenarios.low_contrast])
def test_detects_ball_and_localises(detector, factory):
    n_det, n_tot, errs = _scenario_stats(factory, detector)
    print(f"\n[detect_ml] {factory.__name__}: {n_det}/{n_tot} detected, "
          f"median err={np.median(errs):.2f}px max={max(errs):.2f}px")
    assert n_det >= 8, f"detection rate too low: {n_det}/{n_tot}"
    assert np.median(errs) < 3.0
    assert max(errs) < 5.0


@_XFAIL_ORANGE_AS_FRUIT
def test_detection_contract_populated(detector):
    """Every field the interface promises is present and sane, incl. the native confidence."""
    res = render.render_sequence(scenarios.nominal(resolution=(1280, 720)))
    det = None
    for i in range(0, len(res.frames), 4):        # first frame that detects
        det = detector.detect(res.frames[i])
        if det is not None:
            break
    assert det is not None
    assert det.centroid_px.shape == (2,) and np.all(np.isfinite(det.centroid_px))
    assert det.lowest_px.shape == (2,) and det.lowest_px[1] >= det.centroid_px[1]
    assert det.radius_px > 0
    assert len(det.bbox) == 4
    assert det.n_candidates >= 1
    assert det.confidence is not None and _TEST_CONF <= det.confidence <= 1.0


def test_no_ball_negative_control(detector):
    """§6 negative control: no ball in the scene -> no detection, never a fabricated ball.
    Verified at the permissive test threshold (measured to fire 0 times even at conf=0.02)."""
    res = render.render_sequence(scenarios.no_ball(resolution=(1280, 720)))
    fires = [i for i, fr in enumerate(res.frames) if fr is not None
             and detector.detect(fr) is not None]
    assert fires == [], f"ML detector fabricated a ball on {len(fires)} no-ball frames"


def test_hsv_detection_confidence_is_none():
    """Contract check on the additive field: the HSV baseline has no probabilistic score,
    so its Detection.confidence stays None (the ML detector is the only producer)."""
    res = render.render_sequence(scenarios.nominal(resolution=(1280, 720),
                                                   t_start=0.42, t_end=0.42))
    det = HsvDetector.from_config(CONFIG).detect(res.frames[0])
    assert det is not None and det.confidence is None


def test_from_config_matches_config_defaults():
    d = YoloDetector.from_config(CONFIG)
    assert d.conf == CONFIG["ml_detector"]["conf"]
    assert d.imgsz == CONFIG["ml_detector"]["imgsz"]
    assert d.sports_ball_class == CONFIG["ml_detector"]["sports_ball_class"]


def test_unavailable_error_type_is_clear():
    """MLDetectorUnavailable is a RuntimeError subclass with an actionable message — the
    import-guard test proves it is what gets raised when ultralytics is absent."""
    assert issubclass(MLDetectorUnavailable, RuntimeError)
