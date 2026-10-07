# Audit Report — Optical Ground-Truth Module, Phases 0–4

**Audit type:** Read-only review pass. No files were modified, refactored, or fixed during
this audit — all findings below are reported for a human (or a future executor) to act on.

**Scope reviewed:** `CLAUDE.md` / `Optical.md` v1.0 (spec), `IMPLEMENTATION_NOTES_OPTICAL.md`
(as-built record, Phases 0–4), `CHANGES_OPTICAL.md` (empty — no work orders issued yet),
`config.yaml`, everything under `optical/`, `simulator/`, `scripts/`, `tests/`.

**Test suite result at audit time:** `.\venv\Scripts\python.exe -m pytest tests -q` →
**115 passed, 0 failed, ~32 s.** This matches the count IMPLEMENTATION_NOTES_OPTICAL.md
claims for the end of Phase 4 (115 = 93 prior + 22 new).

**Repo state:** no git (per O1, expected). Directory tree matches §5 exactly. No
`calib/` or `data/` artifacts exist yet (expected — nothing has touched real footage).

---

## How to use this document

This file is a snapshot audit as of the date it was written. If you are a future
executor (human or AI) picking this up:

1. **Verify before acting.** Line numbers and code shown below are exact as of the audit,
   but the codebase may have changed since. Re-read the cited file/line before editing.
2. Findings are ranked by severity: **Major** (could produce a wrong landing point, a wrong
   uncertainty number, or a false GO at the Phase 5 gate), **Moderate** (works but fragile /
   under-tested / spec-divergent), **Minor** (cosmetic).
3. Section 6 lists what genuinely cannot be verified by reading code alone — those items
   are not defects, they are the C1–C7 commissioning checklist by another name.

---

## 1. Overall assessment

The pipeline is **logically sound** and, at the level of the mathematics and module
design, does what CLAUDE.md intends. Specifically verified by hand during this audit:

- The array-frame polar convention and its round-trips (`optical/geometry.py`).
- The homography decomposition algebra (`decompose_camera`) that recovers camera pose
  (C, R) from H + K.
- The analytic parallax correction closed form and its partial derivatives
  (`parallax_correct`, `parallax_sigma` in `optical/uncertainty.py`).
- The polar uncertainty propagation formulas (`polar_sigma`).

All of these check out mathematically and are cross-validated in the test suite against
Monte-Carlo references (see `tests/test_uncertainty.py::test_parallax_sigma_vs_monte_carlo`
and `::test_polar_sigma_vs_monte_carlo`, both asserting agreement within 5%).

