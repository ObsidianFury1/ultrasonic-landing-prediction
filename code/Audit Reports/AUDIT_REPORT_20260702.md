# Codebase Audit — 2026-07-02

Read-only audit per `audit_prompt.md`. Spec baseline: **CLAUDE.md v2.5**;
as-built record: **IMPLEMENTATION_NOTES.md Parts 1–11**; work-order log: **CHANGES.md (D5)**.
Every claim below was verified against the actual working tree on this date; nothing was modified.

## Summary

The codebase is in good health. The full test suite runs **225 passed / 0 failed** (measured, not
quoted — matches IMPLEMENTATION_NOTES Part 11 exactly; the stale `handoff.md` figure of 217 predates
Parts 10–11). No critical logic defect was found in the computational pipeline: the trilateration,
hybrid-stencil, Kalman, landing-covariance, and multilateration math were each re-derived and check
out. The dominant theme is **documentation lagging code in the direction of the code being ahead**:
G1 and D5 are fully built but CLAUDE.md v2.5 still marks them "TO BUILD", and `handoff.md`
contradicts the tree in several places. Four Major findings are recorded — one robustness hole in the
terminal ground-truth write path, and three spec-vs-code drifts around report rendering and the live
failure path. **Nothing found blocks hardware bring-up or campaign data collection**, but Major-1
(non-atomic terminal GT write) and Major-4 (uncaught failure-path traceback) should be fixed before
the real campaign, since both bite exactly during live operation.

## Critical (logic is wrong / would silently corrupt results)

**None found.** Specifically, every "would silently corrupt results" risk named in the audit prompt
was checked and came back clean — see Confirmed-fine.

## Major (spec-vs-code drift, boundary violations, weak tests)

### M-1. Terminal ground-truth write bypasses the atomic writer
- **Where:** [scripts/run_session.py:336-340](scripts/run_session.py) (`run_default`).
- **What:** after `prompt_ground_truth`, the block is persisted via `_write_json` — a plain
  truncate-and-rewrite of the whole `session.json`. The web POST
  ([scripts/serve_report.py:122](scripts/serve_report.py)) and
  `append_ground_truth.py` both go through the atomic
  `update_session_ground_truth` (temp file + fsync + `os.replace`,
  [scripts/append_ground_truth.py:32-56](scripts/append_ground_truth.py)); the terminal path is the
  one GT writer that does not.
- **Why it matters:** CLAUDE.md §12.0/§12.3 establish "ground truth is written only via the atomic
  `update_session_ground_truth`" as a guardrail (repeated in handoff.md §8). A crash/power loss
  mid-write in the terminal path leaves a truncated `session.json` — the prediction is lost and the
  session must be reprocessed from `raw_serial.log` and the tapes re-entered. Low probability, but
  it is precisely the live-campaign path.
- **Fix direction:** replace the three lines with a call to
  `append_ground_truth.update_session_ground_truth(session_dir / "session.json", gt)` (already
  imported by `serve_report.py`; no new machinery needed). A test asserting the terminal path leaves
  no `.session-*.tmp` residue and survives an injected dump failure would close the gap
  (`test_serve_report.py` already has the pattern for the web path).

### M-2. CLAUDE.md v2.5 marks G1 (§10 item 17) and D5 (item 18) "TO BUILD" — both are fully built
- **Where (spec):** CLAUDE.md §10 items 17–18, §12.4 "Migration note (G1-status)", changelog v2.3
  "(G1 … NOT yet built)"; also [CHANGES.md:4](CHANGES.md) ("Status: TO BUILD").
