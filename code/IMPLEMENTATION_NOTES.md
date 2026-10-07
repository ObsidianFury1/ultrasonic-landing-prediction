# IMPLEMENTATION_NOTES.md — build record, deviations, findings, and spec-reconciliation

**Project:** 3D Ultrasonic Projectile Landing-Prediction System (Politecnico di Milano,
Measurements for Mechanical Engineering, A.Y. 2025–26).
**Authoritative spec:** `CLAUDE.md` (v2.5). **Companion:** `Project_File_Structure.pdf`.
**This file's purpose:** a complete, self-contained record of how the software pipeline was
actually built — every deviation from CLAUDE.md, every finding, every change, the plan used
for each step, and the test results — written so that **another agent can use it to edit
CLAUDE.md** and bring the spec into agreement with the implementation.

> **How to read this file (for the downstream CLAUDE.md editor):**
> - §A is the headline: the build-order inconsistency in CLAUDE.md §10 and the **full
>   renumbered build order** that fixes it. This is the single most important edit.
> - §B is the per-step record (plan → files → tests → deviations → findings), one section per
>   build step, in the order actually built.
> - §C is the **cross-cutting findings ledger**: places where a CLAUDE.md requirement was
>   wrong, impossible, or vacuous, with the measured evidence and the recommended spec change.
> - §D lists every API/file created that CLAUDE.md §1 does not mention.
> - §E lists open decisions (mostly `config.yaml`) deliberately left for the user.
> - §F is the consolidated, section-keyed list of recommended CLAUDE.md edits — the actionable
>   checklist. Each item points at the CLAUDE.md section to change and what to change it to.
>
> Every `→ SPEC CHANGE:` callout in §B/§C is collected in §F. When in doubt, §F is the to-do
> list; §B/§C are the justification.

**Status at time of writing:** build order completed through the §9 synthetic acceptance gate
(the last software-only milestone before firmware). **161 tests, all passing.** Nothing in
`config.yaml` or `requirements.txt` was modified. Firmware (sketches 01–05) and the live
`run_session.py` are NOT yet built (they are the next milestones).

Per-file test tally (all green):

| Test file | Tests | Step |
|---|---|---|
| test_geometry.py | 29 | 1 |
| test_simulator.py | 17 | 2 |
| test_corrections.py | 14 | 3 |
| test_trilateration.py | 11 | 4 |
| test_kalman.py | 15 | 5 |
| test_landing.py | 9 | 6 |
| test_bias.py | 15 | 7 (+1 in 8) |
| test_background.py | 14 | 8a |
| test_segmentation.py | 14 | 8b |
| test_process_throw.py | 11 | 8c |
| test_end_to_end_synthetic.py | 12 | 8d |
| **Total** | **161** | |

---

## A. The build-order inconsistency and the full renumbered build order

### A.1 The defect in CLAUDE.md §10

CLAUDE.md §10 ("Development order") lists the acceptance gate as **item 7**
(`test_end_to_end_synthetic.py`, spec §9), but §9 requires the *entire offline processing
chain run end-to-end on a session directory*, which needs three things that §10 never
schedules before item 7:

1. **`background.py`** (§5.3–5.4) — listed in the §1 repo layout and the PDF, but given **no
   build-order slot**.
2. **`segmentation.py`** (§5.5) — same: in the file tree, absent from the build order.
3. **The offline-processing orchestrator** — the "same code path as post-CLOSING in
   `run_session.py`" that §9 step 2 explicitly refers to. CLAUDE.md implies this code lives
   *inside* `run_session.py`, which is **build item 9 — two items AFTER the acceptance gate at
   item 7**. So the acceptance gate depends on code the build order schedules later. This is a
   circular dependency.

This was worked around manually by (a) building `background.py` and `segmentation.py` before
the gate, and (b) **extracting the offline chain into a new pure-orchestrator module
`pipeline/process_throw.py`** (`process_session(session_dir, config)`) that both the acceptance
test and the future `run_session.py` call. See §B-Step-8 and §D.

### A.2 Full renumbered build order (replaces CLAUDE.md §10 wholesale)

Each item lists its dependencies so the ordering is self-justifying. Items marked **[NEW SLOT]**
were missing from the original §10; **[SPLIT]** means an original §10 item is divided to match
the real dependency graph and how it was actually built.

```
SOFTWARE (no hardware; validated against the simulator)
 1. Repo scaffold, config.yaml, geometry.py + tests.
      deps: none.
 2. simulator.py + simulate_session.py.                          [built early, §0.5/§6]
      deps: geometry.
 3. corrections.py + tests.                                      [SPLIT from old item 3]
      deps: geometry, simulator (for test data).
 4. trilateration.py + tests.                                    [SPLIT from old item 3]
      deps: geometry, corrections, simulator.
 5. kalman.py + tests.
      deps: trilateration (+ chain above), simulator.
 6. landing.py (incl. R7 uncertainty) + tests.
      deps: kalman (+ chain above).
 7. bias.py + tests, then calibrate_bias.py.
      deps: landing (+ chain above) for manufacturing calibration throws; geometry.
 8. background.py + tests.                                        [NEW SLOT — was unscheduled]
      deps: corrections (echo_us_to_m), config. (Could be built any time after item 3.)
 9. segmentation.py + tests.                                     [NEW SLOT — was unscheduled]
      deps: config only (operates on a boolean validity stream).
10. process_throw.py (offline orchestrator) + tests.            [NEW MODULE — was implicit in run_session]
      deps: background, segmentation, corrections, trilateration, kalman, landing, bias(optional), geometry.
      This IS the "post-CLOSING code path" §9 refers to. process_session(session_dir, config).
11. test_end_to_end_synthetic.py (acceptance gate, §9) green,    [was old item 7]
      incl. the negative-control variants.
      deps: items 1–10 + simulator + calibrate_bias.py.
HARDWARE
12. Firmware sketches 01→05 on the bench (each gated; 05 via verify_timing.py).  [was old item 8]
13. Acquisition layer (acquisition.py) + run_session.py; dry-run.                [was old item 9]
      run_session.py reuses process_throw.process_session for the post-CLOSING path and
      segmentation.ThrowDetector for the live state machine (do NOT re-implement either).
14. characterize_static.py on hardware; update kalman.sigma_pos_m; survey S_height_m + vertices. [old 10]
15. Real campaign → calibrate_bias.py → corrected sessions → analyze_campaign.py.               [old 11]
```

→ **SPEC CHANGE (§F-1):** replace CLAUDE.md §10 with the 15-item order above. Add
`pipeline/process_throw.py` to the §1 repo layout and to the PDF's pipeline table (see §D).

---

## B. Per-step record

Each step gives the **plan used**, **files created**, **test results (with the key measured
numbers)**, **deviations from CLAUDE.md**, and **findings**. `→ SPEC CHANGE` callouts are the
edits for the downstream CLAUDE.md editor (consolidated in §F).

---

### Step 1 — geometry (`pipeline/geometry.py`, `tests/test_geometry.py`) — 29 tests ✅

**Plan.** Implement §0.1 frame + §8.1 contract as pure logic (config arrives as a parsed dict;
no YAML/file I/O in `pipeline/`). One frozen `ArrayGeometry` dataclass
(`from_config`, `vertices_3d`, `trilateration_system()` giving the constant `A` and `c` of the
general A⁻¹b form — no hardcoded closed form). `polar_to_cart`/`cart_to_polar` (degrees, θ in
(−180, 180]). Two-circle ground-truth solver (§5.5) + analytic tape-uncertainty propagation.

**Files.** `pipeline/__init__.py`, `pipeline/geometry.py`, `tests/test_geometry.py`.

**Tests (29).** Vertex construction from the real `config.yaml`; θ convention
(+x→0°, +z→+90°, −x→**+180° not −180°**); 500-sample polar round-trips; recovery of known
points through `A·[x,z]=b` to <1e−9 incl. ball-height independence (proves the equal-height
h-cancellation); conditioning of A; two-circle solver (recovery, mirror symmetry, tangent,
non-intersecting/coincident errors); uncertainty vs a 20 000-sample Monte Carlo (agrees within
5%, scales linearly with σ_tape).

**Deviations / additions.**
- **New behaviour not in spec:** a ground-truth mark lying exactly on the line through the two
  tape references (tangent circles) makes the uncertainty Jacobian singular → `ground_truth_landing`
  raises a clear `ValueError` instead of emitting NaNs. → **SPEC CHANGE (§F-9):** note this
  degenerate case in §5.5/§8.1.
- Internal: replaced `np.cross` on 2D vectors (NumPy-2.0 `DeprecationWarning`) with the explicit
  scalar 2D cross product. No interface effect.

---

### Step 2 — simulator (`pipeline/simulator.py`, `scripts/simulate_session.py`) — 17 tests ✅

**Plan.** §6 "build early" backbone. Pure logic in `simulator.py` (returns in-memory data);
all file/plot I/O in `simulate_session.py`. RK4 trajectory (exact for drag-free; quadratic drag
via RK4), physically-correct staggered sampling by fixed-point iteration
(`t_hit = t_trig + range/v`, R3), surface ranging (R2), integer echo-µs encoding at the session
temperature, timeouts, background padding, optional dropouts. Emits the **exact hardware serial
format** (`# fw=05,...` header + `sensor_id,echo_us,timestamp_us` CRLF rows).

**Files.** `pipeline/simulator.py`, `scripts/simulate_session.py`, `tests/test_simulator.py`.
Generated 3 demo sessions (seed 42, quadratic drag) under `data/sessions/`.

**Tests (17).** Closed-form/RK4 agreement; landing at y=radius; drag lands measurably short;
fixed-point timing <1 µs; echo encode/decode round-trip; background/dropout behaviour; serial
format + slot offsets (18/36 ms); seeded reproducibility; random_throw heading bounds + arc
geometry.

**Findings.**
- **No beam-cone model → unrealistic triplet count.** The simulator yields **20–22 flight
  triplets**; reality is ~5–6 (§11) because a real HC-SR04 only sees the ball inside a narrow
  ~5–8° cone over a short overlap column. The simulator instead returns any in-flight ball
  within `d_max` round-trip range. The d_max + background gates reproduce *part* of the column,
  but not the cone. → **SPEC CHANGE (§F-7):** add an optional beam-cone/visibility parameter to
  §6 (or explicitly document that the simulator over-produces triplets and that this is the
  conservative direction for the acceptance gate). This interacts with the §9 power problem
  (§C-5).

**Additions (used by later steps).** `SyntheticSession.triplet_arrays()` → `(echo, t_trig,
target)` `(N,3)` arrays (added during Step 3 for test convenience). `speed_of_sound` originally
lived here; **moved to corrections.py in Step 3** (simulator now re-imports it — single source).

---

### Step 3 — corrections (`pipeline/corrections.py`, `tests/test_corrections.py`) — 14 tests ✅

**Plan.** §8.2 chain as pure `(N,3)`-array functions: (a) `echo_us_to_m` (timeout→NaN),
(b) `add_ball_radius` (R2), `mid_echo_sample_time_us` (R3), (c) `temporal_correction`
(Option-A forward difference on `t_sample`, with optional central-difference upgrade A4),
`correct_triplets` convenience chain returning a `CorrectedTriplets` dataclass, and
`temporal_residual_vs_speed` (A4 characterization). Validate against noise-free simulator data
including the R2/R3 negative controls.

**Files.** `pipeline/corrections.py`, `tests/test_corrections.py`; edited `pipeline/simulator.py`
(import `speed_of_sound` from corrections; add `triplet_arrays`).

**Tests (14) — key measured numbers.**
- R2 negative control: without `add_ball_radius`, mean range bias **33.45 mm** vs the 33.5 mm
  ball radius (and exactly = radius on simulator data, since a constant offset passes through
  the velocity differencing untouched).
- R3 negative control: on **linear-range** data, max error **8.9e−16 m** (with mid-echo) vs
  **15.6 mm** (without) — ~1.8e13× inflation in the isolating regime.
- A4 `temporal_residual_vs_speed` (transverse pass, d=1 m): forward 17.2 / 15.2 / 10.3 / 25.1 mm
  at 1/2/3/4 m/s; central-difference 7.6 / 6.5 / 4.4 / 4.6 mm (lower at every speed).

**Deviations.**
- **`speed_of_sound` canonical home is `corrections.py`** (§5.2 is a correction); `simulator.py`
  re-imports it. → **SPEC CHANGE (§F-3):** state where `speed_of_sound` lives.
- **`mid_echo_sample_time_us` lives in `corrections.py`**, though §5.1 assigns the *computation*
  to the acquisition layer. Acquisition (build item 13) will call this helper — one tested
  formula in one place. → **SPEC CHANGE (§F-3).**
- **`central_difference` is a function kwarg, not a config key** (config.yaml has no
  `corrections:` section). Callers pass `config.get("corrections", {}).get("central_difference",
  False)`. → see §E-1 (open config decision).
