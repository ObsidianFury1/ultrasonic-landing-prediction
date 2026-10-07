"""
Common style + single source of truth for every number used in the deck figures.
Edit the DATA blocks below and re-run build_figures.py; all figures update.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle, FancyBboxPatch, Ellipse, Circle, Polygon
import matplotlib.patheffects as pe
import numpy as np
from pathlib import Path

OUT = Path("/mnt/user-data/outputs/figures")
OUT.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# PALETTE  (Politecnico-adjacent: deep ink, teal, warm red accent)
# ----------------------------------------------------------------------------
INK    = "#16222B"   # near-black text
TEAL   = "#177E89"   # primary
TEAL_D = "#0E5561"   # dark teal
TEAL_L = "#7FC6CE"   # light teal fill
RED    = "#C1443C"   # legacy / error / NO-GO
RED_L  = "#F0C4C1"
GREEN  = "#3E8E5A"   # corrected / GO
GOLD   = "#D4A02C"   # highlight / star
GREY   = "#8C9BA5"
GREY_L = "#E4E9EC"
PAPER  = "#FFFFFF"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": PAPER,
    "savefig.facecolor": PAPER,
    "axes.grid": True,
    "grid.color": GREY_L,
    "grid.linewidth": 0.8,
    "axes.axisbelow": True,
})

DPI = 220

# ----------------------------------------------------------------------------
# DATA — provenance-tagged.  CHANGE NUMBERS HERE ONLY.
# ----------------------------------------------------------------------------

# --- MEASURED, campaign (Final_Report.pdf, N = 31 ground-truthed throws) ---
CAMPAIGN = dict(
    n_throws=31,
    n_sessions=34,
    raw_mean=93.0, raw_median=95.0, raw_std=43.0, raw_min=16.0, raw_max=175.0,
    corr_mean_insample=66.0,
    heldout_raw=90.2, heldout_corr=56.1, heldout_p="6e-05",
    along_bias=67.5, along_ci=(45.7, 89.4),
    cross_bias=1.8, cross_ci=(-17.0, 20.7),
    triplets_mean=4.6, triplets_range=(4, 6),
    sigma_r=44.0, sigma_theta=2.9,
    date="2026-07-09",
)

# --- MEASURED, bench study (n = 200 per point) ---
SENSOR_OFFSETS = {"S1": -25.5, "S2": -22.5, "S3": -12.9}   # mm (reads short)

# --- SIMULATOR-CHARACTERISED ---
STENCIL = dict(forward=-24.0, hybrid_lo=-15.0, hybrid_hi=-12.0)  # mm along-track
ELLIPSE_COVERAGE = dict(nominal=95, empirical=93, n=54)          # synthetic throws

# --- TEST-MEASURED ---
CONTACT_SHIFT = dict(measured=19.13, kinematic=19.48)            # mm
R_BALL_MM = 119.4
M_BALL_KG = 0.620

# --- MEASURED, optical commissioning (from Presentation_Flow_Deck.pdf) ---
OPTICAL = dict(gate=15.0, measured=64.4, worst=152.1, drift_removed=61.9, error_floor=17.0)

# --- GEOMETRY / TIMING ---
ARRAY_SIDE_M = 1.000
TILT_DEG = 55
SLOT_MS = 18
PERIOD_MS = 54

# ----------------------------------------------------------------------------
# ABLATION  <<<< PLACEHOLDER — RE-RUN THE LEGACY CONFIG AND FILL THESE IN >>>>
# Set PLACEHOLDER = False once real numbers are in; the red watermark disappears.
# ----------------------------------------------------------------------------
PLACEHOLDER = True

ABLATION = dict(
    legacy_error=185.0,      # mm — mean 2-D error, legacy config, same 34 throws
    steps=[                  # each = mm REMOVED by switching that fix ON
        ("Fix 1\nSensor offset\ncalibration",  -42.0),
        ("Fix 2\nHybrid\nstencil",             -18.0),
        ("Fix 3\nMid-echo +\ny = r_ball",      -14.0),
        ("Fix 4\nKalman +\ntrack-frame bias",  -34.0),
        ("Fix 5\nThree-tape\nground truth",    -11.0),
    ],
    final_error=66.0,        # mm — anchor to the real corrected in-sample number
)


def watermark(ax, text="PLACEHOLDER — fill from ablation re-run"):
    """Stamp any figure whose numbers are not yet real."""
    if not PLACEHOLDER:
        return
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
            fontsize=15, color=RED, alpha=0.16, rotation=18, weight="bold", zorder=50)


def prov(ax, text, loc="lower right"):
    """Provenance tag — Production Note #2: every number is labelled."""
    xy = {"lower right": (0.995, -0.13, "right"),
          "lower left":  (0.0, -0.13, "left")}[loc]
    ax.text(xy[0], xy[1], text, transform=ax.transAxes, ha=xy[2], va="top",
            fontsize=8.0, color=GREY, style="italic")


def save(fig, name):
    p = OUT / f"{name}.png"
    fig.savefig(p, dpi=DPI, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print("wrote", p.name)
    return p


def box(ax, x, y, w, h, label, fc=TEAL_L, ec=TEAL_D, tc=INK, fs=10, lw=1.6, r=0.02, z=3, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.008,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw, zorder=z))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fs, color=tc, zorder=z + 1, weight=weight, linespacing=1.35)


def arrow(ax, p0, p1, c=INK, lw=2.0, ls="-", z=2, mut=16, style="-|>"):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=mut,
                                 color=c, lw=lw, linestyle=ls, zorder=z,
                                 shrinkA=2, shrinkB=2))


def blank(w=13, h=6.2):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100 * h / w)
    ax.axis("off"); ax.grid(False)
    return fig, ax


def title(ax, t, sub=None):
    ax.text(0, ax.get_ylim()[1] * 0.985, t, fontsize=15, weight="bold", va="top", ha="left")
    if sub:
        ax.text(0, ax.get_ylim()[1] * 0.905, sub, fontsize=10.5, color=GREY, va="top", ha="left")
