# 3D Ultrasonic Projectile Landing-Prediction System

Politecnico di Milano — Measurements for Mechanical Engineering, A.Y. 2025–26.

Three HC-SR04 ultrasonic sensors at the vertices of an equilateral triangle (side 1.0 m) range a
basketball thrown over the array by sequential pings. Python reconstructs the trajectory
(trilateration → Kalman filter → parabola fit → floor extrapolation), predicts the landing point in
polar coordinates (r, θ) with per-throw uncertainty, and reports it on a self-contained HTML page
where the surveyed ground truth is entered. An offline bias model calibrates the drag systematic
across a campaign of throws.

**This README is the entry point for a new machine or a new Claude session.** It covers (1) setting
up the environment, (2) the reading order to understand the project, and (3) exactly what to include
when sharing the codebase as a zip.

---

## 1. Environment setup (new device)

Requirements: **Windows** (the documented commands are PowerShell-style; the code itself is
portable), **Python ≥ 3.10**, no other toolchain (the Arduino IDE is needed only at the hardware
bench — see `BENCH_PROCEDURE_v2.pdf`).

From the project root:

```powershell
# 1. Create the virtual environment. The directory MUST be named `venv` —
#    every documented command in this repo invokes .\venv\Scripts\python.exe.
#    (requirements.txt's header suggests `.venv`; the repo convention is `venv`.)
python -m venv venv

# 2. Install the dependencies (numpy, scipy, pandas, matplotlib, filterpy,
#    pyserial, PyYAML, pytest).
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Verify the install by running the full test suite:
.\venv\Scripts\python.exe -m pytest tests -q
```

**Expected: `242 passed` (0 failed, 0 skipped), ~30–60 s.** If the count differs, the tree you
received is incomplete or was modified — reconcile against `handoff.md` §3 before doing anything
else.

### Standing rules (bind every session — full list in CLAUDE.md §0 and handoff.md)

- **Always use the venv interpreter**: `.\venv\Scripts\python.exe …` / `.\venv\Scripts\pytest.exe`.
  Never bare `python` or `pytest`.
- **There is no git.** The working tree is the only copy. Raw session data
  (`data/sessions/**/raw_serial.log`) is sacred — never delete or overwrite it.
- The pure computational modules in `pipeline/` (`geometry, corrections, trilateration, kalman,
  landing, bias, background, segmentation, simulator`) do **no file or serial I/O**. The I/O layer
  is `process_throw.py`, `acquisition.py`, `reporting.py`, `web_report.py`, and `scripts/`.
- Ground truth is written **only** via the atomic `update_session_ground_truth`.
- Generated HTML stays fully self-contained (no CDN, no external fetch); Python console output
  stays ASCII (Windows cp1252).
- Synthetic data note: pass `--beam-cone off` when generating synthetic sessions, or
  campaign-speed throws yield zero detections at the current cone angle. `kalman.sigma_pos_m` and
  the per-sensor electronic offsets are measured from hardware (see §4 below).

---

## 2. Reading order (how to understand this codebase)

Read in this order — each document declares its own authority:

| # | File | What it is |
|---|------|------------|
| 1 | `README.md` | This file — setup, orientation, sharing manifest. |
| 2 | **`CLAUDE.md`** | **The authoritative build specification** (v2.7). Where it conflicts with anything else (including the proposal PDF), CLAUDE.md wins. §0 conventions and §1 repository layout first; the changelogs at the top narrate how the spec evolved (v1→v2.7, decisions D1–D6, G1) — v2.6 is the tennis→basketball target substitution (D6); v2.7 folds in the Nano Every rename, the per-sensor offset correction, `--no-background`, and closes the D6-R1 risk. |
| 3 | `IMPLEMENTATION_NOTES.md` | The as-built record, **Parts 1–17**: every deviation from spec, every finding (the §C ledger: vacuous `q` flag, curvature systematics, power analysis), the audit-remediation record (Part 12), the D6 basketball substitution (Part 15), and the two post-D6 acquisition features — per-sensor offset correction (Part 16) and `--no-background` (Part 17), both now also folded into CLAUDE.md's own v2.7 changelog. Read Part 12, Part 15, and §C at minimum. |
| 4 | `handoff.md` | The **current state**: what is done, what is pending, test count, open placeholders, next action. Verify its claims with live commands before trusting. |
| 5 | `CHANGES.md` | Empty placeholder — the D6 work order that lived here is CLOSED and its record absorbed into CLAUDE.md's v2.6 → v2.7 changelog. Paste the next work order here when one exists. |
| 6 | `BENCH_PROCEDURE_v2.pdf` | The hardware bring-up data sheet. Supersedes `BENCH_PROCEDURE.pdf` (kept for record; its Phase-5 command and ground-truth prompt description predate the current code). |
| 7 | `config.yaml` | Single source of physical truth. `kalman.sigma_pos_m` and the per-sensor electronic offsets are now MEASURED (see comments for provenance). Watch the two YAML float-parsing traps (`1.0e-4`, `1.0e+4` — keep the point/sign). |

