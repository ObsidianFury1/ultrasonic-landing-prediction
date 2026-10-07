# CHANGES_OPTICAL.md — Work Order **WO-OPT-4**

## Target substitution: tennis ball → basketball (optical module)

**Status:** DRAFTED, not executed. Awaiting Hari review of the flagged judgment calls (bottom of file) before any stage runs.
**Trigger:** Main project Decision **D6** (CLAUDE.md v2.6 / v2.7 — target changed from tennis ball to basketball, measured basketball `radius_m = 0.1194 m`). The optical module is the ground-truth instrument for the *same physical throws*; it must track the same ball.
**Predecessor work orders:** WO-OPT-1, WO-OPT-2 (Phase 6a), WO-OPT-3 (audit remediation, Stage 0 = CLAUDE_OPTICAL.md v1.4). Baseline at drafting: **168 passing tests** (WO-OPT-3 audit-time count).
**Spec touched:** `CLAUDE_OPTICAL.md` v1.4 → **v1.5** (Stage 0 of this order).

---

## 0. Why this work order exists (coupling rationale — read first)

The optical module films a throw over the ultrasonic array and recovers the landing point as an **independent cross-validation instrument** (CLAUDE_OPTICAL.md §Purpose). It measures the **same physical ball** the ultrasonic system measures. The main project has substituted the tennis ball for a basketball under D6; therefore the optical module must track a **basketball**, or it is no longer measuring the same object as its reference instrument.

**Critical decoupling point (§12 of CLAUDE_OPTICAL.md):** the optical module *never imports from the main project*. Shared constants — array geometry and `r_ball` — are **duplicated** in the optical `config.yaml`, not shared at runtime. **Consequence: the main project's D6 config edit does NOT propagate to the optical module.** Every tennis→basketball reference in the optical spec, config, and simulator must be changed here, independently. That is the entire job of WO-OPT-4.

---

## 1. Approved parameters (copy from the main D6 register — do NOT re-placeholder)

Because it is the same physical ball, values are **copied from the main project's measured D6 record**, not re-measured, to prevent the two configs drifting:

| Quantity | Old (tennis) | New (basketball) | Provenance |
|---|---|---|---|
| `ball.radius_m` | 0.0335 m | **0.1194 m** | Main CLAUDE.md §config; measured 2026-07-09, circumference C = 0.750 m (tape, ±2 mm), r = C/2π, size-7 |
| ball mass (record only) | ~0.058 kg | **0.620 kg** | Main D6 register (scale) |
| detection colour | tennis yellow-green | **basketball orange** | This work order |

