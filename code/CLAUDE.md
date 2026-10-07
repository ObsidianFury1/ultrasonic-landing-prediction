# CLAUDE.md (v2.8) — 3D Ultrasonic Projectile Landing-Prediction System

**Project:** Measurements for Mechanical Engineering (Politecnico di Milano, A.Y. 2025–26).
Three HC-SR04 ultrasonic sensors at the vertices of an equilateral triangle (side s = 1.0 m),
flat on the floor, each tilted 55° above horizontal aiming radially inward. A **basketball
[AMENDED v2.6 — D6; was: tennis ball]** thrown
over the array is ranged by sequential pings; the trajectory is reconstructed by trilateration,
smoothed by a Kalman filter, fitted with a parabola, and extrapolated to the floor to predict the
landing point, reported in polar coordinates (r, θ) from the array centroid.

This file is the authoritative build specification. Where it conflicts with the proposal PDF,
**this file wins**.

## Development Environment

- OS: Windows
- Python interpreter: `.\venv\Scripts\python.exe`
- Always use the venv interpreter for every command. Never use bare `python` or `pytest`.
- Run Python scripts as: `.\venv\Scripts\python.exe scripts\run_session.py`
- Run tests as: `.\venv\Scripts\pytest.exe` or `.\venv\Scripts\python.exe -m pytest`

### Changelog v1 → v2 (from design review)
- **R1** Background gate hardened: timeout-dominated and zero-variance backgrounds handled;
  minimum band width `d_min_band`; minimum non-timeout sample count. (§5.3, §5.4)
- **R2** Ball-radius range correction: measured ranges point at the ball's *surface*; add
  `ball.radius_m` to every range before trilateration. Tape-to-**centre** convention in static
  characterization. (§8.2a, §7)
- **R3** Mid-echo sample time: physical sampling instant is `t_TRIG + echo/2`, used for all
  Δt computations and Kalman timestamps. (§5.1, §8.2, §8.4)
- **R4** Sensor height `S_height_m` above floor: equal-height assumption made explicit and
  surveyed; `y_floor = y_trilat + S_height_m`. (§0.1, §2, §8.3)
- **R5** Arming triplets retroactively included in the throw buffer. (§5.5)
- **R6** Per-triplet heteroscedastic measurement noise: σ_y ≈ (d/y)·σ_d in a per-triplet R.
  (§8.3, §8.4)
- **R7** Per-throw prediction uncertainty (σ_r, σ_θ) from fit covariance, with small-sample
  caveat. (§8.5)
- **R8** Ground-truth protocol: first-contact marking + two-tape triangulation; ground-truth
  uncertainty fields. (§5.5, §5.6)
- **R9** Campaign planning: 15–20 ground-truthed throws for bias-gate statistical power. (§11)
- **R10** Height from all three spheres averaged + consistency residual quality flag; rollover
  unit test; cross-talk justification sentence. (§8.3, §5.1, §4)

### Changelog v2 → v2.1 (from external engineering audit)
Three amendments accepted from the audit (A1, A2, A4); the remainder was either already covered
by v2, declined as not worth the added complexity (A3), or found to be incorrect (see §13 for
the disposition record, kept so reviewers can see why each major audit claim was handled as it
was).
- **A1** `pulse_timeout_us` reduced 15000 → **12500** µs. d_max = 2.0 m is gated in software;
  echoes beyond ~12 ms are discarded anyway, so the long timeout only narrows the per-slot
  idle margin. 12500 (not 12000) preserves margin at low temperature, where a 2.0 m round trip
  approaches 12.0 ms. Widens idle margin ~3 ms → ~5.5 ms. **No baud-rate change** (115200
  retained; the audit's buffer-overflow mechanism is incorrect — see §13). (§2, §4)
- **A2** Ceiling wrap-around ghost: a static reflector (ceiling) produces a *static* aliased
  echo in the next slot that can pass the d_max gate. Because it is static it is captured by
  the background calibration and rejected by the band rule (R1); the **rigid schedule is kept**
  precisely so the ghost stays static and subtractable (a jittered schedule would defeat this).
  `--background-only` now predicts expected ghost apparent-ranges from an entered ceiling
  height; report paragraph added. (§4, §5.3, §11)
- **A3 — declined.** The audit's empirical speed-of-sound self-calibration was considered and
  **not adopted**: the humidity/pressure error it targets is mm-level (~0.1–0.3%) and accepted
  here. Speed of sound stays formula-based from a typed-in temperature. (§5.2, §13)
- **A4** **Zenith temporal-correction error** is now characterized, not assumed away: the
  simulator already models exact staggered timing, so a test reports the Option-A residual vs
  transverse speed (worst case ~1–2 cm at 4 m/s, d = 1 m — bounded, does NOT trip the NaN
  guard at y ≳ 0.5 m). The central-difference velocity upgrade — **now generalised to the
  hybrid stencil and adopted as the production default in v2.2 (D1)** — cancels the leading
  bias term. (§8.2, §9, §13)
- **A5 (contingency)** If the ball fails the §7 detectability test, escalate a taped-ball or
  hard-sphere substitution to Prof. Zappa before any campaign (target change affects the
  approved proposal and slightly alters mass/drag). (§11)

### Changelog v2.1 → v2.2 (from implementation + three build decisions)
This revision reconciles the spec with the as-built software (the pipeline was built and tested
through the §9 synthetic acceptance gate; 161 tests passing before this revision), records the
**architecture change** discovered during the build, and folds in **three user decisions** (D1–D3)
plus a **session-naming fix** (D4). The concrete, file-by-file work order and the *new* tests that
D1–D4 require live in the companion **CHANGES.md**; this file is the resulting authoritative spec.

- **Architecture (process_throw.py).** §10's original ordering put the acceptance gate (item 7)
  ahead of the code it depends on (`background.py`, `segmentation.py`, and the offline
  post-CLOSING orchestration, which was implicitly buried inside `run_session.py` at item 9) —
  a circular dependency. Resolved by extracting the offline chain into a new pure-orchestrator
  module **`pipeline/process_throw.py`** (`process_session(session_dir, config)`) that BOTH the
  acceptance test and the future `run_session.py` call. The §10 build order is fully renumbered
  (15 items). (§1, §8.8, §10)
- **Implementation reconciliation.** Several v2.1 assertions could not hold as written and were
  corrected against measured evidence: the §8.2 "<1 mm" accuracy claim is impossible on a curved
  arc (split into linear-exact + arc-bounded); the §8.3 consistency residual `q` is identically
  zero by construction for a 3-sensor triplet (vacuous as a noise-growing flag); the §9 R3
  negative control cannot fail an honest end-to-end criterion (verified at unit level instead);
  `numpy.polyfit(cov=True)` cannot be used at the legal dof<3 case and the covariance is computed
  by hand. (§8.2, §8.3, §8.5, §9)
- **(D1) Hybrid temporal-correction stencil — production default.** `corrections.central_difference`
  now means a **hybrid finite-difference stencil**: forward at the first triplet, central in the
  interior, backward at the last triplet. It keeps **all N triplets** (legacy forward mode kept
  only N−1, discarding the last), and roughly halves the along-track curvature systematic
  (~−24 mm forward → ~−12 to −15 mm hybrid). Now `true` in config. (§2, §8.2, §9)
- **(D2) Beam-cone visibility model in the simulator.** The simulator now optionally gates
  synthetic detections to the transducer cone, so triplet counts match reality (~5–6, not
  20–22). Makes the acceptance gate's data density representative. (§2, §6, §9, §11)
- **(D3) Campaign size.** Plan **15–20** ground-truthed throws; extend to **30 if time permits**.
  Justified against the measured realistic along-track drag bias (~8 mm vs ~20 mm scatter): a
  null result at 15–20 is a valid "drag below noise floor" finding, not insufficient data. (§11)
- **(D4) Unique session directory names.** Synthetic session directories are now named
  `sim_YYYY-MM-DD_HHMMSS_S##` (timestamp to the second + batch counter) so same-day re-runs and
  multi-session batches never overwrite. (§2, §5.6, §6)

---

### Changelog v2.2 → v2.3 (HTML reporting layer built; ground-truth protocol revised)
This revision folds in the **browser reporting layer** (built and tested — the former companion
`website.md` is now absorbed here as **§12**) and specifies the **forward ground-truth protocol
change** (designed, NOT yet built) from two-tape to centroid-plus-two-sensor multilateration.

- **(W1) HTML reporting layer — BUILT.** Two independent, self-contained pages generated by
  `pipeline/web_report.py`: a **per-throw `report.html`** in each session dir (input-mode →
  frozen-after-ground-truth) and a **campaign `campaign.html`** in the sessions *parent* dir,
  regenerated after every throw and every ground-truth entry (never frozen). Ground truth is entered
  in the browser via a **local stdlib server** (`scripts/serve_report.py`) that reuses the audited
  solve and writes only the `ground_truth` key (atomic temp+`os.replace`, read-back confirmed,
  success-gated UI). Skipped/closed sessions are completable later (`serve_report.py --session <id>` /
  `--pending`). `run_session.py` gains an additive `--web` flag; the terminal prompt stays the default
  and the fallback. Full spec: **§12**. (§1, §5.6, §5.7, §8.1, §10, §12)
- **(G1) Ground-truth protocol → centroid + 2 recommended sensors, multilateration — FORWARD SPEC
  at v2.3; BUILT in v2.5 (see IMPLEMENTATION_NOTES Part 9).** Replaces the two-tape (centroid + S1,
  two-circle) method of v2.2. The parabola-fit
  prediction **recommends the two sensors nearest the predicted landing**; the operator confirms or
  overrides; the operator measures tape distances to the **centroid + the two chosen sensors** (three
  references); `geometry.ground_truth_landing` solves by **least-squares multilateration** (three
  distance constraints, two unknowns → unique, **no mirror ambiguity**, so the v2.2 z-sign
  disambiguation step is retired). The F-9 tangent-circle **hard `ValueError` softens to a
  condition-number warning** on near-collinear references; the LS **residual** is stored in
  `session.json` as an integrity guard (large residual = mis-tape or wrong sensor logged), and
  `session.json` records **which two sensors** were solved on. Downstream consumers
  (`calibrate_bias.py`, reporting, Kalman pipeline) are unaffected **provided the derived
  `ground_truth` keys keep their names.** (§0.2, §5.5, §8.1, §2, §12.4)
- **(G1-status) Migration complete (v2.5).** The web layer (W1) was originally built on the **old**
  two-tape input (centroid + S1, two fields, `two_circle` solve). The G1 migration has since landed:
  the per-throw input panel is now **centroid + 2 sensor fields with a recommended-pair selector**,
  and the web and terminal paths both use the shared `solve_ground_truth` multilateration core.
  `two_circle_intersection` is retired; no two-tape path remains. Recorded in §12.4 and §10 item 17.

---

### Changelog v2.3 → v2.4 (D5 — demo/live session storage separation)
This revision **partitions simulator/demo sessions from live (hardware) sessions on disk** so the
campaign report never mixes synthetic and real throws. It folds in four user decisions (D5a–D5d). The
file-by-file work order lives in the companion **CHANGES.md (D5)**; this file is the resulting
authoritative spec.

- **(D5) Demo subtree + separate campaigns.** Simulator sessions now live under
  `data/sessions/<sessions.demo_subdir>/` (default `demo/`); live sessions stay directly under
  `data/sessions/`. Each subtree owns its **own** `campaign.html` — `data/sessions/campaign.html`
  (live throws only) and `data/sessions/demo/campaign.html` (demo throws only) — and the two never
  mix. A demo session keeps the **identical internal layout** as a live one (§5.6): `report.html`,
  `session.json`, `trajectory.csv`, `plots/`, etc. (§0.3, §1, §2, §5.6, §6, §8.7, §10, §12.2)
- **(load-bearing) Session-detection predicate.** "A directory is a session **iff it contains a
  `session.json`**" replaces the v2.2 / §VV-1 "directories-only" filter everywhere sessions are
  enumerated — `web_report.build_campaign_data`, `analyze_campaign.load_campaign`, and the
  `calibrate_bias` per-path loader. This single change is what makes the live campaign builder,
  scanning `data/sessions/`, **skip the `demo/` container automatically** (the container holds no
  top-level `session.json`), with **no dependence on directory names or the `sim_` prefix**. (§8.7,
  §12.2)
- **(D5a) Demo campaign auto-regenerates.** `simulate_session.py` regenerates
  `data/sessions/demo/campaign.html` automatically at the end of a batch (mirroring how
  `run_session.py` regenerates the live campaign), so the demo report is never stale.
- **(D5b) Config home.** A **new top-level `sessions:` block** holds `demo_subdir`, kept separate from
  `simulator:` because it is a storage-layout setting, not simulator physics.
- **(D5c) `analyze_campaign.py` hardened.** The predicate is applied inside its `load_campaign`. The
  Part-6 "do not touch `analyze_campaign.py`" stance is **deliberately lifted here**, scoped to this
  one guard, so the CLI is safe to point at the new layout. The same guard extends to the
  `calibrate_bias` per-path loader, which shares the `data/sessions/*` glob hazard.
- **(D5d) One-time migration now, pre-git.** The existing synthetic session dirs are moved into
  `data/sessions/demo/` immediately, **before** version control is set up. Rationale recorded for
  audit: demo sessions are **seeded and reproducible**, not irreplaceable raw campaign data, so the
  "raw data is sacred / migrate only under git" caution — which still binds **real** throws — does not
  bind here.
- **Reserved name.** `sessions.demo_subdir` is a **reserved directory name** under `data/sessions/`; a
  live session must never be named after it.

---

### Changelog v2.4 → v2.5 (military-HUD report restyle)
A visual-only restyle of the two browser report templates (`pipeline/web_assets/campaign_report.html`,
`session_report.html`) into a tactical instrument-HUD look — **chrome only, no data/behaviour change**.
Full as-built record: **IMPLEMENTATION_NOTES Part 11**; design system updated in **§12.6**.
- **Play button removed.** The campaign scope's array **triangle** (S1 right, S2/S3 left → read as a
  "play button") is gone; S1/S2/S3 now render as steel dots in bracket boxes, matching the per-throw
  scope. (§12.2, §12.6)