- **What (code, verified):**
  - G1: `geometry.ground_truth_landing` is the LS multilateration solve
    ([pipeline/geometry.py:145-220](pipeline/geometry.py)) with Gauss–Newton refinement, LS residual,
    and condition-number *flag* (never raises); `recommend_reference_sensors` exists
    ([geometry.py:129](pipeline/geometry.py)); `two_circle_intersection` is gone (only a retirement
    comment remains at [geometry.py:116](pipeline/geometry.py)). All four consumer paths — terminal
    prompt, `append_ground_truth.py`, the server POST body
    `{session_id, L_centroid, sensors, L_a, L_b}`, and the web panel's `sensors`/`recommended`
    `__DATA__` keys — run through the shared `run_session.solve_ground_truth`, and
    `test_web_block_equals_terminal_and_append` proves the blocks identical.
  - D5: `data/sessions/demo/` exists on disk with 12 `sim_*` sessions and its own `campaign.html`;
    the live root holds its own `campaign.html`; `is_session_dir` is defined once
    ([pipeline/web_report.py:51](pipeline/web_report.py)) and routed through all three enumeration
    sites (`build_campaign_data`, `analyze_campaign.load_campaign`, the `calibrate_bias` loader);
    `sessions.demo_subdir` is in config.
- **Why it matters:** the spec is declared authoritative ("this file wins"). A future contributor
  following §10 item 17 would re-migrate an already-migrated ground-truth path, or "fix" the web
  panel back toward the two-tape input §12.4 claims is still as-built. This is the exact stale-doc
  trap the G1-status paragraph was written to prevent — it now points the wrong way.
- **Fix direction:** doc-only. Mark items 17–18 BUILT (pointing at IMPLEMENTATION_NOTES Parts 9–10),
  delete/rewrite the §12.4 migration-gap paragraph, and update CHANGES.md's status line. The same
  pass should clear the stale "(FUTURE)" annotations in the §1 tree (`acquisition.py`,
  `run_session.py`, `verify_timing.py`, `characterize_static.py`, `analyze_campaign.py`,
  `append_ground_truth.py` — all built and tested).

### M-3. Terminal-mode `run_session.py` renders no `report.html` and never regenerates the live campaign
- **Where:** [scripts/run_session.py:333-345](scripts/run_session.py) (`run_default`) and
  [scripts/append_ground_truth.py:59-78](scripts/append_ground_truth.py).
- **What:** only the `--web` flow calls `render_session_report`/`render_campaign_report`. A live
  throw recorded in default (terminal) mode produces a session directory with **no `report.html`**,
  and `data/sessions/campaign.html` is not touched. Likewise, a ground-truth entry via the terminal
  prompt or `append_ground_truth.py` regenerates neither the per-throw page nor the campaign (only
  the web POST handler does, [serve_report.py:147-151](scripts/serve_report.py)).
- **Why it matters:** CLAUDE.md §5.6 lists `report.html` as part of the session layout, and §12.2
  says each campaign page is "regenerated from scratch — the live page **at the end of every
  `run_session.py` run** and … after every ground-truth entry". After a terminal-mode campaign day,
  the live campaign page silently shows stale/absent data even though the sessions are complete —
  an operator checking it would under-count their own throws.
- **Fix direction:** either (a) call `render_session_report(session_dir, config)` +
  `render_campaign_report(args.out_dir, config)` at the end of `run_default` and after
  `append_to_session` writes (cheap; renderers are full-overwrite and already import-safe), or
  (b) amend §12.2/§5.6 to say rendering is `--web`-only and late pages come from
  `serve_report.py --session`. Option (a) matches the spec's intent.

### M-4. Live failure path: uncaught `ValueError`, and the §12.1 failure-state claim is unfulfillable for real failures
- **Where:** [pipeline/process_throw.py:208-246](pipeline/process_throw.py) (raises on "no throw" /
  `< min_fit_points` / non-concave fit **before** the CSV writes at lines 278-288);
  [scripts/run_session.py:312-334](scripts/run_session.py) (`_capture_default` → `run_default`/`run_web`
  have no handler; `main` catches only `KeyboardInterrupt`).
- **What:** a live throw that segments but fails the fit (the expected "~5–6 triplets, one too few"
  campaign scenario, §11) makes `run_session.py` die with a Python traceback. The actionable
  "throw slower/loftier" message is inside the traceback, not printed as a report. No failure-mode
  `report.html` is rendered on this path; and because `process_session` raises before writing
  `triplets_raw.csv`/`trajectory.csv`, even a later `render_session_report` on that session produces
  a failure page **without** the range-vs-time panel — contradicting CLAUDE.md §12.1's "failure mode
  … still renders range-vs-time + stat strip" (the renderer handles the absent CSVs gracefully,
  [pipeline/web_report.py:108-135](pipeline/web_report.py), but the data was never written).
