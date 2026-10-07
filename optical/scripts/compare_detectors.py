"""Detector ablation harness — HSV baseline vs zero-shot YOLO (Optical.md §10, Phase 6a).

SYNTHETIC-ONLY. Runs the full §6 simulator scenario library through BOTH detectors and the
IDENTICAL downstream chain (build_track -> find_descent -> fit_contact), swapping ONLY the
detector per the frozen §5.2 interface. Nothing ML touches geometry (Zone 1) or contact
identification (Zone 3): the ML detector emits the same `Detection`, and the exact same
downstream functions the HSV path uses produce the landing point.

Per scenario x detector it measures:
  1. detection rate per frame (fraction of ball-present frames with a non-null Detection),
  2. localisation scatter: residual of the detected centroid vs the simulator's EXACT
     analytic ball centre (known because the footage is synthetic) - bias + per-axis sigma,
  3. end-to-end landing error: |landing - exact synthetic contact point| through the
     unchanged downstream chain (true homography, so the DETECTOR is the only variable),
plus, once (detector-intrinsic, not per scenario):
  4. CPU inference time per frame: median + IQR over >= 200 frames,
  5. a confidence-threshold sweep for the ML detector (HSV reported at its single configured
     band as the analogous knob),
  6. negative-control check: any non-null Detection on the no-ball scene is a DEFECT.

Outputs (both OUTSIDE the frozen optical_gt.json schema, O7): a machine-readable results
JSON and a human-readable Markdown draft report. The Stage 3 report builds on these.

    .\\venv\\Scripts\\python.exe scripts\\compare_detectors.py            # full library
    .\\venv\\Scripts\\python.exe scripts\\compare_detectors.py --quick     # subsampled, fast

The report this stage emits is a DRAFT; the mandatory "SYNTHETIC-ONLY - NOT EVIDENTIARY FOR
COMMISSIONING" watermark + HSV-optimism caveat are finalised in Stage 3 (§10).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical.detect import HsvDetector                       # noqa: E402
from optical.errors import OpticalError                      # noqa: E402
from optical.geometry import CameraGeometry, load_config     # noqa: E402
from optical.track import build_track, find_descent          # noqa: E402
from optical.contact import fit_contact                      # noqa: E402
from simulator import render, scenarios                      # noqa: E402

# Common render window: the memory-bounded final-descent window the e2e test uses, so scatter
# and landing numbers are directly comparable to the existing regression anchor.
RENDER_KW = dict(resolution=(1280, 720), t_start=0.36)
CONF_SWEEP_GRID = [0.01, 0.02, 0.05, 0.10, 0.25, 0.50]
# Rationale: spans the ultralytics-typical default (0.25) and above (0.50) down to a permissive
# floor (0.01). The synthetic ball's zero-shot confidence sits low (~0.05-0.72, dipping near
# contact, Stage 1), so the interesting trade sits BELOW the default - the sweep exposes exactly
# the detection-rate vs false-positive tension the single HSV band knob cannot show.


# --------------------------------------------------------------------------- #
# Detector construction (ML import is guarded: HSV-only run if the stack is absent)
# --------------------------------------------------------------------------- #

def make_ml_detector(config, conf=None):
    """Instantiate the YOLO detector, or return (None, reason) if the ML stack is absent.
    Import is inside this function so importing the harness never needs ultralytics."""
    try:
        from optical.detect_ml import YoloDetector, MLDetectorUnavailable
    except ImportError as exc:
        return None, f"optical.detect_ml import failed: {exc}"
    d = config["ml_detector"]
    try:
        det = YoloDetector(model=d["model"], sports_ball_class=d["sports_ball_class"],
                           conf=d["conf"] if conf is None else conf, imgsz=d["imgsz"])
    except MLDetectorUnavailable as exc:
        return None, str(exc)
    return det, None


# --------------------------------------------------------------------------- #
# Per-frame metrics                                                            #
# --------------------------------------------------------------------------- #

def _detect_all(detector, frames):
    return [detector.detect(f) if f is not None else None for f in frames]


def detection_metrics(detections, truth_centres):
    """Detection rate + localisation residual stats vs the exact analytic centre.

    Detection rate is over BALL-PRESENT frames (finite truth). Residual = detected - truth,
    aggregated over detected+ball-present frames: mean (bias) and std (scatter, ddof=1) per
    axis, combined sigma_px = sqrt(0.5(su^2+sv^2)) (matching detect.localisation_scatter), and
    RMS |residual|. `false_positives` = detections on NON-ball frames (fabrications)."""
    ball = np.isfinite(truth_centres[:, 0])
    n_ball = int(ball.sum())
    n_det_ball = sum(1 for i in range(len(detections))
                     if ball[i] and detections[i] is not None)
    false_pos = [i for i in range(len(detections))
                 if not ball[i] and detections[i] is not None]

    res = []
    for i in range(len(detections)):
        if ball[i] and detections[i] is not None:
            res.append(detections[i].centroid_px - truth_centres[i])
    out = {"n_ball_frames": n_ball, "n_detected": n_det_ball,
           "detection_rate": (n_det_ball / n_ball) if n_ball else None,
           "n_false_positive": len(false_pos), "false_positive_frames": false_pos}
    if len(res) >= 2:
        r = np.asarray(res)
        su, sv = float(np.std(r[:, 0], ddof=1)), float(np.std(r[:, 1], ddof=1))
        out.update(bias_u_px=float(r[:, 0].mean()), bias_v_px=float(r[:, 1].mean()),
                   sigma_u_px=su, sigma_v_px=sv,
                   sigma_px=float(np.sqrt(0.5 * (su * su + sv * sv))),
                   rms_px=float(np.sqrt(np.mean(np.sum(r * r, axis=1)))))
    else:
        out.update(bias_u_px=None, bias_v_px=None, sigma_u_px=None, sigma_v_px=None,
                   sigma_px=None, rms_px=None)
    return out


def landing_through_chain(detections, res, config):
    """Run the UNCHANGED downstream chain on one detector's detections and return the landing
    error (mm) vs the exact synthetic contact point, or a no-prediction reason. True H is used
    (CameraGeometry.from_model), so the detector is the ONLY variable in the comparison."""
    if res.contact_xz is None:
        return {"landing_error_mm": None, "reason": "scenario has no contact (no-ball)"}
    H_px2floor = np.linalg.inv(res.H_true)
    camera = CameraGeometry.from_model(res.cam)
    try:
        track = build_track(detections, res.times,
                            max_jump_px=float(config["track"]["max_jump_px"]))
        descent = find_descent(track, window=int(config["track"]["descent_window_frames"]),
                               min_rise=int(config["track"].get("min_rise", 2)))
        contact = fit_contact(track, descent, H_px2floor, res.scenario.r_ball,
                              res.scenario.fps_measured, camera=camera)
    except OpticalError as exc:
        return {"landing_error_mm": None, "reason": f"no prediction: {exc}"}
    err_mm = float(np.linalg.norm(contact.landing_xz - res.contact_xz) * 1000.0)
    return {"landing_error_mm": err_mm, "reason": None,
            "end_reason": descent.end_reason, "method": contact.method,
            "contact_flags": list(contact.flags),
            "t_star_err_frame": float(abs(contact.t_star - res.contact_time_s)
                                      * res.scenario.fps_measured)}


def run_scenario(name, factory, detectors, config):
    """Full per-detector metrics for one scenario."""
    res = render.render_sequence(factory(**RENDER_KW))
    out = {"n_frames": len(res.frames),
           "has_ball": res.contact_xz is not None, "detectors": {}}
    for dname, det in detectors.items():
        dets = _detect_all(det, res.frames)
        m = detection_metrics(dets, res.ball_center_px)
        m["landing"] = landing_through_chain(dets, res, config)
        out["detectors"][dname] = m
    return out


# --------------------------------------------------------------------------- #
# Detector-intrinsic metrics: inference timing + ML confidence sweep          #
# --------------------------------------------------------------------------- #

def timing_frames(min_frames=200):
    """A pool of >= min_frames real synthetic frames (content-independent for timing). Each
    memory-bounded RENDER_KW window is ~68 frames, so several scenarios are concatenated
    until the >= 200-frame floor (§10 metric) is met."""
    frames = []
    for factory in (scenarios.nominal, scenarios.bounce, scenarios.blurred,
                    scenarios.shadowed, scenarios.low_contrast):
        frames += [f for f in render.render_sequence(factory(**RENDER_KW)).frames
                   if f is not None]
        if len(frames) >= min_frames:
            break
    return frames


def inference_timing(detector, frames):
    """Median + IQR of per-frame detect() wall time [ms] over >= len(frames) calls. One warm-up
    call is discarded (first YOLO call pays lazy graph/warm-up costs)."""
    detector.detect(frames[0])                         # warm-up, discarded
    t = []
    for f in frames:
        t0 = time.perf_counter()
        detector.detect(f)
        t.append((time.perf_counter() - t0) * 1000.0)
    a = np.asarray(t)
    p25, p50, p75 = (float(np.percentile(a, q)) for q in (25, 50, 75))
    return {"n_frames": len(t), "median_ms": p50, "p25_ms": p25, "p75_ms": p75,
            "iqr_ms": p75 - p25}


def confidence_sweep(config, factories, subsample=4):
    """ML detection rate + scatter vs confidence cutoff, on a subsampled representative set.
    HSV is reported once at its configured band as its analogous single knob."""
    # Pre-render the representative set once (subsampled for speed).
    sets = {}
    for name, fac in factories.items():
        res = render.render_sequence(fac(**RENDER_KW))
        idx = list(range(0, len(res.frames), subsample))
        sets[name] = ([res.frames[i] for i in idx], res.ball_center_px[idx])

    def aggregate(detector):
        rates, sig = [], []
        for frames, truth in sets.values():
            m = detection_metrics(_detect_all(detector, frames), truth)
            if m["detection_rate"] is not None:
                rates.append(m["detection_rate"])
            if m["sigma_px"] is not None:
                sig.append(m["sigma_px"])
        return (float(np.mean(rates)) if rates else None,
                float(np.mean(sig)) if sig else None)

    sweep = []
    for conf in CONF_SWEEP_GRID:
        det, reason = make_ml_detector(config, conf=conf)
        if det is None:
            return {"grid": CONF_SWEEP_GRID, "unavailable": reason, "points": []}
        rate, sigma = aggregate(det)
        sweep.append({"conf": conf, "mean_detection_rate": rate, "mean_sigma_px": sigma})

    hsv_rate, hsv_sigma = aggregate(HsvDetector.from_config(config))
    return {"grid": CONF_SWEEP_GRID, "scenarios": list(factories.keys()),
            "subsample": subsample, "points": sweep,
            "hsv_reference": {"band": {"hsv_lower": config["detect"]["hsv_lower"],
                                       "hsv_upper": config["detect"]["hsv_upper"]},
                              "mean_detection_rate": hsv_rate, "mean_sigma_px": hsv_sigma}}


# --------------------------------------------------------------------------- #
# Orchestration + output                                                       #
# --------------------------------------------------------------------------- #

def run_comparison(config, quick=False):
    """Build the full results dict over the entire §6 scenario library."""
    ml, ml_reason = make_ml_detector(config)
    detectors = {"hsv": HsvDetector.from_config(config)}
    if ml is not None:
        detectors["ml"] = ml

    scen_items = list(scenarios.ALL_SCENARIOS.items())
    if quick:
        keep = {"nominal", "shadowed", "no_ball", "bounce"}
        scen_items = [(n, f) for n, f in scen_items if n in keep]

    results = {"generated": datetime.now().isoformat(timespec="seconds"),
               "stage": "WO-OPT-2 Stage 2 (Phase 6a) — SYNTHETIC-ONLY draft",
               "ml_available": ml is not None, "ml_unavailable_reason": ml_reason,
               "config": {"ml_detector": config.get("ml_detector"),
                          "hsv_band": {"lower": config["detect"]["hsv_lower"],
                                       "upper": config["detect"]["hsv_upper"]}},
               "environment": {"python": platform.python_version(),
                               "platform": platform.platform()},
               "scenarios": {}}
    for name, factory in scen_items:
        results["scenarios"][name] = run_scenario(name, factory, detectors, config)

    results["timing"] = {}
    frames = timing_frames()
    for dname, det in detectors.items():
        results["timing"][dname] = inference_timing(det, frames)

    sweep_factories = {n: scenarios.ALL_SCENARIOS[n]
                       for n in ("nominal", "shadowed", "low_contrast")}
    results["confidence_sweep"] = confidence_sweep(config, sweep_factories)

    # Negative-control roll-up: any fabrication on the no-ball scene, either detector.
    nb = results["scenarios"].get("no_ball", {}).get("detectors", {})
    results["negative_control"] = {
        dname: {"n_false_positive": m.get("n_false_positive", 0),
                "DEFECT": m.get("n_false_positive", 0) > 0}
        for dname, m in nb.items()}
    return results


def _fmt(v, spec=".2f", none="—"):
    return none if v is None else format(v, spec)


def render_markdown(results) -> str:
    L = []
    L.append("# Detector comparison — HSV vs zero-shot YOLO (SYNTHETIC-ONLY DRAFT)")
    L.append("")
    L.append("> **SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING.** Draft output of "
             "WO-OPT-2 Stage 2. The synthetic ball hue sits dead-centre of the config HSV "
             "band (WO-OPT-1 Stage 6.5), so these numbers are structurally optimistic for the "
             "HSV baseline and carry no evidentiary weight; the finalised caveat/watermark is "
             "applied in Stage 3 (§10).")
    L.append("")
    L.append(f"Generated: {results['generated']} · ML available: {results['ml_available']}")
    if not results["ml_available"]:
        L.append(f"\n**ML unavailable:** {results['ml_unavailable_reason']}")
    L.append("")

    # Negative control first — a defect must be impossible to miss.
    L.append("## Negative control (no-ball scene)")
    for dname, nc in results.get("negative_control", {}).items():
        tag = "❌ DEFECT — fabricated a ball" if nc["DEFECT"] else "✅ clean (no detections)"
        L.append(f"- **{dname}**: {nc['n_false_positive']} false positives → {tag}")
    L.append("")

    # Per-scenario table
    L.append("## Per-scenario metrics")
    L.append("")
    L.append("| scenario | detector | det.rate | scatter σ_px | RMS_px | landing err (mm) | note |")
    L.append("|---|---|---|---|---|---|---|")
    for sname, sc in results["scenarios"].items():
        for dname, m in sc["detectors"].items():
            land = m["landing"]
            le = land.get("landing_error_mm")
            note = land.get("reason") or land.get("method") or ""
            L.append(f"| {sname} | {dname} | {_fmt(m['detection_rate'])} | "
                     f"{_fmt(m['sigma_px'])} | {_fmt(m['rms_px'])} | "
                     f"{_fmt(le, '.2f')} | {note} |")
    L.append("")

    # Timing
    L.append("## CPU inference time per frame")
    L.append("")
    L.append("| detector | n_frames | median (ms) | IQR (ms) |")
    L.append("|---|---|---|---|")
    for dname, t in results.get("timing", {}).items():
        L.append(f"| {dname} | {t['n_frames']} | {_fmt(t['median_ms'])} | {_fmt(t['iqr_ms'])} |")
    L.append("")

    # Confidence sweep
    sweep = results.get("confidence_sweep", {})
    L.append("## ML confidence-threshold sweep")
    if sweep.get("unavailable"):
        L.append(f"\n_Unavailable: {sweep['unavailable']}_")
    else:
        L.append(f"\nScenarios: {', '.join(sweep.get('scenarios', []))} "
                 f"(subsample 1/{sweep.get('subsample')}).")
        L.append("")
        L.append("| ML conf cutoff | mean det.rate | mean σ_px |")
        L.append("|---|---|---|")
        for p in sweep.get("points", []):
            L.append(f"| {p['conf']:.2f} | {_fmt(p['mean_detection_rate'])} | "
                     f"{_fmt(p['mean_sigma_px'])} |")
        ref = sweep.get("hsv_reference", {})
        L.append("")
        L.append(f"HSV at its configured band (single knob analogue): "
                 f"mean det.rate {_fmt(ref.get('mean_detection_rate'))}, "
                 f"mean σ_px {_fmt(ref.get('mean_sigma_px'))}.")
    L.append("")
    return "\n".join(L)


def landing_aggregate(results):
    """Aggregate end-to-end landing across ball-present scenarios, per detector: RMS + median
    + max over scenarios that produced a landing, and the count that produced NONE (§10's
    'end-to-end landing RMS' analogue for the single-throw synthetic scenarios)."""
    agg = {}
    for sname, sc in results["scenarios"].items():
        if not sc.get("has_ball"):
            continue
        for dname, m in sc["detectors"].items():
            e = m["landing"].get("landing_error_mm")
            d = agg.setdefault(dname, {"errs": [], "n_no_prediction": 0, "no_pred": []})
            if e is None:
                d["n_no_prediction"] += 1
                d["no_pred"].append(sname)
            else:
                d["errs"].append(e)
    out = {}
    for dname, d in agg.items():
        errs = np.asarray(d["errs"]) if d["errs"] else np.asarray([])
        out[dname] = {
            "n_landed": int(errs.size), "n_no_prediction": d["n_no_prediction"],
            "no_prediction_scenarios": d["no_pred"],
            "rms_mm": float(np.sqrt(np.mean(errs ** 2))) if errs.size else None,
            "median_mm": float(np.median(errs)) if errs.size else None,
            "max_mm": float(errs.max()) if errs.size else None}
    return out


def final_report(results, install_mb) -> str:
    """The polished Phase 6a report (Stage 3): the 7 mandatory sections in order, generated
    from the committed results JSON so it can be regenerated deterministically."""
    L = []
    L.append("# Phase 6a Detector Comparison — HSV baseline vs zero-shot YOLO")
    L.append("")
    # (1) mandatory watermark, verbatim.
    L.append("## SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING")
    L.append("")
    # (2) caveat paragraph, restating the exact WO-OPT-1 Stage 6.5 finding.
    # [WO-OPT-4 Stage 3] The hue is READ from config, never a literal. It used to be the
    # hardcoded string "H=35" (the tennis band centre), asserted verbatim by a test — a live
    # tennis hardcode that would have kept claiming H=35 while the ball was drawn at H=12.
    _band = render._config()["detect"]
    _hue = int(round((_band["hsv_lower"][0] + _band["hsv_upper"][0]) / 2.0))
    L.append("**Caveat (mandatory, §10).** Every number below is measured on the §6 SIMULATOR "
             "scenario library, not real footage. The simulator's basketball-orange colour is "
             f"defined in `simulator/render.py::basketball_bgr` at hue **H={_hue}**, COMPUTED as "
             "the centre of the configured HSV detection band, so it sits **dead-centre "
             "of that band** by construction (WO-OPT-1 Stage 6.5; retargeted yellow-green -> "
             "orange by WO-OPT-4 Stage 2, Decision D18). The synthetic footage is therefore "
             "**structurally optimistic for the HSV "
             "baseline**: HSV meets an idealised, perfectly-in-band, shadow-controlled target it "
             "will not see outdoors. These results characterise the comparison HARNESS and the "
             "ML detector's floor behaviour ONLY; they carry **no evidentiary weight for "
             "commissioning**. The evidentiary ablation is Phase 6b, on real commissioning + "
             "campaign clips after Phase 5, where the HSV band is tuned against real sun/shadow/"
             "ball-wear at checklist step C6.")
    L.append("")
    L.append(f"_Generated from `compare_detectors_results.json` ({results['generated']}); "
             f"environment Python {results['environment']['python']}, "
             f"{results['environment']['platform']}._")
    L.append("")

    # (3) full per-scenario comparison table.
    L.append("## 1. Per-scenario comparison (every §6 scenario)")
    L.append("")
    L.append("| scenario | detector | detection rate | scatter σ_px | landing error (mm) | note |")
    L.append("|---|---|---|---|---|---|")
    for sname, sc in results["scenarios"].items():
        for dname, m in sc["detectors"].items():
            land = m["landing"]
            le = land.get("landing_error_mm")
            note = land.get("reason") or land.get("method") or ""
            L.append(f"| {sname} | {dname} | {_fmt(m['detection_rate'])} | "
                     f"{_fmt(m['sigma_px'])} | {_fmt(le, '.2f')} | {note} |")
    L.append("")
    agg = landing_aggregate(results)
    L.append("**Aggregate landing across ball-present scenarios** "
             "(§10 end-to-end-RMS analogue; single throw per synthetic scenario):")
    L.append("")
    L.append("| detector | scenarios landed | landing RMS (mm) | median (mm) | max (mm) | no-prediction |")
    L.append("|---|---|---|---|---|---|")
    for dname, a in agg.items():
        nopred = (f"{a['n_no_prediction']} ({', '.join(a['no_prediction_scenarios'])})"
                  if a["n_no_prediction"] else "0")
        L.append(f"| {dname} | {a['n_landed']} | {_fmt(a['rms_mm'])} | {_fmt(a['median_mm'])} | "
                 f"{_fmt(a['max_mm'])} | {nopred} |")
    L.append("")

    # (4) confidence sweep.
    sweep = results.get("confidence_sweep", {})
    L.append("## 2. ML confidence-threshold sweep")
    if sweep.get("unavailable"):
        L.append(f"\n_Unavailable: {sweep['unavailable']}_")
    else:
        L.append(f"\nOver {', '.join(sweep.get('scenarios', []))} (subsample "
                 f"1/{sweep.get('subsample')}). The ML analogue of the single HSV band knob.")
        L.append("")
        L.append("| ML conf cutoff | mean detection rate | mean σ_px |")
        L.append("|---|---|---|")
        for p in sweep.get("points", []):
            L.append(f"| {p['conf']:.2f} | {_fmt(p['mean_detection_rate'])} | "
                     f"{_fmt(p['mean_sigma_px'])} |")
        ref = sweep.get("hsv_reference", {})
        L.append("")
        L.append(f"HSV at its configured band (its single tuning knob): mean detection rate "
                 f"**{_fmt(ref.get('mean_detection_rate'))}**, mean σ_px "
                 f"**{_fmt(ref.get('mean_sigma_px'))}**. Lowering the ML cutoff trades higher "
                 f"detection rate for more scatter, but does not reach HSV's rate on this footage.")
    L.append("")

    # (5) runtime / footprint.
    L.append("## 3. Runtime and footprint")
    L.append("")
    L.append("| detector | CPU inference median (ms/frame) | IQR (ms) | install footprint |")
    L.append("|---|---|---|---|")
    t = results.get("timing", {})
    foot = {"hsv": "0 MB extra (core deps only)",
            "ml": f"~{install_mb} MB (ultralytics + CPU PyTorch)"}
    for dname in t:
        L.append(f"| {dname} | {_fmt(t[dname]['median_ms'])} | {_fmt(t[dname]['iqr_ms'])} | "
                 f"{foot.get(dname, '—')} |")
    L.append(f"\n(Timing over {next(iter(t.values()))['n_frames']} frames, ≥ 200 per §10; "
             f"CPU-only PyTorch, one warm-up call discarded.)" if t else "")
    L.append("")

    # (6) negative-control outcomes.
    L.append("## 4. Negative-control outcomes")
    L.append("")
    for dname, nc in results.get("negative_control", {}).items():
        tag = ("❌ **DEFECT** — fabricated a ball" if nc["DEFECT"]
               else "✅ clean — no detections on the empty floor")
        L.append(f"- **{dname}**: {nc['n_false_positive']} false positives → {tag}")
    L.append("")

    # (7) limitations.
    L.append("## 5. Limitations")
    L.append("")
    L.append("This is **zero-shot** detection only: the pretrained "
             f"`{results['config']['ml_detector']['model']}` COCO 'sports ball' class is used "
             "with **no training and no labelling** of our footage. **No fine-tuning was "
             "performed.** Per the §10 escalation gate, fine-tuning on hand-labelled frames of "
             "our own footage is considered ONLY if zero-shot demonstrably fails AND the HSV "
             "baseline ALSO fails on real footage — i.e. only if the module would otherwise be "
             "NO-GO. Otherwise fine-tuning remains Future Works (§13). The synthetic-optimism "
             "caveat above means the real verdict on both detectors is deferred to Phase 6b; "
             "nothing here should be read as HSV 'winning' — only that, on an idealised target, "
             "the classical baseline is exact, fast, and cheap, while zero-shot YOLO is slower, "
             "heavier, and fragile near contact where detections thin out.")
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "comparison"))
    ap.add_argument("--quick", action="store_true",
                    help="subset of scenarios (nominal/shadowed/no_ball/bounce) for a fast run")
    ap.add_argument("--final-report", action="store_true",
                    help="skip the (slow) run; regenerate the polished Phase 6a report from the "
                         "existing results JSON in --out-dir")
    ap.add_argument("--ml-install-mb", type=int, default=816,
                    help="measured ML install footprint [MB] for the runtime/footprint line "
                         "(Stage 1 measured ~816 MB, CPU-only torch)")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    json_path = out_dir / "compare_detectors_results.json"
    final_path = out_dir / "phase6a_comparison_report.md"

    if args.final_report:
        results = json.loads(json_path.read_text(encoding="utf-8"))
        out_dir.mkdir(parents=True, exist_ok=True)
        final_path.write_text(final_report(results, args.ml_install_mb), encoding="utf-8")
        print(f"[compare_detectors] wrote {final_path}")
        return 0

    config = load_config(args.config)
    results = run_comparison(config, quick=args.quick)

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "compare_detectors_report.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    final_path.write_text(final_report(results, args.ml_install_mb), encoding="utf-8")

    print(f"[compare_detectors] wrote {json_path}")
    print(f"[compare_detectors] wrote {md_path}")
    print(f"[compare_detectors] wrote {final_path}")
    for dname, nc in results.get("negative_control", {}).items():
        if nc["DEFECT"]:
            print(f"  !! NEGATIVE-CONTROL DEFECT: '{dname}' fabricated "
                  f"{nc['n_false_positive']} detections on the no-ball scene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