- **Military-HUD language** on both pages: angular bracket-corner panels, numbered `[01]…` section
  tags (CSS counter, label text verbatim), command-banner header, scope reticle + bearing scale
  (`000–330°`) + reduced-motion-safe radar sweep, top-accent stat tiles, amber/coral accent strips.
- **Unchanged & load-bearing:** every value/label/precision, all element `id`s, the `<!--__DATA__-->`
  marker, the input/frozen/failure state machine, and the functional colour channels. Graphics stay
  **`<canvas>` + CSS — no inline SVG** (its `xmlns="http://…"` would fail the §12.5 self-containment
  test). 225 tests green. (§12.5, §12.6)

---

### Changelog v2.5 → v2.6 (D6 — target substitution: tennis ball → basketball; A5 contingency executed)
The §11 A5 contingency fired and is hereby **resolved**. This revision records the measured
failure, the approval, the decision, and every spec touch point. The file-by-file work order
lives in the companion **CHANGES.md (D6)**; this file is the resulting authoritative spec.

- **Measured trigger (hardware evidence, 2026-07).** Bench characterization per §7: the **flat
  board PASSED at 1.0 m** (electronics, wiring, and timing proven good), but the **tennis ball
  produced no valid readings at 1.0 m on-axis** (persistent timeouts). This isolates the target
  as the root cause — the felt surface is a poor reflector at 40 kHz (λ ≈ 8.6 mm; fibrous,
  porous absorber), confirming the v2 top risk and the §13 audit disposition. Raw session data
  retained under `data/sessions/*_static/` per the raw-data-is-sacred rule.
- **Approval (A5 process followed).** The substitution was escalated to **Prof. Zappa**, per A5,
  before any code or config change; Prof. Zappa **approved the change of target to a
  basketball** (2026-07). This supersedes the milder A5 candidate substitutions (taped tennis
  ball / similar-diameter hard sphere), which were presented and passed over in favour of the
  basketball. Scope of the approved proposal is amended accordingly.
- **(D6) Target = basketball.** Acoustic rationale: pressurised rubber/leather shell is
  acoustically hard (vs absorbing felt); pebble texture (~1 mm) is well below λ ≈ 8.6 mm, so the
  surface is quasi-smooth (specular). For a sphere with ka ≫ 1 the backscatter cross-section
  scales as πr²: r ≈ 0.121 m vs 0.0335 m gives **~13× (~+11 dB) stronger return**, and the
  larger subtended angle **widens the effective detection cone**, relieving the §11
  few-triplets-per-throw risk. *(Estimates; the §7 characterization measures the real values.)*
- **What changes (spec level).** `ball.radius_m` → the **measured** basketball radius
  (placeholder 0.121 m until measured — see §2 note; convention: measure circumference C with a
  tape, r = C/2π, record C, r, and mass in the D-register). R2 correction and the landing
  contact condition y = `ball.radius_m` are **parametric and remain exact for any sphere** — no
  algorithm change. Touch points amended inline below: §2 (config), §6 (simulator comment),
  §7 (protocol), §8.2 (R2 negative-control magnitude), §9 (gate re-verification), §11 (risk
  register — detectability risk closed; three basketball-specific risks added).
- **What does NOT change.** Array geometry, firmware, timing, gates, trilateration, Kalman,
  landing fit, bias model, reporting — all untouched. The ~121 mm surface→centre correction is
  larger than the tennis 33.5 mm but structurally identical.
- **Test audit required (CHANGES.md D6).** Any test that hardcodes the tennis radius or its
  consequences (33.5 mm R2 bias, ~80 mm §9 R2-OFF failure magnitude) must be audited and made
  config-driven or updated; the §9 acceptance gate must be re-run green under the new radius
  before any hardware session.
- **Drag numbers to re-derive.** The §11 D3 figures (~8 mm along-track bias vs ~20 mm scatter)
  were tennis-derived. Basketball A/m is **comparable or slightly higher** (~0.072 vs
  ~0.061 m²/kg, approximate — verify with the measured ball mass), so the same order is
  expected; the 15–20 (→30) throw plan stands **pending re-estimate** in CHANGES.md D6.
- **Optical module explicitly DEFERRED.** CLAUDE_OPTICAL.md is intentionally NOT amended here:
  the HSV band (tennis yellow-green → basketball orange), the detector area band, and the
  parallax uncertainty component (scales with r_ball; grows ~3.6×, material vs the 15 mm gate)
  require their own **O-series amendment + work order before Phase 5 fieldwork**. Recorded here
  so it cannot be silently forgotten.
- **Nano Every documentation — RESOLVED in v2.7.** The Arduino Uno → Nano Every hardware-switch
  documentation amendment (noted here as still pending) is complete; see the v2.6 → v2.7
  changelog immediately below.

---

### Changelog v2.6 → v2.7 (bench follow-ons: Nano Every doc, acquisition-layer offset correction, `--no-background`, D6-R1 closed)
Four small, already-shipped changes folded back into the spec so CLAUDE.md matches the as-built
code (IMPLEMENTATION_NOTES Parts 16–17) and the completed 34-throw live campaign
(`data/sessions/2026-07-09_T*`). No pipeline math changed; this is a documentation-and-config-schema
sync, plus one risk-register closure. **CHANGES.md's D6 work order is now closed and its file
wiped** — this changelog, not a separate work-order file, is the record from here on.

- **Hardware — Arduino Nano Every.** The controller was switched from the Arduino Uno to the
  Arduino Nano Every. **Board name only** — wiring, pin numbers (D2/D3/D4/D5/D6/D7), 5V logic, and
  firmware behaviour (`digitalWrite`/`pulseIn`/`micros()`) are unchanged; no firmware or
  wiring-topology edit was required. §2/§3 now say Nano Every throughout.
- **(new) Per-sensor electronic-offset correction — BUILT (IMPLEMENTATION_NOTES Part 16).**
  BENCH_PROCEDURE_v2 Phase 4D found all three sensors' flat-board static offsets SIGNIFICANT
  (§7). A new config key `acquisition.sensor_offset_m` (per-sensor, metres, measured from the
  flat-board static study) is subtracted from every raw range at the acquisition layer:
  `corrected = measured − offset` (a negative offset means the sensor reads short, so it ADDS
  distance). Applied by DEFAULT in `run_session.py`; `--no-offset-correction` disables it.
  Synthetic sessions ignore it (`process_session` defaults `apply_offset=False`) — a
  measurement-layer correction, deliberately outside `bias.py`, and it does NOT affect the
  background gate (a constant per-sensor shift cancels in the band rule). §2, §5.1.
- **(new) `--no-background` flag — BUILT (IMPLEMENTATION_NOTES Part 17).** For open-ground bench
  runs with no static reflector to subtract, `run_session.py --no-background` skips the ~11 s
  background-calibration wait and writes an all-bands-disabled `background.json` directly. This
  is behaviourally identical to a real open-air calibration (§5.3's R1 gate-enable logic already
  disables the band rule when `f0 > bg_timeout_skip`), just without the wait — NOT safe when a
  static reflector (wall/ceiling) is in view; documented as an open-ground convenience only. §5.3,
  §5.7.
- **D6-R1 (rebound re-entry) — CLOSED, entry removed.** Checked against the completed 34-throw
  live campaign (2026-07-09): no post-contact rebound contamination was observed at any session's
  segmentation boundary. The §11 risk-register bullet is removed; the D6 risk list is now
  D6-R2/D6-R3 only.
- **Remaining open item, project-wide.** The **O-series optical amendment** (CLAUDE_OPTICAL.md —
  HSV band, detector area band, parallax uncertainty scaling with `ball.radius_m`) remains
  deliberately deferred, per the v2.5 → v2.6 changelog above, and is required before Phase 5
  fieldwork. **This is now the only outstanding item in the project.**

---

### Changelog v2.7 → v2.8 (legacy-design ablation study — documentation-only, no pipeline change)
Presentation prep (`Presentation_Flow_Deck.pdf`, Speaker A/B/C slides 6–17) required quantified
"legacy vs corrected" numbers that did not exist anywhere in the repo. This revision records that
a **read-only ablation study** was run over the completed 34-throw live campaign
(`data/sessions/2026-07-09_T*`) to produce them. **No pipeline module, config value, or session
file changed** — this is a reporting/documentation pass, full record in the new
**`LEGACY_ABLATION_RESULTS.md`** (repo root) and `IMPLEMENTATION_NOTES.md` Part 19.
- **(new) `LEGACY_ABLATION_RESULTS.md`.** Two standalone, read-only scripts re-processed the 34
  recorded sessions: (a) the full legacy configuration (temperature fixed at 343 m/s, no per-sensor
  offset, no ball-radius R2, forward differencing, nominal fixed-schedule timestamps, no
  sensor-height correction, no Kalman filter, y = 0 landing, no bias model) against each session's
  existing three-tape ground truth; (b) a **leave-one-out (LOO) ablation** from the delivered,
  fully-corrected pipeline, turning off exactly one correction at a time against the shipped
  `correction_model.json` bias. Neither script is part of `pipeline/`/`tests/`; both are archived,
  reference-only, reproducible against the venv interpreter.
- **Headline finding: the legacy pipeline predicts a landing for only 16 of the 34 recorded
  throws** (mean 133.3 mm 2D error on those 16; the other 18 fall below `min_fit_points = 4`
  because forward differencing discards the last triplet of every 4-triplet throw). This is a
  materially different — and more damning — legacy result than an accuracy-only comparison would
  show, and is now the recommended Slide 6 headline.
- **Headline finding: a single "legacy vs corrected" delta cannot be honestly split into five
  independent per-fix numbers**, because the corrections interact (bias model absorption of
  common-mode range offsets, most visibly). The LOO ablation is the methodologically correct
  per-fix Δ; see `LEGACY_ABLATION_RESULTS.md` §4 for the full table and §5 for a recommended star
  reshuffle (promote ball-radius R2, currently unstarred, whose removal costs **+99.3 mm** — the
  single largest measured effect in the system; demote per-sensor offset, temperature, sensor-
  height, Kalman filter, and mid-echo sampling, whose delivered-system deltas are not
  statistically resolvable at n = 34).
- **No code, test, or config change.** `.\venv\Scripts\pytest.exe` re-run after this study:
  **242 passed**, unchanged from v2.7 — this changelog entry and `LEGACY_ABLATION_RESULTS.md` are
  the only artifacts this revision adds.

---

## 0. Non-negotiable conventions (read first, apply everywhere)

### 0.1 Coordinate frame
- **Origin:** array centroid, **on the floor** (y = 0 is the floor plane).
- **+x:** horizontal, from centroid toward sensor S1. **This is the θ = 0 reference axis.**
- **+y:** vertical, upward.
- **+z:** horizontal, perpendicular to x, completing a right-handed frame
  (θ measured counter-clockwise viewed from above goes from +x toward +z).
- **Polar output:** r = √(x² + z²) in metres; θ = atan2(z, x) in **degrees**, CCW from above,
  range (−180°, 180°].
- **Sensor height (R4):** the acoustic centres of the transducers sit at height
  `S_height_m` above the floor (pod base + transducer elevation, expected 3–6 cm). All
  trilateration happens in the **sensor plane** (heights cancel only because all three sensors
  are at *equal* height — see §8.3); the floor frame is recovered by
  `y_floor = y_trilat + S_height_m`. **The Phase-2 survey must measure h at each pod and
  verify equality within ±3 mm**; record all three values in `session.json`/config comments.
- Ideal symmetric horizontal vertex positions (circumradius R_c = s/√3 ≈ 0.5774 m):
  S1 = (R_c, 0), S2 = (−R_c/2, +s/2), S3 = (−R_c/2, −s/2) in (x, z).
  **NOTE:** this is a rotation of the proposal's published convention (which put S1 on +z).
  Trilateration must use the general A⁻¹b form with vertex coordinates read from config —
  never the hardcoded closed form. Measured (not ideal) vertex coordinates go into config
  after the array is built and the three pairwise distances are surveyed.

### 0.2 Polar in, Cartesian inside, polar out
- All landing **outputs** to the user: (r, θ) ± (σ_r, σ_θ) (R7).
- Ground-truth landing **inputs**: via the centroid-plus-two-sensor **multilateration** protocol of
  §5.5 (R8, v2.3 G1), converted to Cartesian internally.
- **All mathematics is Cartesian.** Convert polar→Cartesian immediately on input, convert
  Cartesian→polar only at the final display/report step. **Never fit, average, or regress in
  polar coordinates.**

### 0.3 Session model
- **One session = one throw.** Live program: startup → background calibration → armed wait →
  detect throw → throw ends (gate logic) → process → report (r, θ, σ_r, σ_θ) → ground-truth
  prompt → write outputs → exit. No multi-throw loop.
- Bias calibration is a **separate offline program** run over many single-throw sessions.
- **Storage partition (v2.4 D5).** Live (hardware) sessions are written directly under
  `data/sessions/`; simulator/demo sessions under `data/sessions/<sessions.demo_subdir>/` (default
  `demo/`). Each subtree has its own `campaign.html`; the live and demo campaigns never mix. A
  directory counts as a session only if it contains `session.json` (§12.2). See §5.6.

### 0.4 Units and data hygiene
- Firmware streams **raw echo time in microseconds** (integers). Distances exist only in
  Python, computed with the session temperature. Never convert to distance on the Arduino.
- Internal SI units everywhere in Python: metres, seconds, m/s; temperature input in °C.
- Raw data is sacred: every byte received over serial is logged verbatim before any gating.
  Gating decisions are recorded as flags, never by deleting rows.
