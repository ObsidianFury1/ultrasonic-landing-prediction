"""Generate synthetic session directories (CLAUDE.md section 6).

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\simulate_session.py --n-sessions 3 ^
        --drag quadratic --heading-range-deg 60 --noise-mm 8 --seed 42

Each session folder gets the raw byte stream the hardware would have produced
(raw_serial.log), session.json with the TRUE landing recorded, and true-
trajectory plots. By DEFAULT each session is then run through the offline
pipeline so the processing artifacts (triplets_raw.csv, trajectory.csv,
plots/, report.html) are written too -- giving a demo session the identical
layout as a live one (CLAUDE.md section 5.6 / 0.3). Pass --no-plot to skip
processing and emit raw + truth only.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import reporting
from pipeline.geometry import ArrayGeometry
from pipeline.process_throw import process_session
from pipeline.web_report import render_campaign_report, render_session_report
from pipeline.simulator import (
    SyntheticSession,
    default_drag_k,
    generate_session,
    random_throw,
    session_directory_names,
    speed_of_sound,
)

SENSOR_COLORS = {1: "tab:red", 2: "tab:green", 3: "tab:blue"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-sessions", type=int, default=1)
    p.add_argument("--speed-range", type=float, nargs=2, default=[3.0, 4.0],
                   metavar=("LO", "HI"), help="horizontal speed range [m/s]")
    p.add_argument("--heading-range-deg", type=float, default=60.0,
                   help="heading spread about +x [deg] (throws ~ U(-range, +range))")
    p.add_argument("--noise-mm", type=float, default=8.0,
                   help="1-sigma range noise [mm]")
    p.add_argument("--drag", choices=["none", "quadratic"], default="none")
    p.add_argument("--beam-cone", choices=["on", "off"], default=None,
                   help="(D2) override simulator.beam_cone_enabled from config")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--dropouts", type=int, default=0,
                   help="random mid-throw whole-triplet dropouts per session")
    p.add_argument("--temperature-c", type=float, default=20.0)
    p.add_argument("--out-dir", type=Path, default=Path("data") / "sessions",
                   help="LIVE sessions root; demo sessions go to <out-dir>/<demo-subdir>")
    p.add_argument("--demo-subdir", type=str, default=None,
                   help="(D5) override sessions.demo_subdir for this run; demo "
                        "sessions are written under <out-dir>/<demo-subdir>")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--no-plot", action="store_true",
                   help="skip processing + per-session diagnostic plots/report "
                        "(write raw_serial.log + truth only). By DEFAULT each "
                        "session is processed and gets plots/ + report.html so a "
                        "demo session has the identical layout as a live one (5.6).")
    return p.parse_args()


def plot_trajectory(session: SyntheticSession, geom: ArrayGeometry,
                    out_path: Path, session_id: str) -> None:
    traj = session.trajectory
    truth = session.truth
    landing = truth["landing"]

    fig = plt.figure(figsize=(16, 5.2))
    fig.suptitle(
        f"{session_id} — TRUE trajectory  |  drag={truth['throw']['drag']}, "
        f"landing r={landing['r_m']:.3f} m, theta={landing['theta_deg']:.1f} deg, "
        f"flight {truth['flight_time_s']:.2f} s, apex {truth['apex_y_m']:.2f} m"
    )

    sample_pts = {
        sid: np.array([traj.position(r["t_hit_s"] - truth["t_launch_s"])
                       for r in session.readings
                       if r["target"] and r["sensor_id"] == sid])
        for sid in (1, 2, 3)
    }
    v = geom.vertices_3d
    tri_x = np.append(v[:, 0], v[0, 0])
    tri_z = np.append(v[:, 2], v[0, 2])

    # 3D view
    ax = fig.add_subplot(1, 3, 1, projection="3d")
    ax.plot(traj.pos[:, 0], traj.pos[:, 2], traj.pos[:, 1], "k-", lw=1.2, label="true arc")
    for sid, pts in sample_pts.items():
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 2], pts[:, 1], s=14,
                       color=SENSOR_COLORS[sid], label=f"S{sid} samples")
    ax.plot(tri_x, tri_z, np.full(4, v[0, 1]), "o--", color="gray", ms=5, label="sensors")
    ax.scatter([landing["x_m"]], [landing["z_m"]], [0.0], marker="*", s=120,
               color="crimson", label="true landing")
    ax.set_xlabel("x [m]"); ax.set_ylabel("z [m]"); ax.set_zlabel("y [m]")
    ax.set_title("3D arc")
    ax.legend(fontsize=7, loc="upper left")

    # Floor plan (x-z)
    ax = fig.add_subplot(1, 3, 2)
    ax.plot(traj.pos[:, 0], traj.pos[:, 2], "k-", lw=1.2)
    ax.plot(tri_x, tri_z, "o--", color="gray")
    for i, name in enumerate(["S1", "S2", "S3"]):
        ax.annotate(name, geom.vertices_xz[i], textcoords="offset points", xytext=(6, 4))
    ax.plot(0, 0, "k+", ms=10)
    ax.plot(landing["x_m"], landing["z_m"], "*", color="crimson", ms=14)
    ax.annotate(f"  r={landing['r_m']:.2f} m\n  th={landing['theta_deg']:.1f} deg",
                (landing["x_m"], landing["z_m"]), fontsize=8)
    for sid, pts in sample_pts.items():
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 2], s=12, color=SENSOR_COLORS[sid])
    ax.set_xlabel("x [m]"); ax.set_ylabel("z [m]")
    ax.set_title("floor plan (view from above)")
    ax.set_aspect("equal"); ax.grid(alpha=0.3)

    # Side view (x-y)
    ax = fig.add_subplot(1, 3, 3)
    ax.plot(traj.pos[:, 0], traj.pos[:, 1], "k-", lw=1.2)
    for sid, pts in sample_pts.items():
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 1], s=12, color=SENSOR_COLORS[sid])
    ax.axhline(0.0, color="saddlebrown", lw=1)
    ax.plot(v[:, 0], v[:, 1], "o", color="gray")
    ax.plot(landing["x_m"], 0.0, "*", color="crimson", ms=14)
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    ax.set_title("side view (x-y)")
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_ranges(session: SyntheticSession, temperature_c: float,
                out_path: Path, session_id: str) -> None:
    truth = session.truth
    v_sound = speed_of_sound(temperature_c)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    window = 1.0  # s of context either side of the flight
    t0, t1 = truth["t_launch_s"] - window, truth["t_land_s"] + window
    for sid in (1, 2, 3):
        rows = [r for r in session.readings
                if r["sensor_id"] == sid and t0 <= r["t_trig_s"] <= t1]
        t = np.array([r["t_trig_s"] for r in rows])
        echo = np.array([r["echo_us"] for r in rows], dtype=float)
        d = v_sound * echo * 1e-6 / 2.0
        valid = echo > 0
        ax.plot(t[valid], d[valid], "o", ms=4, color=SENSOR_COLORS[sid], label=f"S{sid}")
        ax.plot(t[~valid], np.zeros((~valid).sum()), "x", ms=4,
                color=SENSOR_COLORS[sid], alpha=0.35)
    ax.axvspan(truth["t_launch_s"], truth["t_land_s"], color="gold", alpha=0.15,
               label="flight window")
    ax.set_xlabel("t_trig [s]"); ax.set_ylabel("apparent range to surface [m]")
    ax.set_title(f"{session_id} — sampled ranges (x at 0 = timeout)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def create_session_folder(out_dir: Path, session_id: str) -> Path:
    """(D4) Create the session directory; NEVER overwrite an existing one.

    With the time+counter naming scheme a collision should be impossible;
    if one happens anyway (clock rollback, manual dirs), refuse loudly —
    raw session data is sacred (CLAUDE.md section 0.4)."""
    folder = out_dir / session_id
    if folder.exists():
        raise RuntimeError(
            f"session directory already exists: {folder} — refusing to "
            "overwrite recorded session data")
    (folder / "plots").mkdir(parents=True)
    return folder


def write_session(session: SyntheticSession, out_dir: Path, session_id: str,
                  config: dict, args: argparse.Namespace, session_seed: int,
                  geom: ArrayGeometry) -> Path:
    folder = create_session_folder(out_dir, session_id)
    plots = folder / "plots"

    with open(folder / "raw_serial.log", "wb") as f:
        f.write(session.serial_bytes())

    meta = {
        "session_id": session_id,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "simulated": True,
        "seed": session_seed,
        "fw_header": session.serial_lines[0],
        "temperature_c": args.temperature_c,
        "truth": session.truth,
        "config_snapshot": config,
    }
    with open(folder / "session.json", "w", newline="", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    plot_trajectory(session, geom, plots / "trajectory_true.png", session_id)
    plot_ranges(session, args.temperature_c, plots / "ranges_true.png", session_id)
    return folder


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    geom = ArrayGeometry.from_config(config)

    # (D5) Demo sessions live under data/sessions/<demo_subdir>/, separate from
    # live (hardware) sessions, so the live campaign never mixes synthetic and
    # real throws (CLAUDE section 0.3 / 5.6 / 12.2). --demo-subdir overrides the
    # config for this run. The internal session layout is identical to a live one.
    demo_subdir = args.demo_subdir or config.get("sessions", {}).get("demo_subdir", "demo")
    demo_root = args.out_dir / demo_subdir
    demo_root.mkdir(parents=True, exist_ok=True)

    master = np.random.default_rng(args.seed)
    drag_k = default_drag_k(config["ball"]["radius_m"]) if args.drag == "quadratic" else 0.0
    # (D2) cone model: CLI flag overrides config; this entry point is where
    # simulator.beam_cone_enabled is honored.
    if args.beam_cone is not None:
        beam_cone = args.beam_cone == "on"
    else:
        beam_cone = bool(config.get("simulator", {}).get("beam_cone_enabled", False))
    # (D4) ONE timestamp per batch: every session of this run shares it and
    # differs only by the S## counter (no mid-batch second-rollover).
    batch_time = datetime.datetime.now()
    session_ids = session_directory_names(config, args.n_sessions, batch_time)

    for i in range(args.n_sessions):
        session_seed = int(master.integers(0, 2**32))
        rng = np.random.default_rng(session_seed)
        throw = random_throw(
            rng,
            speed_range=tuple(args.speed_range),
            heading_range_deg=args.heading_range_deg,
            drag=args.drag,
            drag_k=drag_k,
        )
        session = generate_session(
            config, throw,
            temperature_c=args.temperature_c,
            noise_mm=args.noise_mm,
            rng=rng,
            n_dropouts=args.dropouts,
            beam_cone_enabled=beam_cone,
        )
        session_id = session_ids[i]
        folder = write_session(session, demo_root, session_id, config, args,
                               session_seed, geom)
        landing = session.truth["landing"]
        print(f"{session_id}: drag={args.drag}, "
              f"heading throw seed={session_seed}, "
              f"TRUE landing r={landing['r_m']:.3f} m, "
              f"theta={landing['theta_deg']:+.1f} deg, "
              f"flight={session.truth['flight_time_s']:.2f} s, "
              f"{session.truth['n_triplets']['flight']} flight triplets "
              f"-> {folder}")

        # By default, process each session through the offline pipeline so the
        # per-throw figures AND the per-throw HTML report are written -- giving the
        # demo session the identical internal layout as a live one (CLAUDE section
        # 5.6 / 0.3: report.html). --no-plot skips this (raw + truth only).
        if not args.no_plot:
            try:
                process_session(folder, config)
                for p in reporting.plot_session(folder, config):
                    print(f"  plot: {p}")
                render_session_report(folder, config)
            except ValueError as exc:
                print(f"  plot skipped ({session_id}): {exc}")

    # (D5a) Auto-regenerate the demo campaign so data/sessions/<demo_subdir>/
    # campaign.html is never stale -- the same renderer the live path uses,
    # pointed at the demo root (CLAUDE section 6 / 12.2). Best-effort: a stress
    # run with zero detectable throws must not crash here after the sessions are
    # already on disk, mirroring --plot's graceful skip.
    try:
        render_campaign_report(demo_root, config)
    except Exception as exc:                       # noqa: BLE001 -- cosmetic artifact
        print(f"  demo campaign skipped: {exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
