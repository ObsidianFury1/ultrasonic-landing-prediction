# CHANGES.md — Work Order D6: Target substitution, tennis ball → basketball

**Status:** OPEN
**Spec authority:** CLAUDE.md v2.6 (changelog "v2.5 → v2.6 (D6)") — the spec amendment PRECEDES
this work order and is already written; this order implements it.
**Approval:** Prof. Zappa approved the target change (2026-07), per the A5 escalation process.
**Trigger (measured):** §7 bench characterization — flat board PASSED at 1.0 m; tennis ball
returned persistent timeouts at 1.0 m on-axis. Root cause: felt absorption / weak specular
return at 40 kHz (the v2 top risk, materialised).
**Scope:** ULTRASONIC pipeline only. CLAUDE_OPTICAL.md is deliberately NOT touched by this
order; the optical changes (HSV band, area band, parallax budget) are a separate O-series
amendment + work order that MUST land before Phase 5 fieldwork (tracked in the v2.6 changelog).

---

## Executor ground rules (apply to every stage)

1. **Read actual file state before editing.** Do not trust line numbers, quoted snippets, or
   grep output from this document — files drift. Open and read each target file first.
2. **Windows environment.** Interpreter is `.\venv\Scripts\python.exe`; run tests as
   `.\venv\Scripts\python.exe -m pytest tests -q`. Never bare `python`/`pytest`. Paths via
   `pathlib.Path`.
3. **Stop-and-confirm at every gate.** Each stage ends with explicit pass criteria and a STOP.
   Do not advance without confirmation from Hari.
4. **Surface, never absorb.** Any judgment call discovered mid-stage (an unexpected hardcode, a
   test whose intent is ambiguous, a tolerance that no longer makes sense) is flagged and
   queued for decision — never silently resolved.
5. **Raw data is sacred.** The failed tennis-ball static sessions under `data/sessions/*_static/`
   are evidence for the report — never delete or overwrite them.
6. **Atomic writes** for any generated JSON/HTML, per the existing pipeline conventions.

---

## Stage 0 — Backup and green baseline

- Manual folder backup of the entire project directory (dated copy), per project practice
  (no git).
- Run the full suite: `.\venv\Scripts\python.exe -m pytest tests -q`. Record the passing count
  (expected ~233). If not green, STOP — do not stack this change on a broken baseline.

**Pass criteria:** backup exists; suite green; count recorded.
**STOP — confirm before Stage 1.**

---

## Stage 1 — Measure the ball; sync spec and config

1. **Physical measurement (Hari, bench):** with the tape, measure the basketball's
   circumference C (target ±2 mm); compute r = C/(2π); weigh the ball if a scale is available
   (mass m, grams). Nominal size-7 expectations for sanity: C ≈ 0.75–0.78 m, r ≈ 0.119–0.124 m,
   m ≈ 567–650 g — if the measurement falls outside these bands, re-measure before proceeding.
2. **Config:** in `config.yaml`, set `ball.radius_m` to the measured r (replace the tennis
   0.0335). Add a comment recording C, r, m, date, and "D6".
3. **Spec:** replace the project's live `CLAUDE.md` with the v2.6 amended version; then replace
   the 0.121 placeholder in the §2 `ball:` block comment and the v2.6 changelog with the
   measured value.
4. **Decision register:** append the D6 entry (decision, measured C/r/m, evidence session IDs
   of the board-pass and tennis-fail sweeps, approval note, date).

**Pass criteria:** measured r in config and spec agree to the millimetre; D6 register entry
written; no code touched yet.
**STOP — confirm before Stage 2.**

---

## Stage 2 — READ-ONLY audit: find every tennis hardcode

Search the entire codebase (`pipeline/`, `scripts/`, `tests/`, `firmware/` comments, any
report templates) for radius-coupled constants. Do not edit anything in this stage.

- Grep candidates (case-insensitive, but READ each hit in context): `0.0335`, `0.034`, `33.5`,
  `3.35`, `0.067` (diameter), `tennis`, `radius` literals inside tests, and any numeric
  tolerance in `test_corrections.py`, `test_landing.py`, `test_trilateration.py`,
  `test_end_to_end_synthetic.py` whose derivation depends on the ball radius.
- Known-from-spec items to verify specifically:
  a. **§8.2 R2 negative control** ("mean range bias ≈ 33.5 mm") — must become config-derived.
  b. **§9 R2-OFF e2e failure magnitude** ("~80 mm") — threshold must be config-derived or
     re-measured under the new radius.
  c. **§8.5 landing test** ("y = r_ball vs y = 0 shifts landing by ≈ v_h·r_ball/|v_y|") —
     check whether the ~2%-agreement tolerance was tuned at the tennis radius; the shift is
     ~3.6× larger now.
  d. Simulator defaults: confirm the simulator reads `ball.radius_m` from config everywhere
     (no local default), including `session_factory.py` in tests.
  e. `characterize_static.py --target ball`: confirm the radius it adds comes from config.
- Deliverable: a findings table (file, symbol/assert, current value, proposed change,
  risk of intent change), presented to Hari.

