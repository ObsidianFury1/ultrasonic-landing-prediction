"""Campaign analysis across many ground-truthed sessions (CLAUDE.md section 8.7).

Pure consumption of what process_throw.py and bias.py already wrote: it loads every
session that has BOTH a prediction and ground truth, prints raw + bias-corrected
landing-error statistics and the D3 power note, and saves five diagnostic figures.
It REUSES calibrate_bias.load_record (so it agrees on which sessions count),
calibrate_bias.power_n, bias.evaluate / apply_correction, and — for the raw vs
Kalman comparison — landing.predict_landing on the raw trilateration positions in
trajectory.csv. It loads an existing correction_model.json; it never refits one.

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\analyze_campaign.py --sessions data\\sessions\\*
"""

import argparse
import glob
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from matplotlib.patches import Ellipse  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calibrate_bias  # sibling script: reuse load_record + power_n
from pipeline.bias import CorrectionModel, ThrowRecord, evaluate, to_track
from pipeline.kalman import FilterResult
from pipeline.landing import predict_landing
from pipeline.web_report import is_session_dir  # (D5) shared session predicate


@dataclass
class CampaignThrow:
    session_id: str
    session_dir: Path
    x_pred: float
    z_pred: float
    x_actual: float
    z_actual: float
    heading_deg: float
    v_h_m_s: float
    cov_xz: np.ndarray | None
    sigma_r: float
    sigma_theta: float
    n_triplets_used: int | None

    def to_record(self) -> ThrowRecord:
        return ThrowRecord(self.x_pred, self.z_pred, self.x_actual, self.z_actual,
                           self.heading_deg, self.v_h_m_s)

    @property
    def error_2d(self) -> float:
        return float(np.hypot(self.x_pred - self.x_actual, self.z_pred - self.z_actual))


def load_campaign(session_globs) -> list[CampaignThrow]:
    """Every session with a prediction AND ground truth (reusing load_record)."""
    throws = []
    for pattern in session_globs:
        hits = glob.glob(pattern)
        for h in (hits if hits else [pattern]):
            p = Path(h)
            # (v2.4 D5) session-detection predicate: a directory counts iff it
            # holds session.json (skips a demo/ container or stray campaign.html
            # with no name matching, CLAUDE §8.7, §12.2). A glob may also point
            # straight at a session.json file -- accept that too.
            if p.is_dir():
                if not is_session_dir(p):
                    print(f"  skip {p.name}: no session.json")
                    continue
                session_json = p / "session.json"
            elif p.is_file() and p.name == "session.json":
                session_json = p          # a glob pointed straight at session.json
            else:
                # a stray file (e.g. our own campaign.html matched by root/*)
                print(f"  skip {p.name}: not a session")
                continue
            rec, reason = calibrate_bias.load_record(session_json)
            if rec is None:
                print(f"  skip {session_json.parent.name}: {reason}")
                continue
            with open(session_json, encoding="utf-8") as f:
                meta = json.load(f)
            raw = meta["prediction"]["raw"]
            cov = raw.get("cov_xz_m2")
            throws.append(CampaignThrow(
                session_id=meta.get("session_id", session_json.parent.name),
                session_dir=session_json.parent,
                x_pred=rec.x_pred, z_pred=rec.z_pred,
                x_actual=rec.x_actual, z_actual=rec.z_actual,
                heading_deg=rec.heading_deg, v_h_m_s=rec.v_h_m_s,
                cov_xz=np.array(cov, dtype=float) if cov is not None else None,
                sigma_r=float(raw.get("sigma_r_m", np.nan)),
                sigma_theta=float(raw.get("sigma_theta_deg", np.nan)),
                n_triplets_used=meta.get("gate_summary", {}).get("n_triplets_used")))
    return throws


def _mean_std_ci(errors, alpha):
    e = np.asarray(errors, dtype=float)
    n = len(e)
    mean = float(np.mean(e)) if n else float("nan")
    if n >= 2:
        std = float(np.std(e, ddof=1))
        sem = std / np.sqrt(n)
        t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, n - 1))
        ci = (mean - t_crit * sem, mean + t_crit * sem)
    else:
        std, ci = float("nan"), (float("nan"), float("nan"))
    return mean, std, ci


