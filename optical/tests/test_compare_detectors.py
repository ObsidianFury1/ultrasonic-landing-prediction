"""WO-OPT-2 Stage 2 tests: the detector-comparison harness (scripts/compare_detectors.py).

Two tiers:
  * pure metric logic (detection_metrics, HSV landing through the unchanged chain) — no ML,
    runs in the core suite;
  * ML-gated end-to-end scenario + negative-control checks — skipped if ultralytics is absent.

Kept light (one/two scenarios) so YOLO's ~40 ms/frame doesn't bloat the suite; the FULL §6
library run is exercised by the script itself (its outputs are the Stage 2/3 deliverable)."""

from pathlib import Path

import numpy as np
import pytest

from optical.detect import Detection, HsvDetector
from optical.geometry import load_config
from scripts import compare_detectors as cd
from simulator import render, scenarios

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config.yaml")


def _det(u, v):
    return Detection(centroid_px=np.array([u, v]), bbox=(0, 0, 2, 2),
                     lowest_px=np.array([u, v + 1]), radius_px=1.0, area_px=4.0,
                     circularity=1.0, n_candidates=1)


def test_detection_metrics_rate_and_scatter():
    truth = np.array([[10.0, 20.0], [11.0, 21.0], [np.nan, np.nan], [12.0, 22.0]])
    dets = [_det(10.5, 20.0), _det(11.0, 21.5), None, None]   # 2/3 ball frames detected
    m = cd.detection_metrics(dets, truth)
    assert m["n_ball_frames"] == 3 and m["n_detected"] == 2
    assert m["detection_rate"] == pytest.approx(2 / 3)
    assert m["n_false_positive"] == 0
    # residuals (0.5,0) and (0,0.5): sigma per axis and combined are finite and small
    assert m["sigma_px"] is not None and m["sigma_px"] < 1.0


def test_detection_metrics_flags_false_positive_on_no_ball():
    truth = np.array([[np.nan, np.nan], [np.nan, np.nan]])
    m = cd.detection_metrics([None, _det(5.0, 5.0)], truth)   # a fabrication on frame 1
    assert m["n_ball_frames"] == 0
    assert m["n_false_positive"] == 1 and m["false_positive_frames"] == [1]


def test_hsv_landing_through_unchanged_chain():
    """HSV through the harness's landing_through_chain reproduces the e2e nominal anchor
    (~7 mm, bracket-limited) — proof the harness reuses the real downstream chain, not a fork."""
    res = render.render_sequence(scenarios.nominal(**cd.RENDER_KW))
    dets = [HsvDetector.from_config(CONFIG).detect(f) if f is not None else None
            for f in res.frames]
    land = cd.landing_through_chain(dets, res, CONFIG)
    assert land["landing_error_mm"] is not None
    assert land["landing_error_mm"] < 10.0        # matches test_e2e_nominal_true_H tolerance


def test_no_ball_landing_reports_no_contact():
    res = render.render_sequence(scenarios.no_ball(**cd.RENDER_KW, t_end=0.40))
    land = cd.landing_through_chain([None] * len(res.frames), res, CONFIG)
    assert land["landing_error_mm"] is None and "no-ball" in land["reason"]


# --------------------------------------------------------------------------- #
# ML-gated end-to-end                                                          #
# --------------------------------------------------------------------------- #

pytestmark_ml = pytest.mark.skipif(
    cd.make_ml_detector(CONFIG)[0] is None,
    reason="optional ML stack not installed (requirements-ml.txt)")


@pytestmark_ml
def test_run_scenario_both_detectors_present():
    ml, _ = cd.make_ml_detector(CONFIG)
    detectors = {"hsv": HsvDetector.from_config(CONFIG), "ml": ml}
    out = cd.run_scenario("nominal", scenarios.nominal, detectors, CONFIG)
    assert set(out["detectors"]) == {"hsv", "ml"}
    assert out["detectors"]["hsv"]["detection_rate"] == pytest.approx(1.0)
    # [WO-OPT-4 Stage 6 — characterised limitation, §10; not tuned away.] The ">0.0 at conf
    # 0.25" figure was measured for the TENNIS-era green ball. MEASURED for the basketball:
    # zero-shot YOLO classifies the flat orange disc as COCO 'orange' (fruit), not 'sports
    # ball' (conf ~0.05-0.11, below any sane cutoff, verified down to conf 0.005) -> rate 0.0
    # on `nominal`. The HSV assertion above is UNCHANGED and still a hard pass/fail gate.
    if out["detectors"]["ml"]["detection_rate"] <= 0.0:
        pytest.xfail("WO-OPT-4 D22: YOLO reads the orange basketball synthetic as the COCO "
                     "'orange' fruit class, not 'sports ball' — see test_detect_ml.py")
    assert out["detectors"]["ml"]["detection_rate"] > 0.0