- **Why it matters:** this is the most likely operator-visible event of the campaign. No data is
  lost (`raw_serial.log`/`background.json`/`session.json` survive; the session is reprocessable),
  but the operator gets a crash instead of guidance, and the diagnostic panel that §12.1 promises
  for exactly this case is empty.
- **Fix direction:** two independent pieces: (1) in `run_default`/`run_web`, wrap the
  `process_session` call, print the `ValueError` message cleanly, and still render the (failure)
  report; (2) in `process_session`, write `triplets_raw.csv` (and the gate summary into
  `session.json`) *before* the Kalman/landing stage so a failure session carries its gating
  evidence. (2) is the substantive one; without it §12.1 should be reworded.

## Minor (style, dead code, missing docs)

1. **`--drag-mult` CLI flag not implemented.** CLAUDE.md §2/§6 list it
   (`simulate_session.py` CLI: "--drag-mult (testing knob, §9)"); `parse_args`
   ([scripts/simulate_session.py:44-69](scripts/simulate_session.py)) has no such flag and
   `main` uses the realistic `default_drag_k` unscaled (line 228). The ×3/×5 knobs live only in
   `test_bias.py:70` and `test_end_to_end_synthetic.py:89`. As a *confinement* property this is
   good (the knob cannot leak into demo data via the CLI — see Confirmed-fine 7); as spec text it
   is drift. Either add the flag or strike it from §6.
2. **Demo sessions match the §5.6 layout only under `--plot`.** Without `--plot`,
   `simulate_session.py` writes raw+truth but never processes, so `report.html`, `trajectory.csv`,
   `triplets_raw.csv` are absent ([simulate_session.py:274-281](scripts/simulate_session.py)).
   §0.3/§5.6 say a demo session keeps the "identical internal layout" unconditionally. Doc nuance
   or make `--plot` the demo default.
3. **`config.yaml` header says "(v2.3)"** ([config.yaml:1](config.yaml)) while the spec is v2.5, and
   the **§2 `web:` block (`enabled_default`, `host`, `open_browser`) is absent from config.yaml and
   unused in code** — `serve_report.py` hardcodes `("127.0.0.1", 0)`
   ([serve_report.py:270](scripts/serve_report.py)). The hardcoded loopback is the *safe* direction,
   but §12.3 says "on `config.web.host`". Align one way or the other.
4. **`handoff.md` is stale and contradicts the tree** (dated 2026-06-23, pre-Parts 10–11): claims
   CLAUDE.md = v2.3 (it is v2.5), 217 tests (225), `CHANGES.md` "NOT in the repo" (present, the D5
   order), `demo_web_reports.py` deleted (present and D5-aware — IMPLEMENTATION_NOTES §D5-G itself
   records this correction), 12 sim dirs at the live root (now under `demo/`), and points readers at
   a `handoff2.md` that does not exist. Anyone on-boarding from handoff.md inherits five wrong facts.
5. **`capture_session` has no overwrite guard.** It does `mkdir(exist_ok=True)` then opens
   `raw_serial.log` with `"wb"` ([run_session.py:138,156](scripts/run_session.py)). All current
   callers pass a freshly created dir (`next_session_dir` never reuses), but the public function
   itself would silently clobber a recorded session's raw log — the one file the project calls
   sacred. `create_session_folder` on the simulator side refuses to overwrite
   ([simulate_session.py:171-183](scripts/simulate_session.py)); mirroring that refusal here is one
   `if (session_dir / "raw_serial.log").exists(): raise` away.
6. **`session.json` rewrites outside the GT path are non-atomic** —
   [process_throw.py:286-288](pipeline/process_throw.py) and `capture_session`'s two `_write_json`
   calls. Recoverable (reprocess from the raw log) and not spec-mandated to be atomic, but the
   project has an atomic writer one import away; worth unifying while touching M-1.
7. **`ceiling_ghost_apparent_range` returns one value, docstring says "per sensor"**
   ([pipeline/background.py:129-152](pipeline/background.py)); §5.7 also says "per sensor". With
   equal heights and a common tilt all three values are identical, so the code is right and the
   wording is wrong — but the equal-geometry assumption should be stated where the singular return
   is documented.
