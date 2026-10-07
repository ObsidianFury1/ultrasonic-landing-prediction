# Optical Ground-Truth Landing Module

**Start here.** This is the entry-point document for anyone — human or AI — opening this
repository for the first time on a new machine. It explains what the project is, which files to
read (and in what order), how to build the virtual environment and run the tests, and exactly
which files to include when sharing the codebase as a zip.

---

## 1. What this project is (one paragraph)

A **standalone** measurement module for the Politecnico di Milano *Measurements for Mechanical
Engineering* course (A.Y. 2025-26). A single phone high-speed camera (baseline: OnePlus 12R)
films a tennis-ball throw over an ultrasonic sensor triangle; this module recovers the ball's
**landing point on the floor** — video in, `(r, theta)` out, with a per-throw uncertainty budget
— by planar-homography mapping of the tracked contact point. It is an **automation demonstrator
and independent cross-validation instrument** for the main 3-D ultrasonic landing-prediction
system; the three-tape multilateration protocol remains the metrological reference. The module
**never imports from, writes into, or modifies the main project** — the only planned coupling is
a read-only consumer of the frozen `optical_gt.json` schema.

## 2. Quick facts

| | |
|---|---|
| Authoritative spec | **`CLAUDE.md`** (a.k.a. *Optical.md*), currently **v1.4** — this file wins over everything else |
| Platform | Windows + PowerShell (paths use `pathlib`; commands shown for PowerShell) |
| Python | 3.14.x (the committed venv was built with 3.14.3) |
| Version control | **None by design** — no git. Safety net is a manual folder backup before each edit phase |
| Core dependencies | `opencv-python`, `numpy`, `matplotlib`, `pyyaml`, `pytest` (see `requirements.txt`) |
| Optional ML deps | `ultralytics==8.4.89` (+ CPU PyTorch, ~816 MB) — `requirements-ml.txt`, Phase 6a only |
| Test suite | **190 tests, all green** (`pytest`) |
| Build status | Software Phases 0-4 complete; audit remediation (WO-OPT-1/2/3) complete; **Phase 5 physical commissioning NOT yet run**; Phase 6b gated |

## 3. Read these first, in this order (for a new contributor or AI)

1. **`README.md`** (this file) — orientation, setup, repo map, packaging.
2. **`CLAUDE.md`** — the authoritative build specification. Read in full. Section numbers (`§`)
   are the citation standard used everywhere. Key sections: §2 coordinate contract, §5 pipeline
   architecture, §5.1 calibration, §5.4 parallax, §5.5 sub-frame contact, §5.6 the **frozen**
   `optical_gt.json` schema, §7 uncertainty budget, §8 the GO/NO-GO gate, §10 Zone rules for ML,
   §14 the staged work order, §16 the amendment changelog.
3. **`IMPLEMENTATION_NOTES_OPTICAL.md`** — the as-built record: what was actually built per
   phase, deviations, measured numbers, decisions (D1-D16), and the WO-OPT-1/2/3 closeouts. Read
   this to learn *why* the code looks the way it does (e.g. why the sub-frame timing is a
   kink-intersection, not a polynomial fit).
4. **`Audit_Reports/AUDIT_REPORT_2026-07-06_READONLY.md`** — the most recent independent audit;
   the findings it raised were remediated by WO-OPT-3. (`AUDIT_REPORT_PHASES_0-4.md` is the
   earlier one that drove WO-OPT-1.)
5. **`config.yaml`** — the single source of physical/tuning truth: array geometry, ball radius,
   marker survey, tolerances, HSV band, uncertainty inputs, capture modes. Read the comments.
6. **The code**, in dependency order: `optical/geometry.py` → `simulator/` →
   `optical/calibration.py` → `optical/detect.py` / `track.py` / `contact.py` /
   `uncertainty.py` → `optical/io_session.py` / `overlay.py` → `scripts/`.