@pytestmark_ml
def test_negative_control_no_fabrication_either_detector():
    ml, _ = cd.make_ml_detector(CONFIG)
    detectors = {"hsv": HsvDetector.from_config(CONFIG), "ml": ml}
    out = cd.run_scenario("no_ball", scenarios.no_ball, detectors, CONFIG)
    for dname, m in out["detectors"].items():
        assert m["n_false_positive"] == 0, f"{dname} fabricated a ball on the no-ball scene"


@pytestmark_ml
def test_timing_pool_meets_200_frame_floor():
    frames = cd.timing_frames()
    assert len(frames) >= 200        # §10 requires the median/IQR over >= 200 frames


# --------------------------------------------------------------------------- #
# Final report (Stage 3) — no ML needed; drives the generator off a fixture dict #
# --------------------------------------------------------------------------- #

_RESULTS = {
    "generated": "2026-07-06T00:00:00",
    "environment": {"python": "3.14", "platform": "test"},
    "config": {"ml_detector": {"model": "yolo11n.pt"}},
    "scenarios": {
        "nominal": {"has_ball": True, "detectors": {
            "hsv": {"detection_rate": 1.0, "sigma_px": 0.07,
                    "landing": {"landing_error_mm": 7.2, "method": "analytic_centroid"}},
            "ml": {"detection_rate": 0.6, "sigma_px": 0.4,
                   "landing": {"landing_error_mm": 6.3, "method": "analytic_centroid"}}}},
        "low_contrast": {"has_ball": True, "detectors": {
            "ml": {"detection_rate": 0.0, "sigma_px": None,
                   "landing": {"landing_error_mm": None, "reason": "no prediction"}}}},
        "no_ball": {"has_ball": False, "detectors": {
            "hsv": {"detection_rate": None, "sigma_px": None,
                    "landing": {"landing_error_mm": None, "reason": "no-ball"}}}}},
    "confidence_sweep": {"scenarios": ["nominal"], "subsample": 4,
                         "points": [{"conf": 0.25, "mean_detection_rate": 0.3,
                                     "mean_sigma_px": 0.3}],
                         "hsv_reference": {"mean_detection_rate": 1.0, "mean_sigma_px": 0.06}},
    "timing": {"hsv": {"n_frames": 204, "median_ms": 3.8, "iqr_ms": 2.0},
               "ml": {"n_frames": 204, "median_ms": 40.0, "iqr_ms": 5.0}},
    "negative_control": {"hsv": {"n_false_positive": 0, "DEFECT": False},
                         "ml": {"n_false_positive": 0, "DEFECT": False}}}


def test_landing_aggregate_rms_and_no_prediction():
    agg = cd.landing_aggregate(_RESULTS)
    assert agg["hsv"]["n_landed"] == 1 and agg["hsv"]["rms_mm"] == pytest.approx(7.2)
    assert agg["ml"]["n_landed"] == 1 and agg["ml"]["n_no_prediction"] == 1
    assert agg["ml"]["no_prediction_scenarios"] == ["low_contrast"]


def test_final_report_has_mandatory_watermark_and_caveat():
    rep = cd.final_report(_RESULTS, install_mb=816)
    assert "SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING" in rep     # verbatim (§10)
    # [WO-OPT-4 Stage 3] was: `assert "H=35" in rep` — the tennis band-centre hue baked into
    # the test as a literal. Derive it from the config band, exactly as the report now does.
    _band = render._config()["detect"]
    _hue = int(round((_band["hsv_lower"][0] + _band["hsv_upper"][0]) / 2.0))
    assert f"H={_hue}" in rep and "dead-centre" in rep                     # exact Stage-6.5 finding
    assert "no evidentiary weight" in rep
    assert "escalation gate" in rep and "fine-tuning" in rep               # limitations (§10 gate)
    # all seven sections present, in order
    for marker in ("## SYNTHETIC-ONLY", "## 1. Per-scenario", "## 2. ML confidence",
                   "## 3. Runtime", "## 4. Negative-control", "## 5. Limitations"):
        assert marker in rep
    assert rep.index("## 1.") < rep.index("## 2.") < rep.index("## 3.") < rep.index("## 5.")
