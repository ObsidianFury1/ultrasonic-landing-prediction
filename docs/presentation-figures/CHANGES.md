# CHANGES.md — D5: demo / live session storage separation

**Target spec:** CLAUDE.md v2.4 (§0.3, §1, §2, §5.6, §5.7, §6, §8.7, §10 item 18, §12.2, §12.5).
**Status:** TO BUILD.
**Supersedes:** the v2.2 §VV-1 "directories-only" campaign filter.

> **Coexistence note.** If your repo still holds the prior **G1** work order in `CHANGES.md`, archive
> it (e.g. rename to `CHANGES_G1.md`) before dropping this file in, or the two orders will collide.
> D5 and G1 are independent: D5 touches storage layout + campaign enumeration; G1 touches the
> ground-truth solve. Build order between them is free, but keep one active `CHANGES.md` at a time.

---

## 0. Goal (one sentence)

Stop the campaign report from mixing simulator/demo throws with live (hardware) throws by moving demo
sessions into `data/sessions/<demo_subdir>/` (default `demo/`), giving each subtree its own
`campaign.html`, and switching every session-enumeration site to the predicate **"a directory is a
session iff it contains `session.json`."**

## 1. Decisions baked into this order (for audit)

- **D5a — Demo campaign auto-regenerates** at the end of a `simulate_session.py` batch (no flag).
- **D5b — Config home:** a **new top-level `sessions:`** block (NOT under `simulator:`).
- **D5c — `analyze_campaign.py` IS modified** (predicate guard only); the Part-6 "do not touch" stance
  is lifted for this one guard. The same guard extends to the `calibrate_bias` per-path loader.
- **D5d — Migrate the existing synthetic dirs now, before git.** Rationale: demo sessions are seeded
  and reproducible, so the "raw data is sacred / migrate only under git" caution does not bind them.
  (It still binds real campaign throws — do NOT generalise this to live data.)

## 2. The one load-bearing invariant — read before writing code

Define ONE helper and route every session-enumeration site through it:

```python
def is_session_dir(p: Path) -> bool:
    return p.is_dir() and (p / "session.json").exists()
```

This is the whole separation mechanism. The live campaign builder scans `data/sessions/`, sees the
`demo/` directory, finds no `demo/session.json`, and skips it — **with no name matching**. Do not
implement the split by string-matching `"demo"` or the `sim_` prefix; those are fragile. Put the
helper somewhere both `web_report.py` and `analyze_campaign.py` can import it (suggest:
`pipeline/web_report.py` if that already owns the §VV-1 filter, or a tiny shared util — pick whichever
avoids a new circular import, and STATE which you chose in IMPLEMENTATION_NOTES Part 9/D5).

**Before you start: self-inspect actual file state.** Do not trust this order's line references blindly
— open `pipeline/web_report.py`, `scripts/analyze_campaign.py`, `scripts/calibrate_bias.py`, and
`scripts/simulate_session.py` and confirm where sessions are currently globbed and where
`campaign.html` is currently written. Report what you find before Stage 1.

---

## STAGE 0 — reconnaissance (no edits)  ⟶ STOP & CONFIRM

1. Print the current contents of `data/sessions/` (dirs + files). Confirm the count of synthetic dirs
   (the spec notes 12) and whether a `data/sessions/campaign.html` currently exists.
2. Locate and quote, with file:line:
   - the current session-glob in `web_report.build_campaign_data` (the §VV-1 directories-only filter),
   - the current session-glob in `analyze_campaign.load_campaign`,
   - the per-path loader in `calibrate_bias` (where it reads each `session.json`),
   - where `simulate_session.py` chooses its output directory,
   - whether `web_report.render_campaign_report(sessions_root, config)` writes
     `<sessions_root>/campaign.html` (confirm the signature).
3. Confirm whether `load_record` / `load_campaign` currently **raise** or **skip** when handed a path
   with no `session.json`. This determines whether Stage 2 is a hardening or a behaviour change.

**STOP.** Report findings. Do not proceed until confirmed.

---

## STAGE 1 — config + `is_session_dir` predicate  ⟶ STOP & CONFIRM

1. **config.yaml:** add the new top-level block (place it immediately above `simulator:`):
   ```yaml
   sessions:
     demo_subdir: "demo"
   ```
2. Add `is_session_dir(p)` (exactly as §2 above) in the shared location you chose.
3. Route `web_report.build_campaign_data` AND `analyze_campaign.load_campaign` through it. Each must
   **skip** a non-session path silently with a printed reason (no raise), matching the existing
   defensive-skip pattern.
4. Route the `calibrate_bias` per-path loader through it as well (a path failing the predicate is
   skipped with a printed reason — this protects `calibrate_bias.py --sessions data\sessions\*`).
5. **Tests (add to `test_web_report.py` and `test_analyze_campaign.py`):**
   - a temp `sessions_root` containing N session dirs + one `demo/` subdir (itself holding M session
     dirs) + a stray `campaign.html` → the live builder returns exactly N; the `demo/` and the stray
     file are absent.
   - the demo builder pointed at `<root>/demo` returns exactly M.

**STOP.** Run the full suite (`.\venv\Scripts\python.exe -m pytest tests\ -q`) and report pass count.
Expected: prior 195 + new. Confirm before Stage 2.

---