7. **`CHANGES_OPTICAL.md`** — staged work-order log (currently no active order; points back to
   the implementation notes). This is where the *next* multi-stage change gets written before it
   is built.
8. **`Phase5_Commissioning_Checklist.pdf`** — the printable field datasheet for the upcoming
   physical commissioning (the [C0] phone check plus checklist items C1-C7).

## 4. Repository map

```
Optical Verification/
├─ README.md                         # <- you are here (entry point)
├─ CLAUDE.md                         # authoritative spec (Optical.md v1.4) — READ FIRST
├─ IMPLEMENTATION_NOTES_OPTICAL.md   # as-built record + decision register (D1-D16)
├─ CHANGES_OPTICAL.md                # staged work-order log (no active order)
├─ Audit_Reports/                    # independent read-only audits
│    ├─ AUDIT_REPORT_PHASES_0-4.md
│    └─ AUDIT_REPORT_2026-07-06_READONLY.md
├─ Phase5_Commissioning_Checklist.pdf# printable field datasheet for Phase 5
├─ config.yaml                       # physical/tuning truth (geometry, HSV, tolerances, budget)
├─ requirements.txt                  # core deps (Phases 0-5)
├─ requirements-ml.txt               # optional ML deps (Phase 6a only; pulls PyTorch)
│
├─ optical/                          # the pipeline package (pure logic; no I/O side effects)
│    ├─ geometry.py                  # array-frame polar<->cartesian, camera pose, parallax (§2, §5.4)
│    ├─ calibration.py               # ArUco detect, LS homography, check-point + stability guards (§5.1)
│    ├─ detect.py                    # HSV ball detector behind a swappable Detector interface (§5.2)
│    ├─ detect_ml.py                 # OPTIONAL zero-shot YOLO detector, Zone 2 only (§10, Phase 6a)
│    ├─ track.py                     # nearest-neighbour tracking + descent/reversal segmentation (§5.3)
│    ├─ contact.py                   # sub-frame first-contact solve: bracket / kink (§5.5)
│    ├─ uncertainty.py               # per-throw error budget, 5 components in quadrature (§7)
│    ├─ io_session.py                # FROZEN optical_gt.json schema: build/validate/atomic write (§5.6)
│    ├─ overlay.py                   # landing_overlay.png + terminal summary
│    └─ errors.py                    # typed errors: OpticalDataError vs OpticalConfigError
│
├─ simulator/                        # synthetic footage with EXACT known ground truth (§6)
│    ├─ render.py                    # camera model, floor homography, ball trajectory, rasteriser
│    └─ scenarios.py                 # scenario library incl. negative controls (no-ball, bad survey)
│
├─ scripts/                          # runnable CLIs (I/O orchestrators around optical/)
│    ├─ calibrate_intrinsics.py      # checkerboard intrinsics per video mode (§3.4)
│    ├─ calibrate_homography.py      # pixel->floor homography + optional --camera-measured (§5.1)
│    ├─ process_clip.py              # one throw clip -> optical_gt.json + overlay + manifest
│    ├─ validate_static.py           # the §8 static-point GO/NO-GO gate runner
│    └─ compare_detectors.py         # HSV vs YOLO ablation harness (Phase 6a, synthetic-only)
│
├─ tests/                            # pytest suite (190 tests); test_end_to_end_synthetic.py is the anchor
│
├─ calib/                            # GENERATED at commissioning: intrinsics_<mode>.yaml, homography_<id>.yaml
├─ models/                           # REGENERABLE: yolo11n.pt (auto-downloaded ML weights)
├─ data/
│    ├─ optical/<session_id>/        # per-throw: raw.mp4 (SACRED) + derived optical_gt.json, overlay
│    ├─ manifests/<date>_manifest.yaml
│    └─ comparison/                  # REGENERABLE: Phase 6a ablation outputs
└─ venv/                             # local virtual environment (DO NOT SHARE — rebuild from requirements)
```

