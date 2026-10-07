"""Offline bias calibration across many single-throw sessions (section 8.7).

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\calibrate_bias.py --sessions data\\sessions\\*

Loads every session.json that carries BOTH a raw prediction and a ground
truth, fits the track-aligned correction with a calibrate/validate split,
and writes correction_model.json (path from config bias.model_path) plus a
calibration report next to it. The model is written even when the gate
rejects (mode='none') so run_session.py can state explicitly that no
correction is applied.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import math

import numpy as np
import yaml
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.bias import ThrowRecord, calibrate_with_validation, evaluate
from pipeline.web_report import is_session_dir  # (D5) shared session predicate


def power_n(scatter_m: float, bias_m: float, n: int, alpha: float):
    """(D3) Approximate N at which a two-sided (1-alpha) CI on the along-track
    bias would exclude zero: N ~ (t * s / b)^2, with t from scipy.stats.t (the
    same machinery bias.py uses — never a hardcoded 1.96). Returns None when
    the observed bias is ~0 (not estimable from this sample)."""
    if bias_m is None or abs(bias_m) < 1e-9 or scatter_m <= 0:
        return None
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, max(n - 1, 1)))
    return int(math.ceil((t_crit * scatter_m / abs(bias_m)) ** 2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sessions", nargs="+", required=True,
                   help="session directories (globs ok), each with session.json")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--alpha", type=float, default=None,
                   help="significance level (default: config bias.alpha)")
    p.add_argument("--model-out", type=Path, default=None,
                   help="output path (default: config bias.model_path)")
    p.add_argument("--split", type=float, default=0.5,
                   help="calibration fraction of the calibrate/validate split")
    p.add_argument("--seed", type=int, default=0, help="split shuffle seed")
    return p.parse_args()


def load_record(session_json: Path):
    """ThrowRecord from one session.json, or (None, reason)."""
    with open(session_json, encoding="utf-8") as f:
        meta = json.load(f)

    pred = meta.get("prediction", {}).get("raw")
    if not pred:
        return None, "no raw prediction"

    gt = meta.get("ground_truth")
    if not gt and meta.get("simulated"):
        gt = meta.get("truth", {}).get("landing")     # simulator TRUE landing
    if not gt:
        return None, "no ground truth"

    try:
        return ThrowRecord(
            x_pred=pred["x_m"], z_pred=pred["z_m"],
            x_actual=gt["x_m"], z_actual=gt["z_m"],
            heading_deg=pred["heading_deg"], v_h_m_s=pred["v_h_m_s"],
        ), None
    except KeyError as e:
        return None, f"missing field {e}"


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    alpha = args.alpha if args.alpha is not None else config["bias"]["alpha"]
    model_out = args.model_out or Path(config["bias"]["model_path"])

    folders = []
    for pattern in args.sessions:
        hits = glob.glob(pattern)
        folders.extend(Path(h) for h in (hits if hits else [pattern]))

    records, skipped = [], []
    for folder in sorted(folders):
        # (v2.4 D5) session-detection predicate: skip a path that is not a
        # session dir (e.g. a demo/ container or a stray campaign.html matched
        # by data\sessions\*) with no name matching (CLAUDE §8.7, §12.2).
        if not is_session_dir(folder):
            skipped.append((folder.name, "no session.json"))
            continue
        sj = folder / "session.json"
        rec, reason = load_record(sj)
        if rec is None:
            skipped.append((folder.name, reason))
        else:
            records.append((folder.name, rec))

    print(f"usable sessions: {len(records)}; skipped: {len(skipped)}")
    for name, reason in skipped:
        print(f"  skipped {name}: {reason}")

    min_throws = config["bias"]["min_throws"]
    if len(records) < min_throws:
        print(f"WARNING: only {len(records)} throws < bias.min_throws = "
              f"{min_throws} (campaign target is 15-20, R9) — calibration "
              "will be statistically weak or impossible.")

    recs = [r for _, r in records]
    model = calibrate_with_validation(recs, alpha, split_frac=args.split,
                                      rng=np.random.default_rng(args.seed))
    errs = evaluate(model, recs)

    # (D3) Campaign power note: observed along-track scatter s and |bias| b
    # set the N at which a 95% CI would exclude zero. A 'none' verdict at N
    # below that threshold is an expected underpowered null ("drag below noise
    # floor at this sample size"), not a pipeline failure.
    n = len(recs)
    s_along = model.along.std
    b_along = abs(model.along.mean)
    n_power = power_n(s_along, b_along, n, alpha)
    if n_power is None:
        power_line = ("Statistical power note: observed along-track bias is "
                      f"~0 mm — N to exclude zero is not estimable from this "
                      f"sample. Current N={n}.")
    else:
        power_line = ("Statistical power note: CI excludes zero at "
                      f"approximately N={n_power} throws. Current N={n}.")
    underpowered_null = (model.mode == "none" and n_power is not None
                         and n < n_power)
    null_line = ("Null result is consistent with 'drag below noise floor at "
                 "this sample size', not a pipeline failure."
                 if underpowered_null else "")

    with open(model_out, "w", newline="", encoding="utf-8") as f:
        json.dump(model.to_dict(), f, indent=2)
    report = {
        "n_sessions": n,
        "sessions": [name for name, _ in records],
        "alpha": alpha,
        "mode": model.mode,
        "verdict": model.diagnostics.get("verdict", ""),
        "along_track": model.to_dict()["along"],
        "cross_track": model.to_dict()["cross"],
        "all_throws_error_before_m": float(errs["before"].mean()),
        "all_throws_error_after_m": float(errs["after"].mean()),
        "power_n": n_power,
        "power_note": power_line,
        "underpowered_null": underpowered_null,
        "underpowered_null_note": null_line,
    }
    report_path = model_out.with_name(model_out.stem + "_report.json")
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"mode = {model.mode}")
    print(model.diagnostics.get("verdict", ""))
    print(f"along-track offset = {model.offset_along_m*1000:.1f} mm, "
          f"cross-track = {model.offset_cross_m*1000:.1f} mm")
    print(power_line)
    if null_line:
        print(null_line)
    print(f"wrote {model_out} and {report_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