**Standalone contract holds (§12):** no import or hardcoded path reaches outside the
project directory (`grep` for `\.\.[\\/]`, `parents\[2\]`, absolute paths found nothing
beyond the expected `sys.path` root-insertion boilerplate in `tests/conftest.py` and the
four `scripts/*.py` files, all pointing at `Path(__file__).resolve().parents[1]` — i.e.
this project's own root).

**Zone rules (§10) hold:** no `ultralytics`, `torch`, or `yolo`/`YOLO` reference anywhere
in `optical/`, `simulator/`, `scripts/`, or `tests/` — confirmed by grep, zero hits.

**Test suite is genuinely strong, not just unit-level theater.** Real rendered frames
(not fabricated arrays) go through the full detect→track→contact→parallax chain in
`tests/test_end_to_end_synthetic.py` and are compared against injected ground truth with
a documented, scenario-specific tolerance and one-line justification per test, satisfying
§11's "no bare tolerance without a reason" rule. Both mandatory negative controls (§6) are
asserted to fail loudly, not silently:
  - `test_e2e_negative_no_ball_never_fabricates` — asserts `find_descent` raises.
  - `test_e2e_negative_corrupted_survey_flags_the_throw` — asserts `pytest.warns(UserWarning,
    match="CHECK-POINT GUARD TRIPPED")` AND that the resulting landing error is materially
    large (>5mm), proving the guard is load-bearing, not decorative.

**IMPLEMENTATION_NOTES_OPTICAL.md is unusually honest and accurate.** Cross-checking its
claims against the actual code: the numbers, the design decisions, the "problems found and
fixed" narrative for Phase 3's contact-time solve, and the file lists all matched what is
actually on disk. I did not find a single instance where the notes claimed something the
code doesn't do.

**Where the weaknesses actually are:** almost entirely at the **orchestration layer**
(`scripts/process_clip.py` and what it feeds into the otherwise-correct pure modules), plus
one significant gap in what the end-to-end tests can exercise given the simulator's current
default behavior. The pure math/geometry/uncertainty modules themselves are in good shape.

---

## 2. Major flaws (ranked, most severe first)

### M1 — Per-throw uncertainty is built from silent hardcoded defaults, not measured values

**Files:** `scripts/process_clip.py:90-92`, `scripts/validate_static.py:62-68`, `config.yaml`

In `run_clip_pipeline` (`scripts/process_clip.py`):

```python
sigma_px=float(config.get("uncertainty", {}).get("pixel_sigma_px", 0.5)),
...
sigma_h_m=float(config.get("uncertainty", {}).get("sigma_h_m", 0.004)),
vel_xz=contact.vel_xz, sigma_t_s=contact.sigma_t_s)
```

**`config.yaml` has no `uncertainty:` section at all** (confirmed by reading the full file —
it has `array`, `ball`, `markers`, `tolerances`, `detect`, `track`, `capture`; no
`uncertainty` key). This means on **every real run**, `config.get("uncertainty", {})`
returns `{}` and both fallbacks silently apply:
  - `sigma_px` → hardcoded 0.5 px, never the actual measured value from
    `optical.detect.localisation_scatter` (which C6 / §7 item 3 exists specifically to
    measure).
  - `sigma_h_m` → hardcoded 0.004 m, never justified per-throw.

Worse: `build_budget()`'s `sigma_C_m` parameter (camera-position uncertainty, §7 item 4)
is **never passed** by `process_clip.py`, so it silently defaults to `(0.0, 0.0, 0.0)` in
`optical/uncertainty.py:build_budget`. And `rolling_shutter_m` (§7 item 5, spec text: *"Do
not assume it away; magnitude is phone-dependent and unknown a priori"*) is also never
passed, silently defaulting to `0.0`.

The propagation machinery itself (`optical/uncertainty.py`) is mathematically correct and
tested — there is even a test proving the rolling-shutter term *would* enter correctly if
supplied (`test_budget_rolling_shutter_term_enters`). But the orchestrator never wires the
measured C6 scatter, a real camera-position covariance, or a real rolling-shutter estimate
into the per-throw call. **The exact five components §7 lists as "each measured or
propagated — never assumed" include at least two (camera-position, rolling-shutter) that
are currently assumed away by omission, and one (pixel scatter) that has a live measurement
function nothing calls it from.**

**Consequence at Phase 5:** every `optical_gt.json` produced from real footage will carry
sigma numbers that are partly fabricated from invisible constants. This directly corrupts
the campaign cross-validation statistic (§7's final paragraph: per-throw |E_n| check,
camera vs tape, normalized by *combined* uncertainty of both instruments) — if the optical
module's own uncertainty is wrong, the E_n statistic is meaningless regardless of how
accurate the landing point itself is.

**Same pattern, smaller blast radius, in `scripts/validate_static.py:62-68`:**
```python
budget = unc.build_budget(
    ...
    sigma_h_m=0.004, vel_xz=np.array([0.0, 0.0]), sigma_t_s=0.0)
```
`sigma_h_m` is again a bare hardcoded constant here in the §8 gate-runner itself.

**Suggested fix direction (not implemented — reported only):** add an `uncertainty:` block
to `config.yaml` with named, sourced placeholders (mirroring how `detect:` and `track:`
already do it), thread `localisation_scatter()` output into `run_clip_pipeline` instead of
a fallback constant, and either measure/pass a real `sigma_C_m` (from repeated homography
calibrations) and `rolling_shutter_m` (from the §3.2/§7 characterisation film) or make their
absence loudly visible via a new quality flag rather than a silent zero.

---

### M2 — `fps_measured` is fabricated (copied from nominal) in the production entry point

**File:** `scripts/process_clip.py:199-215`

```python
mode = args.mode or config["capture"]["default_mode"]
fps = float(config["capture"]["modes"][mode]["fps_nominal"])
...
clip_meta = {"file": "raw.mp4", "mode": mode, "fps_nominal": int(fps),
             "fps_measured": fps}
```

There is **no `--fps-measured` CLI argument**, and grepping the entire `scripts/` and
`optical/` tree, **nothing anywhere calls `cv2.CAP_PROP_FPS`** or otherwise reads the
container's delivered frame rate from a real video file. `fps` here comes straight from
`config["capture"]["modes"][mode]["fps_nominal"]` (`config.yaml:87-88`: `720p480:
{fps_nominal: 480, ...}`), and that same nominal value is written into the JSON under
**both** `fps_nominal` and `fps_measured`.

This directly contradicts §3.2 (*"the measured value, not the nominal one, feeds all
timing math"*) and §9 (*"verify the imported file's frame-rate metadata matches capture...
before trusting timing — a re-encode or transcode on transfer would silently corrupt the
temporal base"*). The simulator goes out of its way to bake in `fps_measured = 479.82` vs
`fps_nominal = 480` specifically to force downstream code to consume the measured value
from day one (documented in IMPLEMENTATION_NOTES Phase 1) — and every test correctly uses
`sc.fps_measured`. But the one script that will touch real phone footage discards this
distinction entirely and cannot detect a transfer re-encode (the exact failure §9 exists to
catch) because it never reads the file's actual delivered rate to compare against the C1
frame-rate-verification measurement.

**Consequence:** if the actual delivered rate differs from nominal by even a fraction of a
percent (§3.2 documents this is expected — "some phones deliver slightly variable rates"),
every timing-dependent quantity (contact-time bracket, sub-frame fit, velocity used in the
temporal uncertainty term) is silently off by that fraction, with no flag raised.

---

### M3 — The §5.1 homography stability protocol exists but is never invoked in production

**Files:** `optical/calibration.py` (`stability_check`, lines 244-265), `scripts/process_clip.py` (no caller)

`stability_check()` is implemented correctly and unit-tested
(`tests/test_calibration.py::test_stability_check_flags_camera_bump`,
`::test_stability_check_passes_when_camera_still`) — it re-maps the held-out check point
from a session-start and session-end frame and raises `homography_drift` if the drift
exceeds tolerance, exactly per §5.1 step 5.

**But no script ever calls it.** `scripts/process_clip.py` loads a single already-computed
`homography_<calib_id>.yaml` and never re-runs the stability check against start/end
frames of the actual session being processed. There is no CLI path, no `run_clip_pipeline`
argument, nothing — `homography_drift` is in `io_session.FLAG_VOCAB`
(`optical/io_session.py:20-25`) but **cannot currently be produced by any real workflow.**

**Consequence:** a camera bump mid-session (tripod knocked, tightened mount slipping) — the
exact failure this guard exists to catch — will silently produce confidently wrong landing
points with a clean flag list. Per §5.1, this should exclude the affected throws from
headline statistics; currently there is no mechanism that could ever do so. This is
plausibly the single most consequential gap for producing a **false GO at the Phase 5
gate**, since the §8 static-point validation is exactly the kind of session where a bump
between the first and last of 8+ points would go undetected.

---

### M4 — The standing end-to-end regression test cannot exercise the real bounce path

**Files:** `simulator/scenarios.py` (all `_base(...)` calls, e.g. lines 39-54),
`optical/track.py:find_descent` (the `reversal` branch, lines 146-152),
`tests/test_end_to_end_synthetic.py` (all scenarios)

Every scenario factory in `simulator/scenarios.py` uses the `Scenario` dataclass default
`restitution: float = 0.0` (`simulator/render.py:204`) — i.e. **the ball is never drawn
past first contact; it simply vanishes.** `ball_world_position()`
(`simulator/render.py:236-253`) confirms: with `restitution=0.0`, `vyp = 0`, so `y` never
exceeds `r_ball` again and the function returns `None` on the very next frame after contact.

This means `find_descent()` (`optical/track.py`) **always** takes the `end_reason ==
"track_end"` branch in every single test in `tests/test_end_to_end_synthetic.py` — the
"standing regression anchor" per §11. The `reversal` branch (lines 116-129 of
`optical/track.py`, triggered when the ball's image-v actually turns around after a real
bounce) is unit-tested *only* against fabricated point sequences in
`tests/test_track.py::test_descent_first_reversal_is_taken` — synthetic numbers, not
rendered frames, and critically: **not run through the contact-time bracket logic in
`optical/contact.py` at all in that test.**

Real footage of a real tennis-ball bounce will **always** take the `reversal` branch (the
ball is visible before and after contact, since restitution > 0 physically). But Phase 3's
own investigation (documented in `optical/contact.py`'s module docstring, lines 1-33, and
in IMPLEMENTATION_NOTES Phase 3) found that **the oblique image-v reversal apex sits ~1
frame offset from the true world-contact instant** — this was the explicit reason the
reversal-apex method was rejected as the primary t* solve. The adopted "descent-end
bracket" method assumes the *last tracked descent frame* is the anchor; under
`restitution=0.0` that anchor is well-defined (the ball simply disappears there); under a
real bounce, the anchor is instead "the frame before the reversal is detected", which is a
structurally different and untested quantity.

**Consequence:** the ~7 mm residual quoted throughout Phase 3/4 as "characterised and far
inside the 15 mm gate" is only demonstrated for the vanish-at-contact geometry. There is
currently **no rendered-frame test evidence for what the bracket error looks like on the
scenario shape (bounce with reversal) that real footage will actually produce.** This is a
gap in validation evidence, not a proven bug — but it means the Phase 3/4 "gate passed"
claims should not be read as covering the real-footage case until a `restitution > 0`
end-to-end scenario is added and measured.

**Suggested fix direction (not implemented):** add at least one scenario to
`simulator/scenarios.py` with `restitution` set to a physically plausible tennis-ball value,
run it through `tests/test_end_to_end_synthetic.py`, and record the resulting landing/t*
error the same way the other scenarios are recorded, before treating Phase 3/4 numbers as
representative of real footage.

---

### M5 — "Sub-frame first contact" (§5.5) was not built; a fixed ±0.5-frame bracket was, and the spec was never amended

**Files:** `Optical.md` §5.5 (spec), `optical/contact.py` (implementation)

§5.5 promises: *"Fit the descent-segment floor-track ... and the image-vertical coordinate
v(t) with low-order polynomials ... First contact t* = the instant the ball-bottom height
reaches the floor, solved from the fit — resolution well below one frame."*

What is actually implemented in `optical/contact.py` (lines 140-153, "Adopted: the
descent-end BRACKET"):

```python
ts = 0.5 / fps_measured
sigma_t = (1.0 / fps_measured) / np.sqrt(12.0)
...
flags.append(BRACKET_FLAG)   # "contact_time_bracket"
```

`t_subframe` is **always** exactly `t_frame + 0.5` (confirmed in
`tests/test_contact.py::test_contact_size_refinement_declines_falls_back_to_bracket`:
`assert result.t_subframe == pytest.approx(n - 1 + 0.5, abs=1e-6)`). This is not a fit
result at all — it is a fixed midpoint-of-uncertainty-window estimate with an
analytically-assigned sigma (`1 frame / sqrt(12)`, the uniform-distribution variance
formula), not a polynomial solved for a floor-crossing.

**This is a defensible and well-documented engineering decision** — IMPLEMENTATION_NOTES
Phase 3 records, in detail and with measured numbers, why the two literal sub-frame designs
(image-v crossing; apparent-size height reconstruction) were tried and rejected, and why
landing accuracy in practice is dominated by the clean centroid track rather than by t*
resolution. The reasoning holds up under review.

**But per §0.2, "Amend before building, never after,"** and Optical.md itself still says
sub-frame-fit-with-resolution-below-one-frame. The deviation currently lives only inside
`optical/contact.py`'s docstring and `IMPLEMENTATION_NOTES_OPTICAL.md` — not in the spec
document itself. Before Phase 5 (and certainly before any report describing the method),
Optical.md §5.5 should be formally amended to describe the bracket approach as the adopted
design, so that "what CLAUDE.md says" and "what was built" don't silently diverge for
future readers who only check the spec.

---

## 3. Moderate issues (work but fragile / under-tested / spec-divergent)

- **Overly broad `except ValueError` swallows real errors as "no prediction."**
  `scripts/process_clip.py:74-81` (`run_clip_pipeline`):
  ```python
  try:
      descent = find_descent(...)
      contact = fit_contact(...)
      landing_xz = contact.landing_xz
      method["parallax"] = contact.method
  except ValueError as exc:
      notes = ... + f"no prediction: {exc}"
  ```
  This catches *any* `ValueError` from the whole descent/contact chain — including
  `parallax_correct`'s "camera height C_y must exceed the point height h" guard
  (`optical/geometry.py:210-212`) and `apply_homography`'s "homography maps a point to
  infinity" guard (`optical/calibration.py:50-51`). A misconfigured or malformed camera
  geometry passed in from `process_clip.main` (e.g. a bad `--intrinsics` file producing a
  degenerate `CameraGeometry.from_homography`) would be silently reported as an ordinary
  "no ball in this clip" failure rather than surfaced as a configuration bug. Recommend
  narrowing the catch to the specific data-shape exceptions (`find_descent`'s "no ball
  track" / "no usable descent", `fit_contact`'s "need >= 4 frames") or introducing a
  distinct exception type for configuration-level failures.

- **Silent fallback camera intrinsics with no output-level trace.**
  `scripts/process_clip.py:184-240` (`main`, `_fx_only_K`): when `--intrinsics` is
  omitted, `_fx_only_K` invents a camera matrix from a bare 60° HFOV guess on the mode's
  resolution. This is explicitly documented in the code comment as "smoke-testing only,"
  and IMPLEMENTATION_NOTES Phase 4 flags it in prose ("real runs MUST pass the §3.4
  intrinsics file"). But nothing in the *output* reflects this: no console warning is
  printed when the fallback fires, and no quality flag is set on the resulting
  `optical_gt.json` — a campaign run missing `--intrinsics` by operator error would produce
  an artifact indistinguishable from a properly calibrated one. Given §5.6's flag
  vocabulary already anticipates exactly this kind of thing ("silent fallback ... isn't
  logged or flagged"), this should get its own flag (e.g. add `fallback_intrinsics` to
  `FLAG_VOCAB`) or at minimum a `UserWarning`.

- **`scripts/validate_static.py` has no working CLI — only library functions.**
  `main()` (lines 136-145) is a stub:
  ```python
  print("validate_static: run programmatically with measure_points(...) over your "
        "surveyed static clips, or extend this CLI to enumerate on-disk static "
        "sessions once real footage exists (Phase 5).")
  return 0
  ```
  `static_landing`, `measure_points`, `summarize`, `comparison_table`, `write_report` are
  all implemented and well-tested as library functions, but the §14 Phase 4 deliverable
  ("batch static-point runner producing the §8 comparison table") has no actual
  command-line entry point that enumerates on-disk static-point session directories. This
  means the C7 gate run at Phase 5 — the single most consequential procedure in the whole
  project — will require writing glue code in the field rather than running an existing,
  tested script. Recommend building this CLI before Phase 5, not during it.

- **Reversal detection in `find_descent` has no noise robustness / hysteresis.**
  `optical/track.py:120-129`:
  ```python
  for k in range(1, len(vidx)):
      if v[k] > v[k - 1]:
          rising += 1
      else:
          if rising >= min_run:
              end_k = k - 1
              reason = "reversal"
              break
          rising = 0
  ```
  Any single non-increase in image-v after a `min_run`-frame (default 3) rise is treated as
  the reversal. On sub-pixel-clean synthetic tracks this never misfires. On real detections
  with realistic pixel-level scatter (§7 item 3 anticipates ~0.1–0.5 px, but real footage
  under shadow/blur could be worse per Phase 3's own detect.py tests showing up to ~2 px
  error under shadow), a single noisy frame partway through a genuine descent could
  prematurely end the descent window and drag both t* and the extrapolated landing point.
  This path is untested under any noise model — all `test_track.py` reversal tests use
  perfectly monotonic fabricated sequences.

- **Never-producible quality flags.** `FLAG_VOCAB` in `optical/io_session.py:20-25`
  includes `blur_suspected` and `cond_warn` (both from the original §5.6 spec vocabulary).
  Grepping the whole codebase, **nothing computes a blur metric** and **nothing raises
  `cond_warn`** — the closest analog, `_assert_noncollinear` in `optical/calibration.py`,
  *raises an exception* on bad conditioning rather than setting a warning flag and
  continuing. Combined with M3 above (`homography_drift` unreachable in production), **three
  of the original six §5.6 flags are currently decorative** — defined in the vocabulary,
  never producible by any code path that runs on real data.

- **Marker-survey uncertainty component is charged as a raw constant, not propagated
  through the fit as §7 item 1 specifies.** `optical/uncertainty.py:114`:
  ```python
  survey_ax = np.array([marker_survey_m, marker_survey_m])
  ```
  §7 item 1 says: *"Marker survey σ ... propagated through the homography fit."* The actual
  code charges the raw per-marker survey sigma directly per axis, isotropically, rather
  than propagating it through the least-squares fit (which averages over ~7 markers and
  would in principle shrink the effective contribution, and would also not be isotropic
  given the marker geometry). This is a conservative simplification (it will make the
  budget look *worse* than reality, not better — not dangerous for a GO/NO-GO decision),
  but it is a real deviation from what §7 specifies, and it partially double-counts with
  the `check_point_err_m` term that's already folded into `homography_m`
  (`optical/uncertainty.py:116-118`). Worth flagging in the commissioning report rather than
  silently treating the current formula as "the §7 budget" verbatim.

- **`trimmed.mp4` is not a plain trim of raw footage.** `scripts/process_clip.py:207-211`:
  ```python
  raw = session_dir / "raw.mp4"
  frames = load_clip_frames(raw, args.in_frame, args.out_frame)
  frames = [cal.undistort_frame(f, intr) for f in frames]
  if args.in_frame is not None:
      write_trimmed(frames, session_dir / "trimmed.mp4", fps)
  ```
  The written `trimmed.mp4` contains *undistorted, re-encoded* (mp4v, lossy) frames, not a
  byte-preserving trim of the sacred `raw.mp4`. IMPLEMENTATION_NOTES Phase 4 already
  recommends preferring `raw.mp4 --in/--out` directly on real low-contrast footage rather
  than trusting the re-encoded file, which is the right instinct — but as written,
  `trimmed.mp4` could be mistaken by a future operator for a lighter-weight verbatim clip
  when it is neither verbatim nor guaranteed lossless. Consider making trimmed-file writing
  clearly optional/diagnostic-only in the CLI help text, or renaming it to make the
  undistort+reencode nature explicit (e.g. `trimmed_undistorted.mp4`).

---

## 4. Minor / cosmetic (wouldn't block Phase 5)

- `optical/contact.py`'s module docstring (lines 1-33) describes an "opt-in refined t*"
  path using per-frame apparent-size height reconstruction; `fit_contact()`'s actual
  signature has no such option/parameter — `reconstruct_world_point` and `_root_near` in
  `optical/geometry.py` / `optical/contact.py` are dead code on every call path
  (dormant-by-design per IMPLEMENTATION_NOTES, which is a defensible choice, but the
  contact.py docstring should be updated to say "was investigated, not wired in" rather
  than describing it as a live opt-in).
- `ContactResult.fit_rms_v_px` (`optical/contact.py:61`) is always `float("nan")` on every
  code path — vestigial field from an earlier design iteration.
- The per-frame `"ambiguous"` status recorded in `Track.status` (`optical/track.py`, §5.2
  confidence flag) never propagates into `quality.flags` in the final JSON via
  `_quality_flags()` (`scripts/process_clip.py:41-54`) — it's tracked internally but
  invisible in the frozen output.
- In the throw path, `build_budget()` is called with `parallax_P_mapped=landing_xz` (the
  already-corrected point) rather than the pre-correction mapped point
  (`scripts/process_clip.py:91`); `scripts/validate_static.py:67` does this correctly
  (`parallax_P_mapped=M_c`, the pre-correction point). The effect is a ~2% error on one
  sub-millimeter uncertainty component — cosmetic, but worth aligning the two call sites.
- `append_manifest()`'s docstring (`scripts/process_clip.py:158-159`) says entries are
  deduped "by session_id+throw"; the actual dedup key is `session_id` alone (works
  correctly in practice because session IDs already embed the throw number per the §9
  naming convention, but the docstring overstates the key).
- The simulator's ball colour (`simulator/render.py:52-57`, `tennis_ball_bgr()`) is defined
  at exactly H=35, dead-center of the `config.yaml` HSV detection band `[25,60,60]` to
  `[45,255,255]`. This makes the `detect.py` synthetic tests slightly self-fulfilling by
  construction — acknowledged implicitly since real threshold tuning is explicitly a
  commissioning-time task (C6), not a software-correctness question, but worth remembering
  when reading the Phase 3 detection numbers as "validated."
- Known, already-recorded pytest rootdir quirk (pytest reports the grandparent `Project`
  folder as rootdir because there's no `pytest.ini`/`pyproject.toml`; tests still collect
  correctly via `conftest.py`'s explicit `sys.path` injection). Flagged in
  IMPLEMENTATION_NOTES Phase 0 as low-risk and deliberately left unaddressed to keep the
  scaffold minimal — still true, still low-risk, still unaddressed.

---

## 5. Test suite health assessment (Step 4 detail)

**Command run:** `.\venv\Scripts\python.exe -m pytest tests -q --tb=short`
**Result:** `115 passed in 31.69s` — 0 failed, 0 skipped, 0 errors, 0 warnings surfaced
(the `pytest.warns(...)` blocks in the negative-control tests correctly capture and consume
the expected `UserWarning`s rather than letting them leak as unhandled warnings).

**Does the suite validate end-to-end correctness, or just individual units?** Both, and the
balance is good:

- `tests/test_geometry.py`, `tests/test_uncertainty.py` (most of it), `tests/test_track.py`:
  pure unit tests on fabricated inputs — appropriate, since these are pure math/logic
  functions where exactness matters more than photorealism (explicitly stated in
  `test_track.py`'s module docstring).
- `tests/test_simulator.py`, `tests/test_calibration.py`, `tests/test_detect.py`,
  `tests/test_contact.py`: unit/integration tests against **rendered synthetic frames**
  with exact injected ground truth — not just "does it run," every test asserts a specific
  numeric error bound against truth, with the bound justified in a comment or docstring
  (satisfying §11's requirement).
- `tests/test_end_to_end_synthetic.py`: genuine end-to-end tests — real rendered frames
  through the complete detect→track→descent→contact→parallax→landing chain, compared
  against injected truth, across 6 positive scenarios plus 2 mandatory negative controls.
  This is the real Phase 3 gate and it holds up under review, **except for the bounce-path
  gap documented as M4 above** — every scenario currently exercises only the
  vanish-at-contact geometry, never a real bounce/reversal.
- `tests/test_io_session.py`, `tests/test_process_clip.py`,
  `tests/test_validate_static.py`: schema/I/O correctness (byte-stable round-trip, atomic
  write crash tolerance, GO/NO-GO logic tested exactly at the boundary — `< 8 points`,
  `RMS == gate`, etc.) — no vacuous "just check it runs" tests found; every test in these
  files asserts specific field values or specific verdicts.

**No vacuous/trivial tests were found.** Every test I read asserts either an exact value,
a numeric tolerance with a stated justification, a raised exception with a message-match,
or a specific flag/verdict. I did not find any test that merely calls a function and checks
it didn't crash without also checking the output.

**The one real gap in the suite (restated from M4):** it validates the pipeline thoroughly
against a scenario shape (ball vanishes at contact, `end_reason="track_end"`) that real
footage of an actual bounce will never produce (`end_reason="reversal"`). The `reversal`
branch of `find_descent` is unit-tested only against fabricated point arrays, never through
a full render→detect→track→contact chain. This is the most consequential testing gap found.

---

## 6. What could not be verified by reading code alone

These are not defects — they are the physical commissioning checklist (§8, C1–C7) by
another name, and IMPLEMENTATION_NOTES already defers all of them explicitly:

- **Real HSV thresholds under actual sun/shadow conditions.** `config.yaml`'s
  `detect.hsv_lower/hsv_upper` are explicitly labeled PLACEHOLDER; the synthetic shadow
  scenario in `simulator/scenarios.py::shadowed` is a flat dark ellipse with no soft
  penumbra (documented simplification) — real shadow edges, real ball surface wear/fuzz,
  and real ambient lighting variance are all unknown until C6.
- **Actual pixel-localisation scatter of the detector on real footage** — the synthetic
  `localisation_scatter` numbers (~0.1 px) are a lower bound on a clean render; real
  detector scatter under real motion blur, real compression artifacts, and real lighting
  is unmeasured.
- **Real intrinsics with nonzero distortion recovered through the full image path.**
  `tests/test_calibration.py::test_intrinsics_corner_level_recovers_K_and_distortion`
  validates distortion recovery only at the exact-corner level (no image rendering); the
  full `findChessboardCorners → calibrateCamera` path is validated only at **zero**
  distortion (`test_intrinsics_image_level_zero_distortion`) because rendering a distorted
  checkerboard needs a nonlinear remap the simulator doesn't implement. This is explicitly
  scoped out to C2 in both the script docstring and IMPLEMENTATION_NOTES Phase 2.
- **Rolling-shutter magnitude** — completely unmeasured (see M1); §7 item 5 requires
  characterizing it once against a falling ball or plumb line, and this has not happened
  and cannot happen without a camera.
- **ArUco detectability at real print size, real paper, real outdoor lighting** — the
  synthetic ArUco render→detect test achieved 0.88 px worst-case corner error on a clean
  digital render; real printed markers under field conditions are unverified.
- **The `manual_click_points` / `ginput` UI ergonomics** — deliberately not unit-tested
  (documented as interactive-only); IMPLEMENTATION_NOTES Phase 2 already flags "no undo,
  order-bound clicks, zoom-before-click" as fragility worth a dry run before the field
  session.
- **Actual OnePlus 12R (or replacement, per [C0]) frame-rate behavior** — whether the
  delivered rate is stable, whether `cv2.CAP_PROP_POS_FRAMES` seeks accurately on the
  phone's actual HEVC/H.264 encoding (both `load_clip_frames` and
  `load_calibration_frame`'s median-frame path rely on frame seeking, tested here only
  against MJPG/mp4v synthetic files — OpenCV's seek accuracy is known to be
  codec/container-build-dependent) — is unverified.
- **Whether the ~7 mm bracket residual holds at a real bounce (restated from M4)** — the
  current synthetic evidence structurally cannot answer this, independent of any code fix,
  because the tested scenario shape cannot occur physically. This needs either a
  `restitution > 0` synthetic scenario (partial answer, still simulated) or real footage
  (the only complete answer).
- **The §5.4 chalk-mark commissioning cross-check** — no code exists for this yet (correct,
  per spec — it's manual and commissioning-only), so its practical value can't be assessed
  from the codebase.

---

## 7. Summary punch list (for quick triage)

| # | Severity | Item | File(s) |
|---|----------|------|---------|
| M1 | Major | Uncertainty budget silently uses hardcoded defaults (`sigma_px`, `sigma_h_m`, `sigma_C_m`, `rolling_shutter_m` never wired from measurement) | `scripts/process_clip.py:90-92`, `scripts/validate_static.py:62-68`, `config.yaml` |
| M2 | Major | `fps_measured` in production path is actually `fps_nominal` copied verbatim; nothing reads real container frame rate | `scripts/process_clip.py:199-215` |
| M3 | Major | `stability_check()` (drift guard) implemented + tested but never called by any script; `homography_drift` unreachable in production | `optical/calibration.py:244-265`, `scripts/process_clip.py` |
| M4 | Major | All e2e test scenarios use `restitution=0.0` (vanish-at-contact); real bounces take the untested `reversal` branch of `find_descent`, which Phase 3 found is ~1 frame offset from true contact under an oblique view | `simulator/render.py:204`, `optical/track.py:146-152`, `tests/test_end_to_end_synthetic.py` |
| M5 | Major | §5.5 promises sub-frame fit; code implements a fixed ±0.5-frame bracket instead. Well-justified and documented in IMPLEMENTATION_NOTES, but Optical.md itself was never formally amended (§0.2 violation) | `Optical.md` §5.5, `optical/contact.py:140-153` |
| — | Moderate | Overly broad `except ValueError` in `run_clip_pipeline` can mask real config bugs as "no prediction" | `scripts/process_clip.py:74-81` |
| — | Moderate | Fallback camera K (no `--intrinsics`) fires silently, no warning, no flag | `scripts/process_clip.py:184-240` |
| — | Moderate | `validate_static.py` has no working CLI — only library functions; C7 gate run needs field glue code | `scripts/validate_static.py:136-145` |
| — | Moderate | Reversal detection has no noise robustness/hysteresis; untested under any noise model | `optical/track.py:120-129` |
| — | Moderate | `blur_suspected` and `cond_warn` flags are decorative — nothing can ever set them | `optical/io_session.py:20-25` |
| — | Moderate | Marker-survey uncertainty charged as raw constant, not propagated through the fit per §7 item 1 (conservative direction, not dangerous) | `optical/uncertainty.py:114` |
| — | Moderate | `trimmed.mp4` is undistorted + lossily re-encoded, not a verbatim trim | `scripts/process_clip.py:207-211` |
| — | Minor | Several dead-code/vestigial items, docstring/behavior mismatches, minor call-site inconsistencies | see §4 |

---

*End of audit report. Prepared as a read-only review pass per the CLAUDE.md instruction
that this project take manual backups and never be edited mid-audit; no files other than
this report were created or modified.*
