"""Add ground truth to an existing session after the fact (CLAUDE.md sections 5.5, 8.7).

In a live campaign the first-contact mark often cannot be measured immediately
(chalk dust settles, slow-motion video needs review), so the throw is processed
and reported first and the ground truth is appended later. This REUSES
run_session.py's exact centroid + 2-sensor multilateration protocol
(geometry.ground_truth_landing via run_session.prompt_ground_truth) and writes
ONLY the `ground_truth` block into the session's session.json, leaving every other
field untouched.

A prediction must already exist in the session: its predicted (x, z) drives the
sensor recommendation (same as the live path). If it does not, process the
session first.

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\append_ground_truth.py 2026-06-11_T01
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_session  # sibling script: reuse prompt_ground_truth + load_config + _write_json
from pipeline.web_report import render_campaign_report, render_session_report


def update_session_ground_truth(session_json_path: Path, gt_block: dict) -> None:
    """Set ONLY meta['ground_truth'] and rewrite ATOMICALLY (section 6.2.1).

    Loads the full dict, appends the one new key (every other key preserved in
    order), and writes via a same-directory temp file + fsync + os.replace so a
    crash mid-write leaves the PREVIOUS valid session.json, never a half-written
    one (raw data is sacred). Same indent=2 serialization as run_session._write_json.
    """
    session_json_path = Path(session_json_path)
    with open(session_json_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["ground_truth"] = gt_block

    fd, tmp = tempfile.mkstemp(dir=session_json_path.parent,
                               prefix=".session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, session_json_path)        # atomic same-filesystem rename
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)                          # leave the original untouched
        raise


def append_to_session(config: dict, session_json_path: Path) -> dict | None:
    """Prompt the two-tape ground truth and write it into the session. Returns
    the ground_truth block, or None when there was nothing to add."""
    with open(session_json_path, encoding="utf-8") as f:
        meta = json.load(f)
    raw = meta.get("prediction", {}).get("raw")
    if not raw or "x_m" not in raw or "z_m" not in raw:
        print("session has no prediction yet; process it first (run_session / "
              "process_throw) so the sensor recommendation can be computed.")
        return None
    # Shim carrying the predicted (x, z) that prompt_ground_truth uses to compute
    # the recommended reference sensors (v2.3 G1).
    shim = SimpleNamespace(prediction={"raw": {"x_m": raw["x_m"],
                                               "z_m": raw["z_m"]}})
    gt = run_session.prompt_ground_truth(config, shim)
    if gt is None:
        print("no ground truth entered; nothing changed.")
        return None
    update_session_ground_truth(session_json_path, gt)
    # (M-3) Refresh the per-throw page (now frozen) and the subtree campaign,
    # coupled to the write like serve_report's POST handler. session_dir.parent is
    # the correct subtree root for both live and demo sessions (the is_session_dir
    # predicate excludes the other subtree).
    session_dir = session_json_path.parent
    render_session_report(session_dir, config)
    render_campaign_report(session_dir.parent, config)
    return gt


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("session_id", help="session directory name under --sessions-dir")
    p.add_argument("--sessions-dir", type=Path, default=Path("data") / "sessions")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = run_session.load_config(args.config)
    session_json = args.sessions_dir / args.session_id / "session.json"
    if not session_json.is_file():
        sys.exit(f"no session.json at {session_json}")
    gt = append_to_session(config, session_json)
    if gt is not None:
        print(f"updated ground truth in {session_json}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
