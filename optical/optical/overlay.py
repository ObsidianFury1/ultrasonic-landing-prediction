"""landing_overlay.png — human-readable per-throw landing (Optical.md §5.6).

The contact-adjacent frame with the tracked path drawn, the estimated contact point
marked, and a text block printing session ID, (r, theta) +- (sigma_r, sigma_theta),
method, and flags — readable at a glance without opening the JSON.

Rendered with matplotlib's Agg backend (no display needed). Colours follow the §12.6
functional channels: cyan = prediction, coral would be error (not shown here — the
optical module has no per-frame ground truth), steel = track.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import cv2  # noqa: E402

from optical.calibration import apply_homography  # noqa: E402

CYAN = "#22d3ee"
STEEL = "#7da0c4"
AMBER = "#f5b301"


def render_overlay(frame_bgr: np.ndarray, track, contact, optical_gt: dict,
                   H_px2floor: np.ndarray):
    """Build the overlay figure. `contact` may be None (failure mode: no prediction).
    Returns a matplotlib Figure (caller saves/closes)."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    fig, ax = plt.subplots(figsize=(w / 100.0, h / 100.0), dpi=100)
    ax.imshow(rgb)
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")

    if track is not None:
        v = track.valid
        ax.plot(track.centroid_px[v, 0], track.centroid_px[v, 1], "-o",
                color=STEEL, ms=2.5, lw=1.0, label="tracked path")

    landing = optical_gt.get("landing")
    lines = [f"session {optical_gt['session_id']}"]
    if landing is not None and contact is not None:
        H_f2p = np.linalg.inv(H_px2floor)
        land_uv = apply_homography(H_f2p, [landing["x_m"], landing["z_m"]])[0]
        ax.plot([land_uv[0]], [land_uv[1]], "X", color=CYAN, ms=12,
                mew=2, label="predicted contact")
        u = optical_gt["uncertainty"]
        lines += [
            f"r = {landing['r_m']:.3f} +- {u['sigma_r_m']:.3f} m",
            f"th = {landing['theta_deg']:.1f} +- {u['sigma_theta_deg']:.2f} deg",
            f"x,z = {landing['x_m']:.3f}, {landing['z_m']:.3f} m",
            f"method = {optical_gt['method']['detector']}/"
            f"{optical_gt['method']['parallax']}",
        ]
    else:
        lines += ["NO VALID PREDICTION",
                  f"n_tracked = {optical_gt['quality']['n_tracked_frames']}"]
    flags = optical_gt["quality"]["flags"]
    lines.append("flags: " + (", ".join(flags) if flags else "none"))

    ax.text(0.015, 0.985, "\n".join(lines), transform=ax.transAxes,
            va="top", ha="left", family="monospace", fontsize=9, color="white",
            bbox=dict(boxstyle="round", facecolor="black", alpha=0.65,
                      edgecolor=AMBER if flags else CYAN))
    fig.tight_layout(pad=0)
    return fig


def save_overlay(path: str | Path, frame_bgr, track, contact, optical_gt,
                 H_px2floor) -> Path:
    """Render and save landing_overlay.png."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = render_overlay(frame_bgr, track, contact, optical_gt, H_px2floor)
    fig.savefig(path, dpi=100, facecolor="#0b0e14")
    plt.close(fig)
    return path


def summary_text(optical_gt: dict) -> str:
    """The terminal summary block (also printed by process_clip.py, §5.6)."""
    g = optical_gt
    out = [f"session   : {g['session_id']}",
           f"clip      : {g['clip']['file']} ({g['clip']['mode']}, "
           f"{g['clip']['fps_measured']:.2f} fps)",
           f"calib     : {g['calibration']['calib_id']} "
           f"(reproj {g['calibration']['reproj_rms_px']:.2f} px, "
           f"check {g['calibration']['check_point_err_m'] * 1000:.1f} mm)"]
    landing = g.get("landing")
    if landing is not None:
        u = g["uncertainty"]
        out += [f"landing   : r = {landing['r_m']:.3f} +- {u['sigma_r_m']:.3f} m, "
                f"theta = {landing['theta_deg']:.1f} +- {u['sigma_theta_deg']:.2f} deg",
                f"          : x = {landing['x_m']:.3f}, z = {landing['z_m']:.3f} m",
                f"method    : {g['method']['detector']}/{g['method']['parallax']}"]
    else:
        out.append("landing   : NO VALID PREDICTION")
    out += [f"contact   : t_frame {g['contact']['t_frame']}, "
            f"n_descent {g['contact']['n_descent_frames']}",
            f"tracked   : {g['quality']['n_tracked_frames']} frames",
            f"flags     : {', '.join(g['quality']['flags']) or 'none'}"]
    return "\n".join(out)
