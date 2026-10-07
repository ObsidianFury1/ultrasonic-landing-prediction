# optical/ - Optical ground-truth landing module (closed: NO-GO)

A standalone module that recovers a basketball's **landing point on the floor from phone video**: video in,
(r, theta) out, with a per-throw uncertainty budget, via planar-homography mapping of the tracked contact
point. It was built as an automation demonstrator and independent cross-check for the ultrasonic system in
[`../code/`](../code/). It never imports from or writes into that project.

## Outcome

Phase 5 physical commissioning (2026-07-11) ended **NO-GO** against the pre-registered gate
(RMS <= 15 mm over >= 8 static points): measured **64.4 mm** as captured, 55.3 mm best-case. The gate was
not relaxed. Diagnosis: about 17 mm survey/intrinsics/floor-planarity floor, 20-40 mm camera movement
between calibration and capture, about 7 mm parallax from the decomposed camera position, plus one outlier
point. None of it is a remaining software bug; a recorded path to a future GO needs a fresh field session.
Full detail: [`Phase5_Commissioning_Report_2026-07-11.md`](Phase5_Commissioning_Report_2026-07-11.md) and the
closeout in [`IMPLEMENTATION_NOTES_OPTICAL.md`](IMPLEMENTATION_NOTES_OPTICAL.md).

## Pipeline

`raw video` -> HSV ball detection (`optical/detect.py`) -> nearest-neighbour tracking and descent
segmentation (`track.py`) -> sub-frame contact instant (`contact.py`: +0.5-frame bracket for a vanish, kink
intersection for a bounce) -> parallax-corrected floor mapping (`geometry.py`) -> uncertainty budget
(`uncertainty.py`) -> frozen-schema `optical_gt.json` plus overlay (`io_session.py`, `overlay.py`).

Design rules: geometry and contact timing are closed-form with no ML; ML is allowed only as a swappable
ball detector (a zero-shot YOLO comparison was run on synthetic scenarios); everything is validated against
a simulator with exact ground truth and negative controls first.

## Setup

Python 3.11+ (the project used 3.14). Core dependencies only:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pytest tests -q        # 185 passed (core install)
```

The ML comparison (`requirements-ml.txt`, pulls PyTorch) is optional; the core suite never imports it.
**Known issue:** if the ML extras *are* installed, two tests in `tests/test_detect_ml.py` report
`XPASS(strict)` as failures. Their `xfail` markers date from the orange-ball synthetic hue and went stale
when the hue was corrected to red during commissioning; the tests now pass. This is the logged "re-run the
ML ablation" follow-up, not a pipeline defect.

## Reading order

1. [`CLAUDE.md`](CLAUDE.md) - authoritative specification (v1.6); section 16 is the changelog and the
   Phase 5 closeout.
2. [`IMPLEMENTATION_NOTES_OPTICAL.md`](IMPLEMENTATION_NOTES_OPTICAL.md) - as-built record per phase.
3. [`Phase5_Commissioning_Report_2026-07-11.md`](Phase5_Commissioning_Report_2026-07-11.md) - sign-off.
4. `Audit_Reports/` - two independent read-only audits and what was remediated.
5. [`data/comparison/`](data/comparison/) - HSV vs YOLO comparison reports.

## Missing from this repo

Raw footage (`data/optical/**/*.MOV|mp4`), raw checkerboard photos (`calib/raw/`), the ML weights
(`models/`) and `calibration-frames/` are not tracked because of size. The calibration results
(`calib/*.yaml`) and the per-point surveyed positions (`data/optical/static_gate/*/point.yaml`) are included.
See [`data/optical/README.md`](data/optical/README.md).

The original README (written before commissioning, so partly out of date) is archived in
[`../docs/archive/`](../docs/archive/).