Geometric consequences (used throughout, all exact ratios):
- Radius ratio 0.1194 / 0.0335 = **×3.56**.
- Rendered pixel-area / acoustic-cross-section ratio = 3.56² ≈ **×12.7** (consistent with the main spec's "~13× stronger return").
- Parallax centroid height above floor at contact grows the same **×3.56** (§5.4). This is material — see Stage 5.

> **Honesty flag.** `radius_m = 0.1194 m`, C = 0.750 m, and mass 0.620 kg are the main project's *measured* figures — treat them as authoritative for the shared ball. The **HSV orange band** and the **detector area band** below are **placeholders I am proposing, not measured values**; they must be tuned on real footage at checklist C6 (§8), exactly as the tennis band was a placeholder. They are marked as such in every stage.

---

## 2. Decision register (D17–D22) — appended to `IMPLEMENTATION_NOTES_OPTICAL.md` at closeout

*(Continuing the D-series from WO-OPT-3's D9–D16. See the register-naming flag in §5 — the spec also carries an O-series, O1–O17; confirm which register you want these filed under before closeout.)*

- **D17** — Adopt basketball as the optical target. `r_ball` 0.0335 → 0.1194 m, duplicated from the main D6 measured record (same physical ball; §12 forbids importing it).
- **D18** — HSV detection band retargeted yellow-green → orange. Shipped values are a **placeholder** (tune at C6). The synthetic draw colour is kept **dead-centre of the new orange band** to preserve the WO-OPT-1 Stage 6.5 invariant (so the Phase 6a HSV-optimism caveat stays accurate).
- **D19** — Detector **area band** re-derived from the *rendered* synthetic basketball size (~×12.7 area), not hardcoded. Provisional widening in Stage 1, finalised from measurement in Stage 4.
- **D20** — Parallax correction magnitude and its uncertainty component (§5.4, §7 item 4) grow ~×3.56. Correction remains parametric/exact; the σ(`r_ball` surrogate = contact compression) term is re-characterised for the basketball at C6 (not fabricated).
- **D21** — §5.5 contact-duration narrative re-examined: a basketball's contact is longer than a tennis ball's, so the "possibly zero or one true contact frames at 480 fps" statement may no longer hold (several contact frames now plausible). Duration to be **verified from a primary source** before any number is quoted; the reversal/kink solve margin is re-checked (Stage 5).
- **D22** *(optional, gated)* — Phase 6a ML ablation re-run on the orange synthetic library; COCO "sports ball" class (32) expected to still fire (generic class). Watermark + caveat retained.

---

## 3. Staged work order — **STOP and confirm at every gate**

Discipline (unchanged, per §0.2 / O1): **amend the spec before touching code**; take a manual folder backup before each stage (no version control); **self-inspect actual file state before every edit** — line numbers here are indicative, not authoritative; update `IMPLEMENTATION_NOTES_OPTICAL.md` as part of each stage, not after; **no stage closes with a red suite.**

### Stage 0 — Spec amendment: `CLAUDE_OPTICAL.md` v1.4 → **v1.5** (DOCUMENTATION ONLY, no code)

Amend before building. Edit these sections (grep the live file first; do not trust these line hints):

1. **Header / §Purpose (~line 4)** — "films a **tennis-ball** throw" → "films a **basketball** throw".
2. **§2 Coordinate/Geometry Contract (~line 95)** — `r_ball = 0.0335 m (tennis ball)` → `r_ball = 0.1194 m (basketball)`; keep the cross-reference to main spec §5.3 and add "[AMENDED v1.5 — D17; was: 0.0335 tennis ball]", citing the measured provenance (C = 0.750 m).
3. **§5.2 Ball detection (~line 299)** — "tennis-ball yellow-green band" → "basketball orange band".
4. **§5.4 Parallax (~line 330, 338)** — add a note that the centroid-height correction (`h = r_ball at contact`) is now ~×3.56 larger; the closed-form correction is unchanged (parametric), but its magnitude and uncertainty contribution are material at the working standoff. [AMENDED v1.5 — D20]
5. **§5.5 Contact instant (~line 460)** — "Contact duration for a **tennis ball** is of order a few ms …" → basketball wording; state that basketball contact is longer and **may span several frames at 480 fps** (re-examine the "zero/one contact frame" reasoning); keep the "verify against a primary source before quoting a number" instruction. [AMENDED v1.5 — D21]
6. **§5.6 / §6 simulator (~line 568)** — "drawn ball … **tennis-ball colour**" → "basketball orange".
7. **§7 item 4 (~line 619)** — parallax residual: note σ(`r_ball` surrogate = ball compression at contact) is re-characterised for the basketball; larger absolute correction. [AMENDED v1.5 — D20]
8. **§10 (~line 768)** — the "tennis-ball tracking (TrackNet-family)" recollection: reword so it is not tied to tennis; **keep the "verify from a primary source, do not cite from memory" caveat** (do not invent a basketball-tracking citation).
9. **Changelog** — append a **v1.5** entry (trigger: main D6 / WO-OPT-4; documentation-only stage; no computed number on a passing path changes yet) and record **D17–D21**.

**Do NOT touch** the historical changelog markers that legitimately say "tennis" as *history* (e.g. "was: tennis ball") — those are the audit trail.

*Gate:* spec reads consistently; a grep of `CLAUDE_OPTICAL.md` for "tennis" returns **only** historical/changelog occurrences; version header = v1.5 with a matching changelog entry. **STOP — confirm.**

---

### Stage 1 — `config.yaml` sync

- `ball.radius_m`: 0.0335 → **0.1194**, with a comment recording provenance (measured 2026-07-09, C = 0.750 m, main D6; duplicated per §12).
- **HSV band** (as-built placeholder was `[25,60,60]`–`[45,255,255]`, tennis yellow-green — IMPLEMENTATION_NOTES_OPTICAL Stage-3 record): retarget to **orange**. Proposed **placeholder** (OpenCV H 0–179): `[5,120,120]`–`[20,255,255]`. **This is unverified — mark it `# PLACEHOLDER, tune at C6` and do not present it as measured.**
- **Area band** (as-built `[30, 20000]` px²): the basketball renders ~×12.7 area, so the upper bound will be exceeded. Set a **provisional** widened placeholder (e.g. raise the upper bound by ~×13 and keep a generous lower bound), flagged `# PROVISIONAL — re-derive from rendered size in Stage 4`.
- Circularity threshold (0.6): unchanged (a basketball is still round); note only.

*Gate:* config loads; existing config-load / schema tests green. **STOP — confirm.**

---

### Stage 2 — Simulator sync (`simulator/render.py`)

- The synthetic ball colour is produced by `tennis_ball_bgr` (IMPLEMENTATION_NOTES_OPTICAL Stage-6.5 record). **Retarget it to basketball orange, set dead-centre of the new HSV band** (preserve the WO-OPT-1 Stage 6.5 invariant: synthetic hue at band centre → the Phase 6a HSV-optimism caveat stays true). *Rename vs value-only change is a flagged judgment call — see §5.*
- Drawn radius = `f·r_ball/depth` follows `r_ball` **automatically** now that config `r_ball = 0.1194`; no formula change. **But measure and record the resulting synthetic pixel radius/area** for the nominal §6 scenario — this feeds the Stage 4 area-band finalisation.
- Update the WO-OPT-1 Stage 6.5 comment to say "synthetic hue dead-centre of the *orange* config band".

*Gate:* simulator renders; render unit tests green; **record the measured synthetic pixel area** in the notes. **STOP — confirm.**

---

### Stage 3 — Hardcode audit (mirrors the main D6 hardcode-audit stage)

Grep the optical codebase (`optical/`, `tests/`, `simulator/`, `scripts/`) for tennis-derived constants:
- literal `0.0335`
- `tennis`, `tennis_ball`, `tennis_ball_bgr`
- ball-context `yellow` / `green`
- any hardcoded hue in the 25–45 range or area upper bound `20000` that is not config-driven

Produce an audit table (file · line · old · new · config-driven?). Replace every **live** occurrence with the config value or the basketball value. **Distinguish live code from comments/changelog/history** (which stay).

*Gate:* audit table produced; **no live tennis-derived constant remains**; full suite green. **STOP — confirm.**

---

### Stage 4 — Synthetic acceptance-gate re-run — **THE regression gate**

This is the equivalent of the main project's D6 §9 acceptance-gate re-run and is the load-bearing check of this work order.

- Finalise the **area band** from the Stage-2 measured synthetic pixel area (bracket it with margin; replace the Stage-1 provisional).
- Re-run the **§6 synthetic END-TO-END acceptance test**: nominal scenario recovers the injected landing within tolerance (≤ 3 mm at zero noise; shadowed/blurred within scaled tolerances). The orange ball must be **detected** through the new HSV band + area band, and the parallax correction (now ~×3.56 larger) must still recover truth.
- Re-run **both negative controls**: corrupted marker survey trips the check-point guard; no-ball clip yields a clean "no detection", never a fabricated landing.
- Full suite green. Record the new test count (baseline 168; note any added/changed).

*Gate:* acceptance test + both negative controls green; recovered-landing RMS within tolerance. **STOP — confirm.** *(If detection fails here, the HSV band or area band is mis-set — return to Stage 1/2, do not loosen the tolerance.)*

---

### Stage 5 — Uncertainty & parallax re-characterisation notes (§7, §5.4, §5.5)

No number is fabricated here; this stage records what must be **measured at commissioning** and flags the physics that changed.

- **§7 item 4 (parallax residual):** the σ(`r_ball` surrogate = ball compression at contact) is now a basketball quantity. Keep it as an **unmeasured placeholder** feeding the `unmeasured_uncertainty_components` flag until measured at C6 — do not invent a compression figure.
- **Parallax magnitude:** confirm the `parallax_residual_m` budget line is still *measured/flagged*, not silently rescaled; the correction is ~×3.56 larger in metres.
- **§5.5 contact duration (D21):** update narrative; flag that a basketball may produce **several contact frames at 480 fps** (vs the tennis "zero/one"), which affects the reversal/kink solve margin. **Verify the actual basketball contact duration from a primary source before quoting any millisecond value.**
- **Size-cue re-evaluation (informational, no change now):** the §5.4 apparent-size height method was rejected as *signal-starved* for the tennis ball (pixel radius changed only ~0.05 px across the descent). A ×3.56-larger ball changes pixel radius ~×3.56 more, so this cue **may become viable** — flag it as a Phase 5 / Future-Works re-check, not a v1 change.
- Append the **WO-OPT-4 ledger** (files touched, deviations, test counts) and the **D17–D21** register entries to `IMPLEMENTATION_NOTES_OPTICAL.md`.

*Gate:* notes appended; uncertainty budget prints with the placeholder flag; full suite green. **STOP — confirm.**

---

### Stage 6 — OPTIONAL, droppable: Phase 6a ML ablation re-run (§10) (D22)

Only if Phase 6a is in play. The COCO **"sports ball"** class (id 32) is generic and should fire on an orange basketball synthetic (expected, not guaranteed — verify).

- Re-run `compare_detectors.py` on the updated (orange) §6 simulator library.
- Retain the **"SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING"** watermark and the HSV-optimism caveat (now referencing the orange band).
- Confirm the import-guard test still passes (core suite green with `ultralytics` uninstalled).

*Gate:* 6a report reproduced; import-guard green; core suite green without ML. **STOP — confirm.**

---

## 4. What this work order does **NOT** change (guard against scope creep)

- **The frozen output schema (O7).** `r_ball` is a config constant, **not** a JSON key — no key is added, renamed, or removed. Only an internal value changes.
- **Geometry / homography / (r, θ) conversions.** `r_ball` is a contact-height constant, not a projective parameter.
- **The reference protocol, gates, or thresholds.** The three-tape multilateration reference, the §8 **15 mm GO/NO-GO gate**, `check_point_tol_m`, and the E_n cross-validation statistic are untouched.
- **The main project.** WO-OPT-4 writes only inside the optical directory (§12).

---

## 5. Judgment calls to surface (do NOT resolve silently — Hari to confirm)

1. **HSV orange band placeholder** `[5,120,120]`–`[20,255,255]` — I am **not certain** these are the right thresholds; they are a reasonable starting guess for orange in OpenCV hue space and **must be tuned at C6 on real footage**. Confirm you're happy shipping them as a flagged placeholder.
2. **Area-band upper bound** — my ~×13 widening is derived from the geometric area ratio, but the *actual* rendered pixel area depends on the scenario's camera distance; Stage 4 finalises it from measurement. Confirm the "re-derive from rendered size" approach over a fixed number.
3. **`tennis_ball_bgr` — rename vs value-only change.** Renaming to `basketball_bgr` is cleaner and self-documenting but touches every call site; a value-only change is lower-risk but leaves a misleading name. I lean **rename**; your call.
4. **Basketball contact duration (§5.5).** I do **not** have a verified figure and will not fabricate one. This matters because it may flip the "zero/one contact frames at 480 fps" claim to "several frames." Please confirm a primary source (or leave it flagged for Phase 5 measurement).
5. **Decision-register numbering.** I continued the **D-series (D17+)** from WO-OPT-3. The spec's own register is the **O-series (O1–O17)**. Confirm which register these should live under at closeout.

---

## 6. Suggested next artifact

Once you approve the stages above, the matching **`STAGE_PROMPTS_WO-OPT-4.md`** (self-contained Claude Code executor prompts, one per stage, each re-reading the live spec/config/notes from disk and surfacing rather than resolving the §5 judgment calls) can be generated on the same pattern as `STAGE_PROMPTS_WO-OPT-3.md`. Say the word and I'll produce it.