**Sacred vs generated vs regenerable:** only `data/optical/<session_id>/raw.mp4` is **sacred**
(verbatim from the phone, never overwritten). `calib/` and `data/**` outputs are **generated**
from raw data + calibration. `venv/`, `models/`, `data/comparison/`, and all `__pycache__/` are
**regenerable** and should not be shared.

## 5. Environment setup (new machine)

All commands are PowerShell, from the project root. **Always use the venv interpreter
explicitly** — never bare `python`/`pytest` (a project rule; keeps you off any global Python).

```powershell
# 1. create the virtual environment (Python 3.11+; 3.14 is what the project used)
python -m venv venv

# 2. install the CORE dependencies (everything except the optional ML phase)
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. (OPTIONAL) install the ML deps only if you will run the Phase 6a detector comparison
#    This pulls in CPU PyTorch (~816 MB). Core phases never import it.
.\venv\Scripts\python.exe -m pip install -r requirements-ml.txt

# 4. verify: run the full test suite (expect 190 passed)
.\venv\Scripts\python.exe -m pytest tests -q
```

The core suite passes **without** the ML dependencies installed — `tests/test_ml_import_guard.py`
proves the core never imports `ultralytics`/`torch`. If ML is not installed, the ML-specific
tests skip cleanly.

## 6. Common commands

```powershell
# one-time intrinsics per video mode (needs checkerboard stills)
.\venv\Scripts\python.exe scripts\calibrate_intrinsics.py --images "calib\raw\720p480\*.png" `
    --pattern 9x6 --square-size-m 0.024 --mode 720p480

# homography calibration for a session (optionally record the tape-measured camera centre)
.\venv\Scripts\python.exe scripts\calibrate_homography.py --frame <calib_frame> `
    --calib-id 2026-07-18_A --intrinsics calib\intrinsics_720p480.yaml [--camera-measured X Y Z]

# process one throw clip  ->  optical_gt.json + landing_overlay.png + manifest entry
#   --fps-measured is MANDATORY for real footage (the C1 stopwatch-verified capture rate)
.\venv\Scripts\python.exe scripts\process_clip.py --session data\optical\2026-07-18_T03 `
    --calib calib\homography_2026-07-18_A.yaml --intrinsics calib\intrinsics_720p480.yaml `
    --mode 720p480 --fps-measured 480 --in 120 --out 180

# run the §8 static-point GO/NO-GO gate over a tree of surveyed points
.\venv\Scripts\python.exe scripts\validate_static.py --root <points_root> `
    --calib calib\homography_2026-07-18_A.yaml --intrinsics calib\intrinsics_720p480.yaml

