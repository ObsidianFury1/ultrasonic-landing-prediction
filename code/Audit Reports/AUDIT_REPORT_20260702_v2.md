# Codebase Audit — 2026-07-02 (v2: re-audit, post-remediation)

Second read-only audit per `audit_prompt.md`, run **after** the CHANGES.md audit-remediation work
order (Stages 1–7) completed. Baseline documents: CLAUDE.md v2.5 (as amended by Stages 1/7),
IMPLEMENTATION_NOTES.md Parts 1–12, CHANGES.md (audit-remediation order).

**Filename deviation, noted per the prompt's own rule:** the mandated name
`AUDIT_REPORT_20260702.md` is occupied by the *first* audit (the source document of the remediation;
during this re-audit it was briefly on disk as `AUDIT_REPORT_20260701.md` and has been restored).
Overwriting it would destroy the record the whole of IMPLEMENTATION_NOTES PART 12 traces to, and the
prompt forbids modifying existing files — so this report takes the `_v2` suffix. Nothing was
modified in this audit; this file is the only artifact.

## Summary

The remediation held: the suite measures **232 passed / 0 failed** (matching PART 12's claim), all
four prior Major findings (M-1–M-4) are verifiably fixed **in code, not just in the docs**, the
actionable Minors are closed, and the spec drift from the first audit is gone (zero `TO BUILD`, zero
`(FUTURE)`, one §12 + one §13, G1/D5 recorded as built). The re-audit's fresh surface was the seven
stages of new code, and it found **one genuine new defect introduced by Stage 5** (N-1: a
re-processed session that now fails the fit is left in a mixed stale-prediction / new-gate-summary
state that renders as a valid page instead of a failure page) plus two documentation-freshness
items. **Nothing blocks hardware bring-up or campaign data collection**; N-1 should be fixed before
any campaign-era *re*processing (config retuning, negative controls, bias-model re-runs), which is
exactly when it can bite.

## Remediation verification (prior findings, checked in code — not from the docs)

| Prior finding | Status | Evidence |
|---|---|---|
| M-1 terminal GT write non-atomic | **FIXED** | [run_session.py:376](scripts/run_session.py) calls `update_session_ground_truth`; grep shows all four GT write sites (terminal, web POST, append, demo tool) use the atomic writer; no `_write_json` ground-truth bypass remains; two mirror tests in `test_run_session.py` (no temp residue; injected failure preserves the original byte-for-byte). |
| M-2 stale spec (G1/D5 "TO BUILD") | **FIXED** | Zero `TO BUILD` / `(FUTURE)` in CLAUDE.md; §12.4 + changelog record the G1 migration as complete; the duplicate §12 resolved (§13 disposition record, 6 refs updated); §1 tree completed (but see Minor-2 below — it drifted again by one file). |
| M-3 terminal mode renders nothing | **FIXED** | `run_default` and `append_ground_truth.append_to_session` call `render_session_report` + `render_campaign_report`; asserted by `test_terminal_gt_write_atomic_no_residue` and `test_terminal_append_renders_report_and_campaign`. |
| M-4 failure-path traceback / empty §12.1 panel | **FIXED for fresh sessions (N-1 caveat for reprocessed ones)** | `_capture_default` catches `ValueError` and prints a clean "no prediction: …"; `_render_failure` renders the failure report + campaign in both flows; `process_session` persists `triplets_raw.csv` + the gate summary **before** the fit stage ([process_throw.py:241-263](pipeline/process_throw.py)); `test_run_default_failure_path_preserves_evidence_and_renders` covers all four audit criteria; the e2e module (15 tests) unaffected by the write reordering. |
| Minor-5 overwrite guard | **FIXED** | `capture_session` raises `RuntimeError` on an existing `raw_serial.log`; test asserts refusal + unchanged bytes. |
| Minor-12 / -9 / -10 / -7 / -8 / -16 | **FIXED** | `valid = guard_ok & isfinite(sigma_y)` + zero-radicand test (integer circumcenter geometry); alpha-derived confidence text + `alpha=0.10 → "90%"` test; dead `0.0335` JS fallback removed (template grep clean); background/acquisition docstring notes present; sketch-05 timestamp comment corrected, logic untouched. |
| Minor-1 / -2 / -3 (Stage-7 decisions) | **FIXED as decided** | No `drag_mult`/`drag-mult` anywhere in `pipeline/` or `scripts/` and §6 states the multiplier is test-only; `simulate_session.py` processes by default (`--no-plot` opt-out; the three D5 tests green with the new default); no `web:` config block anywhere, §2/§12.3 document the hardcoded loopback bind as intentional. |
| Minor-3 (doc) / -4 / -13 / -14 | **FIXED** (with -4 regressing to stale — see Minor-1 below) | config.yaml header v2.5; IMPLEMENTATION_NOTES header v2.5, Part 9 renumbered `P9-A…I` with cross-refs remapped; handoff.md was rewritten in Stage 1 but froze mid-work-order. |

## Critical (logic is wrong / would silently corrupt results)

**None found.**

## Major (spec-vs-code drift, boundary violations, weak tests)

### N-1. Re-processing a previously-successful session that now fails leaves a stale-but-rendering hybrid state (introduced by Stage 5)
- **Where:** [pipeline/process_throw.py:169-171](pipeline/process_throw.py) (meta loaded from the
  existing `session.json`) + [process_throw.py:259-263](pipeline/process_throw.py) (the Stage-5
  partial write). The partial write persists the **new** `gate_summary`/`processing_warnings` into
  the loaded dict — but if the session was processed before, that dict still carries the **old**
  `prediction` and `small_sample_caveat`, and the old `trajectory.csv` remains on disk. If the fit
  stage then raises (a `min_fit_points`/`sigma_pos_m` retune, a stricter stencil, a negative
  control), the on-disk result is: new gate summary + stale prediction + stale trajectory.
- **Why it matters:** `web_report.build_session_data` selects the page state from
  `has_landing and traj_arrays` — this failed session renders as **input/frozen with the stale
  prediction**, not as "failure", and `calibrate_bias.load_record` would likewise ingest the stale
  prediction as current. Pre-Stage-5, a failed reprocess wrote nothing, leaving the old file stale
  but *internally consistent*; the new behaviour produces a silently inconsistent hybrid.
  First-time processing is unaffected (no prior keys to leak) — which is exactly why all 232 tests
  pass: no test reprocesses a previously-successful session into a failure.
- **Fix direction:** at the partial write, drop the stale derived keys
  (`meta.pop("prediction", None); meta.pop("small_sample_caveat", None)`) and remove a pre-existing
  `trajectory.csv` before the fit stage. Raw-data-sacred protects `raw_serial.log`, not derived
  artifacts, which `process_session` already overwrites by design on success. Add the missing test:
  process a session successfully, re-process it with `min_fit_points` forced high, assert
  `prediction` is absent from `session.json` and the rendered state is `"failure"`.

## Minor (style, dead code, missing docs)

1. **`handoff.md` froze mid-work-order** ([handoff.md:39-44](handoff.md), [:110](handoff.md),
   [:157](handoff.md)): rewritten during Stage 1, it still says Stages 2–7 are PENDING, that
   "M-1/M-3/M-4 remain live in the code" (all fixed), and its "exact next action" is "Continue at
   Stage 2". Its 225-test figure predates the +7. A post-completion refresh (or a one-line
   "superseded by PART 12" banner) restores it as a trustworthy entry point.