- All physical constants and thresholds live in `config.yaml`. Nothing physical hardcoded.

### 0.5 Validation discipline
- **Every processing layer must be validated against synthetic data before the layer above it
  is built on top of it.** The simulator (§6) is built EARLY (right after geometry) and is a
  first-class deliverable.
- Each module ships with pytest unit tests. The synthetic end-to-end test (§9) is the
  acceptance gate for the pipeline.
- **I/O boundary (clarified v2.2):** the *computational* modules in `pipeline/`
  (`geometry, corrections, trilateration, kalman, landing, bias, background, segmentation,
  simulator`) are pure — no file or serial I/O. The **I/O layer** is `pipeline/process_throw.py`
  (offline orchestrator, §8.8), `pipeline/acquisition.py` (live serial, future), and everything
  in `scripts/`. The "no I/O in `pipeline/`" rule applies to the computational modules; the
  orchestrator is the deliberate, tested exception.

---

## 1. Repository layout

```
projectile-landing/
├── CLAUDE.md                      # this file
├── CHANGES.md                     # latest work order to paste into Claude Code (currently: audit remediation)
├── IMPLEMENTATION_NOTES.md        # as-built record + findings ledger (Parts 1-11)
├── handoff.md                     # session handoff (state, open issues, next action)
├── BENCH_PROCEDURE.pdf            # hardware bring-up / bench-gate checklist
├── config.yaml                    # single source of physical truth
├── firmware/
│   ├── 01_single_sensor/01_single_sensor.ino
│   ├── 02_timeout_discipline/02_timeout_discipline.ino
│   ├── 03_three_sequential/03_three_sequential.ino
│   ├── 04_serial_csv/04_serial_csv.ino
│   └── 05_timing_verify/05_timing_verify.ino   # final flight firmware (= 04 + verified)
├── pipeline/                      # COMPUTATIONAL modules are pure (no I/O); see §0.5
│   ├── __init__.py
│   ├── geometry.py                # frame, vertex handling, polar<->cartesian
│   ├── acquisition.py             # serial reader, triplet assembly, t_sample, modes
│   ├── background.py              # background calibration + hardened gate rules
│   ├── segmentation.py            # IDLE/ACTIVE/CLOSING state machine
│   ├── corrections.py             # temperature + ball-radius + temporal corrections;
│   │                              #   canonical home of speed_of_sound & mid_echo_sample_time
│   ├── trilateration.py           # A^-1 b solve + 3-sphere height + NaN guard + quality flag
│   ├── kalman.py                  # 7-state augmented filter, variable dt, per-triplet R
│   ├── landing.py                 # parabola fit, y = r_ball solve, uncertainty, polar out
│   ├── bias.py                    # throw-aligned bias model (calibrate/apply)
│   ├── simulator.py               # synthetic throw generator (incl. beam-cone model, D2)
│   ├── process_throw.py           # I/O LAYER: offline orchestrator process_session();
│   │                              #   serial-parse helpers reused by acquisition.py. (v2.2)
│   ├── reporting.py               # plots, statistics, session report
│   ├── web_report.py              # (v2.3 W1) per-throw + campaign HTML generators; see §12
│   └── web_assets/                # (v2.3 W1) session_report.html + campaign_report.html templates
├── scripts/
│   ├── run_session.py             # the live one-throw program (reuses process_session)
│   ├── verify_timing.py           # firmware sketch 05 companion
│   ├── characterize_static.py     # stationary-target tool (tape-to-CENTRE convention)
│   ├── analyze_static.py          # aggregate static reports -> beam half-angle + offset recommend
│   ├── calibrate_bias.py          # offline multi-session bias calibration
│   ├── analyze_campaign.py        # cross-session statistics and plots
│   ├── append_ground_truth.py     # add/edit ground truth on an existing session
│   ├── serve_report.py            # (v2.3 W1) local server for browser ground-truth write-back; §12.3
│   ├── demo_web_reports.py        # (D5-aware) generate+process+render HTML for synthetic sessions
│   └── simulate_session.py        # generate synthetic session directories
├── tests/
│   ├── session_factory.py         # shared helper: writes session dirs in the on-disk format
│   ├── test_geometry.py
│   ├── test_simulator.py          # incl. beam-cone gating & session-name uniqueness (D2, D4)
│   ├── test_corrections.py        # incl. ball-radius, mid-echo, hybrid-stencil tests (R2,R3,D1)
│   ├── test_trilateration.py      # incl. height-offset & consistency-flag tests (R4, R10a)
│   ├── test_kalman.py
│   ├── test_landing.py            # incl. uncertainty propagation test (R7)
│   ├── test_bias.py
│   ├── test_background.py         # incl. timeout-dominated & sigma≈0 cases (R1)
│   ├── test_segmentation.py       # incl. arming-triplet retention (R5)
│   ├── test_acquisition.py        # micros() rollover unwrap (R10c)
│   ├── test_run_session.py        # terminal-path guards: overwrite refusal, atomic GT
│   │                              #   write, rendering, failure path (audit remediation)
│   ├── test_characterize_static.py # tape-to-centre convention + beam half-angle
│   ├── test_process_throw.py      # offline orchestrator + parse helpers (v2.2)
│   ├── test_reporting.py          # per-session diagnostic plots
│   ├── test_analyze_campaign.py   # campaign stats, power note, session predicate (D5)
│   ├── test_web_report.py         # (v2.3 W1) renderer: states, self-containment, campaign
│   ├── test_serve_report.py       # (v2.3 W1) write-back == terminal solve; atomic; late entry
│   ├── test_run_session_web.py    # (v2.3 W1) --web headless smokes (POST/skip/Ctrl-C)
│   └── test_end_to_end_synthetic.py   # the §9 acceptance gate
└── data/
    └── sessions/                  # (v2.4 D5) partitioned: live throws here, demo throws under demo/
        ├── campaign.html          # (W1) LIVE campaign — real throws only; §12.2
        ├── <session_id>/          # one directory per LIVE throw, see §5.6
        └── demo/                  # (D5) all simulator/demo sessions; reserved dir name
            ├── campaign.html      # (D5) DEMO campaign — synthetic throws only; §12.2
            └── <sim_session_id>/  # one directory per synthetic throw, identical §5.6 layout
```

Python ≥ 3.10. Dependencies: `numpy`, `scipy`, `pandas`, `matplotlib`, `filterpy`, `pyserial`,
`pyyaml`, `pytest`. Provide `requirements.txt`.

---

## 2. config.yaml schema

```yaml
array:
  # measured HORIZONTAL vertex coordinates [m] (x, z) in the frame of §0.1;
  # replace ideal values with surveyed ones after build
  S1_xz: [0.5774, 0.0]
  S2_xz: [-0.2887, 0.5]
  S3_xz: [-0.2887, -0.5]
  S_height_m: 0.045         # (R4) acoustic-centre height above floor; MEASURE after build.
                            # Equal-height assumption: survey all three pods, require
                            # agreement within ±0.003 m. Record per-pod values in comments.
  tilt_deg: 55.0            # informational; not used in trilateration math

ball:
  radius_m: 0.1194          # [D6, MEASURED 2026-07-09] basketball (was a 0.121 placeholder,
                            # itself replacing 0.0335 tennis ball — see v2.6 changelog above).
                            # Measured: circumference C = 0.750 m (tape, ±2 mm),
                            # r = C/(2π) = 0.1194 m (within the size-7 sanity band
                            # 0.119–0.124 m, near its lower edge), mass m = 0.620 kg (scale).
                            # Full record incl. evidence session paths: D6 decision-register
                            # entry in IMPLEMENTATION_NOTES.md. Used TWICE: (R2) added to
                            # every raw range before trilateration (surface->centre), and
                            # landing solve y = radius_m. Both are parametric — exact for any
                            # sphere.

acquisition:
  port: "/dev/ttyACM0"      # or COMx on Windows; CLI-overridable
  baud: 115200              # (A1) RETAINED. Audit's 500k suggestion solves a non-problem.
  slot_ms: 18
  triplet_ms: 54
  pulse_timeout_us: 12500   # (A1) was 15000. See §4.
  ceiling_height_m: null    # (A2) optional; --background-only predicts wrap-around ghost range.
  sensor_offset_m: [0.0, 0.0, 0.0]
                            # [v2.7, BUILT] per-sensor electronic offset, metres, one value per
                            # S1/S2/S3, measured from the flat-board static study (§7). A NEGATIVE
                            # value means the sensor reads short (adds distance); applied as
                            # corrected = measured - offset at the acquisition layer, BEFORE
                            # trilateration. Measurement-layer correction, deliberately OUTSIDE
                            # bias.py (§7). Does NOT affect the background gate (a constant
                            # per-sensor shift cancels in the band rule). Applied by DEFAULT in
                            # run_session.py; `--no-offset-correction` disables it. Synthetic
                            # sessions ignore it (process_session defaults apply_offset=False).
                            # null / all-zero = no correction.

corrections:                # (D1, v2.2) temporal-correction stencil
  central_difference: true  # true = HYBRID stencil (forward@first / central@interior /
                            #        backward@last), keeps ALL N triplets, ~−12..−15 mm systematic.
                            # false = legacy forward-only (discards last triplet, ~−24 mm).

gates:
  d_max_m: 2.0
  bg_k_sigma: 3.5
  bg_n_triplets: 200
  bg_min_samples: 30        # (R1)
  bg_timeout_skip: 0.9      # (R1)
  d_min_band_m: 0.025       # (R1)
  arm_M: 2
  close_K: 3

kalman:
  sigma_pos_m: 0.010        # per-axis BASE measurement noise (REPLACE with §7 value)
  hetero_R: true            # (R6)
  q_scale: 1e-4

landing:
  min_fit_points: 4

ground_truth:
  sigma_tape_m: 0.005       # (R8)
  recommend_sensors: true   # (v2.3 G1) suggest the 2 sensors nearest the predicted landing as the
                            #   default tape references; operator may override.
  cond_warn: 1.0e4          # (v2.3 G1) condition-number threshold above which the 3 references are
                            #   flagged near-collinear (warn, do NOT abort — replaces the F-9 error).
  residual_warn_m: 0.05     # (v2.3 G1) LS circle-agreement residual above which the tapes / logged
                            #   sensor pair are flagged suspect (integrity guard).

# (v2.3 W1) NO web: config block. The report server (scripts/serve_report.py) binds loopback
# (127.0.0.1) on an ephemeral port UNCONDITIONALLY by design -- host/port are intentionally not
# configurable (localhost-only; never bind a public interface). run_session.py uses the terminal
# ground-truth prompt by default and the browser flow only when --web is passed (see 5.7, 12.3).

bias:
  model_path: "correction_model.json"
  alpha: 0.05
  min_throws: 8             # code floor, NOT the plan. (D3) Plan 15–20 throws; 30 if time
                            #   permits. Realistic along-track drag bias ~8 mm vs ~20 mm scatter
                            #   ⇒ CI rarely excludes zero below ~30 throws; a 15–20 null is a
                            #   valid "drag below noise floor" result. (R9, §11)

sessions:                   # (v2.4 D5) on-disk storage layout (NOT physics)
  demo_subdir: "demo"       # simulator/demo sessions live in data/sessions/<demo_subdir>/ with their
                            #   own campaign.html; live sessions stay directly under data/sessions/.
                            #   RESERVED directory name — never name a live session "demo".

simulator:                  # (D2/D4, v2.2) affects synthetic data only; no effect on hardware
  beam_cone_enabled: true   # gate synthetic detections to the sensor cone (realistic ~5–6
                            #   triplets/throw). false = legacy over-production (~20–22).
  beam_half_angle_deg: 7.0  # ESTIMATE of the HC-SR04 effective detection HALF-angle for a
                            #   BASKETBALL target at ~1–1.5 m [AMENDED v2.6 — D6; was tennis
                            #   ball, which FAILED §7 detectability — see changelog]. The larger,
                            #   acoustically hard target likely WIDENS the effective cone vs the
                            #   flat-wall datasheet figure, but this remains UNVERIFIED — tune
                            #   against §7 static detectability data (re-run with the basketball)
                            #   before trusting synthetic counts.
  session_prefix: "sim"
  session_name_scheme: "{prefix}_{date}_{time}_S{idx:02d}"   # sim_2026-06-12_143052_S03
                            #   date=YYYY-MM-DD, time=HHMMSS(24h). Time prevents cross-run
                            #   overwrite; S{idx} prevents within-batch overwrite. (D4)
```

---

## 3. Hardware wiring (summary; full PDF exists separately)

Controller: **Arduino Nano Every** [v2.7 — was Arduino Uno; board name only, see the v2.6 → v2.7
changelog]. Arduino **5V** → breadboard **+ rail**; Arduino **GND** → breadboard **− rail**.
Per sensor (all VCC on + rail, all GND on − rail; 5 V logic, direct connections, no dividers):

| Sensor | TRIG → Nano Every | ECHO → Nano Every |
|--------|-------------------|-------------------|
| S1     | D2                | D3                |
| S2     | D4                | D5                |
| S3     | D6                | D7                |

Bundle/twist each sensor's four ~0.6 m leads; label bundles S1/S2/S3 at both ends; tug-test
every jumper; confirm common ground. A swapped sensor identity silently corrupts trilateration.

---

## 4. Firmware — five incremental sketches

General firmware rules:
- Plain `digitalWrite`/`pulseIn`/`micros()`; no interrupts, no timer libraries.
- Trigger pulse: TRIG LOW 2 µs → HIGH 10 µs → LOW, then `pulseIn(ECHO, HIGH, pulse_timeout_us)`.
- Timeout → `pulseIn` returns 0; transmit literal `0` (no-echo sentinel).
- Slot discipline: each sensor owns an exact 18 ms slot; absolute scheduler
  `next_slot_us += 18000` (no drift), busy-wait to the boundary after `pulseIn` returns.
  `pulse_timeout_us` = **12500** (A1): with d_max gated at 2.0 m in software, a 12.5 ms
  timeout already covers the full usable range across the lab temperature range while leaving
  ~5.5 ms idle margin per slot for formatting/transmission. **Keep the rigid, equal 18 ms
  slots** — do NOT jitter them (A2): a fixed schedule maps any static reflector (e.g. ceiling)
  to a *static* apparent range that the background calibration can subtract; jittering would
  smear that ghost into untrackable noise and defeat the gate.
