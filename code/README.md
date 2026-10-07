# code/ - Ultrasonic landing predictor

Three HC-SR04 sensors range a thrown basketball; Python reconstructs the trajectory (trilateration, Kalman
filter, parabola fit, floor extrapolation) and predicts the landing point (r, theta) with per-throw
uncertainty. See the [top-level README](../README.md) for results.

## Setup

Python 3.10+. The venv must be named `venv` because every documented command calls
`.\venv\Scripts\python.exe`.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pytest tests -q        # expect: 242 passed
```

## Try it without hardware

```powershell
.\venv\Scripts\python.exe scripts\simulate_session.py --n-sessions 3 --beam-cone off --drag quadratic --seed 11
# then open data\sessions\demo\campaign.html and data\sessions\demo\sim_*\report.html
```

## Reading order

1. [`CLAUDE.md`](CLAUDE.md) - the authoritative specification (conventions in section 0, layout in section 1;
   the changelogs at the top narrate how the design evolved).
2. [`IMPLEMENTATION_NOTES.md`](IMPLEMENTATION_NOTES.md) - as-built record. The top sections are the original
   build up to the synthetic acceptance gate (161 tests); Parts 2-19 bring it forward to the final state
   (242 tests). Read section C (findings ledger), Part 12 (audit remediation) and Part 15 (basketball switch).
3. [`LEGACY_ABLATION_RESULTS.md`](LEGACY_ABLATION_RESULTS.md) - legacy vs corrected, leave-one-out ablation.
4. [`config.yaml`](config.yaml) - single source of physical truth; read the provenance comments.
5. Code in pipeline order: `pipeline/geometry.py`, `simulator.py`, `corrections.py`, `trilateration.py`,
   `kalman.py`, `landing.py`, `bias.py`, `background.py`, `segmentation.py`, `process_throw.py` (the spine),
   `acquisition.py`, then `scripts/run_session.py`.
   `tests/test_end_to_end_synthetic.py` is the acceptance gate and the best single demo of how it composes.

`handoff.md` and `CHANGES.md` are working notes from the development process and are kept for provenance;
they predate the move to git and may mention "no version control".

## Data

`data/sessions/2026-07-09_T*` are the 34 live hardware throws. Each `raw_serial.log` is the verbatim serial
capture and is treated as irreplaceable (it is marked binary in `.gitattributes` so git never rewrites line
endings). `data/sessions/demo/` holds seeded synthetic sessions that can be regenerated.
`data/sessions/campaign.html` is the live campaign dashboard. Bench characterisation sessions
(flat board and ball sweeps) are also under `data/sessions/`.

## Standing rules

- Use the venv interpreter, never bare `python` or `pytest`.
- The pure modules in `pipeline/` do no file or serial I/O; the I/O layer is `process_throw.py`,
  `acquisition.py`, `reporting.py`, `web_report.py` and `scripts/`.
- Ground truth is written only through the atomic `update_session_ground_truth`.
- YAML floats need a decimal point or signed exponent (`1.0e-4`), or PyYAML reads them as strings.