2. **CLAUDE.md §1 tree is one file behind again:** `tests/test_run_session.py` (created in Stage 2,
   *after* the Stage-1 tree pass) is missing from the layout. Same class of drift Stage 1 fixed;
   one-line addition. (The `AUDIT_REPORT_*.md` files are also unlisted; report artifacts arguably
   don't belong in the layout, so only the test file is flagged.)
3. **PART 12 has no record of the intra-order tree drift** — cosmetic: §P12-B introduced
   `test_run_session.py` but nothing notes that the §1 tree (completed one stage earlier) doesn't
   list it. Folding the fix for item 2 into a PART 12 postscript closes both.

## Confirmed-fine (re-checked fresh this audit)

1. **I/O purity:** grep of the 9 pure computational modules — zero file/serial I/O hits. The two
   remediation touches to pure modules (`trilateration.py` guard condition, `background.py`
   docstring) added no I/O, matching the work-order sanction; the other seven pure modules are
   byte-untouched by the remediation.
2. **Single source of physical truth:** no hardcoded physical constants outside
   config/`corrections.py`; the last stray (the session template's `0.0335` JS fallback) is gone.
3. **Raw-data-sacred:** `raw_serial.log` written only into fresh directories, now with an explicit
   refusal guard in `capture_session`; read-only in `process_session`; gating still flags-only.
4. **Ground-truth writes:** all four call sites (`run_session.py:376`, `serve_report.py:122`,
   `append_ground_truth.py:78`, `demo_web_reports.py:78`) route through the atomic
   `update_session_ground_truth`; no new bypass appeared anywhere.
5. **Vacuous `q` flag (C-2):** still computed and stored in `trajectory.csv` only; grep confirms no
   consumer treats it as a quality signal.
6. **Hybrid stencil (D1), Kalman variable-dt, landing covariance, multilateration (G1):** modules
   untouched by the remediation (verified); the prior audit's line-level verification stands.
7. **Drag test knob (C-3–C-5):** no `drag_mult` in any code path; the ×3/×5 multipliers remain
   confined to `test_bias.py`/`test_end_to_end_synthetic.py`; §6 now states this — code and spec
   agree for the first time.
8. **D5/G1 on disk:** demo subtree + dual campaigns intact (`data/sessions/campaign.html` +
   `demo/campaign.html` + 12 `sim_*` dirs); the `is_session_dir` predicate in all three enumerators;
   the byte-equality GT test still present and green.
9. **Test suite:** **232 passed / 0 failed** measured fresh (matches IMPLEMENTATION_NOTES PART 12;
   the first audit's 225 + 7 remediation tests). The 7 new tests were reviewed for weakness: none
   tautological — each asserts the specific behaviour its stage introduced (refusal + unchanged
   bytes; no `.session-*` residue; injected-failure preservation; render side-effects; the four
   M-4 failure-path criteria; zero-radicand invalidation; alpha-derived note text).
10. **Firmware:** only the sketch-05 timestamp comment changed (verified); pin map, 12500 µs
    timeout, absolute scheduler, CSV protocol, 115200 baud all unchanged and consistent with the
    Python-side assumptions. The standing "never toolchain-compiled" caveat (Part 3 S-1) remains
    open pending hardware.
11. **`simulate_session.py` default-processing flip (Stage 7 / Minor-2):** the three D5 tests pass
    under the new default; undetectable throws still skip gracefully; demo-campaign auto-regen
    unchanged; `--no-plot` restores raw+truth-only generation.

---

*Scope note: this re-audit performed line-level review of the code changed by the remediation
(Stages 2–7 diffs in `process_throw.py`, `run_session.py`, `append_ground_truth.py`,
`simulate_session.py`, `trilateration.py`, `analyze_campaign.py`, the template, and the new/updated
tests) plus fresh grep/pytest re-verification of every risk-list item in `audit_prompt.md`. Modules
unchanged since the first audit carry over that audit's line-level verification
(`AUDIT_REPORT_20260702.md`, the v1 report). No handoff needed — the audit is complete.*