Then code, in pipeline order: `pipeline/geometry.py` → `simulator.py` → `corrections.py` →
`trilateration.py` → `kalman.py` → `landing.py` → `bias.py` → `background.py` → `segmentation.py` →
`process_throw.py` (the offline orchestrator — the spine of the system) → `acquisition.py` →
`scripts/run_session.py` → `pipeline/web_report.py` + `scripts/serve_report.py` (HTML layer).
`tests/test_end_to_end_synthetic.py` is the acceptance gate (spec §9) and the best single
demonstration of how everything composes.

### Try it without hardware

```powershell
# Generate + process 3 synthetic throws (demo subtree; processing is the default):
.\venv\Scripts\python.exe scripts\simulate_session.py --n-sessions 3 --beam-cone off --drag quadratic --seed 11

# Then open in a browser:
#   data\sessions\demo\campaign.html          (campaign dashboard)
#   data\sessions\demo\sim_*\report.html      (per-throw pages)
```

---

## 3. Sharing the codebase (zip manifest)

There is **no version control** — a shared zip is a full backup, so completeness matters.

**MUST include (the project is broken or lossy without these):**

```
README.md  CLAUDE.md  CHANGES.md  IMPLEMENTATION_NOTES.md  handoff.md
BENCH_PROCEDURE_v2.pdf
config.yaml  requirements.txt
pipeline/**        (all .py + web_assets/*.html — the two HTML templates are load-bearing)
scripts/**         (all .py)
tests/**           (all .py — includes session_factory.py, a shared helper, not just tests)
firmware/**        (all five .ino sketches)
Audit Reports/**   (includes all the audit reports)
data/sessions/**   (see the data rule below)
correction_model.json + correction_model_report.json   (IF present at root — the fitted bias model)
```

**Data rule:** any **live (hardware) session** under `data/sessions/<id>/` is irreplaceable raw
campaign data — its `raw_serial.log` cannot be regenerated. **Always include the whole
`data/sessions/` tree once real throws exist.** The `data/sessions/demo/` subtree is seeded and
reproducible (regenerate with `simulate_session.py --seed …`), so it *may* be dropped to shrink the
zip — but include it by default; it is small and lets the recipient open working reports
immediately.

**EXCLUDE (recreated locally, never share):**

```
venv/                    (recreate via section 1 — large and machine-specific)
**/__pycache__/          (Python bytecode cache)
.claude/, *.tmp, .session-*.tmp
```

**Recipient checklist:** unzip → section 1 setup → `pytest` shows **242 passed** → read order in
section 2. Hardware is already in hand and bench-gated (see §4); `BENCH_PROCEDURE_v2.pdf` is the
checklist if re-running any bench phase.

---

## 4. Project status at a glance

- **Software: feature-complete and green** (242 tests) through CLAUDE.md §10 items 1–18, including
  the HTML reporting layer (W1), the multilateration ground-truth protocol (G1), demo/live storage
  separation (D5), the full audit-remediation work order (IMPLEMENTATION_NOTES Part 12), and the D6
  target substitution to a basketball (Part 15).
- **Hardware: firmware flashed and bench-gated** (every `raw_serial.log` on disk carries the
  `# fw=05,...` header) and the **live throw campaign is complete**: 34 ground-truthed live
  sessions under `data/sessions/2026-07-09_T*`, all with prediction + ground truth entered. The
  offline bias model (`correction_model.json`, n=31) found a **significant** along-track
  systematic (67.5 mm, 95% CI [45.7, 89.4] mm excludes zero; validation error improved
  90 → 56 mm, p ≈ 0.0001) and `campaign_report/*.png` / `data/sessions/campaign.html` reflect it.
- **Still open, project-wide:** only the **O-series optical amendment** (CLAUDE_OPTICAL.md — HSV
  band, area band, parallax budget), deliberately deferred and required before Phase 5 fieldwork.
  Tracked in CLAUDE.md's own changelog, not in a separate work-order file.