def summary_stats(throws, model=None, alpha: float = 0.05) -> dict:
    """Raw + bias-corrected 2D-error stats and the D3 power note (no refit)."""
    raw_err = np.array([t.error_2d for t in throws])
    out = {"n": len(throws)}
    out["raw_mean_m"], out["raw_std_m"], out["raw_ci_m"] = _mean_std_ci(raw_err, alpha)
    if model is not None:
        after = evaluate(model, [t.to_record() for t in throws])["after"]
        out["corrected_mean_m"], out["corrected_std_m"], out["corrected_ci_m"] = \
            _mean_std_ci(after, alpha)
    else:
        out["corrected_mean_m"] = out["corrected_std_m"] = out["corrected_ci_m"] = None

    # D3 power note over the campaign's along-track residuals (reuses power_n).
    along = np.array([to_track(t.x_pred - t.x_actual, t.z_pred - t.z_actual,
                               t.heading_deg)[0] for t in throws])
    n = len(along)
    bias = float(np.mean(along)) if n else float("nan")
    scatter = float(np.std(along, ddof=1)) if n >= 2 else float("nan")
    n_power = calibrate_bias.power_n(scatter, abs(bias), n, alpha) if n >= 2 else None
    mode = model.mode if model is not None else "none"
    underpowered = bool(mode == "none" and n_power is not None and n < n_power)
    out.update(along_bias_m=bias, along_scatter_m=scatter, power_n=n_power,
               mode=mode, underpowered_null=underpowered)
    if n_power is None:
        out["power_note"] = ("Statistical power note: observed along-track bias is ~0; "
                             f"N to exclude zero is not estimable from this sample. N={n}.")
    else:
        conf = f"{(1.0 - alpha) * 100:.0f}%"
        out["power_note"] = (f"Statistical power note: a {conf} CI excludes zero at "
                             f"approximately N={n_power} throws. Current N={n}.")
    out["underpowered_null_note"] = (
        "Null result is consistent with 'drag below noise floor at this sample size', "
        "not a pipeline failure." if underpowered else "")
    return out


def print_summary(s: dict) -> None:
    print(f"\n=== Campaign summary (N={s['n']} ground-truthed throws) ===")
    lo, hi = s["raw_ci_m"]
    print(f"  raw 2D error:      mean {s['raw_mean_m'] * 1e3:6.1f} mm  "
          f"std {s['raw_std_m'] * 1e3:5.1f} mm  "
          f"95% CI [{lo * 1e3:.1f}, {hi * 1e3:.1f}] mm")
    if s["corrected_mean_m"] is not None:
        clo, chi = s["corrected_ci_m"]
        print(f"  corrected (mode={s['mode']}): mean {s['corrected_mean_m'] * 1e3:6.1f} mm  "
              f"std {s['corrected_std_m'] * 1e3:5.1f} mm  "
              f"95% CI [{clo * 1e3:.1f}, {chi * 1e3:.1f}] mm")
    else:
        print("  corrected:         no correction_model.json (raw only)")
    print(f"  along-track bias {s['along_bias_m'] * 1e3:+.1f} mm, "
          f"scatter {s['along_scatter_m'] * 1e3:.1f} mm")
    print(f"\n  >> {s['power_note']}")
    if s["underpowered_null_note"]:
        print(f"  >> {s['underpowered_null_note']}")


def _raw_landing(session_dir: Path, config: dict):
    """Landing from the RAW trilateration positions in trajectory.csv, or None.

    Reuses predict_landing by wrapping the raw positions in a FilterResult; the
    landing point comes from the position fits, so the dummy velocity is harmless.
    """
    traj = session_dir / "trajectory.csv"
    if not traj.is_file():
        return None
    df = pd.read_csv(traj)
    mfp = config["landing"]["min_fit_points"]
    if len(df) < mfp:
        return None
    t = df["t_sample_s"].to_numpy(dtype=float)
    raw_xyz = df[["x_raw_m", "y_raw_m", "z_raw_m"]].to_numpy(dtype=float)
    filt = FilterResult(t_s=t, pos=raw_xyz, vel=np.zeros_like(raw_xyz),
                        bias=np.ones(len(t)))
    try:
        pred = predict_landing(filt, ball_radius_m=config["ball"]["radius_m"],
                               min_fit_points=mfp)
    except ValueError:
        return None
    return pred.x, pred.z


def _add_ellipse(ax, center, cov):
    vals, vecs = np.linalg.eigh(np.asarray(cov, dtype=float))
    vals = np.clip(vals, 0.0, None)
    angle = float(np.degrees(np.arctan2(vecs[1, 1], vecs[0, 1])))
    width, height = 2.0 * np.sqrt(vals[1]), 2.0 * np.sqrt(vals[0])
    ax.add_patch(Ellipse(center, width, height, angle=angle, fill=False,
                         edgecolor="tab:blue", lw=0.6, alpha=0.5))