- Serial 115200 baud. CSV (sketch 04 onward), one line per reading:
  `sensor_id,echo_us,timestamp_us\n`, where `timestamp_us` is `micros()` at the TRIG instant.
  **The firmware does NOT compute the mid-echo time — that is Python's job (§5.1, R3).**
- Bandwidth: ~25 bytes / 18 ms ≈ 1.4 kB/s ≪ 11.5 kB/s. No buffering risk.
- `micros()` overflows after ~71.6 min; Python unwraps (§5.1) and the unwrap is unit-tested
  (R10c).
- Cross-talk note for the report (R10b, A2): a *late* echo from a previous slot can return
  during the next sensor's window. Two regimes:
  (i) reverberation/echo beyond 3.12 m round trip maps to apparent range > d_max and is gated;
  (ii) **ceiling wrap-around ghost (A2)** — a ping that hits a ceiling tall enough that the
  echo exceeds one 18 ms slot returns during the *next* slot and is timestamped as a *short*
  apparent range that CAN pass the d_max gate. Because the ceiling is static, this ghost is
  static: it appears at the same apparent range every cycle, including during background
  calibration, so the §5.3 band rule subtracts it and the §5.3 sanity check warns if it lands
  inside the ball band. This is the reason the schedule must stay rigid (see slot-discipline
  note above). `--background-only` reports the predicted ghost apparent-range when
  `ceiling_height_m` is set, so the survey can confirm it.

### Sketch 01 — `01_single_sensor`
One sensor on D2/D3. Fire once per 100 ms, print `echo_us` and a display-only distance at an
assumed 343 m/s. **Pass:** flat wall at tape-measured 0.50 / 1.00 / 1.50 m within ±1 cm
(the tape validates *correctness* — round-trip /2, constants, unit slips — not mm accuracy;
real accuracy/noise numbers come from §7).

### Sketch 02 — `02_timeout_discipline`
Adds the 18 ms slot: timeout 12.5 ms, pad to exactly 18 ms via the absolute scheduler. Force
timeouts (open sky/soft target). **Pass:** timeouts print `0`; slot period over 1000 cycles =
18.000 ms, µs-level jitter, no drift.

### Sketch 03 — `03_three_sequential`
All three sensors, S1 at t, S2 at t+18 ms, S3 at t+36 ms, period 54 ms, one absolute
scheduler. **Pass:** readings change independently per sensor; firing order verified by
blocking each sensor in turn.

### Sketch 04 — `04_serial_csv`
Final CSV protocol; startup header `# fw=04,slot_ms=18,timeout_us=12500`.
**Pass:** Python parses 1000 lines with zero malformed rows.

### Sketch 05 — `05_timing_verify` (becomes the flight firmware)
Identical to 04; the test is PC-side: `scripts/verify_timing.py` logs ≥ 1000 lines and asserts
(a) per-sensor period 54.000 ms ± 50 µs, (b) S2−S1 = 18 ms and S3−S1 = 36 ms ± 50 µs,
(c) strictly monotonic timestamps after unwrap, (d) zero parse errors. Prints pass/fail.

---

## 5. Python acquisition layer

### 5.1 Serial reader, triplet assembly, sample-time correction (R3)
- Open port from config (CLI `--port` override). Discard first ~20 lines (auto-reset
  garbage); verify the `# fw=...` header matches config.
- Parse `(sensor_id, echo_us, t_trig_us)`. Unwrap `t_trig_us` across the 2³² µs rollover
  (if t[n] < t[n−1], add 2³²). **Unit test with a synthetic rollover sequence (R10c).**
- **Mid-echo sample time (R3):** the ball's position is interrogated when the pulse arrives
  at it, not at TRIG. Compute per reading:
  `t_sample_us = t_trig_us + echo_us / 2` (timeouts: t_sample = t_trig, flagged invalid
  anyway). **`t_sample` is THE timestamp** for all downstream Δt computations (temporal
  correction §8.2, Kalman §8.4). Both `t_trig` and `t_sample` are logged in
  `triplets_raw.csv` and `trajectory.csv`.
  **(v2.2 home note, F-3):** `speed_of_sound()` and `mid_echo_sample_time_us()` are defined
  ONCE in `corrections.py` (they are corrections), and the acquisition layer calls those
  helpers — a single tested formula in a single place. (Rationale, for the report: the
  common-mode part of echo/2 merely relabels time and is harmless to a spatial fit; the
  *differential* part between sensors — ±1–2 ms ≈ up to ~1 cm at 4 m/s — is what the correction
  actually removes.)
- Assemble triplets keyed on each S1 reading (S1 + following S2 + S3). Order violation →
  triplet malformed, resynchronize on next S1. Log every raw line verbatim to
  `raw_serial.log` BEFORE parsing.
- **Per-sensor electronic-offset correction [v2.7, BUILT]:** `acquisition.sensor_offset_m` (§2) is
  applied per reading, per sensor, right after `echo_us_to_m` and before ball-radius/temporal
  corrections: `corrected = measured − offset`. Applied by default; `--no-offset-correction`
  disables it. Synthetic sessions never apply it. Measurement-layer correction, deliberately
  outside `bias.py` (like the §7 constant-offset-subtraction decision it extends).

### 5.2 Temperature
At program start, prompt: `Ambient temperature [°C]: `. Store in metadata. Speed of sound
`v = 331.4 + 0.606 * T_celsius` [m/s] (verify coefficients against course notes before the
report). Distance `d = v * echo_us * 1e-6 / 2` [m]. `echo_us == 0` → no distance (NaN + flag).
(The residual humidity/pressure error is mm-level — ~0.1–0.3% of range — and is accepted; no
empirical self-calibration is performed. See §13 for why the audit's self-cal proposal was
declined.)

### 5.3 Background calibration (every session, before arming) — hardened (R1)
Operator clears the volume; collect `bg_n_triplets` triplets (~11 s). Per sensor i compute:
- timeout fraction f0_i;
- n_valid_i = count of non-timeout readings;
- over non-timeout readings: μ_bg,i and σ_bg,i (ddof=1) of distance.

**Gate-enable logic per sensor (R1):**
- If `f0_i > bg_timeout_skip` (default 0.9) **or** `n_valid_i < bg_min_samples` (default 30):
  the band rule (§5.4 rule 3) is **DISABLED** for sensor i — the background is open air /
  too sparse to characterize; any non-timeout echo within d_max is treated as signal.
- Else the band half-width is `w_i = max(bg_k_sigma * σ_bg,i, d_min_band_m)` — the floor
  (default 2.5 cm) prevents a quantization-level σ from creating a uselessly thin band.
- Persist everything (f0, n_valid, μ, σ, w, enabled flag, per sensor) to `background.json`.

