# handoff.md — session handoff for the 3D Ultrasonic Projectile Landing-Prediction System

**Written:** 2026-07-02; refreshed 2026-07-03 (audit remediation); refreshed 2026-07-09 (D6
target substitution, hardware bench work, live 34-throw campaign); **refreshed again 2026-07-09**
after CLAUDE.md v2.7 (Nano Every doc, acquisition-layer offset correction + `--no-background`
folded into the spec, D6-R1 closed) and the CHANGES.md D6 work order closing out. This supersedes
all earlier handoffs. There is no `handoff2.md`.

**Every claim below was verified against the working tree at write time** (`pytest -q`, `ls`,
`grep`, file reads). Re-verify before trusting. **There is no git** — `git status` returns
`fatal: not a git repository`, so there is no diff to paste; working-tree state is reported
directly.

---

## 1. Snapshot

3D ultrasonic projectile landing-prediction system (Politecnico di Milano, Measurements for
Mechanical Engineering, A.Y. 2025–26): three HC-SR04 sensors on an equilateral triangle, driven by
an **Arduino Nano Every**, range a thrown **basketball** (D6 — the original tennis ball failed §7
detectability and was replaced with Prof. Zappa's approval) by sequential pings; Python
reconstructs the trajectory (trilateration → Kalman → parabola fit → floor extrapolation),
predicts the landing in polar (r, θ) with per-throw σ, and reports it on a browser page where
ground truth is entered. An offline bias model calibrates the drag systematic across the campaign.

**Spec version:** `CLAUDE.md` = **v2.7** (adds: Nano Every documentation, the per-sensor
electronic-offset correction, `--no-background`, and closes the D6-R1 risk-register entry — see
its own changelog for detail). `IMPLEMENTATION_NOTES.md` is the as-built reconciliation record,
**Parts 1–17**. `CLAUDE.md` wins over the proposal PDF, `config.yaml`, and every other document.

**The entire §10 build order is complete, including every hardware-gated item**, and the project
has a completed, statistically significant live campaign result. There is exactly **one
deliberately open item left project-wide: the O-series optical amendment** (see §5).

---

## 2. Exact current position

- **Two prior audits** (`AUDIT_REPORT_20260702.md`, `AUDIT_REPORT_20260702_v2.md`) were run and
  fully remediated. No open audit finding.
- **D6 target substitution** (tennis → basketball) is documented end-to-end in
  IMPLEMENTATION_NOTES **Part 15**.
- **The live campaign happened and is complete**: 34 sessions on 2026-07-09
  (`data/sessions/2026-07-09_T*`), every one with both a prediction and an entered ground truth.
  `calibrate_bias.py` ran over 31 of them and found a **significant** along-track bias: 67.5 mm,
  95% CI [45.7, 89.4] mm (excludes zero), validation error improved 90.2 → 56.1 mm (p ≈ 0.0001).
  `correction_model.json` / `correction_model_report.json` hold the fitted model;
  `campaign_report/*.png` and `data/sessions/campaign.html` (N=34) hold the campaign dashboard.
- **CLAUDE.md v2.7 closes out every documentation gap found in the prior audit pass**: the
  Arduino Uno → Nano Every rename (board name only, wiring/pins/firmware unchanged), the
  per-sensor electronic-offset correction (`acquisition.sensor_offset_m`, Part 16) and
  `--no-background` (Part 17) now have proper spec entries (§2, §5.1, §5.3, §5.7), and the D6-R1
  rebound-re-entry risk-register bullet is **removed** — checked against the full 34-throw live
  campaign, no post-contact contamination was observed.
- **CHANGES.md (the D6 work order) is closed and wiped** — see §4. CLAUDE.md's v2.6 → v2.7
  changelog is now the record of what D6-adjacent work happened after the original D6 order.
- **No known open bug and no known open documentation gap**, other than the deliberately deferred
  optical amendment (§5).

---

## 3. Test status

Reran now: `.\venv\Scripts\python.exe -m pytest tests -q` →

```
242 passed in ~55s     (0 failed, 0 error, 0 skipped)
```

No code changed in this pass (docs/config-comments/schema only); the count is unchanged from the
prior handoff.

---

## 4. Config / spec notes

- `config.yaml` header now reads "(v2.7)", matching CLAUDE.md. Content: `ball.radius_m = 0.1194`
  (measured), per-sensor `acquisition.sensor_offset_m` (measured, Phase 4A/4D),
  `kalman.sigma_pos_m = 0.010` (measured, Phase 4B — see IMPLEMENTATION_NOTES Part 14 for the
  S3-alignment caveat).
- `cond_warn` and `q_scale` must keep a decimal point / signed exponent in YAML (PyYAML 1.1 parses
  bare `1e4` / `1.0e4` as a **string**). config.yaml uses `1.0e-4` and `1.0e+4`; keep them that way
  on any regeneration.
- `CHANGES.md` has been wiped down to a placeholder — it held the D6 work order, which is now
  closed and fully absorbed into CLAUDE.md's v2.6 → v2.7 changelog. The next work order pasted
  into that file should follow the same stage-gated format the D6 order used (still visible in
  IMPLEMENTATION_NOTES Part 15 as a worked example, if a template is needed).
- The derived `ground_truth` keys (`r_m/theta_deg/x_m/z_m/sigma_x_m/sigma_z_m`) are the contract
  `calibrate_bias.load_record` / reporting / the campaign page depend on; unchanged since G1.

---

## 5. Open issues / known placeholders

- **O-series optical amendment (CLAUDE_OPTICAL.md) — the only open item.** Deliberately deferred
  per CLAUDE.md's v2.5 → v2.6 changelog, and required before Phase 5 fieldwork. Covers: the HSV
  detection band (tennis yellow-green → basketball orange), the detector area band, and the
  parallax-uncertainty component (scales with `ball.radius_m`; grows ~3.6× vs the tennis-derived
  15 mm gate). Out of scope for the ultrasonic module this repo implements; tracked in CLAUDE.md
  itself now, not in a separate CHANGES.md work order.
- `simulator.beam_half_angle_deg` remains at its original estimate (7.0°) — by decision, this is
  not being pursued further; it affects synthetic/demo triplet-count realism only, not the live
  hardware pipeline or the completed campaign.
- All audit findings (first audit M-1–M-4 + Minors, re-audit N-1) remain CLOSED.

---

## 6. Data on disk

- `data/sessions/campaign.html` — the **live** campaign, N=34, reflects the calibrated bias model.
- `data/sessions/2026-07-09_T*` — 34 live throw sessions, each with `raw_serial.log`,
  `background.json`, `triplets_raw.csv`, `trajectory.csv`, `session.json` (prediction + ground
  truth), `plots/`, `report.html`.
- `data/sessions/{S1,S2,S3}_{1,1.3,1.7}/`, `data/sessions/Flat-Board/` — static characterization
  sessions (Phase 4A/4B/4D bench data) underlying the measured `sensor_offset_m` and
  `sigma_pos_m`.
- `correction_model.json` / `correction_model_report.json` — the fitted bias model (n=31,
  significant along-track offset).
- `campaign_report/*.png` — campaign-level analysis plots from `analyze_campaign.py`.
- `data/sessions/demo/` — synthetic sessions + their own `campaign.html`; seeded/reproducible, safe
  to regenerate; never mixed with the live campaign (enforced by `is_session_dir`, not naming).

---

## 7. Exact next action

There is no pending software or documentation task on the ultrasonic module. What remains:

1. **Optical (O-series):** if/when Phase 5 fieldwork is planned, write the O-series amendment
   (HSV band, area band, parallax budget) and its own work order before touching
   `CLAUDE_OPTICAL.md` code.
2. **Report:** the campaign data (34 throws, significant 67.5 mm along-track bias) is ready to
   write up — this is the actual deliverable-facing outcome of the project at this point.

---

## 8. Environment reminders (Windows / PowerShell)

- **OS:** Windows 11. **Shell:** PowerShell primary; a Bash tool is also available (POSIX syntax).
  NOT a git repository.
- **Python — ALWAYS the venv interpreter, never bare `python`/`pytest`:**
  - Suite: `.\venv\Scripts\python.exe -m pytest tests -q`
  - One file: `.\venv\Scripts\python.exe -m pytest tests\test_geometry.py -q`
  - A script: `.\venv\Scripts\python.exe scripts\serve_report.py --pending`
- **View the HTML reports:** `data\sessions\campaign.html` (live, N=34) and any
  `data\sessions\2026-07-09_T*\report.html` are already rendered and frozen (ground truth entered).
  For synthetic data: process a synthetic session, then call
  `pipeline.web_report.render_session_report(session_dir, config)` /
  `render_campaign_report(sessions_root, config)`; or `scripts\demo_web_reports.py` for a full
  generate→render demo. Generate synthetic data with `--beam-cone off` for realistic triplet
  counts.
- **Guardrails still binding:** don't add I/O to the pure computational `pipeline/` modules
  (`corrections, trilateration, kalman, landing, bias, segmentation, background, simulator`;
  `geometry` was the sanctioned G1 exception); ground truth is written only via the atomic
  `update_session_ground_truth`; generated HTML stays self-contained (no CDN/external fetch);
  Python console output stays ASCII-only.