- **The §8.2 headline test ("corrected ranges match true ranges to <1 mm on noise-free simulator
  data") is physically unachievable on a real curved arc** and was split — see §C-1. This is the
  most important Step-3 spec issue.

---

### Step 4 — trilateration (`pipeline/trilateration.py`, `tests/test_trilateration.py`) — 11 tests ✅

**Plan.** §8.3 as pure logic, vectorized over all N triplets: form per-triplet `b` and solve the
constant 2×2 `A`; heights from all three spheres averaged (R10a) with consistency residual `q`;
NaN guard (discard, never clamp/abs) on any negative radicand; `y_floor = y_plane + S_height_m`
(R4); `sigma_y = (d_mean/y_plane)·sigma_pos_m` (R6). `TrilaterationResult` with all-NaN invalid
rows (flags, never deletions).

**Files.** `pipeline/trilateration.py`, `tests/test_trilateration.py`.

**Tests (11) — key measured numbers.**
- Exact recovery <1e−9 m on x, z, y_floor along a noise-free arc.
- **R4 negative control:** simulator sensors at h=0.045 m, pipeline `S_height_m=0` → recovered
  y_floor wrong by **exactly 0.045 m** (asserted to 1e−9, and asserted to *fail* the exactness
  criterion); (x,z) stay exact.
- NaN guard: impossible triplet → all-NaN, neighbours untouched; 500 random range triples split
  cleanly (every valid row reconstructs its ranges to 1e−9).
- GDOP: 5 mm noise → horizontal RMS in the GDOP≈2.3 band.

**Findings (important).**
- **R10a consistency residual `q` is mathematically vacuous — see §C-2.** Three failing tests on
  the first run were all spec-expectation mismatches (q "grows with noise" — impossible; a
  "slightly-shrunk-ranges trips the guard" test that didn't trip; a σ_y "2×" factor that is
  really ~1.41×). All three were rewritten to assert the true behaviour. This is the most
  important Step-4 spec issue.
- σ_y grows toward the floor as required but by **~1.41×** between y=1.5 m and y=0.55 m, not 1/y
  (≈2.7×), because `d` grows with `y` too. Documented in the test.

---

### Step 5 — Kalman (`pipeline/kalman.py`, `tests/test_kalman.py`) — 15 tests ✅

**Plan.** §8.4 7-state `[x,y,z,vx,vy,vz,1]` on `filterpy.KalmanFilter`. Module-level `build_F(dt)`
(gravity only, via the bias-state column); F rebuilt **every** predict step from the measured Δt
of `t_sample` between consecutive used triplets; per-update `hetero_R` (R6) with constant-R
fallback; init position from first used triplet, velocity from first forward difference, generous
velocity P, bias var ≈0, zero process noise on the bias state.

**Files.** `pipeline/kalman.py`, `tests/test_kalman.py`.

**Tests (15) — key measured numbers.**
- Filtered vs raw 3D RMS: 15.7 / 16.4 / 20.5 mm vs 21.3 / 19.7 / 27.2 mm (filter wins every
  seed, asserted <0.95×).
- Velocity RMS (2nd half) 0.03–0.08 m/s (asserted <0.15).
- **Variable-dt:** a gate-style rejection produces a **108 ms** gap (asserted 0.100–0.115 s);
  filter crosses it (2.2 mm y-error, 16 mm RMS). **Negative control** (falsified uniform 54 ms
  timestamps on the same positions): y-error at the gap jumps to **17.5 mm (≈8×)**, post-gap RMS
  15.6→22.3 mm — proves F uses the measured Δt. Simulator's own dropout gives the **162 ms**
  variant; also covered.
- Bias state stays 1 to <1e−11; hetero_R on/off both run with hetero slightly better.

**Deviations.** None of substance — this step matches §8.4 directly.

---

### Step 6 — landing (`pipeline/landing.py`, `tests/test_landing.py`) — 9 tests ✅

**Plan.** §8.5. **Chose the time-parameterized fit variant** (spec-sanctioned in §8.5): x(t),z(t)
degree-1, y(t) degree-2; solve y(t*)=`ball.radius_m` on the descending branch; landing =
(x(t*),z(t*)). Rationale: the ±60° heading spread shrinks the x-span (up to 2×) and steep throws
make x-parameterization ill-conditioned, while t advances monotonically (no degenerate-x-span
abort path); gravity makes y(t) genuinely quadratic. R7 covariance via manual Vandermonde least
squares, propagated through t* to a 2×2 landing covariance → (σ_r, σ_θ). Export heading φ and
v_h for bias.py.

**Files.** `pipeline/landing.py`, `tests/test_landing.py`.

**Tests (9) — key measured numbers.**
- Landing error mean 21.5 mm, max 36.5 mm over seeds.
- **y=r_ball vs y=0:** shift **19.13 mm** vs kinematic prediction v_h·r/|v_y,impact| = **19.48 mm**
  (2% agreement).
- **R7 coverage:** over 54 random throws, 95% ellipse covered the truth **50/54 = 93%** (loose
  band per the small-sample caveat).
- Degenerate rejection: <`min_fit_points` raises the actionable message; M=4 (dof=1) still
  predicts.

**Deviations.**
- **`numpy.polyfit(cov=True)` could not be used** — it refuses M < order+3, i.e. it rejects the
  legal M=4 / dof=1 case that `min_fit_points: 4` permits and that the R7 caveat is *specifically
  about*. The module computes the identical textbook covariance `(RSS/dof)·(VᵀV)⁻¹` by hand. →
  **SPEC CHANGE (§F-6):** §8.5 says "call `numpy.polyfit(..., cov=True)`"; change to "compute the
  polyfit coefficient covariance `(RSS/dof)·(VᵀV)⁻¹` directly (polyfit's `cov=True` refuses
  dof<3, which excludes the min_fit_points=4 case)."
- **The small-sample caveat is returned as a `caveat` string field, not printed** — `pipeline/`
  has no I/O, so `run_session.py` (item 13) prints it once per session. → **SPEC CHANGE (§F-6):**
  reflect this in §8.5.
- **Added a concave-down guard** (not in spec): a flat/rising y(t) fit (curvature ≈ 0) previously
  produced an absurd far-future root; now raises a clean `ValueError`. Robustness gap. →
  **SPEC CHANGE (§F-9).**

---

### Step 7 — bias (`pipeline/bias.py`, `scripts/calibrate_bias.py`, `tests/test_bias.py`) — 14→15 tests ✅

**Plan.** §8.6/§8.7. Track-aligned residuals (rotate by per-throw φ into along/cross), scalar
significance gate via `scipy.stats.t.ppf` (never 1.96), optional linear-on-v_h mode,
`apply_correction` (rotate back, subtract in Cartesian, polar only at output), strict disjoint
calibrate/validate split, never import the Kalman layer. `calibrate_bias.py` does all I/O.

**Files.** `pipeline/bias.py`, `scripts/calibrate_bias.py`, `tests/test_bias.py`.

**Tests (14 at Step 7; 15 after a Step-8 restructure — see §C-4) — key measured numbers (n=30,
±60°).**
- Drag-ON track-frame: along-track **+48.6 mm, CI (43.8, 53.4)**, cross null; validation accepted
  (47→19 mm, p≈0.0004); all-throw error 50.8→16.1 mm.
- **Design-rationale control:** same data in the fixed array frame recovers only **33.5 mm**
  (partial cancellation; E[cos φ]≈0.83 at ±60°) and corrects worse (21.2 vs 16.1 mm) — proves the
  track frame is necessary.
- Drag-OFF: gate returns mode='none'.

**Findings (two important — drive §9 design).**
- **Power problem (§C-5):** with the *realistic* tennis-ball drag, the along-track bias at 3–4 m/s
  is only ~8 mm vs ~20 mm scatter; 12 sessions cannot reach significance (the §11 R9 formula).
  Tests use a **3× drag coefficient** (the §6 testing knob); the e2e later uses 5×.
- **Pipeline self-systematic (§C-3):** forward-difference (Option-A) corrections leave a
  ~**−24 mm** along-track systematic (the A4 curvature residual propagated to the landing).
  Central-difference shrinks it to ~−10 mm. This both erodes the drag signal and can make a
  drag-OFF gate legitimately fire.

**Deviations / fixes.**
- `numpy` scalars (`np.bool_`, `np.float64`) are **not JSON-serializable** → cast `bool(...)`/
  `float(...)` in `AxisStats`. (Caught by the persistence + script tests.)
- `calibrate_with_validation` defaults `allow_linear=False` (a 6-throw linear candidate overfits
  and fails held-out validation that the scalar model passes). Linear remains opt-in. →
  **SPEC CHANGE (§F-8):** note the scalar-default in §8.6.
- "Never touch the Kalman filter" is enforced *structurally* by a test that inspects bias.py's
  import lines (it must not import kalman). Documentation may mention it.

---

### Step 8 — gating, segmentation, orchestrator, acceptance gate — 14+14+11+12 tests ✅

This is the step that resolved the §A build-order defect. Four sub-parts.

#### 8a — background (`pipeline/background.py`, `tests/test_background.py`) — 14 tests ✅
**Plan.** §5.3–5.4 in the distance domain (`(N,3)`, NaN=timeout). `calibrate_background` with the
R1 enable logic (disable if `f0 > bg_timeout_skip` or `n_valid < bg_min_samples`; else
`w = max(k·σ, d_min_band_m)`); `reading_valid`/`triplet_valid` (§5.4 rules 1–3, rule 3 only where
enabled); `sanity_warnings` (§5.3 warn-don't-abort); `ceiling_ghost_apparent_range` (A2).
**Tests (14).** All three R1 edge cases (timeout-dominated → disabled + no NaN leakage + ball
echoes accepted; σ≈0 → w=d_min_band_m; sparse n_valid<30 → disabled); the 3 gate rules; band
rejects background / passes ball; overlap warning; ghost arithmetic + null config.

#### 8b — segmentation (`pipeline/segmentation.py`, `tests/test_segmentation.py`) — 14 tests ✅
**Plan.** §5.5 one-throw machine. `ThrowDetector.update(valid)->state` (reused live in item 13)
+ batch `segment_throw`. IDLE→ACTIVE on `arm_M` consecutive valid with **start = first arming
triplet (R5, retroactive)**; ACTIVE→CLOSING on `close_K` consecutive invalid; trailing K
stripped; one throw only; mid-throw invalid triplets stay in, flagged.
**Tests (14).** One-throw isolation; hysteresis (isolated valid never arms; <close_K invalid runs
don't close; exactly close_K does); **R5 arming triplets in buffer**; trailing-K strip; mid-throw
invalid retained; no-throw→None; end-of-stream close; second throw ignored.

#### 8c — offline orchestrator (`pipeline/process_throw.py`, `tests/test_process_throw.py`) — 11 tests ✅
**This is the new module that fixes the §9 dependency gap (§A).**
**Plan.** `process_session(session_dir, config, *, model=None, _negative_control=None)` runs the
full post-CLOSING chain: parse `raw_serial.log` → background calibrate/load → §5.4 gate →
`segment_throw` → corrections → trilateration → Kalman → landing → optional bias → write
`background.json`, `triplets_raw.csv`, `trajectory.csv`, update `session.json`. Plus pure parsing
helpers (`parse_serial_lines`, `unwrap_micros` [R10c], `assemble_triplets`) that **acquisition.py
will reuse**.
**Tests (11).** micros() rollover unwrap incl. double rollover (R10c); malformed-line resync;
header-mismatch warning; round-trip on a simulator-written session dir (files + schema + accuracy
<80 mm); R5 arming in `in_throw`; background-only session → "no throw" `ValueError`;
unknown-control rejection.

**Deviation (important & openly stated):** `process_throw.py` performs **file I/O on the session
directory**, breaking the "`pipeline/` has no I/O" rule of §1/§8 intro. This is deliberate — it is
the orchestrator `process_session(session_dir, config)` the user specified, and it is what §9 step
2 calls "the same code path as post-CLOSING in `run_session.py`". The *pure* pipeline modules it
calls remain I/O-free; only this orchestrator and the `scripts/` touch the filesystem. →
**SPEC CHANGE (§F-2):** add `process_throw.py` to §1 with an explicit note that it (and `scripts/`)
are the I/O layer, and that the no-I/O rule applies to the *computational* modules.

#### 8d — acceptance gate (`tests/test_end_to_end_synthetic.py`) — 12 tests ✅
**Plan.** §9: 12 drag-ON + 12 drag-OFF synthetic sessions through `process_session`, asserting
one-throw segmentation (R5), landing accuracy, the three negative controls, a significant bias
model, drag-OFF→'none', and R7 coverage. Shared `tests/session_factory.py` writes session dirs in
the simulator's on-disk format.
**Tests (12) — key measured numbers.**
- Every session → exactly one throw; R5 arming in buffer; both R1 background regimes present.
- **Baseline (drag-OFF) accuracy:** mean 47.3 mm, max 100.7 mm.
- **Negative controls:** ball-radius off → mean **80.5 mm (FAILS)**; sensor-height off → **64.7 mm
  (FAILS)** — each its own test; mid-echo off → Δ **+0.1 mm (cannot fail, see §C-1)**.
- **Bias chain** via the real `calibrate_bias.py` subprocess: scalar track model, along
  **+49.8 mm, CI (33.6, 66.1)**, validation 63→34 mm (p=0.004); corrected beats raw (~34 mm);
  drag-OFF→'none'.
- R7 coverage 9/12; caveat recorded per session.

**Design decisions taken in 8d (all measured, all documented in the test module):**
1. **Forward mode + drag k×5** won a 2×2 decision matrix (mode × drag strength). Production config
   is **unchanged** — central_difference is NOT needed in production; forward mode passes the gate
   and keeps drag-OFF at 'none'. k×3 lacked validation power (p=0.08–0.22).
2. **Accuracy + R2/R4 controls run on the drag-OFF set** (drag-ON's deliberate ~50 mm overshoot
   masks/partially cancels the correction-removal effects).
3. **The R3 (mid-echo) control cannot fail an honest end-to-end criterion** — see §C-1.
4. A static reflector at **1.55 m closed the throw mid-flight** (the §5.3 "room must change"
   scenario); the gate uses 1.95 m. Documented in `test_process_throw.py`.
5. `cov_xz_m2` added to the `session.json` prediction block (R7 coverage needs the full 2×2).
6. New shared test helper `tests/session_factory.py` (not a spec file).

---

## C. Cross-cutting findings ledger (spec requirements that were wrong / impossible / vacuous)

These are the cases where a CLAUDE.md assertion could not hold as written. Each has measured
evidence and a recommended spec change. **These are the most important inputs to the CLAUDE.md
edit.**

### C-1. §8.2 / §9: the mid-echo (R3) correction is real but NOT end-to-end-detectable; and the "<1 mm" headline is impossible on curved arcs
- **§8.2 headline test** ("noise-free simulator → corrected ranges match true ranges at the S1
  instant to <1 mm") is **physically impossible on a real curved arc**: gravity makes the radial
  distance curve everywhere (not just at zenith), giving a curvature residual measured at **max
  27 mm / RMS 8.5 mm** on a representative throw. The §8.2 A4 note already concedes a ~1–2 cm
  zenith residual — it just isn't reconciled with the <1 mm test.
  **Resolution implemented:** the accuracy claim is split — on **constant-range-rate (linear)
  data**, where Option A's model is exact, the chain is <1e−6 m (satisfies "<1 mm"); on simulator
  **arcs**, the test asserts the curvature-bounded residual (<3 cm) AND that the correction halves
  the error vs leaving ranges unaligned.
- **§9 step 3** says "disable any one of [R2/R3/R4] and the test must FAIL ... in three
  negative-control variants." **R3 cannot fail any honest end-to-end criterion.** Measured four
  ways: landing error paired Δ **+0.1 mm**; in all four mode×drag configs; aligned-range residuals
  at σ=8 mm (identical medians); noise-free twins (identical to ±0.2 mm). The differential mid-echo
  error (±1–2 ms ≈ up to ~1 cm *per reading*) is averaged out by the landing fit and swamped by
  the curvature residual everywhere else.
  **Resolution implemented:** R3's load-bearing negative control is at **unit level**
  (`test_corrections.py`, ~1.8e13× error inflation in the isolating linear regime). The e2e R3
  variant runs and **pins down the below-noise-floor finding** (asserts |Δ|<5 mm) instead of
  asserting a failure physics does not produce.
- → **SPEC CHANGE (§F-4):** rewrite the §8.2 accuracy test wording (linear-exact vs arc-bounded)
  and amend §9 step 3 to say R2 and R4 fail the end-to-end criterion while **R3 is verified at unit
  level and is below the noise floor end-to-end** (the correction is kept because it is exact and
  free, not because it changes headline accuracy).

### C-2. §8.3 R10a: the 3-sphere consistency residual `q` is identically zero by construction (vacuous)
- §8.3/§5.6/R10a specify `q = max_k |y_k − y_plane|` as a per-triplet quality flag and the §9/
  §8.3 tests expect "q ≈ 0 noise-free, **grows with noise**." **The growth is mathematically
  impossible.** The 2×2 solve *is* the pair of equations "radicand₁ = radicand₂" and
  "radicand₁ = radicand₃"; the solved (x,z) forces all three radicands — hence all three y_k —
  **identical for any input ranges**. Measured: q < 1e−15 even with 8 mm noise and even on 2000
  arbitrary (non-physical) range triples. Three ranges, three unknowns: zero redundancy, so no
  per-triplet consistency residual can exist (a genuine one needs a 4th sensor).
- **Resolution implemented:** `q` is still computed and stored for §5.6 schema compatibility and as
  a numerical-sanity check (~1e−16); the test pins the algebraic fact; the docstring records it.
  The working quality gates (NaN guard, validity flags) are unaffected.
- → **SPEC CHANGE (§F-5):** in §8.3/R10a, replace "consistency residual that grows with noise /
  quality flag" with a statement that `q ≡ 0` by construction for a 3-sensor triplet (kept only as
  a numerical check), and that genuine per-triplet consistency would require a 4th sensor (future
  work). Remove the "grows with noise" expectation from §8.3 and §9.

### C-3. Pipeline carries its own throw-aligned systematic (forward-difference curvature → landing)
- The A4 curvature residual (C-1) propagates to a **~−24 mm along-track** landing bias with
  forward differences, **~−10 mm with central differences**. Consequence: at n≈30 the bias gate
  *correctly* detects a small negative along-track offset on **drag-free** data (empirical bias
  correction fixes any throw-aligned systematic, drag or not). This is why "drag-OFF ⇒ mode='none'"
  is really "**no real bias ⇒ mode='none'**", and why the acceptance gate keeps n=12 (where the
  ~10 mm systematic is below detection power → 'none').
- → **SPEC CHANGE (§F-4/§F-8):** §8.6/§9 should frame the drag-OFF control as "the gate invents no
  correction when there is no *statistically resolvable* throw-aligned bias at the tested N," and
  note the pipeline's own small central-difference residual as a known systematic in the error
  budget (§11).

### C-4. §8.6 drag-OFF test restructured (consequence of C-3 + n)
- The original `test_bias` drag-OFF assertion (`mode == 'none'` on 30 pipeline drag-free throws)
  became false once `allow_linear` defaulted off *and* 30 records made the ~−10 mm systematic
  resolvable. Split into two honest tests: **pure zero-mean-noise records → 'none'** (the gate's
  true null control), and **pipeline drag-free records → small negative scalar detected** (C-3).
  This is the +1 test that took `test_bias` from 14 to 15.

### C-5. §9 power: 12 drag-ON sessions cannot reach significance with realistic drag
- With the true tennis-ball drag coefficient the along-track bias (~8 mm) is far below the ~20 mm
  landing scatter; the §11 R9 power estimate needs ~30 throws. The acceptance gate uses a **5×
  drag coefficient** (the §6 testing knob) so n=12 accepts at p=0.004. The **real campaign's 15–20
  throws (R9) is therefore tight, not comfortable**, for realistic drag.
- → **SPEC CHANGE (§F-4):** §9 should state the drag-coefficient test knob (and value) used to give
  the 12-session gate statistical power, and §11/R9 should be re-examined against the measured
  ~8 mm realistic bias (the campaign may need more than 15–20 throws, or the analysis should accept
  "drag below noise floor" as the likely realistic outcome).

### C-6. σ_y growth weaker than 1/y (minor)
- R6's `sigma_y=(d/y)·σ_pos` grows toward the floor but only **~1.41×** from y=1.5→0.55 m (not
  ~2.7×), because d grows with y. Cosmetic; documented in the test. → optional note in §8.3.

---

## D. Files and APIs created that CLAUDE.md §1 does not list

**New files (add to §1 repo layout / PDF):**
- `pipeline/process_throw.py` — offline orchestrator (`process_session`) + serial parsing helpers.
  **Not in the spec tree at all.** The single most important addition (§A). I/O layer.
- `tests/session_factory.py` — shared test helper writing session dirs in the simulator's on-disk
  format (used by `test_process_throw` and `test_end_to_end_synthetic`).

**Public APIs created (beyond the spec's prose), by module — useful for the editor to cross-check
the §1/PDF "Writes/returns" columns:**
- geometry: `ArrayGeometry` (`from_config`, `vertices_3d`, `trilateration_system`),
  `polar_to_cart`, `cart_to_polar`, `two_circle_intersection`, `ground_truth_landing`.
- simulator: `ThrowParams`, `Trajectory`, `SyntheticSession` (+ `triplet_arrays`),
  `simulate_trajectory`, `random_throw`, `generate_session`, `default_drag_k`, `ballistic_position`.
- corrections: `speed_of_sound` (**canonical home**), `echo_us_to_m`, `mid_echo_sample_time_us`,
  `add_ball_radius`, `temporal_correction`, `CorrectedTriplets`, `correct_triplets`,
  `temporal_residual_vs_speed`.
- trilateration: `TrilaterationResult`, `trilaterate`.
- kalman: `G`, `build_F`, `FilterResult`, `filter_trajectory`.
- landing: `LandingPrediction`, `predict_landing`, `ABORT_MESSAGE`, `CAVEAT_TEMPLATE`.
- bias: `ThrowRecord`, `AxisStats`, `CorrectionModel` (+`frame="track"`, `to_dict`/`from_dict`),
  `to_track`/`from_track`, `calibrate`, `apply_correction`, `evaluate`, `calibrate_with_validation`.
- background: `SensorBackground`, `BackgroundModel`, `calibrate_background`, `reading_valid`,
  `triplet_valid`, `sanity_warnings`, `ceiling_ghost_apparent_range`.
- segmentation: `ThrowDetector`, `ThrowSegment`, `segment_throw`, `IDLE`/`ACTIVE`/`CLOSED`.
- process_throw: `parse_serial_lines`, `unwrap_micros`, `assemble_triplets`, `process_session`,
  `ProcessedSession`, `MICROS_ROLLOVER`, `NEGATIVE_CONTROLS`.

---

## E. Open decisions left for the user (mostly config.yaml — NOT modified)

`config.yaml` and `requirements.txt` were deliberately never edited. Pending items:

- **E-1. `corrections:` config section.** `central_difference` is currently a function kwarg read
  via `config.get("corrections", {}).get("central_difference", False)`. The A4 upgrade is *named*
  in the spec as a config flag. **Production currently uses forward mode (False)** — the acceptance
  gate passes that way — so adding the section is optional. If the central-difference residual
  (~−10 mm, C-3) is to be reduced in production, add:
  ```yaml
  corrections:
    central_difference: false   # A4 upgrade; true cancels the leading curvature bias
  ```
- **E-2. Beam-cone / detectability (C-5, §F-7).** Whether to add an optional simulator visibility
  parameter so synthetic triplet counts match reality (~5–6, not 20–22).
- **E-3. Realistic-drag campaign size (C-5).** Whether §11/R9's 15–20 throws is sufficient given
  the measured ~8 mm realistic bias.

---

## F. Consolidated recommended CLAUDE.md edits (the actionable checklist)

Keyed by spec section. Each references the §B/§C justification.

- **F-1 (§10, §1):** Replace §10 with the **15-item renumbered build order** in §A.2. Add
  `pipeline/process_throw.py` to the §1 repo layout. *(Justification: §A.)*
- **F-2 (§1, §8 intro):** Add `process_throw.py` to the repo tree and the PDF pipeline table;
  clarify that the "no I/O in `pipeline/`" rule applies to the *computational* modules, while
  `process_throw.py` and `scripts/` are the I/O layer. *(§B-8c.)*
- **F-3 (§5.1, §5.2):** State that `speed_of_sound` and `mid_echo_sample_time_us` live in
  `corrections.py` (single tested source); acquisition calls the helper. *(§B-3.)*
- **F-4 (§8.2, §9):** Rewrite the §8.2 accuracy test as **linear-exact (<1 mm) + arc-bounded
  (<3 cm, halves error vs uncorrected)**; amend §9 step 3 so **R2 and R4 fail the end-to-end
  criterion** while **R3 is verified at unit level and is below the noise floor end-to-end**; state
  the **drag-coefficient test knob (×5)** used to give the 12-session gate power, and that
  accuracy/R2/R4 controls run on the **drag-OFF** set. *(§C-1, §C-3, §C-5.)*
- **F-5 (§8.3, §5.6, R10a, §9):** State that the 3-sphere consistency residual `q ≡ 0` by
  construction for a 3-sensor triplet (kept only as a numerical sanity check); remove the
  "grows with noise" expectation; note that genuine per-triplet consistency needs a 4th sensor
  (future work). *(§C-2.)*
- **F-6 (§8.5):** Replace "`numpy.polyfit(..., cov=True)`" with the manual
  `(RSS/dof)·(VᵀV)⁻¹` covariance (polyfit refuses dof<3, excluding min_fit_points=4); record that
  the time-parameterized variant was chosen; note the caveat is returned as a string and printed by
  `run_session.py`; add the concave-down guard to the robustness clause. *(§B-6.)*
- **F-7 (§6, §11):** Add an optional beam-cone/visibility parameter (or document that the simulator
  over-produces triplets, the conservative direction). *(§B-2, §C-5, §E-2.)*
- **F-8 (§8.6):** Note `calibrate_with_validation` defaults to scalar-only (linear opt-in,
  overfits on small calibration halves); reframe the drag-OFF gate as "no *statistically
  resolvable* throw-aligned bias ⇒ 'none'" and record the pipeline's own ~−10 mm central-difference
  systematic in the §11 error budget. *(§B-7, §C-3, §C-4.)*
- **F-9 (§5.5, §8.1, §8.5):** Document the new clean-failure paths added for robustness:
  ground-truth mark on the reference line → `ValueError` (§8.1); landing fit not concave-down →
  `ValueError` (§8.5). *(§B-1, §B-6.)*
- **F-10 (config.yaml, §2):** Decide on the optional `corrections:` section (E-1). Production is
  forward mode; documented as a user decision, not yet applied.

---

## G. What is NOT done (next milestones, unchanged from spec intent)

Firmware sketches 01–05 (§4) and `verify_timing.py`; the live acquisition layer
(`pipeline/acquisition.py`) and `scripts/run_session.py` (§5, §5.7) — which must reuse
`process_throw.process_session` (post-CLOSING) and `segmentation.ThrowDetector` (live machine),
not re-implement them; `characterize_static.py`; `analyze_campaign.py`; `append_ground_truth.py`;
`reporting.py`. These are build items 12–15 in §A.2.

---
---

# PART 2 — v2.2 implementation (D1–D4) — as-built record

> **Context for the downstream editor.** Everything above (§A–§G) documents the build through
> the §9 acceptance gate under spec **v2.1** and *recommended* the v2.2 changes (the §F items).
> This Part 2 records the **actual v2.2 implementation** done afterward against `CHANGES.md` +
> `CLAUDE.md v2.2`. Several §F recommendations are now **implemented** — cross-references are
> marked `[was §F-x]`. CLAUDE.md and config.yaml were already at v2.2 when this work started;
> the deltas below are code + tests + two config bug-fixes.
>
> **Final state: 176 tests passing** (161 pre-v2.2 + 15 new). Order of work: D4 → D2 → D1 →
> §9 re-validation → D3 (the dependency-safe order from `CHANGES.md`).

## H. Headline: two config.yaml bugs found at the v2.2 baseline (before any code)

The v2.2 work order asserted "config.yaml is correct as-is; do not recreate it." It was **not** —
the regenerated v2.2 `config.yaml` had two defects that made the suite red before a single line of
D1–D4 was written. Both were fixed (the q_scale fix was explicitly user-approved; the gates
restoration was load-bearing and is flagged for confirmation).

- **H-1. `q_scale: 1e-4` parsed as the STRING `'1e-4'`.** YAML 1.1's float resolver requires a
  decimal point or a sign in the exponent; bare `1e-4` is a string. `np.eye(6) * '1e-4'` raises,
  so every config-driven Kalman call (test_kalman, test_landing, test_bias chains,
  test_process_throw, the whole e2e) failed at import-of-config. **Fix:** `1e-4` → `1.0e-4`
  (restores the v2.1 value/type; one character). A comment now warns against the bare form.
  → **SPEC/CONFIG NOTE:** any future regeneration of config.yaml must keep the decimal point on
  exponential floats.
- **H-2. The entire `gates:` block was missing from v2.2 config.yaml.** CLAUDE.md §2 (authoritative
  schema) mandates `gates:` (`d_max_m`, `bg_k_sigma`, `bg_n_triplets`, `bg_min_samples`,
  `bg_timeout_skip`, `d_min_band_m`, `arm_M`, `close_K`). Its absence broke 41 tests
  (background, segmentation, process_throw, simulator padding all read `config["gates"]`).
  **Fix:** restored the block verbatim from CLAUDE.md §2 / v2.1, with a comment marking it as a
  v2.2-regression restoration. → **CONFIG NOTE:** confirm this block belongs in the canonical
  config.yaml (it does — it is in the CLAUDE.md §2 schema).

Baseline after both fixes: 158 passed / 3 failed (the 3 e2e failures were the pre-existing
pure-central-mode gate reds, resolved later by D1 — see §K).

## I. D4 — unique session directory names ✅  `[was §F-implicit / D4]`

**Plan.** Name scheme `sim_YYYY-MM-DD_HHMMSS_S##`; ONE `datetime.now()` captured at batch start and
shared by the whole batch; 1-based `S##` counter for within-batch (same-second) uniqueness;
`RuntimeError` instead of overwrite; add `--beam-cone {on,off}` CLI (needed by D2).

**Files.** `pipeline/simulator.py` (new pure `session_directory_names(config, n_sessions, when)` —
no `datetime.now()` inside the pure module; `when` is injected), `scripts/simulate_session.py`
(batch-start datetime, `create_session_folder` with the existence guard, `--beam-cone` flag),
`tests/test_simulator.py` (+3).

**Tests (3 new).** `test_session_names_unique_in_batch` (12 distinct names);
`test_session_name_format` (regex `^sim_\d{4}-\d{2}-\d{2}_\d{6}_S\d{2}$`, and S03 example exact);
`test_session_names_no_overwrite_across_runs` (two datetimes ≥1 s → disjoint; same datetime →
deterministic + the on-disk existence guard raises `RuntimeError`).

**Verified end-to-end:** a `simulate_session.py --n-sessions 3 --beam-cone off` run produced
`sim_2026-06-13_104049_S01/_S02/_S03` (shared timestamp, incrementing counter); seeds identical to
the v2.1 demo (cone-off is byte-identical legacy).

## J. D2 — beam-cone visibility model (simulator) ✅  `[implements §F-7]`

**Plan.** Gate synthetic ball detections to the transducer cone so triplet counts approach reality.

**Files.** `pipeline/simulator.py` only (+ CLI wiring already in `simulate_session.py`).
- `sensor_aim_axes(geometry, tilt_deg)` → (3,3) unit vectors: horizontal component from each vertex
  toward the centroid, elevated `tilt_deg`; **derived from `ArrayGeometry.vertices_xz`, never
  hardcoded** (ties to the §0.1 frame).
- `angle_from_axis_deg(point, sensor_pos, axis)` helper.
- `generate_session(..., beam_cone_enabled=False, beam_half_angle_deg=None)`: per reading, if
  enabled and the ball at the interrogation instant is outside the half-angle → **timeout
  (echo 0)**, flagged `cone_gated`. Half-angle defaults to `config["simulator"]["beam_half_angle_deg"]`.

**Key design decision (deviation from a naïve reading of the work order).** `beam_cone_enabled`
is an **opt-in kwarg defaulting to False (legacy)**, NOT auto-read from config inside
`generate_session`. Reason: every existing test passes the real config (now `beam_cone_enabled:
true`) into `generate_session`; if the kwarg auto-honored that, cone-thinned 5–6-triplet data would
break/hang suites built for the over-producing regime (e.g. test_bias's `n_points ≥ 8` retry loop
would spin). The config key is honored at the **entry points that should obey it**:
`simulate_session.py` (config + `--beam-cone` override) and the e2e density test (passes it
explicitly). Simplification, per the work order: a cone-gated reading is a plain timeout even when a
static background reflector is configured (gating the reflector would silently alter the R1
regimes). `cone_gated` is recorded per reading.

**Tests (4 new).** `test_cone_axis_from_geometry` (axis == tilt-elevated inward unit vector from the
configured vertices); `test_cone_gates_offaxis` (geometric construction at half_angle ∓0.5°, plus
integration: every `cone_gated` reading is a timeout whose cone-off twin was detectable and is
outside the cone; every detection is inside); `test_cone_reduces_triplet_count` (overlap-aimed lob:
cone-on in the band [3, 10], cone-off ≥ 2× more); `test_cone_disabled_matches_legacy` (same seed,
`False` → serial lines **byte-identical** to the default path — the regression guard).

**Finding (surfaced, not silenced) — the 7° estimate is inconsistent with the campaign profile.**
Measured: at the config's **7° half-angle, campaign-speed `random_throw`s (3–4 m/s) yield ZERO
cone-on triplets** (0/200 attempts). Only **slow apex-at-overlap lobs** are admitted, and those give
**3–4** triplets — right at the `min_fit_points=4` floor, not the spec's "~5–6". The 7° figure is
inconsistent with both the campaign throw profile and the spec's own "~5–6 triplets" claim;
config.yaml and CLAUDE.md already flag `beam_half_angle_deg` as **UNVERIFIED, to be tuned against §7
static detectability data**. → **SPEC NOTE (extends §F-7):** when §7 hardware data exists, retune
`beam_half_angle_deg`; until then synthetic absolute triplet counts at cone-on are not trustworthy
(the over-producing cone-off mode remains the conservative default for the headline gate).

## K. D1 — hybrid finite-difference temporal stencil (production default) ✅  `[implements §F-8 / C-3]`

**Plan.** Replace the old pure-central `central_difference=True` path with the **hybrid** stencil:
forward@first / central@interior / backward@last; keep ALL N triplets; NaN fallback to the
available one-sided difference, both-invalid → unusable (never a velocity from one point).
`central_difference=False` stays byte-exact legacy forward-only.

**Files.** `pipeline/corrections.py` only.
- `temporal_correction(..., central_difference=True)` now builds `v_fwd`/`v_bwd`/`v_cen` candidate
  arrays, selects forward@0 / backward@N−1 / central@interior, then `np.where(finite(v), v,
  where(finite(v_fwd), v_fwd, v_bwd))` for the fallback (the endpoints' unavailable one-sided diff
  is already NaN, so the fallback cannot invent a value there).
- `temporal_residual_vs_speed` gained additive keys `forward_interior_m` / `central_interior_m`
  (interior = in-flight triplets excluding the first/last, where both modes use the same one-sided
  stencil; needed because hybrid endpoint residuals tie with forward).

**Tests (4 new + 2 existing expectations re-stated).**
- New: `test_hybrid_stencil_selection_linear` (<1e−9 m at every triplet incl. both endpoints on
  linear data); `test_hybrid_retains_all_triplets` (central → N usable, forward → N−1);
  `test_hybrid_nan_fallback` (interior-predecessor timeout → forward fallback, still exact;
  last triplet still backward-corrected when the timeout is elsewhere; both neighbours invalid →
  unusable, no NaN velocity); `test_hybrid_reduces_interior_residual` (interior residual strictly
  lower than forward at 1/2/3/4 m/s).
- **Two EXISTING `test_corrections.py` assertions were updated** (the documented, plan-approved
  exception to "don't modify existing tests" — D1 *redefines* `central_difference=True`, so these
  encoded the pure-central behaviour being replaced; per the `CHANGES.md` golden rule, the
  expectation is fixed to the truth):
  - `test_usable_flags_forward_and_central`: central mode now keeps all N (`[True]*6`), was
    `[False]+[True]*4+[False]`.
  - `test_residual_characterized`: hybrid's *worst* residual **ties** forward at the endpoints
    (same one-sided stencil), so the strict `cen < fwd` moved to the **interior** residual; overall
    is now `cen ≤ fwd`.

**Measured (`temporal_residual_vs_speed`, hybrid):** interior residual forward → hybrid:
17.2→7.6, 15.2→6.5, 10.3→4.4, 13.9→4.6 mm at 1/2/3/4 m/s; overall worst ties at 25.1 mm at 4 m/s
(an endpoint). Net pipeline self-systematic ~−12 to −15 mm (between forward −24 and pure-central
−10), as CLAUDE.md v2.2 predicts. This **implements the §F-8 / §C-3 recommendation** (it is no
longer just "recommended").

## L. §9 re-validation under the new production defaults ✅

**Plan.** Re-run the full acceptance gate now that `central_difference: true` means the *real*
hybrid (not the old pure-central), and add the two D1/D2 gate tests.

**Outcome — the 3 pre-existing e2e reds resolved themselves under hybrid.** They were failing under
the old pure-central path (rejected drag-ON model p≈0.08, weak R4 margins); hybrid's all-N retention
+ ~−13 mm systematic restored the gate to ~forward-mode behaviour and all 12 original e2e tests pass.

**Tests (3 new — work order asked for 2; a 3rd surgical demonstration was added).**
- `test_gate_drag_off_none_hybrid`: drag-OFF at n=12 under hybrid → **mode='none'**, measured
  along-track **−9.3 mm, 95% CI [−52.6, +34.0]** (spans zero → unresolved). **The `CHANGES.md`
  stopping condition was NOT triggered.** The test codes the documented fallback branch (if a future
  change resolves it: assert −20 mm < offset < 0 and mode='scalar', i.e. the self-systematic, not
  drag — never silence the gate).
- `test_gate_density_realistic_cone` (D1×D2 interaction): cone-on slow lobs each either fit with
  n_points ≥ min_fit_points OR raise the actionable "slower/loftier" message; asserts both arms are
  exercised (not vacuous).
- `test_hybrid_recovers_last_triplet_for_cone_fit` (**the +1 beyond the work order's 14**): a cone-on
  throw admitting **exactly 4** triplets **fits under hybrid** (all 4 retained) but is **refused
  under forward mode** (last dropped → 3 < min_fit_points) — the precise, deterministic reason
  hybrid is the production default for cone-thinned data. This is why the final count is **176, not
  175**.

**Guardrails confirmed:** R2 & R4 e2e controls still FAIL; R3 still |Δ| < 5 mm; drag-ON model still
accepted (along +49.8 mm, p=0.004); corrected < raw. The e2e module docstring was corrected (it
still claimed forward-mode was the production default).

## M. D3 — campaign power note (`calibrate_bias.py`) ✅  `[implements §F-8 / D3]`

**Plan.** Report the N at which a two-sided 95% CI would exclude the observed along-track bias.

**Files.** `scripts/calibrate_bias.py` only.
- `power_n(scatter, bias, n, alpha)` → `ceil((t_crit·s/b)²)` with `t_crit =
  scipy.stats.t.ppf(1−α/2, n−1)` (never 1.96); `b≈0` → `None` ("not estimable").
- Prints "Statistical power note: CI excludes zero at approximately N=… throws. Current N=…" and,
  when `mode='none'` AND `N < N_power`, "Null result is consistent with 'drag below noise floor at
  this sample size', not a pipeline failure." Both also stored in the report JSON (`power_n`,
  `power_note`, `underpowered_null`, `underpowered_null_note`).

**Test (1 new).** `test_power_note_reads_below_threshold`: a 12-session set with a tiny 3 mm
along-track bias in ~20 mm scatter → gate 'none', finite `power_n` (hundreds) > N, underpowered-null
message present in both stdout and report JSON.

## N. v2.2 file-touch summary and guardrail compliance

**Modified:** `config.yaml` (H-1 q_scale, H-2 gates restore), `pipeline/simulator.py` (D4, D2),
`scripts/simulate_session.py` (D4, D2 CLI), `pipeline/corrections.py` (D1),
`scripts/calibrate_bias.py` (D3); tests `test_simulator.py` (+7), `test_corrections.py`
(+4, 2 re-stated), `test_end_to_end_synthetic.py` (+3, docstring fixed), `test_bias.py` (+1).

**Untouched (per guardrails):** `geometry.py`, `trilateration.py`, `kalman.py`, `landing.py`,
`background.py`, `segmentation.py`, `process_throw.py` and all their tests.

**Guardrails honored:** legacy paths byte-identical (`central_difference: false` → forward,
verified by unchanged forward tests; `beam_cone_enabled: false` → legacy, verified by
`test_cone_disabled_matches_legacy`); `bias.py` still imports nothing from `kalman.py` (structural
test green); no new file I/O in `corrections.py` / `simulator.py`. The single intentional
exception to "don't modify existing tests" is the two D1 corrections expectations (§K), which D1's
semantics force and the approved plan pre-authorized.

**New-test ledger (15):** D4 ×3 (test_simulator), D2 ×4 (test_simulator), D1 ×4 (test_corrections),
§9 re-val ×3 (test_end_to_end_synthetic), D3 ×1 (test_bias). 161 + 15 = **176 passed, 0 failed**.

## O. §F status after Part 2 (for the CLAUDE.md editor)

Of the §F recommendations, these are now **implemented in code** (the spec text should be updated to
match the as-built behaviour, but no code change is needed): **§F-7** (beam cone — D2, with the
7°-tuning caveat of §J), **§F-8** (hybrid stencil + scalar-default + power note — D1/D3/§K/§M).
The rest of §F (F-1…F-6, F-9, F-10) remain **documentation/spec edits only** and are unaffected by
Part 2 — except **F-10**, which is now partly moot: the `corrections:` block exists in config.yaml
(central_difference: true) and the `simulator:` block was added for D2/D4; the open config question
that remains is only the §7-tuning of `beam_half_angle_deg`.

---
---

# PART 3 — firmware (CLAUDE.md §10 item 12) + verify_timing.py — as-built record

> **Context for the downstream editor.** Parts 1–2 cover the SOFTWARE half (§10 items 1–11) through
> the §9 acceptance gate, 176 tests green. Part 3 records the first **hardware-phase** deliverable:
> the five incremental Arduino sketches (§4) and the PC-side timing gate `scripts/verify_timing.py`
> (the real test for sketch 05). **The Arduino Uno + 3× HC-SR04 kit is NOT yet in hand**, so the
> bench pass/fail criteria cannot actually be exercised; what was produced is bench-ready firmware
> and an offline-testable verifier. This part is written so a later session (with hardware) can flash,
> gate, and move to item 13 without re-deriving anything.
>
> **State after Part 3:** 6 new files (5 `.ino` + 1 script). **Zero** changes to `pipeline/`,
> `config.yaml`, or any test — the 176-test suite is untouched and still green by construction. The
> firmware bench gates (§4) remain OPEN pending hardware; the `verify_timing.py` offline self-test
> PASSES against simulator output.

## P. Scope and guardrails honored

Task scope was explicit: **firmware `.ino` files and `verify_timing.py` ONLY**. No pipeline code,
no config edits, no test edits. `verify_timing.py` **reuses** the existing
`pipeline.process_throw` helpers (`parse_serial_lines`, `unwrap_micros`, `assemble_triplets`) and
reimplements none of them — the named must-reuse helper was `unwrap_micros`; the other two were
reused for DRY consistency with the rest of the pipeline (reusing pipeline functions is not
"writing pipeline code", and no pipeline module was modified). Confirmed honored.

## Q. Files created

```
firmware/01_single_sensor/01_single_sensor.ino
firmware/02_timeout_discipline/02_timeout_discipline.ino
firmware/03_three_sequential/03_three_sequential.ino
firmware/04_serial_csv/04_serial_csv.ino
firmware/05_timing_verify/05_timing_verify.ino        # the flight firmware
scripts/verify_timing.py                              # sketch 05's PC-side test
```
`firmware/` did not exist before this step. The five sketches are the §4 incremental ladder; each
`.ino` opens with a **comment block quoting its §4 bench pass/fail criterion verbatim**, so the
criterion is hand-checked after upload, never assumed (as the task required).

## R. Approach / design decisions (per the approved plan)

- **Pin map (§3, fixed, do not deviate):** `TRIG[]={2,4,6}`, `ECHO[]={3,5,7}` for S1/S2/S3.
- **Firmware rules (§4) applied throughout:** plain `digitalWrite`/`pulseIn`/`micros()`, no
  interrupts, no timer libraries; TRIG pulse `LOW 2µs → HIGH 10µs → LOW`; `pulseIn` timeout returns
  `0` → emitted as the literal no-echo sentinel; **Serial 115200 baud** (NOT raised — §12 audit
  rejected 500000 on an incorrect buffer-overflow mechanism).
- **Absolute, no-drift scheduler (sketches 02–05):** `next_slot_us += 18000UL;` then
  busy-wait `while ((long)(micros() - next_slot_us) < 0) {}`. The **signed-long cast** makes the
  comparison correct across the `micros()` 32-bit rollover. Chosen idiom over any relative
  `delay()` so there is no cumulative drift (§4 requirement).
- **Busy-wait-THEN-fire ordering (key timing decision).** Each slot first waits to its boundary,
  *then* fires. This makes **every** fire — including the very first — boundary-aligned, so the
  recorded `t_trig` values are exact slot multiples apart: per-sensor period = 54 ms, intra-triplet
  offsets = 18 ms / 36 ms, to within microsecond jitter. (Fire-then-wait would leave the first fire
  unaligned.) `next_slot_us` is seeded to `micros()` in `setup()`.
- **`t_trig` captured at the TRIG HIGH edge, never mid-echo.** Per R3/§5.1 the mid-echo sample-time
  correction (`t_trig + echo/2`) is Python's job; the firmware streams only `micros()` at the
  trigger instant. `t_trig` is recorded *before* the `Serial.print`, so the ~5.5 ms of printing /
  idle padding inside the slot does not contaminate the timestamp.
- **Human-readable 01–03, machine-CSV 04–05 (the spec's intended increment).** Sketches 01–03 print
  debug-friendly lines (`echo_us=… d=… m`; `echo=… dt=… cyc=…`; `sensor=N echo=…`); only 04/05 emit
  the exact parser format `sensor_id,echo_us,timestamp_us` (no spaces, 1-based id) plus the startup
  header. The CSV format and header were matched **exactly** to `parse_serial_lines`
  (sid∈{1,2,3}, strict int fields) and to the parser's header validation substring
  `slot_ms=18,timeout_us=12500`. Headers: `# fw=04,…` (sketch 04) and `# fw=05,…` (sketch 05).
- **Sketch 01 timeout deviation (documented in-file).** Sketch 01 uses a generous `pulseIn` timeout
  of **25000 µs** and `delay(100)`, NOT the flight 12500 µs / 18 ms slot. This is deliberate and
  noted in the file: sketch 01 only proves ranging *correctness*; the 12.5 ms timeout + slot
  *discipline* is the increment that sketch 02 introduces. From sketch 02 onward the timeout is
  12500 µs.
- **Sketch 05 = sketch 04 verbatim except the header version** (`fw=05`). It is a standalone,
  self-contained `.ino` (Arduino requires the sketch be complete in its own folder) — not a shared
  include.

### verify_timing.py design

- Mirrors existing script conventions: `sys.path.insert(0, …parent.parent)` bootstrap, argparse with
  lowercase-hyphen flags, `yaml.safe_load(open(args.config))` default `config.yaml`, and the
  `if __name__ == "__main__": try: main() except KeyboardInterrupt` guard.
- **Two input modes** (mutually exclusive group): live `--port` (default `acquisition.port` from
  config) + `--baud` (default `acquisition.baud`) via **pyserial**, OR **`--replay <logfile>`**
  (user-confirmed addition) that reads a captured/simulated `raw_serial.log`. pyserial is imported
  **lazily inside the serial path** so `--replay` works even if pyserial is absent.
- **Boot-garbage handling — `select_usable()`:** rather than blindly dropping the first N lines, it
  **locates the first `# …fw=…` header and keeps everything from there onward** (pre-header reset
  garbage discarded); `--skip-lines` (default 20, per §5.1) is only the *fallback* when no header is
  present. This preserves the header on a real device while still cleaning boot noise, and is a
  no-op on a clean replay file (header at line 0).
- **Pipeline:** collect lines → `parse_serial_lines` (gives header, rows, malformed count) →
  `unwrap_micros` on the `t_trig` column → rebuild rows with unwrapped timestamps →
  `assemble_triplets` → the four checks.
- **The four §4 checks, one PASS/FAIL line each** (±50 µs band):
  1. per-sensor period `diff(t_trig[:,k]) ≈ 54000 µs`, k=0,1,2 (worst-deviation reported);
  2. intra-triplet offsets `t_trig[:,1]−t_trig[:,0] ≈ 18000` AND `t_trig[:,2]−t_trig[:,0] ≈ 36000`;
  3. unwrapped full stream strictly increasing;
  4. `n_malformed == 0`.
  Guards for too-few rows/triplets emit a clear FAIL (no crash). Process exits **0** iff all pass,
  else **1**.

## S. Problems faced / things not according to plan

- **S-1. No `arduino-cli` (and no Arduino IDE) on the machine.** `Get-Command arduino-cli` → not
  found. The sketches therefore **could not be machine-compiled** here; correctness was established
  by careful review against the AVR/Arduino semantics (types: `pulseIn`/`micros()` return
  `unsigned long`; `(long)` cast for rollover-safe comparison; `s+1` 1-based id; CSV has no spaces).
  → **NOTE for future:** compile-check each sketch in the Arduino IDE / `arduino-cli compile
  --fqbn arduino:avr:uno` before the first flash. No syntax was verified by a toolchain.
- **S-2. The "strictly monotonic after unwrap" check (#3) is close to vacuous as written — honest
  finding.** Because `unwrap_micros` adds 2³² on *any* backward step (it cannot distinguish a true
  ~71.6-min rollover from a small glitch), the unwrapped stream is essentially always strictly
  increasing. So check #3 in practice only catches **duplicate/zero-Δt timestamps** (Δ=0 fails the
  strict `>0`) and a wholesale-empty/broken stream — it will NOT flag a small out-of-order glitch
  (that becomes a ~2³² jump, still `>0`). This faithfully implements the spec's wording ("strictly
  monotonic AFTER unwrapping") and reuses the canonical helper as required, so it was left as-is.
  → **NOTE for future:** if a stronger guarantee is wanted, add a separate sanity check that no
  single forward gap exceeds, say, a few × 54 ms (which WOULD catch a glitch-induced 2³² jump). Not
  added now to stay in scope and avoid reimplementing unwrap logic.
- **S-3. Initial `n_rollovers` computation was convoluted/buggy.** First draft tried to infer wraps
  by comparing unwrapped vs raw diffs; replaced with the direct, correct
  `np.count_nonzero(np.diff(raw_t) < 0)` (a rollover is exactly a backward step in the raw stream).
  Caught and fixed before verification.
- **S-4. Header vs boot-garbage interaction** (resolved by S-R's `select_usable`, above): a naïve
  "drop first 20 lines" would have dropped the header on a clean replay file and risked dropping it
  on hardware. The header-locate approach avoids both.
- **No other deviations.** The plan was followed; the only post-write change to the tree was removing
  the one throwaway synthetic session generated for the self-test (see §T).

## T. Results / verification attained (hardware-independent)

- **Offline self-test PASSED.** Generated one synthetic session
  (`simulate_session.py --n-sessions 1 --beam-cone off --seed 7`) and ran
  `verify_timing.py --replay …\raw_serial.log --min-lines 50`:
  - header read: `# fw=05,slot_ms=18,timeout_us=12500`; 726 data lines, 0 malformed; 242 triplets,
    0 dropped on resync;
  - all four checks **PASS** at **0 µs** worst deviation (the simulator emits perfectly
    slot-aligned timestamps); **exit 0**.
  - This exercises the full parse → unwrap → assemble → 4-check path and the reuse of the three
    `process_throw` helpers.
- **FAIL path confirmed.** Pointing `--replay` at a non-CSV file (`requirements.txt`) → header
  `None`, 0 data lines, 8 malformed; all four checks **FAIL**; **exit 1**. Confirms the guards and
  exit-code contract.
- **Tree left clean.** The transient `sim_2026-06-19_*` test session was removed; `data/sessions/`
  is back to its prior **12** disposable synthetic dirs. No pipeline/test/config files touched →
  the 176-test suite is unaffected (not re-run, because nothing it covers changed).
- **Bench gates (§4) remain OPEN** — they require the physical sensors and are the next session's
  job once hardware arrives.

## U. Notes for the future (hardware session, item 12 → 13)

1. **Flashing order is the gate sequence.** Flash 01→05 **in order** and hand-check each sketch's
   in-file pass criterion BEFORE moving to the next (01: wall at 0.5/1.0/1.5 m within ±1 cm; 02:
   timeouts print `0`, 18.000 ms period no drift over 1000 cycles; 03: per-sensor independence +
   firing order by beam-blocking — **verify each label maps to the right pod, a swap silently
   corrupts trilateration**; 04: 1000 lines parse with zero malformed; 05: `verify_timing.py`).
2. **Compile first (S-1).** No toolchain was available here; compile-check before flashing.
3. **Run the real gate:** `verify_timing.py --port COMx` against sketch 05 (Windows port is `COMx`,
   not the config's Linux `/dev/ttyACM0` default — pass `--port`). Watch the **worst-deviation µs**
   numbers: the simulator gave 0 µs, but real hardware has `pulseIn` latency and busy-wait jitter —
   they should still be well inside ±50 µs, but if not, that is real and must be surfaced, not
   widened away.
4. **Monotonic-check caveat (S-2)** if a timing glitch is ever suspected on hardware.
5. **Item 13 reuse path is already proven.** `verify_timing.py` demonstrates the exact serial
   ingestion pattern `acquisition.py` should follow: `parse_serial_lines` → `unwrap_micros` →
   `assemble_triplets` from `pipeline.process_throw`, plus the `select_usable` header-locate / boot
   drop. Per §10 item 13, `acquisition.py` + `run_session.py` must REUSE
   `process_throw.process_session` (post-CLOSING) and `segmentation.ThrowDetector` (live machine) —
   do NOT re-implement either.
6. **No spec conflict introduced.** The firmware and verifier implement §3/§4 exactly as written;
   no CLAUDE.md edit is required for Part 3 (unlike the §F backlog from Parts 1–2).

---
---

# PART 4 — live acquisition layer + one-throw program (§10 item 13) — as-built record

> **Context for the downstream editor.** Part 3 built the firmware (item 12). Part 4 builds the
> **live software half**: `pipeline/acquisition.py` (serial → triplet stream) and
> `scripts/run_session.py` (the one-throw program, §5.5/§5.7), plus `tests/test_acquisition.py`.
> The hard constraint was **reuse, not reimplementation**: `process_throw.process_session` for ALL
> post-CLOSING work and `segmentation.ThrowDetector` for the live state machine. These modules can
> be exercised fully **without hardware** (injectable byte-line stream), and were.
>
> **State after Part 4: 182 tests passing** (176 + 6 new in `test_acquisition.py`). **Zero** changes
> to any existing module or test — only three new files. Item 13's *hardware dry-run* (`--port COMx`
> against a flashed Arduino) remains the only part still blocked on the kit.

## V. The architectural insight that shaped the whole design

`process_session(session_dir, config)` **re-runs the entire pipeline from `raw_serial.log`** — it
re-parses, re-calibrates/loads background, **re-segments with the batch `segment_throw`**, then
corrections → trilateration → Kalman → landing, and writes the prediction into `session.json`
(verified `process_throw.py:154-291`). Therefore the live `ThrowDetector` is **only a capture-stop
trigger**; it does NOT decide the authoritative segmentation. `run_session`'s real job collapses to:
**capture `raw_serial.log` + write `session.json` metadata, then call `process_session`** exactly as
the offline path does. This is what makes "live == offline" true *by construction* — and is exactly
the guarantee the headline test asserts. It also means the live gating only has to be good enough to
detect throw start/end; the offline re-segmentation is the source of truth.

## W. Files created (3 new; nothing existing modified)

```
pipeline/acquisition.py            # serial reader → Triplet stream (I/O layer, §0.5)
scripts/run_session.py             # one-throw program, four modes (§5.7)
tests/test_acquisition.py          # 6 new tests incl. live==offline
```
- `acquisition.py` reuses `parse_serial_lines`, `unwrap_micros`, `assemble_triplets`
  (`process_throw`) and `mid_echo_sample_time_us` (`corrections`) — **no duplicated parse/unwrap/
  assembly logic**. It logs every raw byte-line **verbatim to `raw_serial.log` BEFORE parsing**
  (§0.4), yields `Triplet(index, echo_us(3,), t_trig_us(3,) unwrapped, t_sample_us(3,))` one at a
  time, and does **not** gate or decide IDLE/ACTIVE/CLOSING.
- `run_session.capture_session(session_dir, config, byte_lines, temperature_c, *, model=None)` is
  the **non-interactive, injectable core** (no prompts, no real serial) that the equality test
  drives; `main()` wires argparse + prompts + live serial on top.

## X. Approach / design decisions (per the approved plan)

- **`acquisition.py` is pure glue; gating lives in `run_session`.** acquisition yields triplets;
  `run_session` converts each to a validity bool (`triplet_valid(echo_us_to_m(echo,T), bg)`) and
  feeds `ThrowDetector`. acquisition stays focused on read→log→parse→assemble→yield. (The user's
  phrasing "ThrowDetector consumes this stream" is satisfied via this one-line adapter in the
  consumer; coupling acquisition to `background`+`corrections` would have muddied the layer.)
- **Background + gate in the SURFACE-distance domain** (`echo_us_to_m` only, NO `add_ball_radius`),
  matching `process_session`'s exact order (radius is added *after* gating). Getting this wrong
  would have shifted every band by the 33.5 mm ball radius and desynced live vs offline.
- **`run_session` persists `background.json` from the live cal**, so the model that gated the throw
  IS the one `process_session` loads (`process_session` loads `background.json` if present, else
  recomputes from the first `bg_n_triplets`). The offline twin recomputes from the same first-N
  triplets → identical model → identical prediction. Either way equality holds; persisting also
  avoids a double calibration.
- **`capture_session` writes a minimal `session.json` (temperature) at the very start**, before the
  throw loop, so a Ctrl-C mid-throw still leaves a reprocessable session dir (`raw_serial.log` +
  `background.json` + `session.json`). The `raw_serial.log` handle is opened in a `with` and flushed
  per line, so the verbatim capture survives an interrupt at any point (§5.5 Ctrl-C requirement).
- **Header-gated start** (the robust form of "discard ~20 auto-reset lines, verify header", §5.1):
  discard everything until the first `# fw=` line, verify the `slot_ms=…,timeout_us=…` substring
  (warn-don't-crash on mismatch); if valid CSV arrives but no header (e.g. a replayed log), warn once
  after 6 data rows and proceed headerless. Same spirit as Part 3's `verify_timing.select_usable`.
- **Four modes** (§5.7): `default` (temperature → background → throw → `process_session` → report
  `r/θ/σ_r/σ_θ` + caveat → two-tape ground truth → write); `--raw-log` (verbatim capture until
  Ctrl-C, backed by `acquisition.raw_capture`, generic for `characterize_static.py` item 14);
  `--background-only` (calibrate, print per-sensor μ/σ/w/enabled + `sanity_warnings`, persist, and —
  when `ceiling_height_m` is set — print the A2 `ceiling_ghost_apparent_range` and flag
  `inside_gate_window`); `--no-correction` (skip the bias model).
- **Ground-truth protocol (§5.5, R8):** prompts `L_centroid`/`L_S1` (empty → skip), solves
  `geometry.two_circle_intersection`, resolves the two-fold ambiguity by matching the predicted
  landing's z-sign (prompts only if genuinely ambiguous), calls `geometry.ground_truth_landing`, and
  merges a `ground_truth` block (`x_m,z_m,r_m,theta_deg,σ,cov,raw tapes`) into `session.json` — shaped
  to what `calibrate_bias.py` reads (`meta["ground_truth"]["x_m"/"z_m"]`). Degenerate/non-intersecting
  inputs are caught (`ValueError`) and skipped with a message, never a crash.
- **Live session dir** `data/sessions/<YYYY-MM-DD>_T##` (next free counter; never overwrite),
  mirroring `simulate_session.create_session_folder`.

## Y. Problems faced / things not according to plan

- **Y-1 (the real bug). Incremental assembly fired phantom "order violation" warnings.**
  My first design called `assemble_triplets` on the whole growing buffer each line. But
  `assemble_triplets` (`process_throw.py:88-110`) uses `i + 2 < n`, so when the buffer ends
  **mid-triplet** (a lone trailing `S1`, or `S1+S2` with no `S3` yet) it treats that leading `S1` as
  a dropped stray and bumps `dropped`. My `dropped > last_dropped` warning then fired on every
  partial triplet (and `dropped` even *decreased* once the `S3` arrived), producing a spurious
  warning with no real violation. **Caught by the new `test_auto_reset_garbage_discarded_before_header`
  test (warns must be empty).**
  **Fix:** only feed `assemble_triplets` the **committed prefix up to the last `S3`** in the buffer
  (`last_s3 = …; commit = last_s3 + 1`); the trailing partial is held back until its `S3` arrives. The
  committed prefix grows only by whole triplets (plus genuine strays), so its `dropped` is monotonic
  and real. This keeps the reuse of `assemble_triplets` intact (no reimplementation) while making it
  safe to call incrementally. Re-ran → all 6 green.
- **Y-2. Unwrap must see full history; buffer is not trimmed.** `unwrap_micros` counts rollovers
  cumulatively, so trimming consumed rows would lose the wrap count. The buffer therefore retains all
  rows for the session (~hundreds); the per-line `unwrap + assemble` over the committed prefix is
  O(n²) but trivial at session scale (~210 triplets). Documented in-code. A prefix-unwrap equals the
  full-sequence unwrap at each index (wraps depend only on earlier samples), so yielded `t_trig`
  values are stable/correct — asserted against `unwrap_micros` as the oracle in the rollover test.
- **Y-3. Streaming triplet assembly is a live *equivalent*, not a literal reuse of the batch path.**
  The user named `parse_serial_lines` and `unwrap_micros` for reuse and *described* triplet assembly
  as a behavior. I reuse `assemble_triplets` for the grouping (via the committed-prefix trick), so no
  assembly logic is duplicated — the analogue of how `ThrowDetector` is the live twin of the batch
  `segment_throw`.
- **Y-4. `--help` exit code shows 255 through the shell pipe.** Cosmetic only — argparse `--help`
  raises `SystemExit(0)`; the non-zero surfaced by the PowerShell pipe is a shell artifact, not a
  script error (a real `capture_session` smoke exited 0).
- **No deviations from the plan's file set or guardrails.** `process_throw.py`, `segmentation.py`,
  `background.py`, and all existing tests were left untouched.

## Z. Results / verification attained

- **`tests/test_acquisition.py` — 6 new tests, all green:**
  1. `test_assembly_t_sample_and_resync` — triplets assemble; `t_sample == t_trig + echo/2`
     (timeouts → `t_sample = t_trig`); a missing-`S2` line drops the stray `S1`+`S3`, fires exactly
     one "order violation" warn, and the next triplet still assembles.
  2. `test_header_mismatch_warns_not_fatal` — a wrong `# fw=99,…` header warns but parsing proceeds.
  3. `test_auto_reset_garbage_discarded_before_header` — binary/garbage before the header is
     discarded silently (no phantom warns — the Y-1 regression guard).
  4. `test_yielded_t_trig_matches_unwrap_micros` — a single + double `micros()` rollover; yielded
     `t_trig` equals `unwrap_micros(raw_t)` (the reused canonical oracle) and is strictly monotonic
     (`MICROS_ROLLOVER + 6000`, `2*MICROS_ROLLOVER + 50`). R10c, reusing the `test_process_throw`
     fixture values rather than inventing new ones.
  5. `test_capture_session_matches_direct_process_session` — **the headline live==offline test**: a
     synthetic full throw → `serial_bytes()` → mocked byte-lines → `capture_session`; the resulting
     `session.json` `prediction["raw"]` (x,z,r,θ,σ_r,σ_θ,heading,v_h to 1e-9; `cov_xz` to 1e-12;
     n_points/dof) AND the full `gate_summary` equal a direct `process_session` on the same captured
     log. Proves no logic diverged between the live and offline paths.
  6. `test_capture_session_writes_expected_artifacts` — `raw_serial.log`, `background.json`,
     `triplets_raw.csv`, `trajectory.csv`, `session.json` all written; one throw segmented;
     `n_triplets_used ≥ min_fit_points`; landing within 100 mm of truth.
- **Full suite: `.\venv\Scripts\python.exe -m pytest tests\ -q` → 182 passed** (176 + 6), ~14 s.
- **End-to-end script smoke (no hardware).** A synthetic throw replayed through `capture_session`
  printed `background calibrated over 200 triplets; bands enabled [False,False,False]` (open-air →
  bands disabled, correct), `THROW DETECTED`, and **`r = 1.654 m, θ = -10.4°, σ_r = 0.008 m,
  σ_θ = 0.3°` vs TRUE `r = 1.647 m, θ = -10.1°`** (7 mm / 0.3° agreement), with the R7 caveat and
  exit 0. Gate: 231 total / 14 used triplets, 0 malformed.
- **Tree left clean.** All test artifacts used `tmp_path`; the smoke removed its own dir;
  `data/sessions/` remains the prior **12** synthetic dirs.

## AA. Notes for the future

1. **Hardware dry-run is the only remaining piece of item 13.** Flash sketch 05, then
   `run_session.py --background-only` (confirm bands/ghost), then a live `--port COMx` throw. Windows
   port is `COMx`, not the config's Linux `/dev/ttyACM0` default — pass `--port`.
2. **`acquisition.serial_byte_lines` is an *infinite* generator** (skips read-timeout empty reads so
   the stream survives idle gaps between echoes); the consumer stops it (ThrowDetector CLOSED or
   Ctrl-C). The hardware-only paths (`open_serial`, `serial_byte_lines`) are marked
   `# pragma: no cover` and were not executed in tests.
3. **Caveat console glyph (cosmetic).** The R7 caveat string (from `landing.py`'s `CAVEAT_TEMPLATE`)
   contains a Unicode em-dash that renders as `�` on the Windows cp1252 console. Harmless; if desired,
   add `sys.stdout.reconfigure(encoding="utf-8")` in `run_session.main()` (a one-liner, in-scope for
   the script, not a `landing.py` change).
4. **`characterize_static.py` (item 14) should wrap `acquisition.raw_capture`** (the `--raw-log`
   primitive) with an `on_line` callback for live stats — the generic hook was added for exactly this.
5. **No CLAUDE.md edit required for Part 4.** `acquisition.py` and `run_session.py` implement §5.1 and
   §5.7 as written; the I/O-layer status of `acquisition.py` is already sanctioned by §0.5.

---
---

# PART 5 — static characterization tools (CLAUDE.md §7, §10 item 14) — as-built record

> **Context for the downstream editor.** Part 4 built the live acquisition layer (item 13). Part 5
> builds the **static characterization** half of item 14: `scripts/characterize_static.py` (collect
> per-sensor stats for one stationary target) and `scripts/analyze_static.py` (aggregate many reports
> → empirical beam half-angle + electronic-offset recommendation), plus `tests/test_characterize_static.py`.
> These turn the array into the NUMBERS that will set `kalman.sigma_pos_m` (noise) and
> `simulator.beam_half_angle_deg` (the still-UNVERIFIED 7.0 estimate, §J). The actual measurement is
> the operator's hardware job; this part delivers the **tooling**, fully testable without hardware.
>
> **State after Part 5: 188 tests passing** (182 + 6 new in `test_characterize_static.py`). The only
> change to an existing file is a 2-line, backward-compatible addition to `acquisition.raw_capture`.

## BB. Scope and the one existing-file change

Two new scripts + one new test file. The single existing-file change, exactly as planned:
**`pipeline/acquisition.py` — `raw_capture` gained an optional `stop=None` predicate**
(keyword-only, checked AFTER `on_line` each line). `stop=None` preserves the exact prior behaviour,
so `run_session.run_raw_log` (which passes only `on_line=print`) is unchanged; the full suite
confirms it. This is the clean enabler for **bounded** capture (auto-stop after N readings) so the
characterizer genuinely *wraps* the `--raw-log` engine instead of re-implementing serial reading —
`raw_capture`'s docstring already named this tool as the intended wrapper. No other existing module
or test was touched.

## CC. Files created

```
scripts/characterize_static.py     # collect + per-sensor stats for ONE static target
scripts/analyze_static.py          # aggregate reports -> beam half-angle + offset recommendation
tests/test_characterize_static.py  # 6 tests incl. the tape-convention guard
```

## DD. Approach / design decisions

- **Reuse, not duplication.** `characterize_static` imports the serial machinery from
  `acquisition` (`open_serial`, `serial_byte_lines`, `raw_capture`) and the canonical parser
  (`process_throw.parse_serial_lines`); distances come from `corrections.echo_us_to_m`. The only new
  logic is the per-sensor accumulation + statistics.
- **Injectable core (`characterize_core(byte_lines, log_fh, *, target, raw_tape_m, radius_m,
  temperature_c, n_readings, angle_off_axis_deg=None) -> dict`).** Takes an iterable of raw byte-lines
  and an open log handle, so it is driven by mocked lists in tests and by `serial_byte_lines(ser)` in
  `main()`. A `_Collector` parses each line and counts per-sensor readings + timeouts + echo_us; its
  `min_count()` drives the `stop` predicate (`min over sensors >= n_readings`), so even an all-timeout
  sensor still reaches the target and the capture terminates.
- **Stats in the distance domain, NaN-safe.** Per sensor: `n`, `n_timeout`,
  `timeout_fraction = n_timeout/n`, `mean_m`, `sigma_m` (ddof=1 over non-timeout), and
  `offset_m = mean_m - centre_reference_m`. An all-timeout sensor yields NaN mean/sigma/offset and
  `timeout_fraction = 1.0`; `_report_to_json` maps non-finite floats to `null` so the on-disk report
  is portable JSON.
- **The tape-to-centre convention (§7, R2) lives in ONE function** —
  `centre_reference_m(target, raw_tape_m, radius_m)`: board -> tape as-is; ball -> tape + radius. It
  is called by both `main()` (to print BOTH the raw tape and the centre reference up front, the §7
  visibility requirement) and `characterize_core`. Reversing it would corrupt every downstream
  offset, so it is the subject of the load-bearing test (FF).
- **`--n-readings` is PER SENSOR** (default 200); `--angle-deg` is recorded in the report for the
  beam sweep; `--temperature-c` (default 20.0) sets the speed of sound for the echo->distance
  conversion. Output dir is `data/sessions/<YYYY-MM-DD_HHMMSS>_static/` with `raw_serial.log`
  (verbatim) + `static_report.json`, and a printed per-sensor table (n, timeout %, mean, σ[mm],
  offset[mm]).
- **`analyze_static.py`** — a pure, testable `beam_half_angle(points) -> float|None` that sorts by
  angle and linearly interpolates the first rising crossing of 0.5 (returns the smallest
  already-saturated angle as an upper bound if no clean rise exists; `None` if the fraction never
  reaches 0.5 — "widen the sweep"). Per sensor it gathers `(angle_off_axis_deg, timeout_fraction)`
  across angle-tagged reports and prints the crossing, then a headline
  `Suggested beam_half_angle_deg: X.X (vs current config value <cfg>)` (median of bracketed sensors;
  `<cfg>` read from config, not hardcoded). The electronic-offset section prefers the flat-board
  reports (they isolate the electronics), prints per-sensor `offset` and `sigma/sqrt(N)`, and flags
  `|offset| > 3*sigma/sqrt(N)` as SIGNIFICANT with the recommendation to subtract a CONSTANT offset
  at the acquisition layer — explicitly labelled a measurement-layer correction kept OUTSIDE
  `bias.py`.
- **Modelling assumption (documented in `--help`).** `--angle-deg` is the operator's recorded
  off-axis angle for the sensor being swept; the per-sensor geometric angle is NOT reconstructed from
  the tape distance. This is the practical input the §7 protocol yields and is sufficient to "produce
  numbers".

## EE. Problems faced / not according to plan

- **EE-1. Em-dashes in my OWN new print strings garbled on the Windows console.** The smoke run
  rendered `—` as `�` (cp1252) in the operator-facing recommendation lines of `analyze_static.py`
  ("widen the angle sweep", "SIGNIFICANT — subtract…", "within noise — leave uncorrected") and the
  Ctrl-C message of `characterize_static.py`. Unlike the pre-existing `landing.py` caveat glyph (a
  file I was scoped not to touch, Part 4 §AA-3), these are my new scripts, so I **replaced the
  em-dashes with ASCII** (`->`, `,`, `-`) — these tools print numbers the operator must read, so
  clean rendering matters. Caught by the offline smoke, before any hardware.
- **EE-2. `raw_capture` `stop` semantics — order matters.** The predicate is evaluated AFTER
  `on_line(line)` so the collector counts the current line before `stop()` is checked; otherwise the
  last reading would be logged but not counted. Documented in the docstring.
- **No deviation from the planned file set.** The `stop` addition to `raw_capture` was in the plan
  (the "one change to an existing file"); nothing else existing was modified.

## FF. Results / verification attained

- **`tests/test_characterize_static.py` — 6 new tests, all green:**
  1. `test_stats_board` — per-sensor `mean_m`/`sigma_m`/`offset_m`/`timeout_fraction` match a numpy
     reference computed with the reused `echo_us_to_m` (no hardcoded distances); an all-timeout
     sensor yields non-finite mean/offset and `timeout_fraction == 1.0`.
  2. `test_radius_applied_ball_not_board` — **the tape-convention guard:** same stream as `board`
     and `ball`; asserts `centre_reference_m(board) == tape`, `(ball) == tape + radius`, and that
     each detected sensor's `offset_m(ball) == offset_m(board) - radius` (mean unchanged — only the
     reference moved). This single test fails loudly if the convention is ever reversed.
  3. `test_convention_helper` — the `centre_reference_m` helper directly.
  4-6. `beam_half_angle` — interpolated crossing (`6.667°` from points straddling 0.5), `None` when
     never bracketed, and the unsorted-input / early-saturation upper-bound case.
- **Full suite: `.\venv\Scripts\python.exe -m pytest tests\ -q` -> 188 passed** (182 + 6), ~12 s.
- **Offline smoke (no hardware).** `characterize_core` on a synthetic board stream printed a correct
  table (S1 mean 1.0046 m, offset +4.58 mm; S3 25% timeout). Three angle-tagged ball reports
  (4°/6°/8° at 0.10/0.40/0.75 S1 timeout) + one board report through `analyze_static` produced:
  `S1: 50% timeout crossing at 6.6 deg`, S2/S3 "widen the sweep",
  `Suggested beam_half_angle_deg: 6.6 (vs current config value 7.0)`, and offset verdicts
  (S1 +4.58 mm SIGNIFICANT, S2 within noise, S3 -3.39 mm SIGNIFICANT). Exit 0.
- **Tree left clean.** Tests use mocked streams / `io.BytesIO`; the smoke removed its own temp dir;
  `data/sessions/` remains the prior **12** synthetic dirs.

## GG. Notes for the future (operator hardware run + config update)

1. **Run order (§7 protocol).** Flat board first at a tape distance (`--target board`) — proves the
   electronics and gives the clean electronic offset. Then the ball (`--target ball`) at
   ~1.0/1.3/1.7 m and several `--angle-deg` values for the beam sweep. One `static_report.json` per
   run.
2. **Windows port + temperature.** Pass `--port COMx` (config default is the Linux `/dev/ttyACM0`)
   and the real `--temperature-c` (it sets the speed of sound; a wrong value biases every distance
   and hence every offset).
3. **Then analyze + update config TOGETHER (not guessed).**
   `analyze_static.py data\sessions\*_static\static_report.json` → take the suggested
   `beam_half_angle_deg` (replaces the §J 7.0 estimate, which probing showed admits ZERO
   campaign-speed triplets) and the per-sensor σ (median/typical → `kalman.sigma_pos_m`). If an
   offset is flagged SIGNIFICANT, implement the constant per-sensor subtraction at the **acquisition
   layer** (NOT in `bias.py`, per §7) — that hook does not exist yet and would be a small addition to
   `acquisition`/`run_session` when the numbers justify it.
4. **Beam-sweep caveat.** `--angle-deg` is a single per-report scalar (the swept sensor's off-axis
   angle); the other sensors' columns in that report are incidental. For a clean per-sensor cone,
   sweep one sensor at a time. The analysis reports all three crossings regardless; read the swept
   one.
5. **No CLAUDE.md edit required for Part 5.** The tools implement §7 as written; the `raw_capture`
   `stop` parameter is an internal enabler, not a spec change. (When the offset-subtraction decision
   is actually made from hardware data, that WOULD touch the acquisition layer and should be recorded
   then.)

---
---

# PART 6 — campaign analysis + late ground truth (CLAUDE.md §8.7, item 15) — as-built record

> **Context for the downstream editor.** Part 5 built the static characterization (item 14). Part 6
> builds the **campaign-consumption** tools (item 15, the last software deliverables):
> `scripts/append_ground_truth.py` (add a session's ground truth after the fact) and
> `scripts/analyze_campaign.py` (aggregate every ground-truthed throw into stats + 5 figures + the
> D3 power note), plus `tests/test_analyze_campaign.py`. Both are **pure consumption** of what
> `process_throw.py` and `bias.py` already write — nothing in `pipeline/` is touched and
> `calibrate_bias.py` is imported, not modified.
>
> **State after Part 6: 193 tests passing** (188 + 5 new). **The software build order is now complete
> through item 15** (items 1–11 software, 13 live acquisition, 14 static tools, 15 campaign tools).
> The only remaining work is hardware-gated: item 12's firmware *bench* pass/fail (the sketches exist,
> Part 3), the live hardware runs of items 13–14, and the real throw campaign that feeds item 15.

## HH. The architecture that keeps the two scripts honest

Both scripts consume the on-disk schema and reuse the existing analysis code rather than
re-deriving it:
- **`append_ground_truth`** reuses `run_session.prompt_ground_truth` verbatim (the same two-tape
  `geometry.ground_truth_landing` solve as the live path), passing a `SimpleNamespace` shim that
  carries only the one field it reads — `prediction["raw"]["z_m"]` (the predicted z that resolves the
  two-fold tape-circle ambiguity). It writes ONLY the `ground_truth` key back.
- **`analyze_campaign`** reuses `calibrate_bias.load_record` for session inclusion (so it agrees
  exactly with calibrate_bias on which sessions "have ground truth", including the
  `truth.landing` fallback for `simulated` sessions), `bias.evaluate`/`apply_correction` for the
  corrected error, `bias.to_track` + `calibrate_bias.power_n` for the D3 note, and — the one clever
  reuse — `landing.predict_landing` for the RAW-trilateration landing (see JJ-1).

## II. Files created (3 new; nothing existing modified)

```
scripts/append_ground_truth.py     # late ground truth -> session.json (only the ground_truth block)
scripts/analyze_campaign.py        # stats + D3 power note + 5 PNGs under campaign_report/
tests/test_analyze_campaign.py     # 5 tests incl. the byte-identity guard
```

## JJ. Approach / design decisions

- **JJ-1. Raw-vs-Kalman landing (plot 2) reuses `predict_landing`, no reimplementation.**
  `predict_landing` needs a `kalman.FilterResult` (it reads `.t_s/.pos/.vel`), but the landing
  *point* comes only from the position polynomial fits; `.vel` feeds the (here-irrelevant)
  heading/v_h fields. So the "raw trilateration landing" is computed by wrapping `trajectory.csv`'s
  `x_raw/y_raw/z_raw` columns in `FilterResult(t_s, pos=raw_xyz, vel=zeros, bias=ones)` and calling
  the real `predict_landing`. Sessions without `trajectory.csv` or with `< min_fit_points` raw rows
  (or a non-concave fit) are skipped gracefully — so bare fixtures (no trajectory.csv) don't break it,
  and the tests (which assert stats, not plots) never need it.
- **JJ-2. `summary_stats` is the testable core.** It takes the loaded throws (+ optional model) and
  returns raw/corrected 2D-error mean/std(ddof=1)/95% CI (`scipy.stats.t.ppf`, never 1.96) and the
  D3 fields. Raw error = per-throw `hypot(pred-actual)`; corrected = `bias.evaluate(model, records)
  ["after"]` (None when no model). The power note recomputes along-track residuals
  (`to_track(...)[0]`) over ALL campaign throws → `power_n(scatter, |bias|, n, alpha)`;
  `underpowered_null = mode=="none" and power_n and n<power_n`. The note WORDING is replicated (it is
  an inline print in calibrate_bias, which stays unchanged, so it cannot be imported) — only the
  `power_n` computation is shared.
- **JJ-3. `append_ground_truth` requires an existing prediction.** Its z resolves the tape ambiguity;
  if `prediction.raw.z_m` is absent the script prints "process it first" and changes nothing — matching
  the real use case (ground truth added *after* processing). The writer
  `update_session_ground_truth(path, gt_block)` loads the full dict, sets only `ground_truth`, and
  re-dumps via `run_session._write_json` (same indent), so unchanged keys keep their order and
  serialization.
- **JJ-4. Fixtures reuse `session_factory.write_session_dir` (no new helper).** Each fixture generates
  a tiny `SyntheticSession`, writes it, then PATCHES `session.json` with a KNOWN `prediction.raw`,
  `ground_truth`, and `gate_summary.n_triplets_used` so the 2D errors and along-track residuals are
  exact and checkable. The injected `ground_truth` block takes precedence over the simulator's
  `truth.landing` in `load_record`.
- **JJ-5. ASCII-only operator output** (the Part-5 lesson): the power-note and summary strings avoid
  the Unicode em-dash that garbles on the Windows cp1252 console.

## KK. Problems faced / not according to plan

- **KK-1 (deliverables: none).** The three shipped files matched the plan; no design change was
  forced during implementation.
- **KK-2 (smoke-only, NOT a bug in the tools). Two simulator realities I'd misjudged when building
  *synthetic sessions for the offline smoke*:**
  - A **small `n_bg_pre`** makes `process_session` sweep flight triplets into the background
    calibration — it calibrates from the first `min(bg_n_triplets, N)` triplets, so if there are
    fewer than `bg_n_triplets` (=200) background triplets ahead of the flight, the flight pollutes the
    background band and the gate rejects the throw (`no throw detected, 0 valid triplets`). Fix: use
    the default `n_bg_pre` (~210), exactly as `test_process_throw` / the e2e gate do.
  - `random_throw` is **not always detectable**, so a one-shot loop hit an undetectable throw. The e2e
    factory (`build_set`) handles this with a **retry loop** (probe-process, discard on `ValueError`);
    the smoke now does the same.
  Both were fixed in the throwaway smoke script; **the shipped tests inject predictions directly and
  depend on neither**, so they are immune to simulator-tuning drift.
- **KK-3 (cosmetic). `--help` exit code 255 through the shell pipe** (argparse `SystemExit`), as in
  earlier parts — not a script error.

## LL. Results / verification attained

- **`tests/test_analyze_campaign.py` — 5 new tests, all green:**
  1. `test_loads_all_four` — `load_campaign` finds all four ground-truthed fixtures.
  2. `test_raw_stats_hand_computed` — for errors `[20,40,40,60] mm` (heading 0, so along-track ==
     x-residual): raw mean/std/95% CI and along bias/scatter match an independent numpy/scipy
     computation, and `power_n` equals the reused `calibrate_bias.power_n(...)`.
  3. `test_none_model_corrected_equals_raw` — a `mode='none'` model passes through (corrected == raw).
  4. `test_updates_only_ground_truth` — the byte-identity guard: `update_session_ground_truth` then
     `new.pop("ground_truth") == old` (every other key unchanged) and the block equals what was passed.
  5. `test_end_to_end_via_prompt` — monkeypatched `input` feeds L_centroid/L_S1 into the
     `prompt_ground_truth` shim path; the written `ground_truth` r/θ match an independent
     `geometry.ground_truth_landing` solve and recover the +z mark (0.8, 0.3).
- **Full suite: `.\venv\Scripts\python.exe -m pytest tests\ -q` -> 193 passed** (188 + 5), ~19 s.
- **Offline smoke (no hardware).** Six drag-ON synthetic sessions (×5 drag, e2e-style retry) were
  `process_session`-ed, then `analyze_campaign` over them printed `raw 2D error: mean 45.3 mm,
  std 15.1 mm, 95% CI [29.5, 61.2] mm`, along-track bias `+44.1 mm`, and the power note
  (`CI excludes zero at approximately N=1` — expected for the inflated ×5 drag), and wrote all **5
  PNGs** including `raw_vs_kalman_error.png` (which exercises the JJ-1 `FilterResult`-wrapper +
  `predict_landing` on `trajectory.csv`). `append_ground_truth.update_session_ground_truth` on a
  processed session changed only the `ground_truth` block (`True`). Exit 0.
- **Tree left clean.** Tests use `tmp_path`; the smoke removed its session dir and the
  `campaign_report_smoke/` figures; `data/sessions/` remains the prior **12** synthetic dirs.

## MM. Notes for the future (operator + remaining work)

1. **Real-campaign flow (item 15).** Throws via `run_session.py` → for any late first-contact marks,
   `append_ground_truth.py <session_id>` (two-tape protocol) → `calibrate_bias.py --sessions
   data\sessions\*` to fit/validate the model → `analyze_campaign.py --sessions data\sessions\*` for
   the figures + the prominent power-note read. A null drag result at the planned 15–20 throws (D3,
   §11) should be read via that note as "below noise floor at this N", not failure.
2. **Triplets histogram is the beam-cone reality check.** After §14 tunes `beam_half_angle_deg`, the
   `triplets_hist.png` over real throws confirms whether the synthetic ~5–6 (or the over-producing
   legacy) density matched reality; feed surprises back into the simulator estimate.
3. **`analyze_campaign` is robust to partial sessions** — it skips (with a printed reason) any session
   lacking a prediction or ground truth, and any plot whose inputs are missing (no `trajectory.csv`,
   no `n_triplets_used`, non-finite `cov_xz`). The figures degrade gracefully rather than crashing.
4. **Build status.** With Part 6 the software is feature-complete per CLAUDE.md §10. Remaining items
   are hardware: bench-gate the firmware (Part 3 sketches), run `verify_timing.py`/`run_session.py`/
   `characterize_static.py` against the Arduino, tune `kalman.sigma_pos_m` + `simulator.
   beam_half_angle_deg` from §7 data, then the campaign.
5. **No CLAUDE.md edit required for Part 6.** The tools implement §8.7 as written.

---
---

# PART 7 — per-session reporting plots (CLAUDE.md §1 "reporting.py", §5.6 plots/) — as-built record

> **Context for the downstream editor.** Part 6 marked the software feature-complete per §10. Part 7
> is a small **additive** follow-up: it builds `pipeline/reporting.py` — the one file in the §1 tree
> that was never created — and populates the `session_dir/plots/` subdirectory (§5.6) that the offline
> path never touched. It also adds an opt-in `--plot` flag to `run_session.py` and
> `simulate_session.py`. No physics, no recompute: it only visualizes what `process_throw.py` already
> wrote.
>
> **State after Part 7: 195 tests passing** (193 + 2 new in `test_reporting.py`). `process_throw.py`,
> `analyze_campaign.py`, and every existing test are untouched; the only edits to existing files are
> the additive, default-off `--plot` wiring in the two scripts.

## NN. Files created / touched

```
pipeline/reporting.py            # NEW: plot_session() -> 2 PNGs into session_dir/plots/
tests/test_reporting.py          # NEW: 2 tests (happy path + missing-trajectory skip)
scripts/run_session.py           # +--plot flag, default mode only (additive)
scripts/simulate_session.py      # +--plot flag, processes-then-plots each session (additive)
```
`reporting.py` is the plotting/I/O member of `pipeline/` — explicitly NOT one of the pure
computational modules of §0.5. It reads `trajectory.csv` / `triplets_raw.csv` / `session.json` and
writes PNGs; it does no trilateration/Kalman/landing math.

## OO. Approach / design decisions

- **`plot_session(session_dir, config) -> list[Path]`** writes two figures:
  - **`trajectory_fit.png`** — two subplots: top-down (x–z) and side view (downrange–y, where
    downrange `s = x·cosφ + z·sinφ` uses the stored `heading_deg`). Each shows the raw trilaterated
    points, the Kalman path, the fitted curve, the predicted-landing marker, and the ground-truth
    marker (if present; same `truth.landing` fallback for simulated sessions as
    `calibrate_bias.load_record`).
  - **`range_vs_time.png`** — three stacked sensor subplots: range vs `t_sample`, with accepted
    (`reading_valid==1`) vs gated (`==0`) readings drawn differently and the in-throw window shaded.
- **The fitted parabola is a cosmetic re-fit, not a recompute.** `numpy.polyfit` over the **Kalman
  columns of `trajectory.csv`** — which are exactly the USED triplets landing.py fit over
  (`process_throw.py:147` writes only used triplets) — so the drawn curve reproduces the pipeline's
  parabola. Crucially the landing **marker** is the stored `session.json` value, never recomputed.
  The floor-contact extent is the descending root of `y(t)=ball_radius`; the whole fit is wrapped so a
  degenerate/non-concave fit degrades to points+markers instead of crashing.
- **Figure 2 converts `echo_us`→range via the existing `corrections.echo_us_to_m(echo, T)`** rather
  than reading `d_centre_m`. Reason (confirmed at `process_throw.py:135`): `d_centre_m` is written
  **empty for gated/timeout readings**, so it cannot show the gated points whose visibility is the
  whole purpose of the figure. Re-deriving range from the raw `echo_us` (the same conversion the
  pipeline used; flags are stored as int 0/1, clean to filter) is a display transform, not new physics.
- **Defensive skip (same pattern as analyze_campaign):** missing `trajectory.csv` or `< min_fit_points`
  rows → printed reason + `return []`, never a raise. `plots/` is `mkdir(exist_ok=True)` (session_factory
  and live dirs don't pre-create it; simulate_session's `create_session_folder` does).
- **`--plot` wiring (default-off, existing behaviour unchanged):**
  - `run_session.py`: default mode only (the only mode that produces `trajectory.csv`); plots after
    the prediction + ground-truth step so the GT marker is available.
  - `simulate_session.py`: since generation does NOT process, `--plot` opts in to running
    `process_session` then `plot_session` per freshly written session, best-effort (catches the
    "no throw" `ValueError` and prints a skip line). This is the one place `--plot` runs the pipeline.

## PP. Problems faced / not according to plan

- **PP-1. matplotlib warning on the gated marker (fixed).** First draft drew the gated `x` marker
  with `facecolors="none", edgecolors="tab:red"`; matplotlib warns that an unfilled marker ignores
  edgecolor. Changed to `c="tab:red", marker="x"`. The test is now warning-free.
- **PP-2 (the real surprise, NOT a bug). `simulate_session --plot` produced ZERO detectable sessions
  at first.** `simulate_session.main` honours `config["simulator"]["beam_cone_enabled"]`, which is
  **`true`** in v2.2, and at the unverified `beam_half_angle_deg = 7.0` campaign-speed `random_throw`s
  yield 0 cone-on triplets (exactly the §J caveat — "0/200 attempts"). So `process_session` raised
  "no throw detected (0 valid triplets)" for every session and the `--plot` block correctly **skipped
  gracefully** (which incidentally proved the defensive path). The fix for *plotting synthetic data*
  is to pass **`--beam-cone off`**; with it, 3/3 sessions processed and wrote real figures. This is a
  config/estimate issue (7° is UNVERIFIED, §J/§E-2), not a code defect — no change made.
  → **NOTE for future:** until `beam_half_angle_deg` is tuned from §7 hardware data, use
  `simulate_session --plot --beam-cone off` for synthetic visual checks. (A lesser, earlier confusion:
  `random_throw` is also independently not-always-detectable — the §C-5 / e2e retry-loop fact — but
  the beam cone was the dominant cause here.)
- **No deviation from the planned file set.** The four files match the approved plan exactly.

## QQ. Results / verification attained

- **`tests/test_reporting.py` — 2 new tests, green & warning-free:**
  1. `test_plots_written` — `generate_session` (proven detectable `ThrowParams(-1.5,0.8,0.2,3.2,4.0,
     -0.5)` + `background_distance_m=1.95`) → `write_session_dir` → `process_session` (CALLED, not
     modified) to populate the CSVs → `plot_session` returns 2 paths, both exist and are non-empty,
     and `plots/trajectory_fit.png` + `plots/range_vs_time.png` are on disk.
  2. `test_missing_trajectory_skips` — `write_session_dir` only (no processing) → `plot_session`
     returns `[]`, prints a reason mentioning `trajectory.csv` (via `capsys`), and raises nothing.
- **Full suite: `.\venv\Scripts\python.exe -m pytest tests\ -q` -> 195 passed** (193 + 2), ~19 s.
- **End-to-end script smoke (no hardware).** `simulate_session.py --n-sessions 3 --seed 11
  --beam-cone off --plot` wrote, for all 3 sessions, real `trajectory_fit.png` (~79 KB) and
  `range_vs_time.png` (~63 KB) into each `plots/` via the full `simulate_session -> process_session ->
  plot_session` path (printed `plot:` lines). The `*_true.png` figures in those dirs are
  simulate_session's own true-trajectory plots, distinct from the two new ones.
- **Tree left clean.** Every smoke session (a throwaway `_plot_smoke/` out-dir and the stray
  `sim_2026-06-19_*` dirs) was removed; `data/sessions/` is back to the prior **12** synthetic dirs.

## RR. Notes for the future

1. **Synthetic plotting needs `--beam-cone off`** until `beam_half_angle_deg` is tuned (PP-2 / §J).
   On real hardware data (item 14 onward) the cone is physical, not a config estimate, so this caveat
   is simulator-only.
2. **`reporting.py` is ready for live use.** `run_session.py --plot` will write the same two figures
   for a real throw once the hardware path runs (it calls the identical `plot_session`). No further
   work is needed there.
3. **Optional polish (not done, out of scope):** a 3D trajectory view, overlaying the bias-corrected
   landing marker, or a combined multi-throw contact-sheet — all additive on top of `plot_session`.
4. **No CLAUDE.md edit required for Part 7.** It implements the §1 `reporting.py` entry ("plots,
   statistics, session report") and the §5.6 `plots/` directory as written; `--plot` is an additive,
   default-off convenience, not a spec change. The §1 tree still also lists `reporting.py` as the home
   of "statistics" and "session report" — only the *plots* half is built here; a text/CSV session
   report remains optional future work if ever wanted.

---
---

# PART 8 — HTML reporting layer (`website.md` Stages 1–4 + visual restyle) — as-built record

> **Context for the downstream editor.** Parts 1–7 cover the CLAUDE.md pipeline (software through the
> §9 gate, firmware, acquisition, static/campaign tooling, reporting plots). Part 8 records a SEPARATE
> approved spec — `website.md` — that adds a browser reporting layer **on top of** the finished
> pipeline: a per-throw `report.html` (input → frozen → failure states) written inside each session
> dir, a campaign `campaign.html` written in the sessions parent dir, and a stdlib local server for
> browser ground-truth entry with audited write-back. It performs **no new physics**; it consumes
> on-disk artifacts and reuses existing analysis code. Built in four stop-and-confirm stages, then a
> visual-design pass against the approved mock, plus a demo helper.
>
> **State after Part 8: 218 tests passing** (195 pipeline + 23 web-layer: `test_web_report` 9,
> `test_serve_report` 10, `test_run_session_web` 4). No pure computational module was modified; no new
> dependency was added (stdlib `http.server` only). `config.yaml`, `requirements.txt`, firmware, and
> all Part 1–7 modules are untouched.

## SS. Files created / touched (Part 8)

**NEW**
```
pipeline/web_report.py                 # session + campaign __DATA__ builders + renderers (I/O member)
pipeline/web_assets/session_report.html# per-throw template (all CSS+JS inline, <!--__DATA__--> marker)
pipeline/web_assets/campaign_report.html# campaign template (idem)
scripts/serve_report.py                # stdlib local server: GET /, /api/health, POST /api/ground-truth
scripts/demo_web_reports.py            # convenience: generate+process+render viewable HTML (no hardware)
tests/test_web_report.py               # Tests 1-4 (state/self-containment/numbers/campaign)
tests/test_serve_report.py             # Tests 5-10 (solve equality, write-back, atomic, late entry)
tests/test_run_session_web.py          # Stage-4 headless smokes (--web POST / skip / Ctrl-C / gt_event)
```
**MODIFIED**
- `scripts/run_session.py` — §6.3 `solve_ground_truth` refactor; `_capture_default` extraction;
  `web_finalize` / `_wait_console_or_post` / `run_web`; `--web`/`--no-web` args; imports.
- `scripts/append_ground_truth.py` — `update_session_ground_truth` strengthened to an ATOMIC write.

**UNTOUCHED (guardrail):** every pure computational module (`geometry, corrections, trilateration,
kalman, landing, bias, segmentation, background, simulator, process_throw`), `analyze_campaign.py`
(reused, not edited), `config.yaml`, `requirements.txt`, firmware.

`web_report.py` is the plotting/I-O member of `pipeline/` (same status as `reporting.py`); it holds the
ONLY templates and contains no physics. Its CSS/JS all live in the two `.html` templates — the Python
just injects one JSON blob at the single `<!--__DATA__-->` marker.

## TT. (VERIFY) reconciliation — real schema vs. the spec's provisional names

`website.md` §3 marked many field names provisional. Confirmed against `process_throw.py` (the writer),
`run_session.py`, `geometry.py`, `simulator.py`. **The real names on the right were used everywhere; the
spec's stand-ins are wrong.**

| spec §3 assumption | REAL key/shape (used) | source |
|---|---|---|
| `sigma_r`, `sigma_theta` | **`sigma_r_m`**, **`sigma_theta_deg`** | `process_throw.py` prediction block |
| `v_h` | **`v_h_m_s`** | same |
| `cov_xz_m2` shape | **nested 2×2 list** `[[a,b],[c,d]]` | `pred.cov_xz.tolist()` |
| `model` id | **`prediction.model_id`** (sibling of `raw`) | same |
| caveat string | **top-level `small_sample_caveat`** (NOT under `raw`) | same |
| `temperature` | **`temperature_c`** | session.json |
| `timestamp` | **often ABSENT** (sim/factory have `session_id`) | session_factory |
| in-window denominator (§4.1) | **`gate_summary.n_triplets_in_throw` already exists** | `process_throw.py` |
| malformed count | **`gate_summary.malformed_lines`** | same |
| trajectory cols | **`t_sample_s, x_raw_m, y_raw_m, z_raw_m, x_kalman_m, y_kalman_m, z_kalman_m`** | `_write_trajectory_csv` |
| triplets layout | **LONG** (one row per triplet×sensor): `triplet,sensor,echo_us,t_trig_us,t_sample_us,d_centre_m,reading_valid,triplet_valid,in_throw` | `_write_triplets_csv` |
| ground_truth σ keys | **`sigma_x_m`,`sigma_z_m`** (Cartesian) + `L_centroid_m`,`L_S1_m`,`sigma_tape_m` | `run_session.prompt_ground_truth` |

→ Net: §4.1's "derive in-window count from CSV" fallback was **not needed** (the field exists). `d_centre_m`
is empty for gated/timeout rows, so the range-vs-time panel derives range from `echo_us` via
`corrections.echo_us_to_m` (mirroring `reporting.py`), exactly as §3.3/§5.5 instructs.

## UU. Stage 1 — session renderer + `session_report.html`

**Approach.** `render_session_report(session_dir, config)` reads `session.json`/`trajectory.csv`/
`triplets_raw.csv`, builds ONE `window.__DATA__` dict, injects it at `<!--__DATA__-->`, writes
`report.html`. Three states selected from disk: **input** (prediction present, no GT), **frozen**
(prediction + GT), **failure** (no usable prediction). Every authoritative number copied verbatim from
`session.json`; the drawn parabola/Kalman/scope are cosmetic re-fits only.

**Tests (3 functions = §10 Tests 1-3):** self-containment (no `http(s)://`/external `src`/`link`,
`window.__DATA__` present); state selection (input/frozen/failure); numbers-from-disk equality.

**Deviations / problems (NOT according to a naive reading of the spec):**
- **D-1 (load-bearing). State must key on the ENTERED `ground_truth` block only — not the simulated
  `truth.landing` fallback.** `reporting.py`/`calibrate_bias` treat `truth.landing` as a GT stand-in.
  If applied here, EVERY simulated session would render "frozen" and the input form could never appear,
  making an input-mode fixture impossible. So `web_report._ground_truth` deliberately drops the sim
  fallback (documented in its docstring). The fallback remains a *campaign-stats* concern (Stage 2).
- **D-2. Failure path: `process_session` RAISES on `< min_fit_points` / no-throw**, before writing the
  CSVs or prediction — so a failure session.json simply lacks `prediction`. The renderer classifies on
  "no usable prediction" and degrades gracefully when CSVs are absent. The "need >= 4" empty-state line
  is **built in Python** and inlined in `__DATA__` (ASCII, testable), not constructed in JS.
- **D-3. Tests assert `__DATA__`, not the DOM.** The tape form lives statically in the template
  (shown/hidden by JS), so input-vs-frozen can't be told apart by static-HTML string matching; the
  meaningful contract is `data.state`. This decision made the later visual restyle safe (see §YY).
- Stage-1 GT submit button shipped **inert** (the live server arrives in Stage 3), so no save could
  silently fail before the POST endpoint existed.

## VV. Stage 2 — campaign renderer + `campaign_report.html`

**Approach.** `render_campaign_report(sessions_root, config)` reuses, never recomputes:
`analyze_campaign.load_campaign` + `summary_stats`, `bias.evaluate`, `CorrectionModel`,
`geometry.cart_to_polar`. Writes `<sessions_root>/campaign.html`, full overwrite every call (never
frozen). `analyze_campaign.py` was confirmed importable without side effects (only `matplotlib.use(Agg)`
at load), so it was **not modified** (the §8/§2 "touch only if needed" was not triggered). The
`scripts/` import is **lazy** inside the campaign functions so the Stage-1 session path never pulls
matplotlib.

**Test (4 functions extend Test 4):** numbers == `summary_stats(...)`; corrected-path with a written
`none` model; overwrite-not-append; empty/awaiting state.

**The real bug found & fixed (NOT a test artifact) — §VV-1.** `analyze_campaign.load_campaign` globs
`sessions_root/*` and feeds EVERY match to `load_record` (`json.load`). Since `campaign.html` is written
INTO that same root, the **next** regenerate fed the HTML to `json.load` and crashed — and §6.5
regenerates the campaign on every run and every GT entry, so this would hit production, not just tests.
**Fix:** `build_campaign_data` globs **session subdirectories only** (`sessions_root.iterdir()` filtered
to dirs), never stray files. `analyze_campaign.py` itself was not changed; the filtering lives entirely
in the new code. This makes `render_campaign_report` safe to call repeatedly, which Stage 4 relies on.

## WW. Stage 3 — `serve_report.py` + the §6.3 solve refactor + atomic write

**§6.3 solve refactor (behaviour-preserving).** Factored the pure part of
`run_session.prompt_ground_truth` into **`solve_ground_truth(L_centroid, L_S1, pred_z, config) ->
gt_block`** (+ a shared `_gt_block` helper). `prompt_ground_truth` now calls it for the default pick and
**keeps the interactive `+/-` two-fold-ambiguity override** (the only remaining `input()`). All three
entry points (terminal prompt, `append_ground_truth`, web POST) reach the same audited solve, so they
**cannot diverge** (proved by Test 5: the three GT blocks are byte-identical). `append_ground_truth`
keeps its `SimpleNamespace` shim → `prompt_ground_truth` (reaches `solve_ground_truth` transitively),
preserving its behaviour and its existing test — flagged as a deliberate choice over the spec's
"remove the shim" suggestion, since the stronger guardrail is "behaviour-preserving".

**§6.2.1 atomic write.** `update_session_ground_truth` was a plain in-place write; strengthened to
**tempfile in the same dir → `json.dump` → `flush` + `os.fsync` → `os.replace`** (atomic rename), with
temp cleanup + re-raise on failure. Still writes only the `ground_truth` key, same `indent=2`/`newline=""`
serialization. A crash mid-write leaves the PREVIOUS valid `session.json` (Test 9 proves: only
`ground_truth` added; a simulated `json.dump` failure leaves the original intact and no `.session-*`
residue; `os.replace` is on the success path).

**Server (`serve_report.py`).** stdlib `ThreadingHTTPServer` on `127.0.0.1:0`. Testable core split from
the HTTP shell: `find_session_dir` (path-safe id→dir; rejects `/`,`\`,`..`), `pending_sessions`,
`compute_error_mm`, and **`handle_ground_truth`** (409 no-z / 422 degenerate / 500 write-fail / 200 from
the **re-read** file → re-render frozen report + campaign). Routes: `GET /` (active report or pending
index), `GET /s/<id>` (regenerate+serve an input page), `GET /api/health`, `POST /api/ground-truth`.
`--session` and `--pending` CLI modes (§6.6). The page's input JS health-checks `/api/health` on load
and is success-gated: it freezes (via `location.reload()` of the server-rewritten frozen file) ONLY on
`200 persisted:true`; on 409/422/5xx/network it surfaces the message and stays in input mode (never
optimistic).

**Problems / not-according-to-plan:**
- **Import cycle:** `serve_report` imports `run_session`; so `run_session` must import `serve_report`
  **lazily** (inside `web_finalize`, Stage 4) — top-level would cycle.
- The §6.2 `200` body returns the **ground-truth** r/θ/x/z + `error_mm_raw`/`error_mm_corrected?` from
  the re-read dict, so the on-screen number is provably the on-disk one.
- Test inputs chosen so the interactive override never fires: a mark at `(0.7, copysign(0.35, pred_z))`
  resolves cleanly (the two circle solutions are mirror-in-z; `pred_z = -0.294` for the standard test
  throw keeps `|d0-d1| >> 0.05`).

**Tests:** 10 functions (§10 Tests 5-10 + a real-socket `http.client` health+POST smoke).

## XX. Stage 4 — `run_session.py --web` integration

**Confirmed Ctrl-C guarantee (preserved):** `main()` is wrapped in `try/except KeyboardInterrupt`;
`capture_session` writes `session.json` first and flushes `raw_serial.log` per line; `process_session`
writes the prediction BEFORE the GT step. So a Ctrl-C during GT entry always leaves a fully-processed,
reprocessable awaiting-GT session.

**Approach.** Additive `--web`/`--no-web` (mutually exclusive; default = terminal, unchanged). Extracted
`_capture_default` from `run_default` (byte-equivalent), so the terminal path is untouched.
`web_finalize(session_dir, config, out_dir, *, open_browser, wait_for_entry)` = render input report →
render campaign → `serve_report.start_background` (REUSED server, not reimplemented) → open browser →
block on `_wait_console_or_post` (a daemon stdin reader for "skip" OR `httpd.gt_event` set by a
successful POST — **no timeout**) → `finally` shuts the server down (so Ctrl-C tears it down and
propagates) → re-render campaign. `wait_for_entry` is the injectable seam for headless tests.

**Server reuse (not duplication):** added `ReportServer.gt_event` (set in `do_POST` on `200 persisted`)
and `start_background(...)`; refactored `serve()` to call `start_background` so bind/serve lives in ONE
place, shared by the CLI and `--web`.

**Browser auto-open:** `webbrowser.open(url)` fires AFTER results are computed and the input report is
rendered, to the live server URL (input mode); best-effort (try/except → headless prints the URL).
Only the per-throw page auto-opens; campaign is regenerated but not opened.

**Problems:** initial `NameError: sys` (run_session lacked `import sys` for the new code path — caught
immediately by the Stage-4 test, fixed). Skip is non-destructive by construction (GT is written ONLY by
the POST handler); late completion reuses the existing Stage-3 `serve_report.py --session/--pending`
(no second late path built).

**Tests:** 4 headless functions — POST→frozen+campaign (real `http.client` against the reused server),
skip→late-complete-equal (block == `solve_ground_truth`), Ctrl-C leaves a clean awaiting-GT session,
`gt_event` set by a real POST.

## YY. Visual-design pass — restyle both templates to the approved mock

The canonical mock (`landing_report_mock.html`, §7) arrived AFTER Stages 1-4 (which had been built to
§7's written spec). This pass restyled **appearance + DOM only** — no backend/data-contract/server/
solve/test-logic change. **Why safe:** every test reads the injected `window.__DATA__`, never the DOM,
so HTML/CSS/canvas restructuring cannot break them as long as the `<!--__DATA__-->` marker and the data
dict survive and Test 1 (self-containment) still holds.

**Kept verbatim:** all real-data wiring (state machine, raw/corrected channel with real fields, yield,
caveat, trajectory/range-vs-time arrays, GT block, error_mm, server endpoints), the live health-check +
success-gated POST, the cosmetic polyfit re-fit and the `cov_xz_m2` eigen-decomposition σ-ellipse.
**Replaced from the mock:** palette/chrome (radial-gradient bg, scanline overlay, `header.bar` pulsing
lamp + mono chips + backdrop blur, blurred panels, hairline eyebrows), big mono numerals, the
scope/profile/3D/campaign/histogram drawing styling — all **fed from `D.*`**, replacing the mock's
hardcoded `SENSORS/PRED/ELL/ARC/CAMP`.

**Dropped (mock-only / would violate §1):** the `<nav class="tabs">` + `showView()` single-file toggle
(the two pages stay independent files); the mock's **client-side `twoCircle`/`computeGT` preview solve**
(replaced by the real server POST — authoritative numbers from Python); both `.mocknote` "MOCK" banners.

**Deliberate deviations from the mock (flagged):**
1. **Stat strip keeps 5 semantically-correct cards**, styled like the mock's `.stat`: yield,
   heading/v_h, temp/sound, **"Fit dof (N − 3)"** alone, **"Malformed lines"** separate. The mock's 4th
   card conflated dof with "Kalman" + malformed, which violates §4.2 / the §12-item-7 requirement.
2. Header shows real fields (session id, timestamp, temperature) — no "SPEC v2.1" stand-in.
3. **Range-vs-time collapsible panel retained** (a real §5.A feature the mock omitted), restyled to match.

Verified standalone via `file://`: both files self-contained (no `http(s)://`/external refs), no
tab/nav linking them (`NO nav.tabs`, `NO showView`), `header.bar` chrome present, real numbers rendered.

## ZZ. `demo_web_reports.py` — viewing the pages without hardware

There is no single existing CLI that emits the WEB reports for synthetic data (`simulate_session --plot`
makes matplotlib PNGs, not HTML; `serve_report`/`run_session --web` need a processed session / hardware).
`scripts/demo_web_reports.py` chains generate (beam cone OFF, since the 7° config placeholder admits zero
campaign-speed triplets) → `process_session` → `render_session_report` + `render_campaign_report`, with
`--with-ground-truth` writing GT for ~half (via `solve_ground_truth` from the true landing) so the FROZEN
view + a populated campaign are visible. Prints `file://` URIs. **Status: convenience/demo tool; flag for
keep-or-remove.** Verified working (3 sessions → 2 frozen + 1 input + campaign.html).

## AAA. §12 acceptance checklist — final status
- [x] frozen `report.html` opens from `file://` with no network (verified on a real generated file).
- [x] submit → `ground_truth` written ONLY via `update_session_ground_truth`; page freezes; error in mm.
- [x] web GT block byte-identical to terminal block (Test 5).
- [x] success-gated freeze (`200 persisted`); displayed error is the read-back value; write atomic.
- [x] skipped/closed session completable later via `--session` / `--pending`; input page health-checks
      and directs the operator; GT entry can never be lost.
- [x] `campaign.html` in `data/sessions/`, regenerates each run + each GT entry, reflects all throws,
      never frozen.
- [x] yield `used / in-window` with ≥4 status; fit dof `N − 3`, not conflated with Kalman/malformed.
- [x] no pure computational module modified; no heavyweight dependency; ASCII console; all tests green.
- [x] **visual parity with the mock** — done in §YY (was the only item pending until the mock arrived).

## BBB. Test ledger + notes for the future
**Tests:** 195 pipeline + 23 web (`test_web_report` 9, `test_serve_report` 10, `test_run_session_web` 4)
= **218 passing**. No existing test was modified for the web layer (they are appearance-agnostic). Run:
`.\venv\Scripts\python.exe -m pytest tests\ -q`.

**Notes for the future:**
1. **The `--web` HARDWARE path is unexercised** — `web_finalize` is proven headless (injected
   `wait_for_entry` + real `http.client`), but a live Arduino throw → auto-opened browser → tape entry
   has never run (no kit). The browser auto-open is stdlib `webbrowser` (best-effort; headless prints
   the URL).
2. **Beam cone still 7° (unverified placeholder)** → all synthetic web generation must use
   `--beam-cone off` / `beam_cone_enabled=False` (the demo does). Tune from §7 hardware data before
   trusting synthetic triplet counts (Part 2 §J).
3. `demo_*` session dirs are disposable (`Remove-Item -Recurse data\sessions\demo_*`).
4. `append_ground_truth`'s `SimpleNamespace` shim was deliberately kept (behaviour-preserving); removing
   it is optional polish if the spec's literal §6.3 reading is preferred.
5. The pre-existing Part 1-2 §F CLAUDE.md spec-text edits remain unapplied (documentation-only, not part
   of this work).
6. **No CLAUDE.md change required for Part 8** — `website.md` is a separate approved spec; the web layer
   adds files + two additive script changes and touches no pipeline contract.

---
---

# PART 9 — G1 ground-truth migration: two-tape → centroid + 2-sensor multilateration

> **Context.** `CHANGES.md` (CLAUDE.md v2.3 §10 item 17 / G1) migrates the ground-truth path from the
> Part-8 two-tape method (centroid + S1, two-circle intersection, interactive mirror override) to
> **least-squares multilateration over the centroid + the two sensors nearest the predicted landing**:
> the pipeline recommends the pair, the operator **accepts (one tap) or overrides**, measures three
> tapes, and the solve is **unique** (no mirror). Built in four stop-and-confirm stages (geometry →
> shared solve/terminal → server → front end), bottom-up, with the user's explicit choice to accept an
> **intermediate red window** between stages (option A) rather than ship a compat shim.
>
> **State after Part 9: 217 tests passing** (the 218 Part-8 baseline − 6 retired two-circle tests + new
> multilateration/recommend/load_record tests; net −1). Only `geometry.py` among the pure computational
> modules was touched (the solver lives there); all other pipeline modules, the atomic writer, the
> self-containment mechanism, and the campaign page are unchanged. The DERIVED `ground_truth` keys
> (`r_m/theta_deg/x_m/z_m/sigma_x_m/sigma_z_m`) are preserved, so `calibrate_bias.load_record` /
> reporting / campaign are unaffected.

## P9-A. Files touched (Part 9)
**Modified:** `pipeline/geometry.py` (new solver + `recommend_reference_sensors`; retired
`two_circle_intersection`), `scripts/run_session.py` (`solve_ground_truth` new sig + accept/override
prompt), `scripts/append_ground_truth.py` (shim carries x_m), `scripts/serve_report.py` (new POST
body/validation), `pipeline/web_report.py` (`sensors`/`recommended`/`residual_warn_m` in `__DATA__`),
`pipeline/web_assets/session_report.html` (recommendation/override panel + scope highlight),
`config.yaml` (`recommend_sensors`/`cond_warn`/`residual_warn_m`), tests `test_geometry.py`,
`test_analyze_campaign.py`, `test_serve_report.py`, `test_run_session_web.py`, `test_web_report.py`.
**Untouched (guardrail):** `corrections, trilateration, kalman, landing, bias, segmentation,
background, simulator, process_throw`, `analyze_campaign.py`, the campaign template, the failure state.

## P9-B. Stage 1 — geometry (multilateration solver)
- `recommend_reference_sensors(landing_xz, config) -> (a, b)`: two nearest sensors, nearest-first,
  **deterministic index tie-break**. `ground_truth_landing(L_centroid, refs, config)`: linear 2×2 solve
  (subtract the centroid equation) + 1–2 Gauss–Newton steps over all three distances; returns
  `x,z,r,theta_deg,sigma_x,sigma_z,cov_xz` + **`ls_residual_m`** (3-distance misfit) + **`cond_number`/
  `cond_warn`**. Uncertainty = the existing delta method generalised 2→3 refs (`G` 3×2, `J=pinv(G)`).
- **F-9 raise→flag:** the solver NEVER raises on near-collinear refs — best lstsq estimate + `cond_warn`,
  no NaNs (CLAUDE.md §8.1 G1). The landing-fit concavity F-9 in `landing.py` is unrelated, untouched.
- **Problem / deviation:** the planned tie-break test assumed the centroid is equidistant from all three
  vertices; with the *rounded* config coords S2/S3 sit at circumradius 0.5773 vs S1 0.5774, so the real
  nearest pair from the origin is (S2,S3), not a tie. Fixed the test to a controlled symmetric layout
  where the tie is exact → asserts index ordering (S1,S2).
- **Gate:** geometry green; the ~10 caller tests went red as designed (option A), restored in Stages 2–3.

## P9-C. Stage 2 — shared solve + terminal prompt + schema + config
- `run_session.solve_ground_truth(L_centroid, refs, config)` (dropped `pred_z`); `prompt_ground_truth`
  rewritten to the **accept[Enter]/override** flow + three relabelled tape prompts + ASCII integrity
  warning; the `+/-` mirror override **removed**. `_gt_block`/`_tape_references` deleted. `append`'s shim
  now carries `x_m` (the recommendation needs it); it still routes through `prompt_ground_truth` →
  `solve_ground_truth` so the three paths stay byte-identical.
- **Schema:** kept the derived keys; replaced `L_S1_m` with `references: [{name,L_m}…]` + `sensors_used`;
  added `ls_residual_m,cond_number,cond_warn`. `two_circle_intersection` retired (its last caller was the
  old path; §1.4) + `_TANGENT_TOL` dead constant removed + `TestTwoCircleIntersection` dropped.
- **Problem / deviation:** `config.yaml cond_warn: 1.0e4` parsed as a **string** — PyYAML 1.1 needs a
  *signed* exponent (the H-1 lesson again). Fixed to `1.0e+4`. (geometry already falls back to a default,
  so the bug only surfaced once the key was added.)
- **New tests:** terminal == direct-`solve_ground_truth` byte-equality through the accept flow;
  `calibrate_bias.load_record` ingests a new-format `ground_truth` block. **Gate:** analyze_campaign GT
  test restored; the 9 server/web tests stayed red (Stage 3).

## P9-D. Stage 3 — server (handle_ground_truth + POST body)
- `handle_ground_truth(sessions_root, session_id, L_centroid, sensors, L_a, L_b, config)`: **409** no
  prediction; **422** if `sensors` ≠ two distinct of {S1,S2,S3} OR a degenerate solve; atomic write
  (**500** on failure); read-back **200** body now adds **`residual_m`** + **`cond_warn`**. `do_POST`
  parses the new body `{session_id, L_centroid, sensors, L_a, L_b}`. No `pred_z` anywhere.
- **Deviation:** the old `test_degenerate_tapes_422` (two-circle non-intersection) no longer applies —
  multilateration via lstsq never "fails to intersect". Replaced with `test_invalid_sensors_422`
  (duplicate / wrong-count sensors). Byte-equality (Test 5) re-proved under the new body. **Gate: full
  suite green (217)** — the intermediate red window closed.

## P9-E. Stage 4 — `__DATA__` + recommendation/override front end
- `web_report` adds `sensors` (3× name+x/z), `recommended` (the pair), `residual_warn_m`; frozen
  `sensors_used/ls_residual_m/cond_warn` flow through the existing `ground_truth` passthrough.
- `session_report.html`: replaced the two-field form with a **recommendation readout + locked-centroid +
  S1/S2/S3 chips** (recommended = cyan ring, selected = steel fill), **"Accept recommended"** one-tap,
  **three live-relabelled distance fields**, a **scope highlight** (cyan ring on the selected sensors),
  a **defensibility hint** (the recommendation only eases measurement; the three distances determine the
  landing), and a frozen **sensors-used line + amber integrity note**. Success-gated POST of
  `{session_id, L_centroid, sensors, L_a, L_b}` unchanged in mechanism. No new physics in JS; the solve
  is still Python's.
- **Tests:** `test_state_input` asserts `sensors`+`recommended`; `test_state_frozen` uses the new-format
  block + asserts `sensors_used`. Self-containment / numbers-from-disk unchanged. Manual `file://` smoke:
  input page shows chips + recommended pair + scope rings; a server POST freezes it with `sensors_used`
  and zero residual on consistent tapes; no nav/tabs; no `http(s)://`.

## P9-F. CHANGES.md §10 acceptance — final status
- [x] GT solved by LS multilateration over centroid + 2 chosen sensors; **unique, no mirror prompt**
      anywhere (terminal or web).
- [x] Prediction recommends the 2 nearest sensors; **one-click accept** or **override** to any valid
      pair, in both the terminal and the HTML page.
- [x] Recommendation + override are **on-palette, first-class** (chips, readout); selected references
      **highlighted on the scope**; the three distance fields **relabel live**.
- [x] `session.json` records `sensors_used`, `ls_residual_m`, the condition flag; derived keys
      unchanged; `calibrate_bias.load_record` still works (test).
- [x] Terminal, `append_ground_truth`, and web POST produce a **byte-identical** `gt_block` (Test 5).
- [x] Near-collinear refs **flag** (no raise/NaN); a bad tape shows as a large residual warning without
      blocking the save; write still atomic + success-gated.
- [x] Campaign page, failure state, all pipeline modules unchanged; no new dependency; ASCII console;
      full suite green (217).

## P9-G. Test ledger + notes
**Tests:** 217 passing. Deltas vs the 218 Part-8 baseline: `test_geometry` 29→27 (−6 two-circle,
+multilateration/recommend), `test_analyze_campaign` 5→6 (+load_record new-format). `test_serve_report`
(10), `test_run_session_web` (4), `test_web_report` (9) updated in place to the new protocol. Run:
`.\venv\Scripts\python.exe -m pytest tests\ -q`.

**Notes for the future:**
1. `cond_warn`/`residual_warn_m` are **starting values to tune** (CHANGES §4), not gospel.
2. The `--web` HARDWARE path remains unexercised (no kit); the new panel is proven headless + via the
   real local server. The 7° `beam_half_angle_deg` is still the untuned placeholder (out of G1 scope).
3. `geometry.recommend_reference_sensors` is the single home of the default pair (terminal, web, append)
   — keep it that way so the recommendation cannot diverge across paths.
4. **No CLAUDE.md change required** — v2.3 already specifies G1; this brought the code up to it.

## P9-H. Housekeeping — `demo_web_reports.py` removed (post-G1)

**What & why.** `scripts/demo_web_reports.py` (added in Part 8 §ZZ as a convenience to generate +
process + render viewable HTML from synthetic data without hardware) was **deleted**. It was never
imported by any production module or test — a grep found references only in its own file and these
notes — and it is not needed for present working or future function: the real entry points cover every
use:
- **viewing a per-throw page:** `serve_report.py --session <id>` (live input/accept-override flow) or a
  frozen `report.html` opened from `file://`;
- **rendering programmatically:** `web_report.render_session_report` / `render_campaign_report` (the
  exact functions the demo wrapped);
- **a real run:** `run_session.py --web`.

So the demo was redundant surface area, not a capability. This resolves the Part 8 "keep-or-remove"
open item in favour of **remove**. **Part 8 §ZZ is left intact** (as-built record; it now describes a
file that no longer exists — noted here rather than by editing Part 8).

**Approach / result.** Deleted the script; also removed the disposable `demo_*` session dirs and the
demo-written `data/sessions/campaign.html` it had produced, leaving `data/sessions` at its prior 12
synthetic `sim_*` dirs. **Nothing else changed.**

**Tests.** Re-ran the full suite after deletion: **217 passed** (unchanged) — confirming the demo was
not load-bearing. No problems or surprises; nothing deviated from intent.

**Note for the future.** If a one-command synthetic viewer is ever wanted again, it is ~40 lines:
`random_throw` (beam-cone OFF) → `write_session_dir` → `process_session` → `render_session_report` +
`render_campaign_report`, printing `file://` URIs. Re-create only if the manual `serve_report.py` path
proves insufficient.

## P9-I. The ground-truth solve: 2 distances → 3, then recommendation (one-place headline)

> This is a scannable summary of the change "the ground-truth landing solve went from **2 distances** to
> **3**, and the pipeline now **recommends** which two sensors to tape." The full stage-by-stage record
> (files, math, problems, tests) is **§P9-A–§P9-G above**; this section restates only the conceptual
> before/after so it is findable by that description. (To be precise about wording: this is the
> **ground-truth landing** solve in `geometry.py`, not the per-throw *ball* trilateration in
> `trilateration.py` — that always used three sensors and was not touched.)

**Before (2 distances).** Ground truth was solved by **two-circle intersection**: tape to the centroid
(`L_centroid`) and to **S1** (`L_S1`) → two circles → **two** candidate points (a mirror pair across the
centroid–S1 line). The operator/`pred_z` resolved the mirror, occasionally via an interactive `+/-`
prompt. Two distances, two unknowns, **inherently ambiguous**.

**After (3 distances).** Ground truth is solved by **least-squares multilateration** over the **centroid
+ two sensors** (three tape distances): subtract the centroid equation from each sensor equation → a
unique 2×2 linear solve (refined by 1–2 Gauss–Newton steps over all three residuals). **The third
distance breaks the reflection symmetry → the solution is UNIQUE: no mirror, no `pred_z`, no `+/-`
prompt.** Side-benefits the third constraint enables: an **`ls_residual_m`** integrity guard (a
mis-measured tape / mislogged sensor shows up as a large residual instead of a silently-wrong point) and
a **condition-number flag** for degenerate sensor pairs (warn, never raise).

**Then: recommendation.** Because any two sensors now suffice, the pipeline picks the **two sensors
nearest the predicted landing** (`geometry.recommend_reference_sensors`, deterministic index tie-break)
— the easiest, most accurate tapes — and the operator **accepts in one tap or overrides** to any valid
pair, in both the terminal prompt and the HTML page (chips + live-relabelled distance fields + scope
highlight). Honest framing kept visible in the UI: the recommendation only chooses *which tapes are
easiest to measure*; the landing is determined by the three measured distances, so accepting it does
**not** bias the result.

**Problems / not-according-to-plan (recap, detail in §P9-B–§P9-E).** (1) the tie-break test wrongly assumed
the centroid is equidistant from all three rounded vertices (S2/S3 at 0.5773 vs S1 0.5774) → fixed with
a controlled symmetric layout; (2) `config.yaml cond_warn: 1.0e4` parsed as a **string** (PyYAML 1.1
needs a signed exponent) → `1.0e+4`; (3) the old `degenerate-tapes → 422` test no longer applies (lstsq
never "fails to intersect") → replaced by an **invalid-sensor-selection → 422** test. The build was
deliberately **bottom-up with an intermediate red window** (geometry first; ~10 caller tests red until
Stages 2–3 rewired them) — a chosen approach, not an accident.

**Result / guardrails.** Unique solve everywhere; **byte-identical** `gt_block` across terminal /
`append_ground_truth` / web POST (anti-divergence); DERIVED keys preserved so `calibrate_bias` /
reporting / campaign are unaffected; only `geometry.py` among pure modules touched; atomic write,
self-containment, ASCII console intact.

**Tests.** **217 passing** (218 Part-8 baseline − 6 retired two-circle tests + new multilateration /
recommend / new-format-`load_record` tests; net −1). Run: `.\venv\Scripts\python.exe -m pytest tests\ -q`.

---

# PART 10 — D5: demo / live session storage separation — as-built record

*(Part-number note: the D5 work order prospectively referred to this record as "Part 9/D5"; by the
time it was written the G1 migration had already claimed Part 9, so the D5 record is **Part 10**.)*

**Spec:** CLAUDE.md v2.4 (§0.3, §1, §2, §5.6, §5.7, §6, §8.7, §10 item 18, §12.2, §12.5).
**Work order:** CHANGES.md (D5), Stages 0–5, built in five stop-and-confirm stages.
**One sentence:** stop the campaign report from mixing simulator/demo throws with live throws by
moving demo sessions under `data/sessions/<demo_subdir>/` (default `demo/`), giving each subtree its
own `campaign.html`, and routing every session-enumeration site through one predicate.

## D5-A. The one mechanism — `is_session_dir` (where it lives and why)

```python
def is_session_dir(p) -> bool:
    return Path(p).is_dir() and (Path(p) / "session.json").exists()
```

**Home: `pipeline/web_report.py`** (just below the `_MARKER` constant). Chosen there because
web_report already owned the §VV-1 "directories-only" campaign filter this supersedes, and because the
import topology is cycle-free: web_report's top-level imports are pure `pipeline` (corrections,
geometry); it imports `analyze_campaign` only **lazily** inside `_campaign_modules()`. So
`analyze_campaign` and `calibrate_bias` (both in `scripts/`) doing `from pipeline.web_report import
is_session_dir` at module level form **no cycle**.

**Routed through all three enumeration sites** named in CLAUDE §8.7 / §12.2:
- `web_report.build_campaign_data` — replaced `... iterdir() if p.is_dir()` with the predicate; a
  non-session subdir now prints `skip <name>: no session.json`.
- `analyze_campaign.load_campaign` — directory case routed through the predicate (prints a skip
  reason; previously skipped **silently**). See deviation D5-D(1) for the file-case hardening.
- `calibrate_bias` per-path loader (`main`) — routed through the predicate; non-session paths recorded
  in `skipped`.

This is the whole separation: the live builder scanning `data/sessions/` sees the `demo/` directory,
finds no `demo/session.json`, and skips it — **no name matching on "demo" or "sim_"**. Config gained a
new **top-level `sessions:` block** (`demo_subdir: "demo"`, D5b) placed immediately above `simulator:`,
kept separate because it is storage layout, not simulator physics.

## D5-B. Stage 0 finding — raise vs skip (the load-bearing question)

Self-inspected at Stage 0 (file:line quoted in the session log):
- `analyze_campaign.load_campaign` already **skipped silently** (`continue`, no print) on a path with
  no `session.json`.
- the `calibrate_bias.main` loader already **skipped with a recorded reason** (`skipped.append(...)`).
- `calibrate_bias.load_record` itself opens the path unguarded and **would** raise `FileNotFoundError`,
  but both callers gate it behind an `is_file()` check, so in practice it never raises.

**Conclusion:** the predicate is a **hardening / consolidation, not a behaviour change**. A `demo/`
subtree dropped under `data/sessions/` was *already* excluded from the live campaign (build_campaign_data
is non-recursive `iterdir`, and `load_campaign` skipped `demo/` for want of `demo/session.json`). D5 just
gives that implicit skip one named predicate and a printed reason. The genuine behaviour changes are
*where* `simulate_session` writes (Stage 2), the auto demo-campaign regen (D5a), and the migration.

## D5-C. Files touched

- `config.yaml` — new top-level `sessions: { demo_subdir: "demo" }` (D5b).
- `pipeline/web_report.py` — `is_session_dir`; `build_campaign_data` routed through it.
- `scripts/analyze_campaign.py` — import + `load_campaign` routed through it (incl. file-case
  hardening, D5-D(1)).
- `scripts/calibrate_bias.py` — import + per-path loader routed through it.
- `scripts/simulate_session.py` — `--demo-subdir` flag; writes under `<out-dir>/<demo_subdir>/`;
  end-of-batch best-effort `render_campaign_report(demo_root, config)` (D5a).
- `run_session.py` / `serve_report.py` — **unchanged** (Stage 3): both already call
  `render_campaign_report` on the **live** root, so the predicate excludes `demo/` for free; there was
  no name-based exclusion to remove.
- Tests: `test_web_report.py` (+2), `test_analyze_campaign.py` (+1), `test_simulator.py` (+2),
  `test_serve_report.py` (+1) = **+6**.

## D5-D. Deviations from the work order (with justification)

1. **`load_campaign` file-branch hardened (Stage 1).** The original loop accepted *any* non-directory
   glob match as a `session.json` path (`session_json = p`). A `data\sessions\*` glob matching our own
   `campaign.html` would then hand HTML to `load_record` → `json.load` → **crash** (a latent bug now
   reachable once a sibling `campaign.html` exists). Restricted the file branch to accept a file **only
   if its name is `session.json`**; any other stray file prints `skip <name>: not a session`. Consistent
   with D5's "the predicate is the single gate". `calibrate_bias` was already safe (it always does
   `folder / "session.json"`), so no equivalent change there.

2. **Stage 4 was DELETE + REGENERATE, not MOVE (user decision).** CHANGES.md Stage 4 specified moving
   the existing synthetic dirs into `demo/`. The user instead chose to **delete** the old synthetic dirs
   and **regenerate** a fresh batch in the new destination. Justified by D5d's own rationale: demo
   sessions are **seeded and reproducible**, not irreplaceable raw campaign data, so deletion is safe
   (the "raw data is sacred" caution still binds real throws). Deletion was guarded: only dirs whose
   `session.json` had `simulated == true` were removed.

3. **Classified by the `simulated` flag, not the `sim_` prefix (Stage 0/4).** CHANGES.md Stage 4
   assumed the synthetic dirs carried the `sim_` prefix. The on-disk dirs were actually
   `demo_2026-06-25_005254_T01..T12` (created by something other than the current code — current config
   is `session_prefix: "sim"`, `S##`), so the `sim_` rule would have matched **zero**. Classifying by
   `session.json` `simulated: true` (all 12 qualified) is the robust, name-independent criterion and is
   what the deletion guard used.

## D5-E. Stage 4 migration record (delete-log + regenerate)

- **Deleted (12)** from `data/sessions/` — each confirmed `simulated: true` before removal:
  `demo_2026-06-25_005254_T01 … T12`.
- **Regenerated (12)** into `data/sessions/demo/` via
  `simulate_session.py --n-sessions 12 --beam-cone off --drag quadratic --heading-range-deg 60
  --noise-mm 8 --seed 20260625 --plot` →
  `sim_2026-06-25_145012_S01 … S12` (correct `sim_..._S##` naming; processed, with `plots/`). The
  demo campaign auto-regenerated (D5a) with **12 throws**.
- **Cleared** the stale root `data/sessions/campaign.html`, then regenerated the **live** campaign:
  console showed `skip demo: no session.json` → **0 throws (awaiting)**.
- Final: `data/sessions/campaign.html` → `n=0, awaiting=True`; `data/sessions/demo/campaign.html` →
  `n=12, awaiting=False`.

## D5-F. Tests + final gate

**223 passing** (217 Part-9 baseline + 6 D5 tests; 0 failed, 0 skipped). Run:
`.\venv\Scripts\python.exe -m pytest tests\ -q`. New tests: live campaign excludes a `demo/` subtree +
stray `campaign.html` and the `is_session_dir` predicate (web_report); `load_campaign` skips
non-session paths in a `root/*` glob (analyze_campaign); batch writes under `demo/` + `--demo-subdir`
override + demo-campaign auto-regen (simulator); the live web POST regenerates only the live campaign
(serve_report). CLAUDE.md is already at **v2.4** with the D5 changelog.

## D5-G. Follow-up — per-throw `report.html` for demo sessions + `demo_web_reports.py` made D5-aware

A post-D5 review found the demo `sim_*` sessions had no per-throw `report.html`, even though CLAUDE
§0.3 / §5.6 require a demo session to keep the **identical internal layout** as a live one
(`report.html` included). Root cause: `simulate_session.py` rendered only the demo *campaign*
(`render_campaign_report`, D5a), never the per-throw page (`render_session_report`). Two changes:

1. **`simulate_session.py` --plot now renders `report.html`.** In the `--plot` branch (the only mode
   that runs `process_session`), after the matplotlib plots it calls
   `render_session_report(folder, config)` inside the same `try` (an undetectable throw still
   `ValueError`-skips cleanly, no half-baked page). Processed demo sessions now match the §5.6 layout.
   The existing 12 sessions were **backfilled in place** (render `report.html` per dir + refresh the
   demo campaign; non-destructive — only `report.html`/`campaign.html` written).

2. **`demo_web_reports.py` made D5-aware (it was a live-root pollution hazard).** This convenience
   viewer — which *does* call `render_session_report` per session — defaulted its output to the **live**
   root `data/sessions/` and named dirs `demo_<stamp>_T##`. That is exactly how the original polluting
   `demo_..._T##` dirs (deleted in Stage 4) were created, and a run with defaults would have re-polluted
   the live campaign. Fixed to mirror `simulate_session.py`: resolve `demo_root = out_dir /
   sessions.demo_subdir` (with a `--demo-subdir` override), write sessions there, adopt the `sim_`
   naming (`session_directory_names`), and render the campaign over `demo_root`.
   **Correction to §P9-H / handoff.md:** `demo_web_reports.py` was reported *deleted* there; it was in
   fact still present (now D5-aware), not removed.

**Tests (+2 → 225 passing).** `test_simulator.py` — `--plot` batch yields `report.html` +
`trajectory.csv` in every demo session; `test_serve_report.py` — `demo_web_reports.main()` writes under
`<root>/demo/` with `sim_` names + `report.html` + a demo campaign, and leaves the live root clean.

---

# PART 11 — Military-HUD visual restyle of both report pages — as-built record

**Spec:** CLAUDE.md §12.6 (design system). **Scope:** appearance + canvas-drawing chrome only — **no**
data contract, server, solve, or test-logic change. Supersedes the look of Part 8 §YY (kept as the
prior as-built record).

## D11-A. What prompted it

The campaign scope's central element read as a "play button" — it was the sensor-array **triangle**
(S1 on +x → right, S2/S3 → left, so the outline points right). The user asked to remove it and to
evolve both browser pages (`campaign_report.html`, `session_report.html`) into a "slightly modernistic
military grade" instrument-HUD look, **without changing any displayed value, label, precision, or
functionality**. Two design mockups (campaign + per-throw) were shown and approved before coding.

## D11-B. Why this is safe (same argument as §YY)

Every test reads the injected `window.__DATA__`, never the DOM, so CSS/canvas restructuring cannot
break them provided the `<!--__DATA__-->` marker, the data dict, all element `id`s, and the
input/frozen/failure state machine survive — they all did. The **load-bearing constraint** is
`test_self_contained` ([test_web_report.py:62](tests/test_web_report.py:62)): it asserts
`"http://" not in html`, so the restyle **stays canvas + CSS and uses NO inline SVG** (an SVG
`xmlns="http://www.w3.org/2000/svg"` would fail it). No CDN / web fonts / `<script src>` / `<link href>`
either; `prefers-reduced-motion` disables all animation.

## D11-C. Changes (both templates, shared language)

- **Play button removed.** Campaign `drawCampScope` and per-throw `drawScope` no longer stroke the
  array triangle; S1/S2/S3 are drawn as **steel dots in bracket boxes** (`strokeRect`), with labels and
  (per-throw) the G1 selected-reference cyan ring preserved. The 3-D floor-plan triangle in
  `drawProf3D` is left intact (there it is a floor footprint, not a centered play-button).
- **Scope HUD.** Added a center reticle (crosshair with a gap), a bearing scale (`000–330°` tick
  labels), range-ring tick labels, and a subtle CSS `conic-gradient` **radar sweep** behind each polar
  scope (`<div class="sweep">`, `@keyframes` rotate, disabled under reduced-motion). Throw / GT / error
  markers and the σ-ellipse are unchanged (same `D.*`).
- **Chrome.** Panels 14px→3px radius with cyan L-bracket corner ticks (`::before/::after`); eyebrows
  became **numbered HUD tags** (`[01]…` via a CSS `counter`, label text verbatim) with a trailing
  hairline rule; header is a command banner (`//` separators feel, tick-mark underrule); body font is
  now monospace throughout; stat tiles got a top accent rule + `tabular-nums` (brackets suppressed on
  `.stat`); chips/inputs/toggles squared off (2–3px); the GT save button got a notched corner
  (`clip-path`); caveat / integrity / failure boxes became amber/coral left-accent strips; the
  histogram + plots gained framed baselines and brighter bar caps. **All numbers, labels, precision,
  and `fnum()` formatting are byte-identical** to the pre-restyle pages.

## D11-D. Verification

- **Full suite 225 passing**, 0 failed (web tests guard self-containment, state selection,
  numbers-from-disk, campaign numbers).
- Generated pages re-checked end-to-end: campaign + per-throw **input** + per-throw **frozen** are all
  self-contained, carry the numbered eyebrows + sweep, and the campaign has the triangle stroke removed
  and the sensor bracket boxes present.
- **Regenerated (delete old UI → remake):** 12 demo `report.html` + `data/sessions/demo/campaign.html`
  (n=12) + `data/sessions/campaign.html` (live, n=0 awaiting). The render functions full-overwrite, so
  a regen *is* the remake; no live `report.html` exists yet (those regenerate on the next
  `run_session.py` run).

## D11-E. Follow-up — polar-scope display radius 2 m → 3 m

The predicted landing is a **floor extrapolation** of the parabola fit, so it routinely lands beyond
the `gates.d_max_m = 2.0 m` *range-reading* gate (the demo set has throws at r ≈ 2.0–2.3 m). With the
scope display radius at ~2 m the outer landing dots clipped against / fell outside the last range ring.
Raised the **display radius (canvas `RMAX`) to 3.0 m** in both polar scopes — `drawCampScope`
(campaign, 2.2 → 3.0) and `drawScope` (per-throw, 2.1 → 3.0) — and extended the range rings to
`…,2.5,3.0`. The scale `sc=(min(W,H)/2-26)/RMAX` is unchanged in form, so every `sc`-drawn element
(sensors, reticle, bearing labels, Kalman track, predicted dot + σ-ellipse, GT dot + error vector,
throw dots) auto-rescales and all landings now sit inside the 3 m rings.

**Pure UI** — no data/value/label/id change; **`gates.d_max_m` was NOT touched** (it bounds real range
readings, a different quantity from the extrapolated landing point). Suite still **225 passing**; demo
set + both campaigns regenerated; generated pages confirm `RMAX=3.0` + the new rings and stay
self-contained.

**Sweep enlarged to match.** The decorative `conic-gradient` radar **sweep** (CSS `.scopewrap .sweep`)
was sized to the new 3 m rim so the rotating wedge spans the full display: campaign `488px`, per-throw
`508px` (= the canvas rim diameter `min(W,H) − 52`, since the rim radius `RMAX*sc = min(W,H)/2 − 26` is
RMAX-independent). Added `max-width:90%;aspect-ratio:1` so it never overflows the scope on a narrow
viewport, and nudged the alpha `.14 → .13` so the larger wedge stays subtle.

---
---

# PART 12 — Audit remediation (AUDIT_REPORT_20260702 → CHANGES.md) — as-built record

**Source:** `AUDIT_REPORT_20260702.md` (read-only audit against CLAUDE.md v2.5: 0 critical, 4 Major
M-1–M-4, 16 Minor). **Work order:** `CHANGES.md` (audit-remediation version), Stages 1–7, executed
per-stage with a plan-and-gate at each. **One sentence:** fix every Major and Minor finding in a
dependency-safe order — docs first, then the raw-data guard, the atomic GT write, terminal-mode
rendering, the live failure path, and a bundle of small hygiene fixes.

**Final state: 232 tests passing** (225 baseline + 7: Stage 2 ×1, Stage 3 ×2, Stage 4 ×1, Stage 5 ×1,
Stage 6 ×2). Stage 7 (three open decisions) is deliberately NOT implemented — it awaits the user's
call (see §P12-G). Guardrails honored throughout: the only pure computational module touched was
`trilateration.py` (a `valid`-guard condition, §P12-F) and `background.py` (a docstring), both
sanctioned by the work order; every ground-truth write into an existing session goes through the
atomic `update_session_ground_truth`; no existing passing test was weakened (the few that changed are
called out below with the reason).

## P12-A. Stage 1 — documentation reconciliation (M-2, Minor-3 doc half, Minor-4, -13, -14)

Docs only; no `pipeline/`/`scripts/`/`tests/`/`firmware/` source touched (config.yaml header line only).
- **CLAUDE.md:** §10 items 17 (G1) and 18 (D5) marked **BUILT** (→ Parts 9/10); §12.4 migration note
  and the v2.2→v2.3 changelog G1/(G1-status) entries rewritten to past tense ("migration complete;
  `two_circle_intersection` retired; no two-tape path remains"). §1 tree: all `(FUTURE)` markers
  removed, `CHANGES.md (currently: D5)` → `(currently: audit remediation)`, and the missing files
  added (`analyze_static.py`, `demo_web_reports.py`, four test files, and the three root docs). The
  **duplicate `## 12`** resolved by renumbering the *Audit disposition record* → **§13** (in place,
  annotated) and updating its 6 inbound refs; the HTML reporting layer keeps §12/§12.x (~30 refs +
  "absorbed as §12").
- **config.yaml:** header `(v2.3)` → `(v2.5)`.
- **IMPLEMENTATION_NOTES.md:** header spec `(v2.1)` → `(v2.5)`; **Part 9's section letters CC–KK
  renumbered to P9-A…P9-I** (they collided with Part 5's BB–GG *and* Part 6's HH–MM), with the 3
  inbound cross-refs remapped (§CC–§II, §DD–§GG in Part 9; §JJ in Part 10 §D5-G → §P9-H); Part 10's
  header gained a note reconciling the old "Part 9/D5" forward-reference (G1 took Part 9).
- **handoff.md:** rewritten from scratch (v2.5, 225 tests, CHANGES.md present, `demo_web_reports.py`
  present & D5-aware, sessions under `demo/`, `handoff2.md` reference removed).

## P12-B. Stage 2 — raw-data overwrite guard (Minor-5)

`run_session.capture_session` now refuses (raises `RuntimeError`) if the target directory already
holds a `raw_serial.log`, mirroring `simulate_session.create_session_folder`. Guard placed before the
`session.json` write so an existing session's metadata is protected too. New file
`tests/test_run_session.py` (the terminal-defaults-path home for Stages 2–5) with
`test_capture_session_refuses_to_overwrite_raw_log` (raises + original bytes unchanged).

## P12-C. Stage 3 — terminal ground-truth write via the atomic writer (M-1)

`run_default` replaced its plain `_write_json` GT merge with a lazy-imported
`append_ground_truth.update_session_ground_truth` (temp + fsync + `os.replace`) — the same writer
`serve_report`'s POST and `append_ground_truth` use, so all three GT paths are now atomic with no
bypass. Lazy import avoids the `append_ground_truth ↔ run_session` cycle (same idiom as
`web_finalize`'s lazy `serve_report`). Two new tests (mirroring `test_serve_report`'s atomic tests):
no `.session-*` residue on success; injected `json.dump` failure leaves the original `session.json`
byte-identical.

## P12-D. Stage 4 — terminal-mode report + campaign rendering (M-3)

`run_default` and `append_ground_truth.append_to_session` now call `render_session_report` +
`render_campaign_report` (the same renderers the `--web` path uses), so a terminal-mode throw and a
terminal-mode GT entry produce/refresh `report.html` + the subtree `campaign.html` per §5.6/§12.2. In
`append_to_session` the render is coupled to the write (like the web POST handler);
`session_dir.parent` is the correct subtree root for live and demo. **Test-touches (flagged):** the
Stage-3 success test gained `out_dir` on its args namespace (run_default now reads `args.out_dir`) +
two file-existence assertions; adding render to `append_to_session` gives
`test_serve_report.test_web_block_equals_terminal_and_append` a harmless render side-effect (still
passes). New `test_terminal_append_renders_report_and_campaign`.

## P12-E. Stage 5 — live failure-path robustness (M-4, two parts)

- **Part 2 (substantive), `process_throw.process_session`:** the gate summary + `triplets_raw.csv` +
  a partial `session.json` are now written **before** the Kalman/landing stage, so a fit-stage
  failure (`< min_fit_points`, `< 2` used, non-concave) still leaves the range-vs-time evidence the
  §12.1 failure report renders. On success the final `session.json` write adds `prediction` + caveat
  (content unchanged). The "no throw" segment-`None` case is untouched (raises earlier, nothing to
  show).
- **Part 1, `run_session`:** `_capture_default` wraps the `capture_session` call in
  `try/except ValueError`, prints a clean `"no prediction: …"`, and returns `(session_dir, None)`;
  `run_default`/`run_web` render the failure report + campaign and return on `None` (shared
  `_render_failure`). The Stage-2 overwrite `RuntimeError` is deliberately **not** caught. `main`
  reviewed and left unchanged (documented failure now handled upstream; broadening its catch would
  mask real bugs).
- New `test_run_default_failure_path_preserves_evidence_and_renders` (mocked serial, forced
  `min_fit_points=999`) covers all four audit criteria: no crash, clean message, `triplets_raw.csv` +
  gate summary persisted, failure report with a populated range-vs-time panel. **Test-touch
  (flagged):** the two Stage-3/4 tests that returned `(folder, None)` from a monkeypatched
  `_capture_default` were updated to a non-`None` sentinel, because `None` is now the failure signal.
- **Gate check:** `test_end_to_end_synthetic.py` re-run on its own (15 passed) — the write-ordering
  change disturbed no e2e assumption; the forward-mode `< min_fit` refusal (line ~441) and
  `test_process_throw`'s no-throw test still raise (neither asserted nothing-was-written).

## P12-F. Stage 6 — small robustness & hygiene (Minor-12, -9, -10, -7, -8, -16)

- **Minor-12** `trilateration.py`: `valid = guard_ok & np.isfinite(sigma_y)` (+ `divide="ignore"`) so
  a zero-radicand / `y_plane==0` row is flagged invalid, not returned valid with `sigma_y=inf`. Test
  uses the integer geometry `(5,0),(3,4),(3,-4)` (circumcenter at origin, R=5) → exact-zero radicand.
- **Minor-9** `analyze_campaign.summary_stats`: power-note confidence level derived from `alpha`, not
  hardcoded "95%"; test asserts `alpha=0.10` → "90%".
- **Minor-10** `session_report.html`: dead `(D.ball_radius_m||0.0335)` fallback removed.
- **Minor-7** `background.py`: docstring note that the single ghost range is correct under the
  equal-height/equal-tilt pod assumption.
- **Minor-8** `acquisition.py`: docstring note on the `_HEADERLESS_AFTER-1` consumed rows (live-only;
  no effect offline).
- **Minor-16** `05_timing_verify.ino`: comment corrected (timestamp captured just before the HIGH
  edge; latency common-mode, inside the ±50 µs budget).

## P12-G. Stage 7 — open decisions (RESOLVED by the user)

Three items with real trade-offs were reported to the user, who chose all three recommendations:

- **Minor-1 — strike the `--drag-mult` CLI flag (spec-only).** The `simulate_session.py` CLI never
  had such a flag; the drag-coefficient multiplier lives only in test code (`test_bias.py` ×3,
  `test_end_to_end_synthetic.py` ×5). CLAUDE.md §6 (CLI list) and §9 reworded to remove the flag and
  state the multiplier is test-only, so an artificial multiplier can never leak into demo/campaign
  data. No code change.
- **Minor-2 — `--plot` is now the DEFAULT for `simulate_session.py` (code).** Replaced the opt-in
  `--plot` (`store_true`) with an opt-out `--no-plot`; the usage guard is now `if not args.no_plot:`.
  By default every generated demo session is processed and gets `plots/` + `report.html` (the §5.6
  layout, matching a live session per §0.3); `--no-plot` restores raw+truth-only. Module docstring +
  flag help updated. The Stage-1 `test_plot_renders_per_throw_report_html` dropped its now-removed
  `--plot` arg; the other two D5 `simulate_session` tests already omit it and now process too (their
  dir-placement / `out.iterdir()==["demo"]` / campaign assertions still hold — processing writes only
  inside the demo subtree).
- **Minor-3 code-half — strike the `config.web` block (spec-only).** Confirmed no code reads
  `config["web"]` and config.yaml has no `web:` block; `serve_report.py` hardcodes
  `("127.0.0.1", 0)`. CLAUDE.md §2 `web:` block removed (replaced by a comment stating the loopback
  bind is unconditional by design) and §12.3's `config.web.host` reference reworded to "hardcoded
  loopback bind, not configurable." No code change.

**Gate:** full suite still **232 passing** (Minor-2 is a default flip of an already-tested path — the
`report.html` assertion pre-existed; test count unchanged). This completes the CHANGES.md work order.

## P12-H. Not actioned (informational, per the work order)

Minor-11 (`demo_web_reports.py` importing from `tests/`) and Minor-15 (coverage gaps in
`verify_timing.py` / the now-closed `run_default` GT lines) were explicitly left as informational.

## P12-I. Post-completion re-audit + N-1 follow-up

After Stage 7 landed, the `audit_prompt.md` audit was **re-run** against the remediated tree
(`AUDIT_REPORT_20260702_v2.md`; the first audit remains on disk as `AUDIT_REPORT_20260702.md`).
Outcome: every prior finding verified fixed **in code** (232/232 green at re-audit time), plus **one
new Major introduced by Stage 5 (N-1)** and three doc-freshness Minors — all fixed in this follow-up:

- **N-1 (Major, code).** `process_session` loads `meta` from the existing `session.json`, so
  re-processing a previously-successful session under a config that now FAILS the fit left a mixed
  state: the Stage-5 pre-fit partial write persisted the new `gate_summary` while the OLD
  `prediction`/`small_sample_caveat` keys and the OLD `trajectory.csv` survived — the failed session
  then rendered as a valid input/frozen page with stale data (and `calibrate_bias.load_record` would
  ingest the stale prediction). First-time processing was unaffected, which is why no existing test
  caught it. **Fix:** at the partial write, `meta.pop("prediction")`/`meta.pop("small_sample_caveat")`
  and `trajectory.csv` unlinked (`missing_ok=True`) — derived artifacts only; `raw_serial.log` and
  the operator-measured `ground_truth` are untouched. On success the final write re-adds everything
  (success-path file content unchanged). **Test:**
  `test_process_throw.test_reprocess_failure_clears_stale_prediction` — process successfully,
  re-process with `min_fit_points=999`, assert no `prediction`/caveat, no `trajectory.csv`,
  `triplets_raw.csv` retained, and `web_report.build_session_data(...)["state"] == "failure"`
  (self-contained `tmp_path` session; the shared module fixture is not mutated).
- **Re-audit Minor-1:** `handoff.md` had frozen mid-work-order (still said Stages 2–7 PENDING /
  "M-1/M-3/M-4 remain live"); refreshed to the completed state incl. the re-audit and this follow-up.
- **Re-audit Minor-2:** the CLAUDE.md §1 tree was one file behind again — `tests/test_run_session.py`
  (created in Stage 2, after the Stage-1 tree pass) added.
- **Re-audit Minor-3:** this very section (the intra-order tree drift and the follow-up were
  previously unrecorded).

**Final state: 233 tests passing** (225 pre-remediation baseline + 7 work-order tests + 1 N-1
regression test). No known open finding remains; the remaining work is hardware-gated (§10 items
12–15).

---

# PART 13 — Bench Phase-4 findings: static-offset centre-referencing + `--ball-radius-m` override + config-radius revert — as-built record

Recorded during the hardware bench bring-up (BENCH_PROCEDURE_v2 Phase 4, static characterization).
Three linked changes: a display-correctness fix in `characterize_static.py` surfaced while reading
live ball data, a new CLI override to support a pending-approval target, and the revert of an
unapproved `config.yaml` edit that had been silently breaking the §9 acceptance gate.

## P13-A. Static ball `offset`/`mean` were surface-vs-centre (display bug) — FIXED
**Symptom (bench).** Every `--target ball` run reported an `offset` of roughly **−(one radius)**
(e.g. −97 mm with the 0.125 m football radius in config), regardless of how clean the sensor was.
Operator flagged it as absurd.

**Root cause.** `_sensor_stats` computed `mean` from `echo_us_to_m(echo)` — the **surface** distance,
radius NOT added — but for a ball `reference_m = tape + radius` (the **centre**). So
`offset = surface_mean − centre_reference ≈ (true electronic offset) − radius`. The mean and the
reference were on different reference points. (The flat-board path was already correct: board
`reference = tape`, both surface.)

**Why it was low-impact but still worth fixing.** `analyze_static.analyze_offset` **prefers board
reports** (`src = board or reports`) for the electronic-offset verdict, so the ball `offset` column
never fed the Phase-5 significance decision as long as a 4A board run exists. But the printed ball
`mean`/`offset` were genuinely misleading to the operator (and would mis-feed the offset verdict in
the board-less fallback).

**Fix.** `_sensor_stats` gained `radius_correction_m` (added to every reading, mirroring the
pipeline's R2 `add_ball_radius`); `characterize_core` passes `radius_m` for `--target ball`, `0.0`
for board. Now the ball `mean` is the **centre** distance and `offset = centre_mean − centre_ref` =
the true electronic bias, directly comparable to the board's (the radius cancels). `sigma` is a pure
constant shift and is unchanged. **Test:** `test_radius_applied_ball_not_board` re-pinned — ball
`mean == board mean + radius`, ball `offset == board offset` (was: offset == board − radius).

## P13-B. `--ball-radius-m` CLI override (pending-approval target, A5) — NEW
The tennis ball failed the §7/Phase-4B detectability test on the bench (persistent timeouts at ~1 m,
consistent with the known felt-absorption risk, CLAUDE.md §13). Per **A5**, substituting a target
(football / hard sphere) is a Prof.-Zappa approval item, **not** a committed-config change. To let the
operator bench an unapproved target **without** mutating the committed `ball.radius_m`,
`characterize_static.py` gained `--ball-radius-m <r>`: `main()` uses it when present (printing a NOTE
that the config value is unchanged), else falls back to `config["ball"]["radius_m"]`. It is a
measurement-tool convenience only; nothing in `pipeline/` reads it. **Tests:**
`test_ball_radius_override_flag` (CLI contract) and `test_overridden_radius_lifts_ball_mean_to_centre`
(the override radius drives the centre reference + centre-lifted mean/offset in `characterize_core`).

## P13-C. `config.yaml ball.radius_m` reverted 0.125 → 0.0335 — root cause of 5 gate/bias failures
**Finding.** During P13-A/B work, the full suite showed **5 deterministic failures** in
`test_end_to_end_synthetic.py` (bias-chain + `[sensor_height]` negative control),
`test_bias.py::TestDragOff::test_gate_detects_real_pipeline_systematic`, and
`test_corrections.py::...test_chain_bounded_and_better_than_no_correction`. Initially mis-triaged as
"pre-existing / library drift" — corrected on inspection.

**Actual root cause.** `config.yaml` had been edited to `ball.radius_m: 0.125` (the football) with the
comment still reading "tennis ball". The §9 gate and bias tests use the **production config
unchanged** (by design), and `simulator.default_drag_k(radius_m)` scales with **`radius**2`** — so
0.125 vs 0.0335 is a ~14× drag change. That destroyed the tuned ×5 drag-ON bias magnitude (calibrated
to ~50 mm at n=12, p≈0.004): the significance gate flipped to `mode='none'` (corrected == raw
exactly, which was the tell), and the radius-dependent negative-control thresholds no longer held.

**Fix + guard.** Reverted `ball.radius_m` to the (then-)approved **0.0335**, and expanded the config
comment to state explicitly: do NOT edit this to a pending-approval target (it breaks the §9 gate via
`default_drag_k ∝ radius²`); use `characterize_static.py --ball-radius-m` for bench experiments
instead. This is the committed-physics counterpart to P13-B: production config stays the approved
target; an unapproved substitute is benched only via the override. All 5 failures cleared on revert.

**Superseded same-day by D6.** Later the same session, the target substitution itself was escalated
and approved (Prof. Zappa) — the committed target moved from tennis ball to **basketball**,
`radius_m = 0.1194` (measured; see CLAUDE.md v2.6 changelog and the config.yaml `ball:` comment). The
**mechanism** recorded here (production config carries only the currently-approved target; anything
else goes through `--ball-radius-m`) is unaffected and remains in force — only *which* value is
currently approved changed. `default_drag_k ∝ radius²` sensitivity noted above is exactly why
CLAUDE.md's D6 changelog separately mandates a full radius-coupled test/threshold audit
(CHANGES.md D6 Stages 2–4) before the basketball value is trusted end-to-end by the §9 gate — that
audit is tracked separately and was NOT re-run as part of this note.

## P13-D. Files touched + final gate
- `scripts/characterize_static.py` — `radius_correction_m` in `_sensor_stats`; ball radius correction
  in `characterize_core`; `--ball-radius-m` arg + `main()` selection/NOTE; docstring.
- `tests/test_characterize_static.py` — re-pinned `test_radius_applied_ball_not_board`; `_expected`
  gained `radius_correction_m`; new `test_ball_radius_override_flag`,
  `test_overridden_radius_lifts_ball_mean_to_centre`.
- `config.yaml` — `ball.radius_m` 0.125 → 0.0335 + expanded guard comment.

**Final state: 235 tests passing** (233 prior + 2 new override/centre-reference tests). The 5
"failures" were a config-edit regression, not a code defect; no pipeline module changed. Remaining
work stays hardware-gated (§10 items 12–15).

---

# PART 14 — Bench Phase-4B: `kalman.sigma_pos_m` derived from hardware — as-built record

BENCH_PROCEDURE_v2 Phase 4B (ball distance series) is a manual data-collection step; neither
`characterize_static.py` nor `analyze_static.py` computes `kalman.sigma_pos_m` automatically (the
aggregator only derives the beam-half-angle crossing and the electronic-offset verdict — confirmed by
inspection, no `sigma_pos` reference in `analyze_static.py`). The value is a operator read-off from the
`sigma [mm]` column across the 4B runs, recorded here for provenance.

## P14-A. Measured data (basketball target, 3 sensors x 3 distances, n=200/run, 2026-07-09)
| Distance | S1 sigma | S2 sigma | S3 sigma |
|---|---|---|---|
| ~1.0 m | 7.68 mm | 12.88 mm | 9.16 mm |
| ~1.3 m | 3.16 mm | 3.74 mm | 15.65 mm |
| ~1.7 m | 4.73 mm | 3.15 mm | 9.02 mm |

Session dirs: `data/sessions/{S1,S2,S3}_{1,1.3,1.7}/static_report.json`. Median of the 9 values:
7.68 mm.

## P14-B. Derivation and choice
BENCH_PROCEDURE_v2 Phase 4B instructs: take a representative sigma across sensors at the realistic
distances — **median, or the larger/conservative end** (sigma tends to grow with range). The operator
chose the **conservative end: 0.010 m (10 mm)**, over the bare median (7.68 mm), because:
- S3's Phase-4B offsets were flagged as **unverified alignment** during the same bench session (its
  ball-target offset sign/magnitude diverged sharply from its own Phase-4A flat-board offset — see the
  S3 offset-mismatch discussion in this session's chat log; not yet re-resolved on hardware at the time
  of this note), so S3's sigma values (9-16 mm) are the least trustworthy of the 9 and should not be
  averaged away by a median that could mask them.
- An over-estimated `sigma_pos_m` is low-risk: it only makes the Kalman filter trust individual range
  measurements slightly less and lean more on the constant-acceleration motion model — mild,
  conservative behavior, not a correctness hazard (contrast with an UNDER-estimate, which would let a
  bad S3 reading pull the filtered trajectory further than it should).

## P14-C. Config change
`config.yaml kalman.sigma_pos_m` was already `0.010` (the pre-measurement placeholder happened to
equal the chosen value); the comment was rewritten from "REPLACE with S7 value" (placeholder marker)
to a full provenance record: the 9-value table, the median, the conservative-choice rationale, the
open S3-alignment flag, and the explicit note that GDOP (~2.3x) was **not** applied to convert this
range-domain sigma to a horizontal position-noise figure — that conversion, if wanted, is an error
budget / report step, not a config value.

## P14-D. Open follow-up
S3's beam alignment should be re-verified against its own Phase-4A board offset before its Phase-4B
numbers are trusted at face value (see the P13 series and the chat record for the specific mismatch:
4A board offset -12.9 mm vs a 4B ball-run offset of +48.5 mm at ~1.0 m — opposite sign, large gap).
This does not block using `sigma_pos_m = 0.010` (the conservative choice already discounts for it),
but it should be resolved before S3's raw offset numbers are used for anything more precise (e.g. an
acquisition-layer per-sensor offset subtraction, CLAUDE.md S4D/Phase 5).

**No test changes** — `sigma_pos_m` is read dynamically from config by every test that uses it
(confirmed: `test_bias.py`, `test_kalman.py`, `test_landing.py`, `test_trilateration.py` all read
`config["kalman"]["sigma_pos_m"]`; the handful of literal `0.01` values in `test_kalman.py` are
standalone fixture inputs, not config comparisons). Full suite re-run: **235 passed**, unchanged from
Part 13's final count.

---

# PART 15 — D6 Stages 0–1: backup, green baseline, ball measurement + config/spec sync — as-built record

**Work order:** `CHANGES.md` (D6 — target substitution, tennis ball → basketball), Stages 0–1,
executed stop-and-confirm per the work order's ground rules. **Scope this stage:** manual backup +
baseline verification, then measuring the actual ball and syncing `config.yaml`/`CLAUDE.md` §2 to
the measured radius. No `pipeline/`/`scripts/`/`tests/`/`firmware/` source touched.

## P15-A. Stage 0 — backup + green baseline
- Manual dated folder copy (this project's version control; no git):
  `C:\Personal\Polimi\Sem-2\Measurements\Project\Code_backup_2026-07-09_D6-Stage0`, via
  `robocopy /E /MT:16` of the entire project directory including `venv/`. Verified identical to the
  source by file count and total size: **12,799 files / 385.9 MB** on both sides.
- Suite run exactly per CLAUDE.md's Development Environment section:
  `.\venv\Scripts\python.exe -m pytest tests -q` → **235 passed, 0 failed** (33.45 s). Matches the
  235-passing state Part 13 (P13-D) left the tree in; no drift since.

## P15-B. Stage 1 — measured the ball; synced config.yaml and CLAUDE.md §2
**Measurement (Hari, bench, 2026-07-09):** circumference C = 0.750 m (tape, ±2 mm); computed
r = C/(2π) = 0.1194 m; mass m = 0.620 kg (scale). Sanity-checked against the CHANGES.md size-7
bands — C ≈ 0.75–0.78 m, r ≈ 0.119–0.124 m, m ≈ 567–650 g — **all three within band** (C and r sit
near the bands' lower edge, which is internally consistent: C = 0.750 m is exactly the band's own
lower bound). No re-measurement triggered.

**`config.yaml` (`ball:` block):** `radius_m` changed **0.0335 → 0.1194**. Note the starting value:
`config.yaml` had *not yet* been bumped to the 0.121 placeholder CLAUDE.md v2.6 §2 already carried —
it still held the pre-D6-approval P13-C guard ("do NOT edit this to a pending-approval target...");
that guard's premise is now moot (Prof. Zappa approved D6). Edited directly to the measured value,
replacing the guard comment with the D6 measurement record (C, r, m, date, pointer to this entry,
and an explicit carry-forward note that `radius_m` also drives `simulator.default_drag_k`
(∝ radius²) and the §9 gate thresholds — CHANGES.md Stages 2–4 still need to audit those before the
value is trusted end-to-end).

**`CLAUDE.md` §2 (`ball:` block comment):** the committed value there differed from the measured
result by 1.6 mm (0.121 placeholder vs 0.1194 measured), so it was rewritten to state the measured
C/r/m and drop the "PLACEHOLDER — MEASURE" language, per the stage instruction that spec and config
must never disagree. **Left untouched, deliberately:** four other `~0.121 m` mentions in the v2.5→
v2.6 changelog narrative (the "What changes" bullet, the R10b/A2 cross-talk note, and the D6-R3 risk
entry) — these are historical/estimate prose explicitly marked as such at the time of writing
("*(Estimates; the §7 characterization measures the real values.)*") and are not the committed-value
statement Stage 1 scoped; rewriting them would blur the historical record of what was known before
measurement.

## P15-C. Evidence gap found — no tennis-ball session exists on disk (flagged, not resolved)
CLAUDE.md's v2.6 changelog "Measured trigger" paragraph states raw session data for the board-pass
**and** tennis-fail sweeps is "retained under `data/sessions/*_static/`". Searching the entire
`data/sessions/` tree (15 top-level entries, exhaustively listed) for a `ball_radius_m: 0.0335`
static report found **none**. What actually exists:
- **Board-pass (matches the narrative):** `data/sessions/Flat-Board` — target=board, tape-ref
  1.0 m, 0% timeout on all 3 sensors, means 0.974–0.987 m.
- **NOT tennis:** seven bench sessions at `ball_radius_m: 0.12` — `data/sessions/S1_1`, `S1_1.3`,
  `S1_1.7`, `S2_1`, `S2_1.3`, `S2_1.7`, `S3_1` (mtimes 2026-07-08 20:29–21:17) — run via the P13-B
  `--ball-radius-m` override while the committed config was still 0.0335. These are a **basketball**
  on-axis detectability trial (mostly 0%, one at 11%, timeout on the on-axis sensor) that predates
  and is distinct from the formal Stage-5 basketball sweep; they demonstrate the D6 physics
  rationale but are not tennis-fail data. Plus four more radius=0.12 attempts at 21:24–21:27
  (`data/sessions/2026-07-08_212401_static` through `..._212743_static`): the first fully failed
  (100% timeout, all 3 sensors — an isolated mis-positioning retry), three subsequent ones
  succeeded; one further directory (`..._212719_static`) is completely empty (zero files, an
  aborted attempt).
- **Asked Hari directly** whether the tennis-fail session was saved under an unfound name/location.
  Confirmed (2026-07-09): **no session was ever saved** — the persistent-timeout observation that
  triggered A5/D6 was made live at the bench and was never captured to a `raw_serial.log` /
  `static_report.json`. Recorded here as fact, not resolved by substitution.
- **Flag for the report-writer:** the v2.6 changelog's "retained under `data/sessions/*_static/`"
  claim is correct for the board half and incorrect for the tennis half. A future CLAUDE.md wording
  pass should soften that sentence (out of scope here — Stage 1 is config/§2-comment sync only, not
  a narrative rewrite); the campaign report should describe the tennis-ball timeout as an
  observed-but-unlogged bench finding, not cite a session path.

## P15-D. D6 decision-register entry
**Decision:** D6 — target substitution, tennis ball → basketball. Approved by **Prof. Zappa,
2026-07**, per the A5 escalation process (CLAUDE.md §11 A5). Trigger: §7 bench characterization —
flat board PASSED at 1.0 m; tennis ball produced persistent timeouts at 1.0 m on-axis, observed at
the bench and not captured to a saved session (§P15-C).

**Measured (2026-07-09):** C = 0.750 m (tape, ±2 mm); r = C/(2π) = **0.1194 m**; m = **0.620 kg**
(scale). All three within the CHANGES.md size-7 sanity bands (C 0.75–0.78 m, r 0.119–0.124 m,
m 567–650 g), near the bands' lower edge.

**Evidence:**
- Board-pass: `data/sessions/Flat-Board`.
- Tennis-fail: no on-disk artifact exists (confirmed with Hari; see §P15-C).
- Supplementary (incidental, pre-approval, r = 0.12 m): `data/sessions/S1_1`, `S1_1.3`, `S1_1.7`,
  `S2_1`, `S2_1.3`, `S2_1.7`, `S3_1`, and `data/sessions/2026-07-08_212401_static` /
  `..._212435_static` / `..._212726_static` / `..._212743_static` — basketball on-axis
  detectability, distinct from the formal Stage-5 sweep.

**Files changed this stage:** `config.yaml` (`ball.radius_m` + comment), `CLAUDE.md` (§2 `ball:`
block comment), `IMPLEMENTATION_NOTES.md` (this entry). No `pipeline/`/`scripts/`/`tests/` touched.

## P15-E. Read-only post-edit test check (no code touched; informational only)
Re-ran `.\venv\Scripts\python.exe -m pytest tests -q` after the `config.yaml` edit, purely to report
accurate state (Stage 1 forbids touching Python/tests, but leaving the suite's status unknown would
violate "surface, never absorb"). Result: **4 failed, 231 passed** — `test_bias.py::TestDragOff::
test_gate_detects_real_pipeline_systematic`, `test_end_to_end_synthetic.py::TestLandingAccuracy::
test_negative_control_fails_accuracy[sensor_height]`, `...TestBiasChain::
test_significant_along_track_model`, `...TestBiasChain::test_corrected_beats_raw_on_drag_on_set`.
This is the **exact failure family Part 13 (P13-C) already diagnosed**: `simulator.default_drag_k`
scales with `radius**2`, so any `ball.radius_m` change re-tunes the drag-chain magnitude the bias
gate and negative controls were calibrated against (0.0335 → 0.1194 is a ~12.7× radius change, a
~161× drag-k change). **Expected, not a regression, not fixed here** — this is precisely
CHANGES.md's Stage 2 (read-only radius-hardcode audit) and Stage 3 (approved fixes) scope. Recorded
so Stage 2 starts from a known, explained baseline rather than rediscovering it.

**Status:** Stage 0–1 complete.

## P15-F. Stage 2 — read-only radius-hardcode audit
Swept `pipeline/`, `scripts/`, `tests/`, report templates, config for `0.0335`/`0.034`/`33.5`/
`3.35`/`0.067`/`tennis`/`radius`. **Headline: every executable radius path was already
config-driven** — `simulator.py:296`, `simulate_session.py:233`, `characterize_static.py:203`
(+`--ball-radius-m` override), the live `session_report.html` template (`RBALL=D.ball_radius_m`, no
`||0.0335` fallback — audit Minor-10 had already removed it), and all test `radius` fixtures read
`config["ball"]["radius_m"]`. The ONLY functional tennis coupling was `simulator.default_drag_k`'s
mass/Cd defaults (`_TENNIS_BALL_MASS_KG=0.0577`, `_TENNIS_BALL_CD=0.55`); with config radius bumped
to basketball but tennis mass, `default_drag_k` inflated ~12.7× (radius²), which is what broke the 4
Stage-1 tests. Findings table delivered to Hari; all items approved (`Confirm everything`), with the
"go option 2" decision to pull the drag re-tune forward into Stage 3.

## P15-G. Stage 3 — implement approved changes (suite green: 235)
- **B1 (crux).** `simulator.py` drag-truth defaults tennis → basketball: `_BASKETBALL_MASS_KG=0.620`
  (measured), `_BASKETBALL_CD=0.47` (smooth-sphere estimate, per CHANGES.md Stage 4 — approximate),
  constants renamed, comment rewritten. **Key physics verified:** basketball `default_drag_k` = 0.02080
  vs old tennis 0.02058 — **+1.0%**. The larger A/m (~0.072 vs ~0.061 m²/kg) is almost exactly
  cancelled by the lower Cd (0.47 vs 0.55), so the drag magnitude the tests were tuned against is
  preserved and the drag scales `K_SCALE=5`/`k_scale=3` carry over UNCHANGED. This alone cleared 3 of
  the 4 failures.
- **Two category-(ii) radius-physics findings surfaced to Hari before fixing (Stage-3 rule), both
  resolved with his approved option:**
  1. **e2e R4 (sensor_height) control no longer fails.** At the basketball contact height
     y = r_ball ≈ 119 mm (was 33.5 mm), the omitted 45 mm sensor-height offset maps to only ~4 mm of
     landing error (measured drag-OFF: baseline 34.5 → 38.6 mm; cf. R2-off 34.5 → **159.6 mm**). No
     `MEAN_TOLERANCE` can separate 34.5 from 38.6. **Resolution (approved):** R4 removed from the e2e
     must-fail parametrize (R2 remains the load-bearing must-fail control); added
     `test_negative_control_sensor_height_below_floor` pinning the ~4 mm sub-floor delta, mirroring the
     R3/mid_echo pin. R4 correctness stays guarded by the radius-independent unit control
     `test_trilateration.py::test_negative_control_R4_height_offset_bites`.
  2. **drag-OFF pipeline self-systematic shrank.** From ~-10 mm (tennis) to **~-8 mm** (shorter
     extrapolation to y = r_ball). Full-set `calibrate` still finds it significant (along mean -8.1 mm,
     CI (-14.4, -1.9) excludes 0), but the validated split-half returns 'none' at n=30 (and n-bumping
     is seed-fragile: n=50 detects, n=60 doesn't). **Resolution (approved):**
     `test_gate_detects_real_pipeline_systematic` reframed to assert BOTH truths — (1) systematic real &
     significant on the full set, (2) validated gate correctly conservative → 'none' at n=30. Strengthens
     the test; consistent with the e2e drag-OFF 'none'.
- **Mechanical/comment fixes (config-derived assertions were already correct; only stale prose):**
  `test_corrections.py` R2 docstring/comment; `test_simulator.py` drag-scale comment; `config.yaml`
  `beam_half_angle_deg` comment (tennis → basketball); `test_bias.py` + `test_end_to_end_synthetic.py`
  probe numbers refreshed to measured D6 values (drag-ON track along 46.1 mm, array |bias| 34.3 mm,
  e2e drag-ON offset 54 mm, drag-OFF baseline 34.5 mm / R2-off 159.6 mm); `MEAN_TOLERANCE_M`=0.055 and
  `PER_SESSION_CAP_M`=0.12 kept (wide margin under D6) with refreshed comments; `README.md` + `handoff.md`
  narrative "tennis" → "basketball".
- **NOT touched (correct):** the old demo `data/sessions/demo/sim_*/report.html`+`session.json`
  (`0.0335`) are generated artifacts — regenerated in Stage 4, never hand-edited.
- **Suite: 235 passed, 0 failed** (`.\venv\Scripts\python.exe -m pytest tests -q`), stable across two
  consecutive runs. Every changed assertion is config-derived or carries a `[D6]` derivation comment.

**Status:** Stage 0–3 complete; suite green.

## P15-H. Stage 4 — acceptance gate re-verified; demo regenerated; drag re-estimate
- **Demo regen (step 1).** Cleared the old tennis-radius demo batch (`sim_2026-06-25_145012_S01..S12`,
  radius 0.0335 — delete-logged; seeded/reproducible per D5d, backed up at Stage 0) and regenerated
  under the basketball radius: `simulate_session.py --n-sessions 12 --drag quadratic --beam-cone off
  --seed 42 --temperature-c 20`. **10 of 12 sessions predict** at mean 27.6 mm / max 47.8 mm vs truth
  (drag-ON demo — within tolerance). The 2 that failed (S02, S05) are high-|θ| far throws
  (θ ≈ +52.7° / −48.0°, landing r ≈ 1.7–1.9 m): the **+119 mm surface→centre correction pushes their
  slant ranges past `d_max = 2.0 m`**, leaving only 1–2 valid triplets (a real, mild D6 effect on far
  throws — NOT a pipeline defect; the §9 gate's `build_set` resamples such throws, so the gate is
  unaffected). The 2 incomplete session dirs were removed so every demo session is a complete artifact;
  `data/sessions/demo/campaign.html` regenerated (10 throws). All 10 carry `radius_m = 0.1194` and a
  `report.html`.
- **§9 acceptance gate (step 2).** Green under the new radius (part of the 235-passing suite).
  **Measured negative-control magnitudes** (drag-OFF set, gate fixture master_seed=11): baseline
  **34.5 mm** (max 60.5), **R2-OFF 159.6 mm** (max 197.0), R4-OFF 38.6 mm. CLAUDE.md updated:
  §9 R2 note now records the measured **~160 mm** (was "re-measured, not assumed"); §9 R4 note records
  the **demotion** (no longer an e2e must-fail — pinned; guarded by the unit control); §8.2 R2
  range-bias figure ~121 → **~119 mm** (measured r). Note: the CHANGES.md Stage-4 guess of "≳200 mm-class"
  was NOT assumed — the **measured** figure is 159.6 mm.
- **Drag re-estimate (step 3, analysis).** Two quantities, both measured, flagged approximate:
  1. **Drag force** a_drag = ρ·Cd·π·r²·v²/2m with m=0.620, r=0.1194, Cd≈0.47 → 0.187 / 0.255 / 0.333
     m/s² at v = 3.0 / 3.5 / 4.0 — **+1% vs tennis** (A/m ↑18% cancelled by Cd ↓15%; same invariance as
     `default_drag_k` 0.02080 vs 0.02058).
  2. **Pipeline along-track prediction bias** (the apples-to-apples analog of the tennis-derived
     ~8 mm): realistic unscaled drag, 3–4 m/s, cone-off, N=120 → **+17.5 mm** (drag-ON total),
     drag-OFF self-systematic −7.5 mm, **net drag-attributable ~+25 mm**. Roughly **2× the tennis
     ~8 mm** — driven by the higher y = r_ball ≈ 119 mm contact height amplifying the extrapolation
     overshoot, NOT by drag force (which is ~unchanged). (Sanity: the direct true-landing drag
     shortfall is ~−183 mm, but that is the full drag effect on the ACTUAL landing, not the pipeline
     PREDICTION bias — the measured points already encode drag, so the parabola fit + short
     extrapolation captures most of it.)
  - **Plan decision: UNCHANGED.** A ~2× larger bias is the detection-FAVORABLE direction (easier to
     resolve, not harder), so no throw-count increase is warranted; the real campaign's fewer triplets
     (cone-on ~5–6) raise scatter, so keeping **15–20 (→30 if time permits)** is the safe call.
     CLAUDE.md §11 D3 bullet updated with these measured figures.
- **Rebound note (step 4).** The D6-R1 rebound-re-entry risk (a basketball rebounding back into the
  upward-tilted cones within `close_K` and contaminating the fit) **cannot be pre-verified
  synthetically** — the simulator has no restitution model (the ball vanishes at y = r_ball). It is a
  first-live-session check (Stage 5 checklist), recorded here so nobody expects a simulator answer.

**Status:** Stage 0–4 complete; suite green (235). Stage 5 (hardware re-characterization with the
basketball) is hardware-gated and NOT started.

---

# PART 16 — Phase 5: acquisition-layer per-sensor electronic-offset correction — as-built record

BENCH_PROCEDURE_v2 Phase 4D flagged all three sensors' flat-board offsets SIGNIFICANT, and Phase 5
item 7.3 requires "add the constant per-sensor offset subtraction at the acquisition layer ... This
hook does not exist yet." This part builds it, with a runtime toggle to see the uncorrected landing.

## P16-A. The measured trigger (Phase 4D)
`analyze_static.py data/sessions/Flat-Board/static_report.json`:
- S1: offset = -25.54 mm, sigma/sqrt(N) = 0.08 mm -> SIGNIFICANT
- S2: offset = -22.54 mm, sigma/sqrt(N) = 0.12 mm -> SIGNIFICANT
- S3: offset = -12.87 mm, sigma/sqrt(N) = 0.39 mm -> SIGNIFICANT

All three are electronic offsets (measured against a flat board, so no ball-geometry contamination),
tens of mm, hugely outside their 3*SEM bounds. offset = mean_measured - reference; all NEGATIVE
(the sensors read short), so the correction ADDS distance.

## P16-B. Design — where it lives and why
- `corrections.apply_sensor_offset(d_m, offset_m)`: pure, NaN-transparent, broadcasts a (3,) offset
  across (N,3) triplet arrays; `corrected = measured - offset`. Raises on a non-3 offset vector.
  Deliberately OUTSIDE bias.py (which owns only the throw-aligned drag residual, S7).
- `process_throw.process_session(..., apply_offset=False)`: applies the config
  `acquisition.sensor_offset_m` to the distances feeding trilateration when `apply_offset` is True
  AND the config key is present. **Opt-in (default False)** so synthetic callers — the section-9
  acceptance gate and every simulator-written session — are unaffected: synthetic data carries no
  electronic offset, so applying a real one would corrupt it (same failure class as the P13-C radius
  regression). Recorded in `gate_summary` (`sensor_offset_applied`, `sensor_offset_m`) for
  reproducibility.
- **Background gate untouched.** The correction is applied to the trilateration-path distance only;
  the section-5.3/5.4 band gate keeps using raw `d_surface`. A constant per-sensor shift cancels in
  the band rule (`|d - mu_bg| > w`), so gating is provably unchanged whether the offset is on or off.
- `run_session.capture_session(..., apply_offset=True)` and the `--no-offset-correction` CLI flag:
  the LIVE path enables the correction BY DEFAULT (real hardware has the offset); the flag disables it
  so the operator can see the uncorrected landing. Terminal and web flows share the one capture call,
  so the flag covers both.

## P16-C. Config
`config.yaml acquisition.sensor_offset_m: [-0.0255, -0.0225, -0.0129]` (the Phase-4D board values,
rounded to 0.1 mm), with a full-provenance comment: source study, sign convention, "does not affect
the background gate", the run_session default-on / --no-offset-correction toggle, and "synthetic
sessions ignore it". null / all-zero = no correction.

## P16-D. Tests + gate
- `test_corrections.py`: `test_sensor_offset_subtracts_per_sensor` (per-sensor subtract, broadcast,
  NaN-transparent), `test_sensor_offset_none_is_noop`, `test_sensor_offset_bad_length_raises`.
- `test_process_throw.py`: `test_offset_correction_toggle` (same synthetic session both ways: on
  shifts the landing and is logged in gate_summary; off is inert — guards the acceptance gate, which
  never sets apply_offset), `test_offset_default_off_when_config_absent` (opt-in on BOTH the flag and
  the config key).
- `test_acquisition.py`: the live==offline parity test now compares like-for-like (offline twin gets
  `apply_offset=True` to match capture_session's default).
- `test_run_session.py`: failure-path test's args gained `no_offset_correction=False`.

**Files touched:** `pipeline/corrections.py`, `pipeline/process_throw.py`, `scripts/run_session.py`,
`config.yaml`, `tests/test_corrections.py`, `tests/test_process_throw.py`, `tests/test_acquisition.py`,
`tests/test_run_session.py`.

**Final state: 240 tests passing** (235 prior + 3 corrections offset tests + 2 process_throw toggle
tests). No acceptance-gate change (apply_offset defaults off for synthetic callers). Phase 5 item 7.3
is now satisfied; the remaining Phase-7 checklist is hardware-gated.

---

# PART 17 — `--no-background`: skip background calibration for open-ground runs — as-built record

**Request:** avoid the ~11 s background calibration on every throw when testing on open ground,
where there is no static reflector to subtract, so the calibration buys nothing.

## P17-A. Why skipping is safe on open ground
The section-5.3 R1 gate-enable logic already DISABLES the band rule per sensor when the background is
open air (`f0 > bg_timeout_skip`) — an open-ground calibration would produce all-disabled bands
anyway. So skipping the wait and going straight to an all-disabled background is behaviourally
identical to what a real open-air calibration yields, minus the 11 s. It is NOT safe when a static
reflector is in view (a wall/ceiling) — those readings would then be treated as signal; the flag is
explicitly an open-ground convenience, documented as such.

## P17-B. Design
- `background.disabled_background(gates_cfg)`: returns a `BackgroundModel` with every
  `SensorBackground` `enabled=False` (f0=1, mu/sigma/w = NaN). `reading_valid` then applies only rules
  1+2 (non-timeout AND `<= d_max`); rule 3 (the band) never fires. Pure, no I/O.
- `run_session.capture_session(..., skip_background=False)`: when True, skips
  `_calibrate_background_phase` (the triplet-consuming ~11 s loop) and instead builds the disabled
  background. **It is still persisted to `background.json`** so the offline `process_session` LOADS it
  rather than recalibrating from the log — critical, because a skipped-calibration capture has no
  background padding at the head of `raw_serial.log`, so a recalibration would wrongly characterize
  the room from throw data. The throw is detected from the very first triplets (open-air padding, if
  any, is timeouts that do not arm).
- `--no-background` CLI flag -> `_capture_default` -> `capture_session(skip_background=...)`. Covers
  both terminal and web flows (shared capture call). Independent of `--no-offset-correction` and
  `--background-only` (the latter is a distinct mode that ONLY calibrates).

## P17-C. Tests
- `test_background.py::test_disabled_background_gates_on_dmax_only`: all bands disabled; a mid-range
  echo passes, a timeout (NaN) and an over-`d_max` echo are rejected.
- `test_acquisition.py::test_capture_session_skip_background`: `skip_background=True` writes a
  background.json with every band disabled and STILL segments the throw to a usable landing (open-air
  padding does not arm).
- `test_run_session.py`: failure-path test's args gained `no_background=False`.

**Files touched:** `pipeline/background.py`, `scripts/run_session.py`, `tests/test_background.py`,
`tests/test_acquisition.py`, `tests/test_run_session.py`.

**Usage:**
```
.\venv\Scripts\python.exe scripts\run_session.py --port COM5 --plot --no-background
```

**Final state: 242 tests passing** (240 prior + 1 disabled-background unit test + 1 skip-background
capture test). No acceptance-gate change.

---

# PART 18 — D6 work-order close-out + CLAUDE.md v2.7 (doc-only pass, no code changed)

**Trigger:** a documentation audit of the working tree found `README.md`/`handoff.md` badly stale
relative to actual progress (they still described "hardware not yet started" while
`data/sessions/2026-07-09_T*` already held a completed 34-throw live campaign with a calibrated,
significant bias model), and found the Part 16/17 acquisition features (per-sensor offset
correction, `--no-background`) were never folded back into CLAUDE.md despite it being the
declared authoritative spec. This part records the clean-up.

## P18-A. What changed
- **CLAUDE.md v2.6 → v2.7**, doc-and-schema-only (no pipeline math touched):
  - §2: added `acquisition.sensor_offset_m` to the config schema (per-sensor, metres, measured
    from the flat-board static study, applied `corrected = measured − offset`, default-on,
    `--no-offset-correction` to disable, synthetic sessions ignore it).
  - §3: wiring table and controller reference renamed Arduino Uno → **Arduino Nano Every** — board
    name only, per Hari's confirmation that pins/wiring/firmware behaviour are unchanged.
  - §5.1: one bullet documenting where the offset correction is applied in the acquisition chain.
  - §5.7: two new CLI flag bullets, `--no-background` and `--no-offset-correction`.
  - §11: the `(D6-R1, new) Rebound re-entry into the detection cones` risk-register bullet was
    **removed entirely**, per Hari's direction — checked against the completed 34-throw live
    campaign and no post-contact rebound contamination was observed at any session's
    segmentation boundary. D6's risk list is now D6-R2/D6-R3 only.
  - New **"Changelog v2.6 → v2.7"** section added, documenting all of the above plus stating
    explicitly that the O-series optical amendment is now the *only* remaining open item
    project-wide (previously tracked partly in CHANGES.md; now tracked solely in CLAUDE.md).
- **`CHANGES.md` wiped** to an empty placeholder. The D6 work order it held is closed; its record
  now lives in CLAUDE.md's own changelog (this Part + the v2.6/v2.7 sections) rather than a
  separate work-order file. The placeholder explains this and points at Part 15 as a template for
  the next work order's stage-gated format.
- **`README.md` / `handoff.md`** rewritten to match current reality: v2.7 spec version, 242 tests,
  the completed campaign and its significant bias result, `CHANGES.md`'s new empty state, and the
  optical amendment as the sole open item. `requirements.txt` and `config.yaml` header comments
  updated from stale version tags (v2.1 / v2.5) to v2.7; the `pyserial` comment's "Arduino Uno" was
  also renamed to "Arduino Nano Every".

## P18-B. What did NOT change
No file under `pipeline/`, `scripts/`, `firmware/`, or `tests/` was touched. `config.yaml`'s only
edits were its header-comment version string (content/values unchanged). Full suite re-run:
**242 passed**, identical to Part 17's final count — this was a documentation-and-spec-comment
pass only.

## P18-C. Provenance note on the D6-R1 closure
The "no contamination observed" claim is Hari's direct assertion (session instruction), not an
independently re-derived measurement in this pass — no new script output or session-file
re-inspection was run as part of Part 18 itself. If a future session needs the underlying
evidence, the honest state is: 34 live `trajectory.csv`/`triplets_raw.csv` files exist on disk
under `data/sessions/2026-07-09_T*` and have not been mechanically re-checked for post-contact
triplets since this closure; a spot-check would be a cheap, worthwhile confirmation before citing
this in a formal report.

---

# PART 19 — Legacy-design ablation study for presentation prep (documentation-only, no pipeline change)

**Trigger:** `Presentation_Flow_Deck.pdf` (the four-speaker slide plan) requires quantified
"legacy vs corrected" numbers on Slides 6, 8–13, 15, 17 — every one of them a `[X mm]`
placeholder with an explicit instruction (Production Note #1) to "run the ablation first" and "fill
every placeholder" from a re-processing of the 34-throw live campaign, and (Production Note #2) to
label every number's provenance. Neither existed anywhere in the repo before this pass. Hari
specified the legacy configuration directly: "plain prediction run with no active error
corrections... forward differencing and without all other edits to improve accuracy."

## P19-A. Scope discipline (why this is Part 19 and not a config/pipeline change)
Two standalone, read-only scripts were written **outside** `pipeline/`/`scripts/`/`tests/**`
(archived in the session scratchpad, referenced by path in `LEGACY_ABLATION_RESULTS.md` §6). They
import and reuse the real `pipeline/` modules (`corrections`, `trilateration`, `geometry`,
`segmentation`, `background`, `kalman`, `landing`, `bias`) exactly as `process_throw.process_session`
does, but compose them under the legacy/leave-one-out knobs instead of calling
`process_session` — **no session directory, `session.json`, `background.json`, `trajectory.csv`,
or any other on-disk artifact was written to**; ground truth and background models are only ever
read from the existing recorded files. No file under `pipeline/`, `scripts/`, `firmware/`, or
`tests/` changed. `.\venv\Scripts\pytest.exe` re-run after this study: **242 passed**, identical to
Part 18's final count.

## P19-B. Two separate ablations, because they answer different questions
1. **Full legacy re-run** (`legacy_ablation.py`): every accuracy correction OFF **simultaneously**
   — fixed 343 m/s, no per-sensor offset, no ball-radius R2, forward differencing, nominal
   fixed-schedule timestamps (no mid-echo), no sensor-height correction, no Kalman filter, y = 0
   landing, no bias model. Throw detection (background gate + arm/close segmentation) is left ON,
   using the real temperature-based bands, so the SAME triplets are being compared ("same throws,
   only the corrections differ" — the deck's own Slide 15 line). This produces the Slide 6 number.
2. **Leave-one-out ablation** (`loo_ablation.py`): starting from the delivered, fully-corrected
   pipeline (all corrections ON, `correction_model.json`'s shipped bias applied — baseline mean 2D
   error 64.5 mm, n = 34/34), turn OFF exactly **one** correction at a time and measure the paired
   per-throw error increase. This produces the Slide 8–13 per-fix Δ numbers.

These cannot be merged into one table: a single "legacy − corrected" delta split five ways would
misattribute error, because the corrections interact — most visibly, the shipped bias model
(`offset_along_m = 67.5 mm`) was calibrated with the offset/temperature/height corrections already
applied, so it partially absorbs their common-mode effect. Removing those three corrections WITH
the bias model still on barely moves the error (Δ ≈ +1–3 mm, none significant at n = 34); removing
them WITHOUT the bias model actually *lowers* error (§P19-D). Both are true and neither is "the"
number — the deck needs the first (as-delivered-system) framing, which is §4.1 of
`LEGACY_ABLATION_RESULTS.md`.

## P19-C. Headline finding 1 — legacy coverage collapses, not just accuracy
The legacy re-run predicts a landing for only **16 of 34** throws (mean 133.3 mm on those 16,
median 118.4, 95% CI [107.1, 159.4]). The other 18 are not a random subset: every one of them had
**exactly 4** triplets survive gating under the corrected pipeline (`gate_summary.n_triplets_used`
distribution across all 34 sessions: `{4: 18, 5: 14, 6: 2}`). Forward differencing has no successor
for the last triplet of a throw, so it is flagged unusable — a 4-triplet throw becomes 3, below
`min_fit_points = 4`. This is precisely the effect the corrected pipeline's hybrid stencil (D1,
CLAUDE.md §8.2c) exists to prevent ("keeps ALL N triplets" vs forward's N−1). The coverage
collapse, not the accuracy delta, is the recommended Slide 6 headline.

## P19-D. Headline finding 2 — ball-radius R2 is the largest measured effect in the system, and is currently unstarred
Leave-one-out from the delivered pipeline (baseline 64.5 mm, n = 34), each row bias-held at its
shipped value:

| Correction OFF | Δ (mm) | 95% CI | Significant (n=34)? |
|---|---:|---|:---:|
| Ball-radius R2 | **+99.3** | [+82.0, +116.7] | yes |
| Hybrid stencil → forward | +65.6 (+ 18 throws lose prediction entirely) | [+32.1, +99.1] | yes |
| Track-aligned bias model | +27.9 | [+15.5, +40.4] | yes |
| Landing y = r_ball → y = 0 | +21.2 | [+9.7, +32.8] | yes |
| Kalman filter → raw fit | +4.3 | [−2.0, +10.5] | no |
| Per-sensor electronic offset | +3.2 | [−3.6, +10.0] | no |
| Temperature-based speed of sound | +1.9 | [−5.2, +8.9] | no |
| Sensor-height correction | +1.2 | [−4.4, +6.9] | no |
| Mid-echo sample instant → t_TRIG | +0.0 | [−0.2, +0.2] | no |

R2 (surface→centre range, currently a plain "Physical corrections" inventory line in the deck, NOT
starred) removed alone costs nearly **100 mm** — by far the largest single measured effect,
consistent with the basketball radius being ~13% of a 1 m slant range (CLAUDE.md D6-R3). The
cross-check with bias OFF everywhere (`LEGACY_ABLATION_RESULTS.md` §4.2) confirms R2's effect is
robust to the bias interaction (+11.0 mm there too, in the same direction, smaller only because the
pre-bias baseline is itself less accurate). Mid-echo sampling resolves to exactly 0.0 mm
end-to-end — consistent with the pre-existing finding C-1 above (§C-1: "real but NOT
end-to-end-detectable... below the noise floor"); this ablation is the first end-to-end,
real-campaign confirmation of that simulator-derived claim.

**Recommended star reshuffle** (detailed slide-by-slide mapping in
`LEGACY_ABLATION_RESULTS.md` §5): promote ball-radius R2 to a starred, headline fix; split the
current ★3 (mid-echo + y=r_ball) and ★4 (Kalman + bias) rows, keeping only the significant half of
each starred (y = r_ball; bias model) and demoting the other half (mid-echo; Kalman) to the plain
inventory table alongside offset/temperature/sensor-height, all of which remain worth keeping as
bench-proven measurement-layer corrections even though their delivered-system prediction-error
delta is not resolvable at n = 34.

## P19-E. Files and provenance
- **New:** `LEGACY_ABLATION_RESULTS.md` (repo root) — full per-throw legacy table (all 34
  sessions), the matched 16-throw waterfall comparison, the complete leave-one-out table with 95%
  CIs, the pre-bias cross-check, and a slide-by-slide mapping back onto the deck (§5). This is the
  primary reference; treat this Part as a pointer + headline summary.
- **`CLAUDE.md` v2.7 → v2.8**: new changelog section pointing at this Part and
  `LEGACY_ABLATION_RESULTS.md`; header bumped to reflect it. No spec conventions, config schema, or
  build order changed.
- **Not written:** any file under `pipeline/`, `scripts/`, `firmware/`, `tests/`, `config.yaml`, or
  any `data/sessions/**` artifact. The ablation scripts themselves are reference material (session
  scratchpad), not committed to the package — they are not pytest-collected and are not a
  regression gate; if a future editor wants them promoted to a tracked, reproducible tool (e.g.
  `scripts/ablate_legacy.py`), that is a new, explicit work order, not implied by this Part.

**Final state: 242 tests passing**, unchanged from Part 18 — this Part is a reporting pass, not a
build step.