8. **Headerless replay loses the first 5 CSV rows from live gating** —
   [pipeline/acquisition.py:96-103](pipeline/acquisition.py) consumes `_HEADERLESS_AFTER - 1` valid
   rows while still hoping for a header. Verbatim log is intact and offline reprocessing sees
   everything, so impact is nil; worth a docstring sentence.
9. **`analyze_campaign.summary_stats` hardcodes "95%" in the power-note text**
   ([scripts/analyze_campaign.py:149-150](scripts/analyze_campaign.py)) while `alpha` is a
   parameter; `calibrate_bias`'s wording avoids the number. Wrong text if ever run with
   `alpha ≠ 0.05`.
10. **Dead JS fallback constant:** `RBALL=(D.ball_radius_m||0.0335)`
    ([pipeline/web_assets/session_report.html:594](pipeline/web_assets/session_report.html)). The
    builder always emits `ball_radius_m` ([web_report.py:214](pipeline/web_report.py)), so the
    literal never fires; it is also the only place a physical constant appears outside
    config/corrections. Display-only; drop the fallback.
11. **`demo_web_reports.py` imports from the test tree** (`from tests.session_factory import
    write_session_dir`, [scripts/demo_web_reports.py:48](scripts/demo_web_reports.py)) — a
    scripts→tests dependency; fine for a demo tool, but it breaks if `tests/` is ever excluded from
    a deployment.
12. **`sigma_y` can be `inf` on a zero radicand.** `radicand == 0` passes the `>= 0` NaN guard, so
    `y_plane == 0` yields `valid=True` with `sigma_y = inf`
    ([pipeline/trilateration.py:84-90](pipeline/trilateration.py)); a used triplet like that would
    crash `filter_trajectory`'s finite-`sigma_y` check with a confusing message. Measure-zero in
    practice (overlap floor keeps y ≳ 0.5 m); a `radicand > 0` strictness or an `isfinite(sigma_y)`
    term in `valid` would close it.
13. **Doc hygiene inside IMPLEMENTATION_NOTES.md:** the header still says "Authoritative spec:
    CLAUDE.md (v2.1)"; Part 5 and Part 9 both use section letters CC–GG, so cross-references like
    "§CC" are ambiguous; D5 is recorded as "Part 10" although CHANGES.md asked for "Part 9/D5".
    Also **CLAUDE.md contains two sections numbered §12** ("Audit disposition record" and "HTML
    reporting layer"), making every "§12.x" reference formally ambiguous (readers must disambiguate
    by subsection).
14. **§1 repository-layout drift (inventory, Step 1):** present on disk but absent from the §1 tree —
    `scripts/analyze_static.py`, `scripts/demo_web_reports.py`, `tests/test_analyze_campaign.py`,
    `tests/test_characterize_static.py`, `tests/test_reporting.py`, `tests/test_run_session_web.py`,
    plus root files `IMPLEMENTATION_NOTES.md`, `handoff.md`, `BENCH_PROCEDURE.pdf`. Nothing in §1 is
    missing from disk. All extras are documented in IMPLEMENTATION_NOTES, so this is §1-tree
    staleness, not shadow code.
15. **Coverage gaps:** `scripts/verify_timing.py` has zero pytest coverage (its offline replay
    self-test is manual — Part 3 §T; its near-vacuous monotonic check #3 is honestly documented at
    S-2 and re-verified here at [verify_timing.py:166-172](scripts/verify_timing.py));
    `run_default`'s GT-persistence lines (the M-1 site) are untested (the solve itself is covered
    transitively via `append_ground_truth` in `test_serve_report.py`).
16. **Firmware nit:** `t_trig = micros()` is captured just *before* the TRIG HIGH edge
    ([05_timing_verify.ino:66-67](firmware/05_timing_verify/05_timing_verify.ino)) though the
    comment says "HIGH edge"; the offset is a few µs of `digitalWrite` latency, common-mode across
    sensors, and far inside the ±50 µs verify budget. Comment-accuracy only. The Part-3 caveat that
    **no sketch has ever been toolchain-compiled** (S-1) still stands and belongs on the bench
    checklist.