## STAGE 2 — `simulate_session.py` writes under the demo subtree + auto demo-campaign  ⟶ STOP & CONFIRM

1. Resolve the demo root: `demo_root = sessions_root / config["sessions"]["demo_subdir"]`, overridable
   by a new `--demo-subdir` CLI flag. `mkdir(parents=True, exist_ok=True)` the demo root once.
2. Point `create_session_folder` (and its existence guard) at `demo_root` instead of `sessions_root`.
   The `sim_YYYY-MM-DD_HHMMSS_S##` naming (D4) is unchanged — only the parent moves.
3. **(D5a)** After the batch finishes, call `web_report.render_campaign_report(demo_root, config)` so
   `data/sessions/demo/campaign.html` is rebuilt automatically. Make this best-effort with a printed
   skip line if there are zero usable sessions (reuse the §RR `--plot` graceful-skip pattern), so a
   pure stress-run that produces no detectable throw does not crash on campaign render.
4. Confirm the existing `--plot` path still works (it writes per-session `plots/`, now under `demo/`).
5. **Tests (add to `test_simulator.py` or a `simulate_session` smoke):** a batch writes its dirs under
   `<root>/demo/`, NOT directly under `<root>`; after the batch `<root>/demo/campaign.html` exists.

**STOP.** Run the suite; run a real `simulate_session.py --n-sessions 3 --beam-cone off --seed 11` into
a throwaway root and show the resulting tree (dirs under `demo/`, a `demo/campaign.html`, and an empty
live `<root>` with no `campaign.html`). Clean up the throwaway. Confirm before Stage 3.

---

## STAGE 3 — live path inherits the split (verify, minimal edits)  ⟶ STOP & CONFIRM

1. Confirm `run_session.py --web` and the POST handler regenerate **only** the live campaign
   (`render_campaign_report(sessions_root, config)` with the live root), and that — because of the
   Stage-1 predicate — the `demo/` subtree is now excluded from it automatically. No new logic should
   be needed here; if any name-based exclusion was added anywhere, REMOVE it (the predicate is the only
   mechanism).
2. **Test:** a live root containing live session dirs + a populated `demo/` subtree → the live campaign
   numbers equal `summary_stats` over the live dirs only.

**STOP.** Report. Confirm before Stage 4.

---

## STAGE 4 — one-time migration of existing synthetic dirs (D5d)  ⟶ STOP & CONFIRM

> Pre-git, by decision D5d. Make it **reversible-in-practice** anyway: do a dry run first, log every
> move, and never overwrite.

1. **Dry run (no moves):** list every entry in `data/sessions/` that satisfies `is_session_dir`. Of
   those, classify as demo by the `sim_` prefix (these are the synthetic dirs). Print the proposed
   `src -> dst` move list (`data/sessions/<sim_*>` -> `data/sessions/demo/<sim_*>`). Print the count.
   Do NOT touch the stale `data/sessions/campaign.html` yet — it will be regenerated.
2. **STOP & CONFIRM the move list** (expected ~12 dirs). Only proceed on explicit go.
3. **Execute:** `mkdir data/sessions/demo`; move each `sim_*` dir in; refuse (abort with message) if a
   destination already exists. Print each move as it happens.
4. **Regenerate both campaigns:** `render_campaign_report(data/sessions, config)` (live — should now be
   empty/awaiting, since all sim dirs moved out) and `render_campaign_report(data/sessions/demo,
   config)` (demo — should show the migrated throws). Delete the stale root `campaign.html` first if it
   predates the regenerate, so the live page is rebuilt clean.
5. Show the final tree and open both campaign pages' titles/first stats line to confirm the demo
   campaign carries the synthetic throws and the live campaign is empty.

**STOP.** Report. Confirm before Stage 5.

---

## STAGE 5 — docs + final gate

1. **IMPLEMENTATION_NOTES.md — add Part 9 (or D5 section):** record (a) where `is_session_dir` lives
   and why, (b) the raise-vs-skip finding from Stage 0.3, (c) the migration move-log (src→dst, count),
   (d) any deviation from this order with justification.
2. Confirm `CLAUDE.md` is already at v2.4 with the D5 changelog (it is, if you used the amended file).
3. **Final gate:** full suite green; print the pass count and the two campaign file paths.

---

## Out of scope (do NOT do here)

- No change to the per-throw `report.html` contents or the GT solve (that is G1).
- No change to `session.json` schema or any derived key (`calibrate_bias.load_record` depends on them).
- No git initialisation (separate item; consult the team first).
- No tuning of `beam_half_angle_deg` or `kalman.sigma_pos_m` (hardware items 14).

## Acceptance checklist

- [ ] `sessions.demo_subdir` in config; new `simulate_session.py` writes under `data/sessions/demo/`.
- [ ] `is_session_dir` is the single predicate in web_report + analyze_campaign + calibrate_bias.
- [ ] Live campaign excludes `demo/`; demo campaign excludes live; neither loads a `campaign.html`.
- [ ] `simulate_session.py` auto-regenerates the demo campaign; graceful-skips on zero throws.
- [ ] Existing synthetic dirs migrated into `data/sessions/demo/`; move-log recorded.
- [ ] Full pytest suite green (≥ 195 + new D5 tests); IMPLEMENTATION_NOTES Part 9 written.