def make_plots(throws, out_dir, config) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. triplets-per-throw histogram (beam-cone tuning check, item 14 / D2)
    nts = [t.n_triplets_used for t in throws if t.n_triplets_used is not None]
    if nts:
        fig, ax = plt.subplots()
        ax.hist(nts, bins=range(min(nts), max(nts) + 2), align="left",
                rwidth=0.85)
        ax.set_xlabel("triplets used per throw")
        ax.set_ylabel("count")
        ax.set_title("Triplets per throw (beam-cone tuning check)")
        fig.savefig(out_dir / "triplets_hist.png", dpi=120)
        plt.close(fig)

    # 2. raw-trilateration vs Kalman landing error
    pairs = []
    for t in throws:
        rl = _raw_landing(t.session_dir, config)
        if rl is None:
            continue
        raw_err = float(np.hypot(rl[0] - t.x_actual, rl[1] - t.z_actual))
        pairs.append((t.session_id, raw_err, t.error_2d))
    if pairs:
        idx = np.arange(len(pairs))
        fig, ax = plt.subplots()
        ax.bar(idx - 0.2, [p[1] * 1e3 for p in pairs], 0.4, label="raw trilateration")
        ax.bar(idx + 0.2, [p[2] * 1e3 for p in pairs], 0.4, label="Kalman")
        ax.set_xlabel("throw")
        ax.set_ylabel("2D landing error [mm]")
        ax.set_title("Raw vs Kalman landing error")
        ax.legend()
        fig.savefig(out_dir / "raw_vs_kalman_error.png", dpi=120)
        plt.close(fig)

    # 3. error vs triplets used
    pts = [(t.n_triplets_used, t.error_2d * 1e3) for t in throws
           if t.n_triplets_used is not None]
    if pts:
        fig, ax = plt.subplots()
        ax.scatter([p[0] for p in pts], [p[1] for p in pts])
        ax.set_xlabel("triplets used")
        ax.set_ylabel("2D error [mm]")
        ax.set_title("Error vs triplets used (does more data help?)")
        fig.savefig(out_dir / "error_vs_ntriplets.png", dpi=120)
        plt.close(fig)

    # 4. error vs heading (symmetric-corridor check, section 11)
    fig, ax = plt.subplots()
    ax.scatter([t.heading_deg for t in throws], [t.error_2d * 1e3 for t in throws])
    ax.set_xlabel("heading [deg]")
    ax.set_ylabel("2D error [mm]")
    ax.set_title("Error vs heading (symmetric-corridor check)")
    fig.savefig(out_dir / "error_vs_heading.png", dpi=120)
    plt.close(fig)

    # 5. predicted vs actual with per-throw 1-sigma ellipses (R7)
    fig, ax = plt.subplots()
    for t in throws:
        ax.plot([t.x_pred], [t.z_pred], "o", color="tab:blue", ms=4)
        ax.plot([t.x_actual], [t.z_actual], "x", color="tab:red", ms=6)
        ax.plot([t.x_pred, t.x_actual], [t.z_pred, t.z_actual],
                color="gray", lw=0.5)
        if t.cov_xz is not None and np.all(np.isfinite(t.cov_xz)):
            _add_ellipse(ax, (t.x_pred, t.z_pred), t.cov_xz)
    ax.plot([], [], "o", color="tab:blue", label="predicted")
    ax.plot([], [], "x", color="tab:red", label="actual")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("z [m]")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Predicted vs actual (1-sigma ellipses, R7)")
    ax.legend()
    fig.savefig(out_dir / "predicted_vs_actual.png", dpi=120)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sessions", nargs="+", required=True,
                   help="session directories (globs ok), each with session.json")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--out-dir", type=Path, default=Path("campaign_report"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    model = None
    model_path = Path(config["bias"]["model_path"])
    if model_path.is_file():
        with open(model_path, encoding="utf-8") as f:
            model = CorrectionModel.from_dict(json.load(f))
        print(f"loaded bias correction model (mode={model.mode})")

    throws = load_campaign(args.sessions)
    if not throws:
        sys.exit("no sessions with both a prediction and ground truth")
    print(f"loaded {len(throws)} ground-truthed throw(s)")

    print_summary(summary_stats(throws, model, config["bias"]["alpha"]))
    make_plots(throws, args.out_dir, config)
    print(f"\nwrote figures to {args.out_dir}/")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