# OPTIONAL: HSV-vs-YOLO detector ablation (needs requirements-ml.txt)
.\venv\Scripts\python.exe scripts\compare_detectors.py
```

## 7. How the pipeline works (30-second version)

`raw.mp4` → **detect** (HSV blob, `detect.py`) → **track** (nearest-neighbour + descent
segmentation, `track.py`) → **contact** (sub-frame first-touchdown: `+0.5`-frame bracket for a
vanish, kink-intersection for a bounce, `contact.py`) → **parallax-correct** the landing through
the floor homography (`geometry.py`) → **uncertainty budget** (`uncertainty.py`) →
**`optical_gt.json`** + **`landing_overlay.png`** (`io_session.py`, `overlay.py`).

Three binding rules to know before touching anything:
- **Zone rules (§10):** geometry and contact identification are **closed-form, no ML, ever**. ML
  is permitted only as a swappable ball *detector* (Zone 2), characterised like a transducer.
- **Frozen schema (§5.6):** `optical_gt.json` keys are frozen at `schema_version 1.0`. Extend
  additively (new `quality.flags`), never rename/remove. `build_optical_gt` + `validate_schema`
  enforce it.
- **Simulator-first (§6):** every path is validated against exact synthetic ground truth with
  negative controls (no-ball must not fabricate a landing; a corrupted survey must trip the
  check-point guard) before real footage is trusted.

## 8. Project status

- Phases **0-4 (software)**: complete. Full chain runs end-to-end on synthetic footage.
- **WO-OPT-1/2/3** (audit remediation + Phase 6a ML split + pre-commissioning hardening):
  complete; spec at v1.4; suite at 190 green. See `IMPLEMENTATION_NOTES_OPTICAL.md`.
- **Phase 5 (physical commissioning): NOT yet run.** Next real-world step. Use
  `Phase5_Commissioning_Checklist.pdf` — start with the **[C0] phone re-verification gate**, then
  checklist C1-C7, then the pre-registered §8 GO/NO-GO.
- **Phase 6b** (real-footage ML ablation): gated on the Phase 5 [C0] verdict and the §8 result;
  requires a new work order.

## 9. Packaging the codebase for sharing (zip)

The goal: the recipient can unzip, rebuild the venv from `requirements.txt`, and get **190
passing tests** — without carrying gigabytes of regenerable or machine-specific files.

**INCLUDE (the shareable project):**
- `README.md`, `CLAUDE.md`, `IMPLEMENTATION_NOTES_OPTICAL.md`, `CHANGES_OPTICAL.md`
- `Audit_Reports/`, `Phase5_Commissioning_Checklist.pdf`
- `config.yaml`, `requirements.txt`, `requirements-ml.txt`
- `optical/`, `simulator/`, `scripts/`, `tests/` — **but not** their `__pycache__/` subfolders
- `calib/` (structure; may be empty until commissioning)
- `data/comparison/` is optional (regenerable Phase 6a outputs) — include only to share results

**EXCLUDE (regenerable, machine-specific, or sacred/large):**
- `venv/` — **always exclude**; it is machine- and OS-specific and large. Rebuild from
  `requirements.txt` (see §5).
- every `__pycache__/` and `.pytest_cache/` — Python bytecode caches
- `models/yolo11n.pt` — ~5.4 MB, auto-downloads on first ML use; exclude unless the recipient
  has no internet
- `data/optical/**` real captured clips — `raw.mp4` files are large and are the sacred raw data;
  share these only deliberately and separately (they are currently empty — Phase 5 not run)
- `data/manifests/**` session manifests (session-specific)

**PowerShell one-liner** (zips the project excluding the heavy/regenerable paths):

```powershell
$exclude = @('venv','__pycache__','.pytest_cache','models','data\optical','data\manifests')
$staging = "$env:TEMP\optical_share"
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
robocopy . $staging /E /XD $exclude /XF *.pyc | Out-Null
Compress-Archive -Path "$staging\*" -DestinationPath ".\optical-gt-share.zip" -Force
Remove-Item $staging -Recurse -Force
```

After unzipping, the recipient runs §5 steps 1-4. The `.pyc` bytecode, the venv, and the ML
weights all regenerate; the tests confirm the transfer was clean.

## 10. Conventions & gotchas

- **Interpreter:** always `.\venv\Scripts\python.exe ...` (and `... -m pytest`), never bare
  `python`/`pytest`.
- **No git:** there is no commit history. Take a **manual folder backup of the whole project**
  before any phase that edits files.
- **Atomic writes:** every JSON/YAML output is written temp-file + `os.replace`; `raw.mp4` is
  never modified.
- **`--fps-measured` is mandatory** on real-footage `process_clip.py` runs (the container's
  reported rate may be the playback rate, not the capture rate; a gross mismatch makes the
  pipeline refuse rather than emit a garbage timing base).
- **`§` in the source** is the section-citation standard (points into `CLAUDE.md`); runtime
  console messages spell out "section N" to avoid Windows-console mojibake.
- **When in doubt, `CLAUDE.md` wins** over this README, the audit reports, and any external draft
  (e.g. the discussion-draft PDF referenced in `CLAUDE.md`).
