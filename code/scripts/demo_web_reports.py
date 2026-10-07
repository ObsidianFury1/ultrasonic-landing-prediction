"""Generate viewable HTML reports from synthetic data (no hardware needed).

A convenience/demo tool: it (1) generates N synthetic throws with the beam cone
OFF (the configured 7 deg cone is an unverified placeholder that admits zero
campaign-speed triplets), (2) processes each through the real offline pipeline
(process_session -> prediction + trajectory.csv), then (3) renders the per-throw
report.html and the campaign.html (pipeline.web_report). With --with-ground-truth
it also writes a ground_truth block for ~half the throws via the AUDITED v2.3 G1
solve (run_session.solve_ground_truth over the centroid + the 2 recommended
sensors, distances taken from the simulator's TRUE landing) so the FROZEN per-throw
view and a populated campaign are visible.

This is for LOOKING at the pages without hardware. The real paths are
run_session.py --web (live) and serve_report.py --session <id> (browser GT entry).

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\demo_web_reports.py
    .\\venv\\Scripts\\python.exe scripts\\demo_web_reports.py --n-sessions 5 --with-ground-truth
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_session                                   # reuse solve_ground_truth
from pipeline.geometry import recommend_reference_sensors
from pipeline.process_throw import process_session
from pipeline.simulator import (
    generate_session,
    random_throw,
    session_directory_names,
)
from pipeline.web_report import render_campaign_report, render_session_report

sys.path.insert(0, str(Path(__file__).resolve().parent))   # for append_ground_truth
from append_ground_truth import update_session_ground_truth


def _make_one(config, folder, rng):
    """Write + process one detectable synthetic session, or None if undetectable."""
    from tests.session_factory import write_session_dir
    throw = random_throw(rng)
    session = generate_session(config, throw, temperature_c=22.4, noise_mm=8.0,
                               rng=rng, beam_cone_enabled=False)
    write_session_dir(folder, session, 22.4)
    try:
        process_session(folder, config)
    except ValueError as exc:                        # undetectable / too few triplets
        print(f"  skip {folder.name}: {exc}")
        return None
    return folder


def _add_ground_truth(config, folder):
    """Write a ground_truth block from the simulator's TRUE landing via the real
    v2.3 G1 multilateration solve (centroid + the 2 recommended sensors)."""
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    truth = (meta.get("truth") or {}).get("landing")
    pred = (meta.get("prediction") or {}).get("raw")
    if not truth or not pred:
        return
    names = recommend_reference_sensors((pred["x_m"], pred["z_m"]), config)
    mark = np.array([truth["x_m"], truth["z_m"]])
    l_c = float(np.hypot(*mark))
    refs = [{"name": n, "L": float(np.hypot(*(mark - np.array(config["array"][n + "_xz"]))))}
            for n in names]
    try:
        gt = run_session.solve_ground_truth(l_c, refs, config)
    except (ValueError, TypeError):
        return
    update_session_ground_truth(folder / "session.json", gt)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-sessions", type=int, default=3)
    p.add_argument("--with-ground-truth", action="store_true",
                   help="also write ground truth for ~half the throws (frozen view)")
    p.add_argument("--out-dir", type=Path, default=Path("data") / "sessions",
                   help="LIVE sessions root; demo sessions go to <out-dir>/<demo-subdir>")
    p.add_argument("--demo-subdir", type=str, default=None,
                   help="(D5) override sessions.demo_subdir; demo sessions are "
                        "written under <out-dir>/<demo-subdir>")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    out_dir = Path(args.out_dir)
    # (D5) demo sessions live under data/sessions/<demo_subdir>/, never the live
    # root, so this convenience viewer can't pollute the live campaign (CLAUDE
    # section 0.3 / 12.2). --demo-subdir overrides the config for this run.
    demo_subdir = args.demo_subdir or config.get("sessions", {}).get("demo_subdir", "demo")
    demo_root = out_dir / demo_subdir
    demo_root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    # (D4) sim_ naming via the simulator's scheme, one batch timestamp for the
    # run; names[len(made)] is stable across undetectable-throw retries (the dir
    # is overwritten on retry, exactly as the old T## scheme behaved).
    names = session_directory_names(config, args.n_sessions, datetime.datetime.now())
    made = []
    attempt = 0
    while len(made) < args.n_sessions and attempt < args.n_sessions * 6:
        attempt += 1
        folder = demo_root / names[len(made)]
        if _make_one(config, folder, rng) is None:
            continue
        if args.with_ground_truth and len(made) % 2 == 0:
            _add_ground_truth(config, folder)
        report = render_session_report(folder, config)
        made.append((folder, report))

    if not made:
        sys.exit("no detectable sessions were produced; try a different --seed")

    campaign = render_campaign_report(demo_root, config)

    print("\nOpen these in a browser (file://):")
    for folder, report in made:
        gt = "ground_truth" in json.loads(
            (folder / "session.json").read_text(encoding="utf-8"))
        print(f"  [{'frozen' if gt else 'input'}] {report.resolve().as_uri()}")
    print(f"\nCampaign dashboard:\n  {campaign.resolve().as_uri()}")
    print("\nAn 'input' page needs the live server to accept tape entry:\n  "
          ".\\venv\\Scripts\\python.exe scripts\\serve_report.py --session "
          f"{made[0][0].name}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