**Pass criteria:** findings table delivered; zero edits made.
**STOP — Hari approves the change list item-by-item before Stage 3.**

---

## Stage 3 — Implement approved test/code changes

- Apply exactly the approved Stage 2 list. Preferred pattern: derive expected magnitudes from
  the config/fixture radius at test runtime (e.g. `expected_bias = cfg["ball"]["radius_m"]`)
  rather than swapping one hardcode for another.
- Where a tolerance must widen (e.g. the §8.5 shift check), record the new derivation in a
  test-file comment referencing D6.
- Re-run the full suite. Any failure is analysed, not tuned away: distinguish (i) stale
  hardcode missed in Stage 2, (ii) genuinely radius-sensitive physics needing a re-derived
  tolerance, (iii) a real regression. Categories (ii)/(iii) are surfaced before fixing.

**Pass criteria:** suite green; every changed assertion is config-derived or carries a D6
derivation comment.
**STOP — confirm before Stage 4.**

---

## Stage 4 — Re-run the synthetic acceptance gate; re-derive drag planning numbers

1. Regenerate demo sessions (`simulate_session.py`, default demo subtree) under the new
   radius; confirm the demo campaign regenerates and landings remain within tolerance of truth.
2. Re-run the §9 end-to-end acceptance test including all negative controls. Record the NEW
   measured R2-OFF failure magnitude (expected ≳ 200 mm-class at r ≈ 0.12 m — measure, do not
   assume) and update the §9 note in CLAUDE.md with the measured figure.
3. **Drag re-estimate (analysis, no code):** with the measured m and r, recompute the expected
   along-track drag bias at 3–4 m/s (a_drag = ρ·C_d·π·r²·v²/(2m), C_d ≈ 0.47 for a smooth-ish
   sphere — flag as approximate) and compare to the tennis-derived ~8 mm figure. Update the
   §11 D3 bullet if the result materially changes the N = 15–20 (→30) campaign plan; otherwise
   record "plan unchanged" in the D6 register.
4. **Rebound note:** the main simulator has no restitution model (ball vanishes at floor); the
   D6-R1 rebound-re-entry risk therefore CANNOT be pre-verified synthetically and is verified
   on the first live sessions (Stage 5 checklist item). Recorded so nobody expects a simulator
   answer.

**Pass criteria:** acceptance gate green under the new radius; measured R2-OFF magnitude
recorded into CLAUDE.md §9; drag re-estimate written into the D6 register.
**STOP — confirm before Stage 5 (hardware).**

---

## Stage 5 — Hardware re-characterization with the basketball (bench)

Prerequisites: S3 replacement installed and Sketch 01–05 gates green; the open ~3.6% bias
investigation (suspected ambient-temperature input) should be closed FIRST or in the same
session — pass the verified `--temperature-c` to every run below, and record the thermometer
reading in each session's notes.

1. Board sweep: already PASSED at 1.0 m — repeat only if wiring changed since (S3 swap ⇒ yes,
   repeat for S3 at minimum).
2. Basketball sweep, per §7: on a stand at ≈ 1.0 / 1.3 / 1.7 m, on-axis, ≥ 200 readings per
   sensor per position (`characterize_static.py --target ball`). Then the off-axis angle sweep
   (several `--angle-deg` values) at ≈ 1.3 m.
3. `analyze_static.py` over the full set → adopt the recommended `kalman.sigma_pos_m` and
   `simulator.beam_half_angle_deg` into config **together, from the same data** (per the
   orientation guide's rule); update the CLAUDE.md comments to mark them MEASURED, with the
   session IDs.
4. Record timeout fractions vs range and angle in the D6 register — this is the quantitative
   closure of the detectability risk and prime report material (felt vs shell comparison plot:
   the failed tennis sessions from the evidence folder vs the new basketball sessions).
5. First live throw sessions: explicitly inspect segmentation boundaries against the rebound
   (D6-R1). If post-contact triplets contaminate any throw buffer, STOP and open a new work
   order for a segmentation rule — do not tune `close_K` silently.

**Pass criteria:** basketball detectable at all three ranges with low timeout fraction
(quantified, not asserted); sigma_pos_m and beam_half_angle_deg measured and adopted; D6-R1
checked on live data.
**STOP — confirm before close-out.**

---

## Stage 6 — Documentation close-out

- Append the full as-built record to IMPLEMENTATION_NOTES.md (stages, measured values, test
  count, deviations if any).
- Mark this work order CLOSED in CHANGES.md with date and final test count.
- Open items intentionally left OUT of this order (verify they are tracked elsewhere):
  1. **O-series optical amendment** (HSV orange band, area band upper limit, parallax
     uncertainty component scaling with r_ball) — REQUIRED before Phase 5 fieldwork.
  2. Arduino Uno → Nano Every documentation amendment in CLAUDE.md §2/§3.
  3. G1 web-reporting follow-through (pre-existing, unrelated).

**Pass criteria:** IMPLEMENTATION_NOTES appended; work order closed; the three open items
confirmed tracked.