**Sanity check (warn, don't abort):** if any enabled band [μ_bg,i ± w_i] overlaps
[0.5 m, d_max], print a loud warning that gating will eat real ball readings near that
distance — the array/room geometry should be reconsidered.

**Tests (R1):** timeout-dominated background → band disabled, no NaN propagation, ball echoes
accepted; σ_bg ≈ 0 background → band width = d_min_band; mixed sparse background
(n_valid < 30) → band disabled.

### 5.4 Validity gate (per reading, then per triplet)
A reading is VALID iff:
1. `echo_us != 0`;
2. `d <= d_max_m`;
3. `|d − μ_bg,i| > w_i` — **only if the band rule is enabled for sensor i** (§5.3).
A triplet is VALID iff all three readings are valid. Store per-reading and per-triplet flags;
never drop rows.

### 5.5 Throw state machine (one throw, then exit)
- **IDLE/ARMED:** stream and log; transition to ACTIVE when `arm_M` (=2) consecutive triplets
  are VALID. Print "THROW DETECTED".
  **(R5) The `arm_M` arming triplets are retroactively included in the throw buffer and
  processed identically to ACTIVE triplets.** With only ~5–6 triplets per throw and the last
  one consumed by the temporal correction, discarding the arming triplets would starve the
  fit. **Test:** `test_segmentation.py` asserts the arming triplets appear in
  `triplets_raw.csv` flagged as part of the throw.
- **ACTIVE:** accumulate triplets (valid and invalid, flagged). Transition to CLOSING when
  `close_K` (=3) consecutive triplets are INVALID.
- **CLOSING:** strip the trailing K invalid triplets, finalize, stop acquisition, process
  (§8 via `process_session`, §8.8), print the prediction as
  `r = … m, θ = … °, σ_r = … m, σ_θ = … °` (R7), then run the **ground-truth protocol (R8)**:
  1. Identify first contact: lightly talc/chalk-dust the ball (or floor strip), or use
     slow-motion phone video; mark the contact point with tape.
  2. **Sensor-recommended multilateration (replaces two-tape; v2.3 G1):** the pipeline takes the
     predicted landing (x, z) and **recommends the two sensors whose surveyed floor positions are
     nearest it** (of S1/S2/S3) as the default tape references. The operator **confirms or overrides**
     the pair, then measures straight-line floor distances from the contact mark to **three**
     references: the **centroid** (L_c) and the **two chosen sensors** (L_a, L_b, each at its
     `config.array.S?_xz`). `geometry.ground_truth_landing` solves the **over-determined least-squares
     multilateration** (three distance circles, two unknowns) for (x, z) and converts to (r, θ). Three
     references make the solution **unique** — there is no mirror/two-fold ambiguity to resolve and no
     downrange-side prompt. Rationale unchanged: tape readings at ±5 mm beat tape+protractor — 1° of
     protractor error is ~2.6 cm cross-range at r = 1.5 m.
     **(v2.3 G1, replaces F-9):** if the three references are near-collinear (degenerate geometry),
     the normal-matrix **condition number** exceeds `ground_truth.cond_warn` → emit a clear **warning**
     and flag the throw (no NaNs, no hard abort — the LS solve still returns its best estimate). The LS
     **residual** (circle-agreement misfit) is stored as an integrity guard: a residual above
     `ground_truth.residual_warn_m` signals a mis-measured tape or a mislogged sensor.
  3. Prompts: the recommended pair is shown for confirmation (e.g.
     `recommend S2,S3 — accept / override [combination]:`), then `L_centroid [m]:`, `L_<first> [m]:`,
     `L_<second> [m]:` (empty input = skip; ground truth can be added later with
     `scripts/append_ground_truth.py` or the web late-entry mode, §12.3). **Record which two sensors
     were solved on** in `session.json`. Propagate `ground_truth.sigma_tape_m` through the LS Jacobian
     to per-throw (σ_x_actual, σ_z_actual), stored in session.json alongside the residual and
     condition-number flag.
- Ctrl-C anywhere: flush logs, write what exists, exit cleanly.

### 5.6 Session directory layout (one per throw)
```
data/sessions/<session_id>/      # live: data/sessions/2026-06-11_T01
                                 # demo: data/sessions/demo/sim_2026-06-12_143052_S03 (D4, D5)
├── raw_serial.log          # verbatim serial capture
├── background.json         # per-sensor μ, σ, w, f0, n_valid, enabled flag, k, d_max
├── triplets_raw.csv        # assembled triplets: t_trig & t_sample per reading + flags
├── trajectory.csv          # per-triplet: t_sample, raw (x,y,z), Kalman (x,y,z),
│                           #   per-triplet sigma_y, height-consistency residual (R10a)
├── session.json            # metadata: timestamp, temperature, config snapshot, fw header,
│                           #   prediction raw & corrected (r,θ) + (σ_r,σ_θ) (R7), cov_xz_m2,
│                           #   model id/None, ground truth (r,θ) + sigmas + raw tape readings
│                           #   + sensors-used + LS residual + cond-number flag (R8, v2.3 G1),
│                           #   n_triplets total/valid/used, gate summary
├── plots/
└── report.html             # (v2.3 W1) per-throw HTML report: input-mode -> frozen after
                            #   ground truth; fully self-contained. See §12.1.
```
**(W1 + D5) Campaign pages — two, never mixed.** A campaign page sits at the **root of each subtree**,
NOT inside any session:
- `data/sessions/campaign.html` — the **live** campaign (real throws only).
- `data/sessions/demo/campaign.html` — the **demo** campaign (synthetic throws only).
Each is regenerated from scratch after every throw and every ground-truth entry in its own subtree
(never frozen). The builders enumerate sessions by the **session-detection predicate** — a directory
is a session **iff it contains `session.json`** (§12.2) — so the live builder, scanning
`data/sessions/`, sees the `demo/` container, finds no top-level `session.json`, and **skips it
automatically**. No name-matching is involved.
**(D4) Synthetic session naming.** `simulate_session.py` names directories from
`simulator.session_name_scheme` → `sim_YYYY-MM-DD_HHMMSS_S##` and writes them under
`data/sessions/<sessions.demo_subdir>/` (D5). The HHMMSS timestamp prevents same-day re-runs from
overwriting; the `S##` batch counter prevents the sessions of a single `--n-sessions N` run (all
created in the same second) from overwriting each other.

### 5.7 Modes of `run_session.py`
- default: full one-throw session. Background cal, then the throw; post-CLOSING processing is
  delegated to `process_throw.process_session` (§8.8) — `run_session.py` does NOT re-implement
  the chain. If `correction_model.json` exists it is loaded and the corrected (r, θ) is reported
  alongside raw; `--no-correction` forces raw.
- `--web`: **(v2.3 W1)** additive. After the throw and `process_session`, render the per-throw
  `report.html` (input mode), regenerate `campaign.html`, start the local server (§12.3), open the
  browser, and enter ground truth **there** instead of at the terminal prompt; block (no timeout)
  until submit or skip; then finalize and regenerate the campaign page. Without `--web`, behaviour is
  exactly the terminal `prompt_ground_truth` flow (default + fallback). A skipped/closed session is a
  normal "awaiting ground truth" session, completable later (§12.3). **(D5)** The regenerated page is
  the **live** campaign `data/sessions/campaign.html`; the `demo/` subtree is skipped by the
  session-detection predicate (§12.2), so real and demo throws never co-mingle.
- `--raw-log`: no state machine, no gating — stream and log until Ctrl-C (used by §7).
- `--background-only`: background cal, print/persist, exit. **(A2)** If
  `acquisition.ceiling_height_m` is set, also compute and print, per sensor, the expected
  ceiling wrap-around apparent range: slant to ceiling along the 55° beam → round-trip time →
  subtract one slot (18 ms) → apparent range; flag any that fall inside [0.5 m, d_max] so the
  operator can confirm the static ghost is being captured by the band rule (or reposition).
- `--no-background` **[v2.7, BUILT]**: additive, combinable with the default/`--web` modes. Skips
  the ~11 s background-calibration wait and writes an all-bands-disabled `background.json`
  directly (`background.disabled_background`) instead — behaviourally identical to a real
  open-air calibration (§5.3's R1 gate-enable logic already disables the band rule when
  `f0 > bg_timeout_skip`), just without the wait. An open-ground convenience only: NOT safe when a
  static reflector (wall/ceiling) is in view, since those readings would then be treated as
  signal. The disabled background is still persisted so offline `process_session` LOADS it rather
  than recalibrating from a log that has no background padding at its head.
- `--no-offset-correction` **[v2.7, BUILT]**: disables the §2 `acquisition.sensor_offset_m`
  per-sensor correction (applied by default). Independent of `--no-background` and
  `--background-only`.

---

## 6. Simulator (`simulator.py`, `simulate_session.py`) — BUILD EARLY

Generates, for a specified throw:
1. **True trajectory:** drag-free projectile from (x₀, y₀, z₀, vx, vy, vz); optional
   quadratic-drag RK4 integrator (configurable coefficient) for testing `bias.py`. A
   **drag-coefficient multiplier** (the §6 testing knob) inflates drag so the bias gate has
   statistical power on small synthetic sets (see §9).
2. **Sensor sampling at the physically correct instants (R3):** the simulator must solve the
   implicit timing — the range sampled by sensor i in triplet n corresponds to the ball's
   position at `t = t_trig + d/v_sound` (one-way). Implement by fixed-point iteration
   (2–3 iterations converge). This makes the simulator the ground truth against which the
   pipeline's `t_sample = t_trig + echo/2` correction is validated.
3. **(D2) Beam-cone visibility model.** When `simulator.beam_cone_enabled` is true, a sensor
   detects the ball in triplet n ONLY if the ball lies within `beam_half_angle_deg` of that
   sensor's aim axis (the 55°-elevation inward-pointing direction from the vertex). Outside the
   cone → that reading is a timeout (echo_us = 0), exactly as real hardware would behave. This
   makes synthetic throws yield the realistic ~5–6 flight triplets instead of the ~20–22 that
   the unconstrained d_max+background gates produce. `beam_cone_enabled: false` reproduces the
   legacy over-producing behaviour for A/B comparison. **`beam_half_angle_deg` is an estimate —
   tune it against the §7 static detectability data before trusting absolute triplet counts.**
4. **Measurement corruption:** ranges are to the ball **surface** (subtract `ball.radius_m`
   — R2 — so the pipeline's +radius correction is exercised); add zero-mean Gaussian noise;
   convert to echo_us with the configured temperature so synthetic data enters at the SAME
   raw format as hardware data; inject background readings/timeouts before/after the throw;
   optional mid-throw dropouts (exercise variable-dt Kalman); sensors at `S_height_m` (R4).
5. **Output:** complete synthetic session directory (§5.6 format, named per D4), written under
   `data/sessions/<sessions.demo_subdir>/` (v2.4 D5, default `demo/`), with TRUE landing recorded, so
   the whole offline pipeline runs unchanged.
6. **(D5) Demo campaign auto-regen.** At the end of a `simulate_session.py` batch, the **demo**
   campaign `data/sessions/<demo_subdir>/campaign.html` is regenerated by calling
   `web_report.render_campaign_report` pointed at the demo root — the same renderer the live path uses,
   pointed at a different root. The demo campaign therefore contains demo throws only (the predicate,
   §12.2). This is automatic (no flag needed), mirroring the live campaign behaviour.

`simulate_session.py` CLI: `--n-sessions`, `--speed-range`, `--heading-range-deg`
(default spread ±60° about +x — the throw-aligned bias model must be tested against direction
diversity), `--noise-mm`, `--drag {none,quadratic}`,
`--beam-cone {on,off}` (overrides config), `--seed`, `--demo-subdir` (overrides
`sessions.demo_subdir` for this run), `--no-plot` (skip processing/plots; by DEFAULT each session
is processed and gets `plots/` + `report.html`, the §5.6 layout).
**There is NO `--drag-mult` CLI flag:** the drag-coefficient testing multiplier is applied in TEST
code only (`test_bias.py` ×3, `test_end_to_end_synthetic.py` ×5, §9), never on the CLI, so an
artificial multiplier can never leak into demo or campaign data.

---

## 7. Static characterization (`characterize_static.py`)

Wraps `--raw-log`. Operator places a stationary target at a tape-measured distance.
**(R2) Tape convention: the recorded distance is sensor face to the target's CENTRE.** For the
ball: tape to the nearest surface point, then ADD `ball.radius_m`, and record both numbers.
For the flat board: tape to the board face (no radius). This keeps the extracted per-sensor
offset purely electronic/acoustic, uncontaminated by the surface-vs-centre geometry.

Collect ≥ 200 readings; report per sensor: mean, σ (ddof=1), offset = mean − reference,
timeout fraction. Protocol: flat board first (proves electronics), then the **basketball
[AMENDED v2.6 — D6]** on a
stand at ≈ 1.0 / 1.3 / 1.7 m (proves the realistic target is detectable). **History (D6): the
board sweep PASSED at 1.0 m; the tennis ball returned persistent timeouts at 1.0 m on-axis —
target substituted per A5 with Prof. Zappa's approval; the ball sweep must be re-run in full
with the basketball.** The tape-to-CENTRE convention is unchanged (tape to nearest surface
point + `ball.radius_m`; the added radius is now ~0.121 m, so record both numbers with extra
care). Outputs feed
`kalman.sigma_pos_m`, the report's error budget, the decision on a per-sensor constant offset
subtraction (if |offset| ≫ σ/√N, subtract at acquisition — measurement-layer correction,
deliberately OUTSIDE `bias.py`), **and the empirical tuning of `simulator.beam_half_angle_deg`
(D2): the angle/range at which timeout fraction climbs bounds the real detection cone.**

---

## 8. Offline processing core

Computational modules are pure functions, no I/O, unit-tested (§0.5). The I/O orchestrator is
§8.8.

### 8.1 `geometry.py`
- Vertices from config: horizontal (x, z) + common `S_height_m` → full 3D vertex coordinates
  (X_i, h, Z_i). Build the trilateration matrix A and offsets once (general A⁻¹b form).
- `polar_to_cart` / `cart_to_polar`; **(v2.3 G1)** `ground_truth_landing` — least-squares
  **multilateration** over the **centroid + two chosen sensor** floor references (config
  `array.*_xz`), with uncertainty propagation from `sigma_tape_m` through the LS Jacobian. Returns
  (x, z), per-axis σ, the **LS residual**, and the reference **condition number**. Unique solution →
  no mirror branch, no downrange-side argument.
- **(v2.3 G1, replaces the v2.2 F-9 *tangent-circle ground-truth* case — the landing-fit concavity
  F-9 in §8.5 is unaffected)** near-collinear references no longer raise: `ground_truth_landing`
  flags a **condition-number warning** above `ground_truth.cond_warn` and still returns the best LS
  fit; the caller records the flag + residual in `session.json`.
- `recommend_reference_sensors(landing_xz, config) -> (sensor_a, sensor_b)` returns the two sensors
  nearest the predicted landing (default tape references; used by terminal, web, and
  `append_ground_truth.py`).
- The non-interactive solve core is `solve_ground_truth(L_centroid, L_sensor_a, L_sensor_b,
  sensors, config) -> gt_block`, shared by the terminal prompt, `append_ground_truth.py`, and the web
  handler (§12.3/§12.4) so the three paths cannot diverge.
- Tests: round-trips; θ convention (point on +x → 0°, on +z → +90°, on −x → +180° not −180°);
  multilateration solver (exact recovery on synthetic, residual ≈ 0 on consistent tapes, residual
  grows with an injected tape error, condition-number flag fires on collinear references, **no NaNs**
  in the degenerate case); `recommend_reference_sensors` picks the correct nearest pair; uncertainty
  vs a Monte-Carlo reference (agree within ~5%, scales linearly with σ_tape).

### 8.2 `corrections.py`
**(a) Temperature:** `echo_us_to_m(echo_us, T_celsius)`. `speed_of_sound()` is defined here
(canonical home, F-3); `mid_echo_sample_time_us()` likewise.
**(b) Ball-radius (R2):** `d_centre = d_raw + ball.radius_m`, applied to every valid reading
immediately after (a) and BEFORE the temporal correction and trilateration. (Exact for a
sphere: the nearest surface point lies on the sensor–centre line.)
**(c) Temporal correction (Option A, per-sensor) — HYBRID stencil (D1):** estimate each
sensor's radial range-rate from same-sensor consecutive readings on **t_sample** timestamps
(R3), then extrapolate d2, d3 back to the triplet's S1 t_sample instant. The velocity stencil
depends on `corrections.central_difference`:
  - **`true` (production default, hybrid):**
    - first triplet (n = 0): forward difference `(d[1] − d[0])/(t[1] − t[0])`;
    - interior triplets: central difference `(d[n+1] − d[n−1])/(t[n+1] − t[n−1])`;
    - last triplet (n = N−1): backward difference `(d[n] − d[n−1])/(t[n] − t[n−1])`.
    **All N triplets are retained.** (Legacy forward mode kept only N−1.) Central differences
    cancel the leading curvature-bias term on interior triplets; the two endpoints keep the
    first-order forward/backward estimate. Net along-track landing systematic ~−12 to −15 mm
    (vs ~−24 mm forward, ~−10 mm impossible-pure-central which would drop both endpoints).
  - **`false` (legacy forward):** forward difference everywhere; the last triplet has no
    successor → flagged unusable (N−1 retained), ~−24 mm systematic.
  - **NaN safety (both modes):** if a needed neighbour is a timeout/invalid (NaN), that triplet
    falls back to the one-sided difference it can still form (forward or backward); if neither
    is available, it is flagged unusable. Never produce NaN velocity from a single valid point.
**(c′) Curvature residual — characterized, not assumed away (A4):** the radial distance d(t)
is curved (max curvature at closest approach, d̈ ≈ v⊥²/d). Provide `temporal_residual_vs_speed()`
that, on noise-free simulator data, reports the residual across transverse speeds and stencils
for the report's error budget. Worst case (forward, 4 m/s transverse, d = 1 m): ~1–2 cm per
reading; bounded, does NOT trip the NaN guard at y ≳ 0.5 m. Hybrid lowers the interior residual.
**Tests (rewritten v2.2, F-4):**
- **Accuracy is split** (the old "<1 mm on simulator data" headline is physically impossible on
  a curved arc): on **constant-range-rate (linear) data**, where Option A's model is exact, the
  corrected ranges match truth to **<1e−6 m** (satisfies "<1 mm"); on **simulator arcs** the
  test asserts the curvature-bounded residual **<3 cm** AND that the correction **halves** the
  error vs leaving ranges unaligned.
- **R2 negative control:** without `add_ball_radius`, mean range bias ≈ **`ball.radius_m`**
  (**~119 mm** for the basketball, measured r = 0.1194 m; the historical 33.5 mm figure was the
  tennis ball) — asserts R2 bites. **[AMENDED v2.6 — D6]** The test derives the expected bias
  from config (`radius` fixture), never a hardcoded radius (audit item, CHANGES.md D6).
- **R3 negative control (unit-level, load-bearing):** on **linear-range** data, max error
  **~1e−16 m** with mid-echo vs **~15.6 mm** without — ~1e13× inflation in the isolating regime.
  (R3's end-to-end effect is below the noise floor; see §9.)
- **(D1) hybrid-stencil tests (new — see CHANGES.md):** stencil-selection correctness on linear
  data (all three stencils exact); **all N triplets retained** in hybrid vs N−1 in forward;
  NaN-fallback to one-sided differences; `temporal_residual_vs_speed` interior residual lower in
  hybrid than forward at every tested speed.

### 8.3 `trilateration.py`
- Vertices at (X_i, h, Z_i), h = `S_height_m` (R4). Sphere subtraction (S1 from S2, S3):
  with **equal heights the h-terms cancel exactly** and the 2×2 system in (x, z) is unchanged.
  **This is an assumption, surveyed in Phase 2 (±3 mm), and stated in the report; unequal
  heights would leave residual linear-y terms and invalidate the 2×2 reduction.**
- Solve A·[x; z] = b (general inverse; A is constant and well-conditioned for an equilateral
  array). Height (R10a): compute the radicand from **all three** spheres,
  `y_k = sqrt(d_k² − (x−X_k)² − (z−Z_k)²)`, k = 1,2,3 (heights above the SENSOR plane); if ANY
  radicand < 0 → NaN guard: flag and discard the triplet (never clamp, never abs()).
  Else `y_plane = mean(y_1, y_2, y_3)`.
- **Consistency residual `q` (reconciled v2.2, F-5):** `q = max_k |y_k − y_plane|` is computed
  and stored per triplet for schema compatibility and as a **numerical sanity check only**.
  **It is identically zero (≈1e−16) by construction for a 3-sensor triplet:** the 2×2 solve *is*
  the pair of equations "radicand₁ = radicand₂" and "radicand₁ = radicand₃", so the solved
  (x, z) forces all three y_k equal for ANY input ranges — `q` does NOT grow with noise (three
  ranges, three unknowns, zero redundancy). A genuine per-triplet consistency residual would
  require a **4th sensor** (documented as future work). Do not use `q` as a noise-driven quality
  gate; the working gates are the NaN guard and the §5.4 validity flags.
- Floor-frame height: `y_floor = y_plane + S_height_m` (R4). All downstream stages operate in
  floor-frame y.
- **Per-triplet vertical noise (R6):** `sigma_y = (d_mean / y_plane) * sigma_pos_m`. It grows
  toward the overlap floor but only **~1.41×** between y = 1.5 m and y ≈ 0.55 m (not ~2.7×),
  because d_mean grows with y as well (documented; F-cosmetic). The y→0 divergence is never
  visited (overlap floor keeps y_plane ≳ 0.5 m).
- Tests: noise-free simulator → true positions to < 1e−9 m; **R4 negative control** — simulator
  sensors at h = 0.045 m with pipeline `S_height_m = 0` → recovered y_floor wrong by exactly
  0.045 m (asserted; (x,z) stay exact); NaN guard flags impossible triplets without touching
  neighbours; σ = 5 mm noise → horizontal RMS in the GDOP ≈ 2.3 band; **`q` pinned at ≈0 even
  under 8 mm noise and on arbitrary non-physical range triples** (asserts the algebraic fact).

### 8.4 `kalman.py`
- `filterpy.KalmanFilter`, 7-state [x, y, z, vx, vy, vz, 1]ᵀ, floor-frame y.
- **F rebuilt every predict step from the measured Δt of t_sample (R3)** between consecutive
  USED triplets (rejections create ~108/162 ms gaps):
  ```
  F(dt) = [[1,0,0,dt,0,0, 0           ],
           [0,1,0,0,dt,0, -0.5*g*dt**2],
           [0,0,1,0,0,dt, 0           ],
           [0,0,0,1,0,0,  0           ],
           [0,0,0,0,1,0,  -g*dt       ],
           [0,0,0,0,0,1,  0           ],
           [0,0,0,0,0,0,  1           ]]
  ```
  g = 9.81. **The 7th (bias) state encodes gravity ONLY. Never modify F or the bias state to
  absorb drag or anything else.**
- H selects [x, y, z]. **(R6)** If `hetero_R`: per-update
  `R = diag(σ_pos², σ_y(triplet)², σ_pos²)`; else `R = diag(σ_pos²)·I₃`. The neglected
  x–y–z cross-correlation is a documented simplification (report sentence).
- Q small (q_scale); 7th-state process noise 0, initial variance ~0.
- Init: first used triplet sets position; velocity from first forward difference; generous
  initial velocity P.
- Tests: filtered RMS < raw RMS on noisy simulator data (asserted < 0.95×); velocities within
  tolerance; **variable-dt negative control** — a gate-style rejection produces a ~108 ms gap
  the filter crosses (≈2 mm y-error), while falsified uniform timestamps on the same positions
  jump the gap y-error ~8× (proves F uses the measured Δt); simulator dropout gives the ~162 ms
  variant; bias state stays 1 to <1e−11; hetero_R on/off both run.

### 8.5 `landing.py`
- **Time-parameterized fit chosen (spec-sanctioned variant, v2.2):** x(t), z(t) degree-1;
  y(t) degree-2; solve y(t*) = `ball.radius_m` on the descending branch; landing =
  (x(t*), z(t*)). Chosen over x-parameterization because the ±60° heading spread shrinks the
  x-span (ill-conditioned for steep throws) while t advances monotonically; gravity makes y(t)
  genuinely quadratic. Require ≥ `min_fit_points` (=4).
- **(R7) Per-throw prediction uncertainty:** compute the polyfit coefficient covariance
  **`(RSS/dof)·(VᵀV)⁻¹` by hand (v2.2, F-6)** — `numpy.polyfit(..., cov=True)` refuses dof<3,
  which excludes the legal `min_fit_points = 4` (dof = 1) case the R7 caveat is specifically
  about. Propagate through t* (delta method) to a 2×2 landing covariance `cov_xz_m2` →
  (σ_r, σ_θ) at the predicted point. Log σ_r [m], σ_θ [deg], and `cov_xz_m2` in session.json.
  **Small-sample caveat (mandatory in report; returned as a `caveat` STRING field — pipeline
  has no I/O, so `run_session.py` prints it once per session, F-6):** with 4–6 points and 3
  parameters the covariance rests on 1–3 dof and is itself highly uncertain; treat the ellipse
  as indicative.
- **(v2.2 clean-failure, F-9):** a flat/rising y(t) fit (not concave-down, curvature ≈ 0) would
  produce an absurd far-future root → raise a clear `ValueError` (concave-down guard).
- Export heading φ = atan2(mean vz, mean vx) and v_h = √(vx²+vz²) from Kalman states for
  `bias.py`.
- Tests: simulator truth recovered within tolerance (mean ~21 mm); y = r_ball vs y = 0 shifts
  the landing by ≈ v_h·r_ball/|v_y,impact| (~2% agreement); (R7) the 1-σ ellipse covers the true
  landing at a rate consistent with its nominal level over many synthetic throws (loose
  tolerance per the small-sample caveat); degenerate/non-concave input rejected cleanly; M = 4
  (dof = 1) still predicts.

### 8.6 `bias.py` — throw-aligned drag correction
Implements the agreed amendment: **residuals are calibrated in a per-throw track-aligned frame**
(throws are spread in heading; drag overshoot rotates with heading, so fixed-axis averaging
cancels real bias).
- Per calibration throw: heading φ; residual (r_x, r_z) = (x_pred − x_actual, z_pred − z_actual);
  rotate to track frame: r_along = r_x·cosφ + r_z·sinφ, r_cross = −r_x·sinφ + r_z·cosφ.
  Expect mean r_along > 0, mean r_cross ≈ 0.
- Scalar mode: mean, std (ddof=1), SEM, 95% CI via `scipy.stats.t.ppf` (never hardcode 1.96)
  per track axis; **significance gate:** correction nonzero only if the CI excludes 0.
  Linear mode (optional): regress r_along on v_h; accept only if slope p < alpha AND scatter
  reduces vs scalar.
- Application: build track-frame offsets, rotate back by the NEW throw's φ, subtract in
  Cartesian, then convert to (r, θ).
- `CorrectionModel` dataclass (spec fields + `frame: "track"`), JSON persistence (cast numpy
  scalars to `float`/`bool` — not JSON-serializable otherwise), full diagnostics.
- Validation (mandatory): **`calibrate_with_validation` defaults to scalar-only** (a 6-throw
  linear candidate overfits the held-out half; linear is opt-in, F-8). Strict disjoint
  calibrate/validate split or k-fold; before/after mean 2D Euclidean error with CIs (also
  reporting the §5.5 ground-truth uncertainty in the error budget — R8); accept only on
  significant improvement, else mode = 'none'. **Never calibrate and validate on the same
  throws. Never import or touch the Kalman filter** (enforced structurally by a test inspecting
  bias.py's import lines).
- **Reframed drag-OFF gate (v2.2, F-8):** "drag-OFF ⇒ mode='none'" means **"no *statistically
  resolvable* throw-aligned bias at the tested N ⇒ 'none'."** The pipeline carries its own small
  along-track systematic from the temporal-correction curvature residual (~−10 mm hybrid /
  ~−24 mm forward); on enough drag-free throws (n ≳ 30) the gate will correctly detect THAT
  systematic. This is recorded in the §11 error budget.
- Tests: drag-ON simulator with ±60° headings → track-aligned model finds significant positive
  r_along and validation error decreases; SAME data in the fixed array frame (test-only path)
  recovers a weaker/partially-cancelled bias (E[cosφ] ≈ 0.83 at ±60°) and corrects worse —
  asserts the design rationale; **two honest drag-OFF tests (F-8):** pure zero-mean-noise records
  → 'none' (true null control), and pipeline drag-free records → small negative scalar detected
  (the self-systematic).

### 8.7 `calibrate_bias.py` and `analyze_campaign.py`
- `calibrate_bias.py --sessions data/sessions/*`: load sessions having BOTH prediction and
  ground truth; estimate, validate, write `correction_model.json` + calibration report
  (N, per-axis stats, gate outcomes, before/after errors, ground-truth uncertainty
  contribution). Warn below `min_throws`. **(D3) also print the power note**: given measured
  scatter and bias, the N at which the CI is expected to exclude zero, so a null result is
  read as physics, not as too-few-throws.
- `analyze_campaign.py`: campaign statistics — mean/std/95% CI of 2D landing error (raw and
  corrected), triplets-per-throw histogram, raw-vs-Kalman comparison, error vs n-triplets,
  error vs heading (symmetric-corridor check), predicted-vs-actual scatter with per-throw
  σ ellipses (R7), all saved as figures.
- **(v2.4 D5) Session-detection predicate, shared.** `analyze_campaign.load_campaign`,
  `web_report.build_campaign_data`, and the `calibrate_bias` per-path loader all enumerate sessions
  via `is_session_dir(p) = p.is_dir() and (p / "session.json").exists()`, skipping non-sessions
  silently (printed reason). Consequences: a sibling `demo/` container or a stray `campaign.html` is
  ignored, so `analyze_campaign.py --sessions data\sessions\*` and `calibrate_bias.py --sessions
  data\sessions\*` aggregate **live** sessions only; point them at `data\sessions\demo\*` for the
  demo set. This **supersedes** the v2.2 §VV-1 "directories-only" filter (a directory alone is no
  longer sufficient) and intentionally lifts the Part-6 "do not modify `analyze_campaign.py`" stance,
  scoped to this one guard.

### 8.8 `process_throw.py` — offline orchestrator (I/O layer, v2.2)
**This module fixes the §10 build-order circular dependency** (the acceptance gate needed the
post-CLOSING chain, which was implicitly inside `run_session.py` two build-steps later).
- `process_session(session_dir, config, *, model=None, _negative_control=None) -> ProcessedSession`
  runs the full post-CLOSING chain on a session directory: parse `raw_serial.log` → background
  calibrate/load → §5.4 gate → `segment_throw` → corrections → trilateration → Kalman → landing
  → optional bias; writes `background.json`, `triplets_raw.csv`, `trajectory.csv`, updates
  `session.json` (incl. `cov_xz_m2`, R7).
- Pure parse helpers reused by the future `acquisition.py`: `parse_serial_lines`,
  `unwrap_micros` (R10c, incl. double rollover), `assemble_triplets`.
- **This module and `scripts/` are the ONLY places that touch the filesystem** (§0.5). The
  pure pipeline modules it calls stay I/O-free.
- `_negative_control` takes a value from `NEGATIVE_CONTROLS` (e.g. radius-off, height-off,
  mid-echo-off) so the §9 gate can disable one correction at a time; unknown values are rejected.
- Tests (`test_process_throw.py`): micros() rollover unwrap incl. double rollover (R10c);
  malformed-line resync; header-mismatch warning; round-trip on a simulator-written session dir
  (files + schema + accuracy < 80 mm); R5 arming in `in_throw`; background-only session →
  "no throw" `ValueError`; unknown-control rejection.

---

## 9. End-to-end synthetic acceptance test (`test_end_to_end_synthetic.py`)

Must pass before any hardware session is trusted. Uses `tests/session_factory.py` to write
session dirs in the simulator's on-disk format, and runs them through
`process_throw.process_session` (the same code path as post-CLOSING in `run_session.py`).

1. Generate 12 drag-ON + 12 drag-OFF synthetic sessions (spread headings ±60°, σ = 8 mm,
   sensors at h = 0.045 m, surface-ranging on, mid-echo on, 1–2 random dropouts each, background
   padding incl. a timeout-dominated background in ≥1 session). **Drag-ON uses a ×5
   drag-coefficient testing knob (applied in the test, not a CLI flag; §6):** with the *realistic* drag coefficient the along-track
   bias (~8 mm) is far below the ~20 mm scatter and 12 sessions cannot reach significance (the
   §11 R9 power estimate needs ~30); ×5 gives the 12-session gate power (accepts at p ≈ 0.004).
2. Assert every session segments to exactly one throw (arming triplets included — R5); both R1
   background regimes present.
3. **Negative controls (amended v2.2, F-4)** — run on the **drag-OFF** set (drag-ON's deliberate
   overshoot masks the effects):
   - **R2 (ball-radius) OFF → the end-to-end test MUST FAIL** (mean landing error rises to
     ~80 mm at the tennis radius; **[MEASURED v2.6/D6] ~160 mm at the basketball radius
     r = 0.1194 m — drag-OFF baseline 34.5 mm → 159.6 mm (max 197 mm), the ~119 mm
     surface→centre correction dominating**). Asserted against a config-derived threshold, not
     a hardcoded millimetre figure. **Under D6, R2 is the sole load-bearing e2e must-fail
     control (see R4).**
   - **R4 (sensor-height) OFF → [AMENDED v2.6/D6] NO LONGER an e2e must-fail — pinned instead.**
     At the tennis radius it failed (~65 mm); at the basketball radius the y = `ball.radius_m`
     contact height rose from ~33.5 mm to ~119 mm, so the omitted 45 mm sensor-height offset
     maps to only ~4 mm of landing error (measured drag-OFF 34.5 mm → 38.6 mm) — below the e2e
     floor and inseparable from baseline by any `MEAN_TOLERANCE`. It is therefore pinned as a
     small below-floor delta (like R3), and R4 correctness is guarded by the radius-independent
     UNIT control in `test_trilateration.py` (recovered y_floor wrong by exactly `S_height_m`).
     Measured, not assumed.
   - **R3 (mid-echo) is verified at UNIT level (§8.2), NOT here:** disabling it changes the
     landing by ~0.1 mm (the per-reading error averages out in the fit and is swamped by the
     curvature residual). The e2e R3 variant therefore asserts **|Δ| < 5 mm (below noise floor)**,
     not a failure physics does not produce. R3 is kept because it is exact and free.
4. `calibrate_bias.py` over the 12 drag-ON sessions produces a significant along-track model
   (scalar track frame; CI excludes 0); corrected validation error < raw; per-throw σ ellipses
   have sane R7 coverage.
5. Drag-OFF set: gate returns mode='none' at n = 12 (the pipeline self-systematic is below
   detection power at this N — see §8.6, §11).

**(D1 re-validation, see CHANGES.md):** the production default is now the **hybrid** stencil.
The gate must be re-run and must still satisfy step 5 (drag-OFF → 'none' at n = 12) under hybrid
mode; the hybrid self-systematic (~−12 to −15 mm) must remain below detection power at n = 12.
If it does not, lower n or document the resolvable systematic explicitly — do NOT silence the
gate.

**(D2 data-density check, see CHANGES.md):** with `beam_cone_enabled: true` the synthetic throws
must still yield ≥ `min_fit_points` usable triplets after the hybrid correction; assert the
realistic regime (~5–6 triplets) clears the fit, or fails cleanly with the actionable message.

---

## 10. Development order (build and validate in THIS sequence)

Renumbered (v2.2) to remove the circular dependency: `background.py`, `segmentation.py`, and the
offline orchestrator `process_throw.py` now precede the acceptance gate. Each item lists deps.

```
SOFTWARE (no hardware; validated against the simulator)
 1. Repo scaffold, config.yaml, geometry.py + tests.                deps: none.
 2. simulator.py + simulate_session.py (incl. beam-cone D2,         deps: geometry.
    session naming D4).
 3. corrections.py + tests (incl. hybrid stencil D1).               deps: geometry, simulator.
 4. trilateration.py + tests.                                       deps: 1–3.
 5. kalman.py + tests.                                              deps: 1–4.
 6. landing.py (incl. R7 uncertainty) + tests.                      deps: 1–5.
 7. bias.py + tests, then calibrate_bias.py.                        deps: 1–6, geometry.
 8. background.py + tests.                          [was unscheduled] deps: corrections, config.
 9. segmentation.py + tests.                        [was unscheduled] deps: config.
10. process_throw.py (offline orchestrator) + tests.   [NEW MODULE]  deps: 1–9. This IS the
    "post-CLOSING code path" §9 refers to: process_session(session_dir, config).
11. test_end_to_end_synthetic.py (acceptance gate, §9) green,                deps: 1–10 +
    incl. negative controls + D1 re-validation + D2 data-density check.      calibrate_bias.py.
HARDWARE
12. Firmware sketches 01→05 on the bench (each gated; 05 via verify_timing.py).
13. acquisition.py + run_session.py; dry-run. run_session.py REUSES
    process_throw.process_session (post-CLOSING) and segmentation.ThrowDetector (live machine) —
    do NOT re-implement either.
14. characterize_static.py on hardware; update kalman.sigma_pos_m; survey S_height_m + vertices;
    tune simulator.beam_half_angle_deg (D2) against measured detectability.
15. Real campaign (§11) → calibrate_bias.py → corrected sessions → analyze_campaign.py.

REPORTING & GROUND-TRUTH REVISION (software; validated against the simulator)
16. **(W1, BUILT)** web_report.py renderers + serve_report.py + run_session.py --web + tests
    (per-throw report.html, campaign.html, atomic write-back, late entry).   deps: process_throw,
    reporting, analyze_campaign, geometry. See §12.
17. **(G1, BUILT — see IMPLEMENTATION_NOTES Part 9)** geometry.ground_truth_landing ->
    multilateration over centroid + 2 chosen sensors; recommend_reference_sensors; condition-number
    flag + LS residual; the terminal prompt, append_ground_truth.py, AND the web GT panel/solve all
    migrated onto the shared solve_ground_truth.                               deps: geometry,
    landing. See §5.5, §8.1, §12.4.
18. **(D5, BUILT — see IMPLEMENTATION_NOTES Part 10)** `sessions.demo_subdir` config + write synthetic dirs under the demo subtree in
    simulate_session.py + shared `is_session_dir` predicate in web_report / analyze_campaign /
    calibrate_bias + auto demo-campaign regen + one-time migration of the existing synthetic dirs into
    data/sessions/demo/. See CHANGES.md (D5), §2, §5.6, §6, §8.7, §12.2.       deps: web_report,
    analyze_campaign, simulator.
```

---

## 11. Campaign planning and known risks (surface loudly, never absorb silently)

- **(R9, D3) Throw count.** `min_throws = 8` is the code's hard floor, NOT the plan. Measured
  realistic **tennis-ball** along-track drag bias at 3–4 m/s is **~8 mm** against **~20 mm** landing
  scatter, so the 95% CI excludes zero only around **N ≳ 30** (before the calibrate/validate
  split). **[RE-ESTIMATED v2.6/D6 Stage 4 — measured, approximate]** With the measured
  m = 0.620 kg, r = 0.1194 m, Cd ≈ 0.47, the drag *force* is essentially unchanged
  (a_drag = ρ·Cd·π·r²·v²/2m ≈ 0.19–0.33 m/s² over 3–4 m/s, +1% vs tennis: the ~18% higher A/m,
  ~0.072 vs ~0.061 m²/kg, is cancelled by the lower Cd). But the *pipeline along-track prediction
  bias* measured **~15–18 mm** (sim, unscaled drag, 3–4 m/s, cone-off) — roughly **2× the tennis
  ~8 mm**, because the higher y = `ball.radius_m` ≈ 119 mm contact height amplifies the
  parabola-extrapolation overshoot (not a drag-force effect). This is the **detection-favorable**
  direction (a larger bias is easier to resolve), so it needs **no increase** in throw count.
  **Plan UNCHANGED** (see D6 register, IMPLEMENTATION_NOTES Part 14): the real campaign's fewer
  triplets (cone-on ~5–6) raise scatter, so keeping 15–20 (→30) is the safe call.
  **Plan 15–20 ground-truthed throws; extend to 30 if time permits.** A null result at
  15–20 is then interpretable as physics ("drag below noise floor"), not insufficient data. The
  acceptance gate reaches significance at N = 12 only because it uses the ×5 drag-coefficient
  testing knob (§9); the real campaign has no such knob. Vary heading deliberately (±60° about
  +x, off the triangle's symmetry axes). **Interaction with D2:** the beam-cone model means real
  throws give only ~5–6 triplets, so per-throw landing scatter is at the higher end of the
  estimate — another reason 30 throws is the safer target if drag detection is a goal.
  **(D6 mitigation)** the basketball's larger subtended angle should widen the effective cone
  and raise triplets/throw; quantify via the re-run §7 sweep before re-planning N.
- **Pipeline self-systematic (v2.2 error budget, F-8).** The temporal-correction curvature
  residual propagates to a small along-track landing bias: **~−24 mm forward / ~−12 to −15 mm
  hybrid (production)**. It is below the per-throw scatter but is real; it both erodes the drag
  signal and can make a drag-OFF bias gate legitimately fire at large N. Report it in the error
  budget; it is NOT removed by the gravity-only Kalman F.
- **Few triplets per throw.** At 3–4 m/s the ball crosses the overlap column in ~250–330 ms
  ≈ 5–6 triplets. With the **hybrid** stencil all are retained (forward mode lost the last);
  `run_session.py` prints n_triplets used and refuses the fit below `min_fit_points` with an
  actionable message ("throw slower/loftier"). The simulator's beam-cone model (D2) reproduces
  this density so the acceptance gate is representative.
- **Ball detectability at range — RESOLVED via A5 (v2.6, D6).** The §7 test ran: flat board
  PASSED at 1.0 m; the tennis ball produced persistent timeouts at 1.0 m on-axis. Per A5 the
  substitution was escalated (NOT silently swapped) and **Prof. Zappa approved the basketball**.
  Residual obligation: re-run the full §7 ball sweep (1.0 / 1.3 / 1.7 m + angle sweep) with the
  basketball and report timeout/validity fractions prominently per session; do not tune around
  any residual dropout silently. The original A5 text is retained below for the audit trail:
  *(A5, historical)* if the ball fails the §7 detectability test (persistent timeouts at
  1.3–1.7 m), do NOT silently swap targets — escalate to Prof. Zappa a proposed substitution
  (tape-wrapped tennis ball to remove felt absorption while preserving mass/size, or a hard
  smooth sphere of similar diameter). Any change alters the approved scope and slightly the
  mass/drag, so it is an approval item, not a code change.
- **(D6-R2, new) Pod-strike hazard.** A ~0.6 kg ball landing or rebounding inside a 1.0 m
  triangle can strike a printed sensor pod (vertices are only 0.577 m from the centroid, within
  ~5 ball radii of central landings). Operational rule: aim landings away from the vertices,
  and physically shield or be ready to re-survey a struck pod (a moved pod invalidates the
  surveyed vertex coordinates — re-tape the three pairwise distances after any strike).
- **(D6-R3, new) Larger surface→centre correction.** R2 now adds ~0.121 m — ~13% of a 1 m slant
  range vs 3.4% before. The correction stays exact for a sphere, but any radius mis-measurement
  propagates 1:1 into every range; measure C with the tape to ±2 mm (r to ±0.3 mm) and record
  it. The §7 tape-to-nearest-surface convention becomes correspondingly more sensitive to
  sloppy taping.
- **Ceiling wrap-around ghost (A2):** a sufficiently tall ceiling produces a static aliased
  echo that can pass the d_max gate. Defended by the rigid schedule + background band rule
  (static ghost → subtractable); verified at survey time via `--background-only` ghost
  prediction (set `ceiling_height_m`). If the predicted ghost lands inside the ball band and
  cannot be moved out of it, reposition the array or tilt. Strong Measurements-course discussion.
- **Background echo inside the ball band** (§5.3 warning) means the room must change, not the
  thresholds.
- **Symmetric-corridor throws** weaken depth; campaign keeps headings off the axes;
  `analyze_campaign.py` plots error vs heading. (The 2×2 A is constant and well-conditioned —
  the effect is anisotropic noise projection, not matrix blow-up; see §13.)
- **Equal-sensor-height assumption (R4)** is surveyed (±3 mm), recorded, and stated in the
  report as a model assumption.
- **Ground-truth uncertainty (R8)** (~mm-level from two tapes + first-contact identification) is
  part of the validation error budget and bounds how well the bias model can ever validate.
- **Beam-cone angle (D2)** is an estimate until §14 tunes it; synthetic absolute triplet counts
  are only as trustworthy as `beam_half_angle_deg`. The over-producing legacy mode is the
  conservative direction (more data than reality) and remains available for A/B comparison.
---

## 13. Audit disposition record (v2 → v2.1)

*(Numbered §13 to resolve the duplicate-§12 collision with the HTML reporting layer below; this
appendix predates §12 and is left in place.)*

Kept so any reviewer can see why each major external-audit claim was adopted or rejected.
"Adopted" items became A1–A5 above; "rejected" items are recorded with the reason. **v2.2 note:**
A4's optional central-difference upgrade is now generalised to the hybrid stencil and adopted as
the production default (D1); the beam-cone partial-triplet risk is now modelled in the simulator
(D2). **v2.6 note:** the top-row felt-absorption risk MATERIALISED on hardware (board passed at
1.0 m, tennis ball did not); the A5 contingency was executed and closed with Prof. Zappa's
approval of the basketball target (D6). The row below is retained verbatim as history.

| Audit claim | Disposition | Reason |
|---|---|---|
| Tennis-ball felt absorption / weak specular return causes timeouts | **Already covered** (risk #1) + **A5 contingency** | v2's top risk; §7 tests it before any campaign. "Mie regime" label is wrong (ka ≈ 24 ⇒ geometric/specular); cited 0.8–0.9 absorption figures are audio-band, not 40 kHz. |
| Reduce `pulse_timeout_us` | **Adopted (A1)** as 12500 | d_max is software-gated; long timeout only shrinks idle margin. |
| Raise baud to 500000 | **Rejected** | `Serial.print` is interrupt-driven & background-drained; 20 B / 18 ms never fills the 64 B TX buffer. Mechanism incorrect. |
| Ceiling wrap-around ghost | **Adopted (A2)** — best catch | Valid alias mechanism. Fix inverted: ghost is *static*, so the rigid schedule + band rule subtracts it; jittering would defeat the gate. |
| Humidity/pressure thermodynamics ignored | **Declined (A3)** | Real effect ~0.1–0.3% (mm-level), not structural; speed of sound stays formula-based. |
| Drag "completely omitted from predictor" | **Rejected (factually wrong)** | The audit missed `bias.py`: empirical, throw-aligned, significance-gated drag correction. Folding α into F contaminates the gravity-only F we locked. |
| Zenith linear-extrapolation "collapse" + NaN cascade | **Partly adopted (A4 → D1)** | Curvature error is real but ~1–2 cm worst case, not "sphere outside the bounding box"; radicand ≈ y² ≥ 0.25 m² at y ≳ 0.5 m. Now measured by `temporal_residual_vs_speed()`; the hybrid stencil (D1) is the production fix. |
| "216 ms gaps destabilize the covariance" | **Rejected** | Describes a fixed-dt filter; F is rebuilt from measured Δt (§8.4); gaps inflate P correctly and the filter coasts. Real cost (data starvation) is risk #1. |
| Symmetric corridor ⇒ "matrix inversion blows up" | **Rejected (mathematically wrong)** | The 2×2 A depends only on fixed vertex positions; the trajectory enters only b. A is constant and well-conditioned. Real (mild) effect is anisotropic noise projection → `analyze_campaign.py` plots it. |
| Effective beam 5–8°, partial-triplet starvation | **Acknowledged risk; now MODELLED (D2)** + EKF fallback = stretch goal | Plausible and in the risk register; the simulator now reproduces it via the beam-cone model. Single-range EKF updates remain a legitimate future enhancement on top of a working baseline. |
| Replace whole pipeline with tightly-coupled EKF | **Rejected for this project; future work** | Superior textbook architecture, but trilateration is course content and the approved method; the loosely-coupled chain is layer-by-layer testable; tuning burden high for a 2-person project. Cite as known-better alternative. |

**Net:** three substantive amendments (A1, A2, A4) + one contingency (A5); A3 declined. v2.2 then
adds the process_throw.py architecture fix, the implementation reconciliations (F-1…F-9), and the
three build decisions (D1 hybrid stencil, D2 beam-cone, D3 campaign size) + D4 session naming.

---

## 12. HTML reporting and web ground-truth layer (v2.3)

Absorbs the former `website.md` build spec. Two **independent**, **self-contained** browser
deliverables sharing one design system. This layer **consumes** on-disk artifacts and **reuses**
existing analysis code; it performs **no new physics**. The only thing it writes back into the
pipeline is the `ground_truth` block, via the existing `update_session_ground_truth`.

### 12.0 Guardrails (apply throughout)
- **No pipeline math reimplemented** in Python *or* JavaScript. The ground-truth solve runs through
  `geometry.solve_ground_truth` / `geometry.ground_truth_landing` (§8.1); campaign statistics through
  `analyze_campaign.summary_stats` + `calibrate_bias.load_record` + `bias.evaluate`; any raw-vs-Kalman
  landing through `landing.predict_landing`.
- **JS curves are cosmetic.** The drawn parabola / Kalman path is a display re-fit (same rule as
  `reporting.py`). **Every authoritative number — landing (r, θ), (x, z), σ's, 2-D error, all stats —
  comes from `session.json` / `summary_stats` verbatim.** A clearly-labelled in-browser "preview" of
  the tape solve is allowed, but the value that is *saved* is the one Python computed and read back.
- **Pure computational modules are not modified** (geometry/corrections/trilateration/kalman/landing/
  bias/segmentation/background/simulator/process_throw); reuse by import only.
- **Raw data is sacred.** The layer reads `triplets_raw.csv`, `trajectory.csv`, `session.json`,
  `background.json`; it writes **only** the `ground_truth` key, **only** via
  `update_session_ground_truth`.
- **Self-contained output** (no CDN, no external fetch). The input-mode `report.html` POSTs to the
  **local** server only while awaiting ground truth; once frozen it is fully static.
- **Stdlib only** for the server (`http.server.ThreadingHTTPServer`); no Flask/Jinja. Template = one
  static HTML file per page with a single `<!--__DATA__-->` marker into which the generator injects
  `<script>window.__DATA__ = {...}</script>`.
- **ASCII-only Python console output** (cp1252). Negative numbers in the HTML UI use the proper minus
  glyph; Python prints stay ASCII.
- **Additive.** The terminal `prompt_ground_truth` path stays as default + fallback; the web layer is
  opt-in (`--web`) and reuses the same audited solve.

### 12.1 Per-throw `report.html` (each session dir)
Three mutually-exclusive states, chosen by the generator from `session.json`:
- **Input mode** (prediction present, no `ground_truth`): polar **landing scope** (signature — range
  rings in metres, bearing spokes, the surveyed S1/S2/S3 triangle, the Kalman ground-track, the
  predicted return + its 1-σ ellipse from `cov_xz_m2`); predicted-landing readout (r ± σ_r, θ ± σ_θ,
  x, z) with a **raw / bias-corrected** toggle; the **ground-truth input panel** (see §12.4);
  **trajectory** vertical profile (downrange × height) with raw points / Kalman / parabola fit / apex /
  `y = r_ball` contact, and a **2D/3D toggle** (hand-rolled vanilla-canvas orthographic, drag-to-rotate,
  no CDN); a **collapsible range-vs-time** panel (per-sensor accepted-vs-gated readings, throw window
  shaded, mirroring `reporting.py`'s derivation); a **stat strip**; and the amber **small-sample
  caveat** lamp.
- **Frozen mode** (prediction + `ground_truth` present): as input mode, but the GT panel shows surveyed
  r/θ/x/z and the **2-D Euclidean error (mm)**, the scope draws the surveyed return + coral error
  vector, the input form is gone, and the page is fully self-contained / server-independent. This is
  the durable artifact.
- **Failure mode** (no valid prediction: `< min_fit_points` used, or non-concave fit): no scope return;
  shows "No valid prediction · N triplets used (need >= 4)."; still renders range-vs-time + stat strip;
  no GT input (the solve needs a prediction-derived sensor recommendation).

**Stat strip labels (must be exact):** detection yield = **`n_triplets_used` / triplets-in-throw-window**
(the in-window count, not the session total which is dominated by background calibration), with the
**>= min_fit_points (4)** pass/fail status; **fit dof = N − 3** (the parabola-fit residual dof, read from
`prediction.raw.dof` — NOT a Kalman quantity, and kept separate from the malformed count); heading φ &
v_h; temperature & derived speed of sound (display value from the config coefficient).

### 12.2 Campaign `campaign.html` (root of each subtree)
**(D5) There are two campaign files, never mixed:** `data/sessions/campaign.html` (live throws) and
`data/sessions/demo/campaign.html` (demo throws). Each lives at the **root of its subtree**, NOT
inside any session. **Not frozen**: each is regenerated from scratch — the live page at the end of
every `run_session.py` run and inside the POST handler after every ground-truth write; the demo page
at the end of every `simulate_session.py` batch (§6) — reflecting all sessions **in its own subtree**
to date.

`render_campaign_report(sessions_root, config)` takes the subtree root as an argument and writes
`<sessions_root>/campaign.html`; the live and demo campaigns are the **same renderer pointed at
different roots**. Session enumeration uses the shared **predicate** `is_session_dir(p) = p.is_dir()
and (p / "session.json").exists()` (§8.7). This is what keeps the two campaigns disjoint: the live
builder, scanning `data/sessions/`, sees the `demo/` container, finds no top-level `session.json`, and
skips it; the demo builder, scanning `data/sessions/demo/`, sees only the synthetic session dirs. The
predicate also skips a subtree's own `campaign.html` (a file, not a session dir) — superseding and
strengthening the v2.2 §VV-1 directories-only filter.

Content (identical for both pages): a campaign scope (every throw's prediction + truth pair + error
vector), raw-vs-corrected mean error with 95% CI, the bias-model status (mode, along-track mean ± CI,
significance gate, from `correction_model.json`), a 2-D error histogram, and a throws table. All
numbers come from `analyze_campaign.summary_stats` / `calibrate_bias.load_record` (reuse, do not
recompute; the only permitted touch to `analyze_campaign.py` is the §8.7 D5 predicate guard plus
making `summary_stats` importable without side effects). Error stats are computed over the
ground-truthed subset exactly as those loaders decide inclusion (including the `truth.landing`
fallback for simulated sessions — which is why the demo campaign populates from `truth.landing` even
before any tape entry).

### 12.3 Local server + write-back (`scripts/serve_report.py`)
Stdlib `ThreadingHTTPServer` on a hardcoded loopback bind (`127.0.0.1`, ephemeral port; not
configurable, by design). Routes:
- `GET /` -> current session's `report.html`.
- `GET /api/health` -> `200 {ok:true, session_id}` (the input page health-checks on load).
- `POST /api/ground-truth {session_id, L_centroid, L_a, L_b, sensors}`:
  1. load `prediction.raw` (409 if absent);
  2. **audited solve** via `geometry.solve_ground_truth` (§8.1, §12.4);
  3. **atomic write** via `update_session_ground_truth` (temp file + `os.replace`, fsync before rename
     — strengthen the writer if it is not already atomic; it writes **only** the `ground_truth` key);
  4. **read the file back** and compute the displayed error from the persisted values;
  5. re-render `report.html` (frozen) and regenerate `campaign.html`;
  6. respond `200 {r, theta, x, z, error_mm_raw, error_mm_corrected?, persisted:true}` built from the
     re-read values.
  Degenerate solve -> `422`, nothing written; write/read-back failure -> `5xx`, nothing partial left.
- **Success-gated UI:** the page flips to frozen / "saved" **only** on `200 persisted:true`; on any
  error it keeps the form and surfaces the message. It never claims "saved" optimistically on click.
- **Late entry** (skip / close / Ctrl-C all leave an "awaiting ground truth" session — there is **no
  input deadline** and no way to lose the ability to enter GT): `serve_report.py --session <id>`
  regenerates a working input page against a fresh port and accepts the identical handler;
  `serve_report.py --pending` lists every session with a prediction and no `ground_truth`. The terminal
  `append_ground_truth.py` is the no-browser fallback and a test oracle. If the input page's
  `/api/health` check fails (no server), it disables save and directs the operator to
  `serve_report.py --session <id>`.

### 12.4 Ground-truth input under the G1 protocol (forward)
The per-throw GT panel and the solve follow §5.5 (v2.3 G1):
- `geometry.recommend_reference_sensors(prediction.raw_xz, config)` returns the **two sensors nearest
  the predicted landing**; the panel pre-selects them and lets the operator **override** to any 2 of 3.
- The operator enters **three** tape distances — centroid + the two chosen sensors — and the shared
  `geometry.solve_ground_truth(...)` runs the **least-squares multilateration** core (unique, no mirror
  branch), returning the `ground_truth` block incl. **sensors-used**, **LS residual**, and
  **condition-number flag**, with σ propagated from `sigma_tape_m`. The same core serves the terminal
  prompt, `append_ground_truth.py`, and the web handler so the paths cannot diverge.
- **Migration note (G1-status) — COMPLETE.** The web layer (W1) was originally built on the old
  two-tape input (centroid + S1, two fields, `two_circle`); the G1 migration (item 17 of §10,
  IMPLEMENTATION_NOTES Part 9) has since landed. The per-throw panel is now **centroid + 2 sensor
  fields + recommended-pair selector**, and the terminal prompt, `append_ground_truth.py`, and the
  web POST all run the shared `solve_ground_truth` multilateration core (proven byte-identical by
  test). `two_circle_intersection` is retired. No two-tape path remains.

### 12.5 Tests
- **Renderer** (`test_web_report.py`): self-containment (no external `http(s)` resource refs;
  `window.__DATA__` present); state selection (input / frozen / failure); rendered (r,θ,x,z,σ) equal
  `session.json` verbatim (no recompute); campaign numbers equal `summary_stats`, and a second render
  overwrites (not appends). **(D5)** a `demo/` container beside live session dirs is excluded from the
  live campaign (predicate skips it); the demo campaign rendered over `data/sessions/demo/` includes
  exactly the demo sessions and nothing from the live root; a stray `campaign.html` in either root is
  never loaded as a session.
- **Server** (`test_serve_report.py`): the web GT block is **byte-identical** to the terminal path's
  block for the same inputs (guards the shared-solve refactor); POST writes `ground_truth` + flips the
  page to frozen + updates the campaign; degenerate tapes -> error, nothing written; **read-back
  round-trip** (200 body == an independent re-read of `session.json`); **atomic-write integrity** (only
  `ground_truth` added, all other keys intact; a simulated failure leaves the original file unchanged);
  **late entry** (`--session` completes an awaiting-GT session with a block identical to the terminal
  path; `--pending` lists exactly the awaiting-GT sessions).
- All prior tests stay green; the web layer is additive.

### 12.6 Design system (military-HUD instrument console)
Sonar / instrument console; the boldness is spent on the **polar landing scope** (the data is defined
in polar (r, θ) from the centroid). Functional colour channels (unchanged, load-bearing): **cyan** =
prediction, **amber** = ground truth + caveat lamp, **coral** = error vector, **steel-blue** =
sensors/structure. Monospace tabular numerals for every readout; no web fonts / no CDN; respect
`prefers-reduced-motion`.

**(v2.5) Military-HUD evolution — as-built.** The pages were restyled into a tactical-HUD look
(IMPLEMENTATION_NOTES Part 11), superseding the original `landing_report_mock.html` chrome (§YY). The
visual language, applied identically to both files: angular panels (≈3px radius) with cyan L-bracket
corner ticks; **numbered section tags** (`[01]…`, CSS counter, label text verbatim); a command-banner
header; monospace body; stat tiles with a top accent rule; squared chips/inputs/toggles; amber/coral
left-accent strips for caveat/integrity/failure. The polar scopes gain a **center reticle**, a
**bearing scale** (`000–330°`), range-ring tick labels, and a subtle `conic-gradient` **radar sweep**
(reduced-motion safe). The polar-scope **display radius is 3 m** (range rings to 3.0 m) so that
floor-extrapolated landings beyond 2 m fit inside the diagram — this is a canvas display scale and is
**distinct from the `gates.d_max_m = 2.0 m` physical range gate**, which is unchanged. **The campaign scope's array triangle was removed** (it read as a "play button"
— S1 right, S2/S3 left); S1/S2/S3 now render as steel dots in bracket boxes, matching the per-throw
scope. The restyle changed **chrome only** — every value, label, precision, element `id`, the
`<!--__DATA__-->` marker, and the input/frozen/failure state machine are unchanged.

**Hard constraint (why no SVG):** `test_self_contained` asserts `"http://" not in html`, so all
graphics stay **`<canvas>` + CSS** — inline SVG is forbidden because its `xmlns="http://www.w3.org/2000/svg"`
would trip the self-containment test.

The real build is **two independent files** (§12.1, §12.2) with no shared nav (the old mock's single-file
`Per throw / Campaign` nav-tab toggle was review-only).
