"""Per-session diagnostic plots (CLAUDE.md section 1 "reporting.py", section 5.6 plots/).

PURE PLOTTING: this module only visualizes what process_throw.py already wrote to
a session directory (trajectory.csv, triplets_raw.csv, session.json). It performs
no trilateration/Kalman/landing math and does not recompute the prediction — the
landing markers come straight from session.json; the only fit here is a cosmetic
re-fit of the already-written Kalman points to draw a smooth parabola.

It is the plotting/I/O member of pipeline/ (NOT one of the pure computational
modules of section 0.5): it reads the session's CSV/JSON and writes PNGs into
session_dir/plots/. No I/O beyond that.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.corrections import echo_us_to_m  # noqa: E402


def _ground_truth(meta: dict):
    """The ground-truth landing, or None (same fallback as calibrate_bias)."""
    gt = meta.get("ground_truth")
    if not gt and meta.get("simulated"):
        gt = meta.get("truth", {}).get("landing")
    if gt and "x_m" in gt and "z_m" in gt:
        return float(gt["x_m"]), float(gt["z_m"])
    return None


def _downrange(x, z, heading_deg):
    """Project horizontal position onto the throw heading (for the side view)."""
    phi = np.radians(heading_deg)
    return x * np.cos(phi) + z * np.sin(phi)


def _plot_trajectory_fit(path, df, meta, config):
    """Figure 1: top-down (x-z) and side (downrange-y) with the fitted parabola."""
    t = df["t_sample_s"].to_numpy(dtype=float)
    t0 = t - t[0]
    xr, yr, zr = (df[c].to_numpy(dtype=float) for c in ("x_raw_m", "y_raw_m", "z_raw_m"))
    xk, yk, zk = (df[c].to_numpy(dtype=float)
                  for c in ("x_kalman_m", "y_kalman_m", "z_kalman_m"))

    pred = meta.get("prediction", {}).get("raw", {})
    px, pz = pred.get("x_m"), pred.get("z_m")
    heading = float(pred.get("heading_deg", 0.0))
    radius = config["ball"]["radius_m"]
    gt = _ground_truth(meta)

    # Cosmetic fit over the Kalman points (the same points landing.py fit, so this
    # reproduces the pipeline parabola); the landing MARKER stays the stored value.
    ax_c = az_c = ay_c = None
    t_curve = None
    try:
        ax_c = np.polyfit(t0, xk, 1)
        az_c = np.polyfit(t0, zk, 1)
        ay_c = np.polyfit(t0, yk, 2)
        # floor contact: descending root of y(t) = ball radius
        roots = np.roots([ay_c[0], ay_c[1], ay_c[2] - radius])
        roots = sorted(r.real for r in roots if abs(r.imag) < 1e-9)
        t_land = next((r for r in reversed(roots) if r >= t0[-1] - 1e-9), None)
        hi = t_land if t_land is not None else t0[-1]
        t_curve = np.linspace(t0[0], hi, 200)
    except (np.linalg.LinAlgError, ValueError):
        t_curve = None

    fig, (ax_top, ax_side) = plt.subplots(1, 2, figsize=(12, 5))

    # --- top-down x vs z ---
    ax_top.scatter(xr, zr, s=18, c="0.6", label="raw trilateration", zorder=2)
    ax_top.plot(xk, zk, "-o", color="tab:blue", ms=3, label="Kalman path", zorder=3)
    if ax_c is not None:
        ax_top.plot(np.polyval(ax_c, t_curve), np.polyval(az_c, t_curve),
                    "--", color="tab:green", lw=1.2, label="fitted track", zorder=3)
    if px is not None:
        ax_top.plot(px, pz, "*", color="tab:red", ms=16,
                    label="predicted landing", zorder=5)
    if gt is not None:
        ax_top.plot(gt[0], gt[1], "P", color="tab:purple", ms=11,
                    label="ground truth", zorder=5)
    ax_top.set_xlabel("x [m]  (toward S1)")
    ax_top.set_ylabel("z [m]")
    ax_top.set_aspect("equal", adjustable="datalim")
    ax_top.set_title("Top-down")
    ax_top.legend(fontsize=8)
    ax_top.grid(True, alpha=0.3)

    # --- side view: downrange vs y ---
    s_raw = _downrange(xr, zr, heading)
    s_kal = _downrange(xk, zk, heading)
    ax_side.scatter(s_raw, yr, s=18, c="0.6", label="raw", zorder=2)
    ax_side.plot(s_kal, yk, "-o", color="tab:blue", ms=3, label="Kalman", zorder=3)
    if ax_c is not None:
        s_curve = _downrange(np.polyval(ax_c, t_curve), np.polyval(az_c, t_curve),
                             heading)
        ax_side.plot(s_curve, np.polyval(ay_c, t_curve), "--", color="tab:green",
                     lw=1.2, label="fitted parabola", zorder=3)
    if px is not None:
        ax_side.plot(_downrange(px, pz, heading), radius, "*", color="tab:red",
                     ms=16, label="predicted landing", zorder=5)
    if gt is not None:
        ax_side.plot(_downrange(gt[0], gt[1], heading), radius, "P",
                     color="tab:purple", ms=11, label="ground truth", zorder=5)
    ax_side.axhline(radius, color="0.7", lw=0.8, ls=":")
    ax_side.set_xlabel("downrange distance [m]")
    ax_side.set_ylabel("y height [m]")
    ax_side.set_title("Side view (parabola to floor)")
    ax_side.legend(fontsize=8)
    ax_side.grid(True, alpha=0.3)

    r, theta = pred.get("r_m"), pred.get("theta_deg")
    suptitle = meta.get("session_id", Path(path).parent.parent.name)
    if r is not None:
        suptitle += f"  -  predicted r={r:.3f} m, theta={theta:+.1f} deg"
    fig.suptitle(suptitle)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_range_vs_time(path, triplets, meta):
    """Figure 2: per-sensor range vs t_sample, gated vs ungated, throw shaded."""
    temperature = float(meta["temperature_c"])
    t_us = triplets["t_sample_us"].to_numpy(dtype=float)
    t0 = (t_us - t_us.min()) * 1e-6
    triplets = triplets.assign(_t_s=t0,
                               _range_m=echo_us_to_m(
                                   triplets["echo_us"].to_numpy(dtype=float),
                                   temperature))

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for sid, ax in zip((1, 2, 3), axes):
        sub = triplets[triplets["sensor"] == sid]
        finite = sub[np.isfinite(sub["_range_m"])]      # drop timeouts (echo 0)
        ok = finite[finite["reading_valid"] == 1]
        gated = finite[finite["reading_valid"] == 0]
        ax.scatter(ok["_t_s"], ok["_range_m"], s=22, c="tab:blue",
                   label="accepted", zorder=3)
        ax.scatter(gated["_t_s"], gated["_range_m"], s=40, c="tab:red",
                   marker="x", label="gated", zorder=3)
        # shade the in-throw window
        throw = sub[sub["in_throw"] == 1]
        if not throw.empty:
            ax.axvspan(throw["_t_s"].min(), throw["_t_s"].max(),
                       color="tab:green", alpha=0.08, zorder=1)
        ax.set_ylabel(f"S{sid} range [m]")
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("t_sample [s]  (relative to first reading)")
    fig.suptitle(f"{meta.get('session_id', '')}  -  per-sensor range vs time "
                 "(gate behaviour)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_session(session_dir, config) -> list[Path]:
    """Write trajectory_fit.png + range_vs_time.png into session_dir/plots/.

    Visualizes only what process_throw.py already wrote. Returns the written PNG
    paths, or [] (with a printed reason, never a raise) when the session has no
    usable trajectory.
    """
    session_dir = Path(session_dir)
    with open(session_dir / "session.json", encoding="utf-8") as f:
        meta = json.load(f)

    traj_path = session_dir / "trajectory.csv"
    if not traj_path.is_file():
        print(f"  plot skipped ({session_dir.name}): no trajectory.csv")
        return []
    df = pd.read_csv(traj_path)
    min_pts = config["landing"]["min_fit_points"]
    if len(df) < min_pts:
        print(f"  plot skipped ({session_dir.name}): trajectory.csv has "
              f"{len(df)} rows (< min_fit_points={min_pts})")
        return []

    plots_dir = session_dir / "plots"
    plots_dir.mkdir(exist_ok=True)

    out = []
    fig1 = plots_dir / "trajectory_fit.png"
    _plot_trajectory_fit(fig1, df, meta, config)
    out.append(fig1)

    triplets_path = session_dir / "triplets_raw.csv"
    if triplets_path.is_file():
        fig2 = plots_dir / "range_vs_time.png"
        _plot_range_vs_time(fig2, pd.read_csv(triplets_path), meta)
        out.append(fig2)
    else:
        print(f"  range_vs_time skipped ({session_dir.name}): no triplets_raw.csv")
    return out