## Confirmed-fine (checked from the risk list; found correct)

1. **I/O purity boundary (§0.5).** Grep of `geometry, corrections, trilateration, kalman, landing,
   bias, background, segmentation, simulator` for `open(`, `serial.`, file writes, csv/json I/O:
   zero hits (all matches are docstrings or the simulator's in-memory `serial_lines` strings). The
   sanctioned I/O members (`process_throw`, `acquisition`, `reporting`, `web_report`, `scripts/`)
   are exactly the ones doing I/O.
2. **Single source of physical truth.** The speed-of-sound formula exists once
   ([corrections.py:23-25](pipeline/corrections.py)); simulator re-imports it. Sensor coordinates,
   radius, heights, gates all flow from the config dict. `G = 9.81` appears in `kalman.py` and
   `simulator.py` with cross-referencing comments (physics constant, spec-sanctioned in §8.4). The
   simulator's drag-truth constants are deliberately module-local with the rationale in its
   docstring. Only stray literal: the dead JS fallback (Minor-10).
3. **Raw-data-sacred.** `raw_serial.log` is opened for writing only in freshly created session
   directories (`next_session_dir` / `create_session_folder` never reuse; the simulator path
   *refuses* to overwrite); `process_session` reads it via `read_bytes()` only. Gating is flags in
   `triplets_raw.csv`, never row deletion. (Latent hazard in the public `capture_session` API noted
   as Minor-5.) The atomic GT writer is real: temp file + `fsync` + `os.replace` with cleanup-and-
   reraise, and `test_updates_only_ground_truth` / the injected-failure test guard it. The audit
   question "is `update_session_ground_truth` the only writer into existing sessions?" is answered
   precisely: it is the only *ground-truth* writer except the terminal path (→ M-1);
   `process_session` also rewrites `session.json`/CSVs, which §8.8 sanctions.
4. **G1 status.** Migrated in code everywhere (detail under M-2); the docs, not the code, are stale.
5. **D5 status.** Built and live on disk: `data/sessions/campaign.html` (live, n=0) +
   `data/sessions/demo/campaign.html` + 12 `sim_2026-06-25_145012_S##` sessions; predicate routed
   through all three enumerators; `load_campaign`'s file branch additionally hardened to accept only
   files literally named `session.json` ([analyze_campaign.py:76-86](scripts/analyze_campaign.py)),
   so a stray `campaign.html` can never reach `json.load`.
6. **Vacuous `q` flag (C-2).** `q` is computed and stored ([trilateration.py:88](pipeline/trilateration.py)),
   written to `trajectory.csv` as `height_consistency_q_m` — and grep confirms **no consumer**
   (reporting, web_report, analyze_campaign, calibrate_bias, bias, kalman) reads it as a quality
   signal. The working gates are the NaN guard + validity flags, and the used-triplet mask checks
   all of them: `used = usable & t_valid & tri.valid & seg.in_throw`
   ([process_throw.py:236](pipeline/process_throw.py)). The docstring records the vacuousness; the
   tests pin it (`test_q_identically_zero_even_with_noise`).
7. **Hybrid stencil NaN fallback (D1).** Re-derived from
   [corrections.py:82-107](pipeline/corrections.py): the fallback `where(isfinite(v_fwd), v_fwd,
   v_bwd)` cannot fabricate an endpoint velocity because the unavailable one-sided difference is
   structurally NaN at each end; a NaN in a row's own reading always propagates through
   `d_aligned = d + v·dt` regardless of a finite central-difference velocity; both-neighbours-invalid
   leaves the row NaN → `usable=False`; even a duplicate timestamp (zero Δt) produces ±inf →
   non-finite → unusable. N=1 and N=2 edge cases degrade correctly. `test_hybrid_nan_fallback`
   covers the documented cases.
8. **Drag test knob confinement (C-3–C-5).** The ×5 multiplier exists only in
   `test_end_to_end_synthetic.py` (`K_SCALE`) and ×3 in `test_bias.py`; `simulate_session.py` and
   `simulator.default_drag_k` use the realistic coefficient; nothing config-driven scales drag. No
   leak into any production or demo default.
9. **Kalman variable dt.** `F = build_F(dt)` is rebuilt **inside the update loop** from
   `t_s[n] − t_s[n−1]` of mid-echo `t_sample` timestamps
   ([kalman.py:106-109](pipeline/kalman.py)); `R` is rebuilt per update (hetero σ_y); strictly-
   increasing-t and finiteness are validated at entry. The negative control
   (falsified-uniform-timestamps ≈ 8× gap error) exists in `test_kalman.py`. `Q` is constant per
   step (not dt-scaled) — exactly what §8.4 specifies ("Q small (q_scale)"), noted here only for
   completeness.
10. **Landing math (R7/F-6/F-9).** Manual `(RSS/dof)·(VᵀV)⁻¹` covariance; delta-method through the
    shared root time t* with the x–z cross term; concave-down guard, discriminant guard,
    descending-root selection, and the dof = m−3 caveat string all verified line-by-line in
    [landing.py](pipeline/landing.py).
11. **Multilateration math (G1).** Linearisation (subtract the centroid sphere), 2 Gauss–Newton
    steps over all three residuals, `cov = σ²(GᵀG)⁻¹` via `pinv` (algebraically confirmed), unique
    solution (no mirror), warn-not-raise conditioning — all correct in
    [geometry.py:145-220](pipeline/geometry.py).
12. **Web layer guardrails.** Templates contain zero `http(s)://`, external `src`, `link href`, or
    `xmlns` (grep, independent of the test that asserts the same); `__DATA__` injection escapes
    `</`; the POST handler's 409/422/500/200-with-read-back state machine matches §12.3, including
    "regeneration is best-effort *after* the durable write" so a plot error can't fake a failed
    save; `find_session_dir` rejects path separators and `..`.
13. **Firmware vs Python assumptions (Step 5).** Pin map matches §3 exactly; timeout is 12500 µs
    from sketch 02 onward, matching `config.acquisition.pulse_timeout_us` and the header substring
    `process_throw` validates; one absolute scheduler (`next_slot_us += 18000UL`) with the
    rollover-safe signed-long comparison; timeouts print literal `0`; CSV
    `sensor_id,echo_us,timestamp_us` matches `parse_serial_lines` (1-based ids, no spaces); baud
    115200 retained per the §12 audit disposition; no distance math on the Arduino; sketch 01's
    generous 25 ms timeout is documented in-file as bench-only.
14. **Test suite (Step 4).** Measured **225 passed, 0 failed, 0 skipped** in 40 s; per-file
    collection re-counted (geometry 27, simulator 27, corrections 18, e2e 15, bias 16, kalman 15,
    background 14, segmentation 14, serve_report 12, web_report 11, trilateration 11,
    process_throw 11, landing 9, analyze_campaign 7, acquisition 6, characterize_static 6,
    run_session_web 4, reporting 2). The load-bearing assertions were spot-read rather than trusted:
    the e2e negative controls assert failure in *both* directions (baseline passes AND control
    fails); the R3 e2e variant asserts the below-noise-floor bound (|Δ| < 5 mm) per the C-1
    reconciliation; the D1×D2 density test asserts both the fit arm and the clean-failure arm were
    exercised (explicitly anti-vacuous); the drag-OFF hybrid gate asserts either 'none' or the
    bounded self-systematic, never silence; Test 5 asserts dict equality of the GT block across
    web/append/direct-solve. No tautological test was found in the files read.
15. **Session-name/overwrite discipline (D4).** `session_directory_names` is pure (injected
    datetime), `create_session_folder` raises rather than overwrite, and `next_session_dir` probes
    for the next free `_T##`.

---

*Scope note (in lieu of a handoff): all of `pipeline/` and `scripts/` was read in full except
`characterize_static.py`/`analyze_static.py` (skimmed against their Part-5 record plus their tests)
and the ~58 KB of template JS (audited by grep for self-containment, physics reimplementation, and
hardcoded constants rather than line-by-line). Test files were spot-read at the load-bearing
assertions listed above rather than exhaustively. No further areas remain that the audit prompt
required.*
