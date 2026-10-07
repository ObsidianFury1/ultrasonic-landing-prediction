from deck_common import *
from matplotlib.lines import Line2D

# ============================================================================
# SLIDE 7 — Error-budget diagram: source → pipeline stage
# ============================================================================
fig, ax = blank(13, 5.6)
title(ax, "Where the error comes from",
      "Each of the next five slides kills one of these")

stages = ["RANGE", "POSITION", "GEOMETRY", "EXTRAPOLATION"]
w, gap, x0, y0, h = 19.5, 6.0, 2.0, 8.0, 9.0
cx = []
for i, st in enumerate(stages):
    x = x0 + i * (w + gap)
    cx.append(x + w / 2)
    box(ax, x, y0, w, h, st, fc=TEAL_L, ec=TEAL_D, fs=11, weight="bold", r=0.03)
    if i < 3:
        arrow(ax, (x + w + 0.6, y0 + h / 2), (x + w + gap - 0.6, y0 + h / 2), lw=2.2, mut=18)

sources = [
    ("Sensor bias\n(each sensor reads short)", 0, "Fix 1"),
    ("Staggered firing (54 ms)\n+ sampling instant", 1, "Fix 2 · Fix 3"),
    ("Surface-vs-centre\n(echo ≠ ball centre)", 2, "Fix 3"),
    ("Drag\n(not in the gravity-only model)", 3, "Fix 4"),
]
ys = 30.0
for lab, idx, fx in sources:
    x = cx[idx]
    ax.text(x, ys + 3.2, lab, ha="center", va="center", fontsize=9.4, color=INK, linespacing=1.4,
            bbox=dict(boxstyle="round,pad=0.42", fc=RED_L, ec=RED, lw=1.2))
    arrow(ax, (x, ys - 1.4), (x, y0 + h + 0.4), c=RED, lw=2.0, mut=15)
    ax.text(x + 0.4, (ys - 1.4 + y0 + h) / 2, fx, ha="left", va="center",
            fontsize=8.6, color=RED, weight="bold", style="italic")

ax.text(50, 4.0,
        "Ground truth itself is an error source (Fix 5) — you cannot claim mm-level prediction error without mm-level truth.",
        ha="center", fontsize=10, color=GOLD, weight="bold")
save(fig, "slide07_error_budget")

# ============================================================================
# SLIDE 8 — ★ Fix 1: per-sensor offset calibration (bench data)
# ============================================================================
fig = plt.figure(figsize=(13, 5.8))
gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1], wspace=0.30)

ref = np.array([0.5, 0.8, 1.1, 1.4, 1.7, 2.0])
axA = fig.add_subplot(gs[0])
axA.plot([0.4, 2.1], [0.4, 2.1], color=INK, lw=1.6, ls="--", label="ideal (measured = reference)")
cols = {"S1": TEAL_D, "S2": TEAL, "S3": GOLD}
for name, off in SENSOR_OFFSETS.items():
    meas = ref + off / 1000.0
    axA.plot(ref, meas, "o-", color=cols[name], ms=7, lw=1.8,
             label=f"{name}   offset = {off:+.1f} mm")
    axA.errorbar(ref, meas, yerr=0.0035, fmt="none", ecolor=cols[name], capsize=3, alpha=0.8)
axA.set_xlabel("reference distance  [m]"); axA.set_ylabel("mean measured range  [m]")
axA.legend(loc="upper left", fontsize=9.5, frameon=True)
axA.set_title("Bench study — every sensor reads SHORT, by a different amount",
              fontsize=12, weight="bold", loc="left")
prov(axA, "BENCH-MEASURED, n = 200 per point per sensor")

axB = fig.add_subplot(gs[1])
names = list(SENSOR_OFFSETS)
vals = [SENSOR_OFFSETS[k] for k in names]
sem = [0.35, 0.32, 0.30]
bars = axB.bar(names, vals, color=[cols[k] for k in names], edgecolor=INK, lw=1.2, width=0.58)
axB.errorbar(names, vals, yerr=[3 * s for s in sem], fmt="none", ecolor=INK, capsize=7, lw=1.8)
for b, v in zip(bars, vals):
    axB.text(b.get_x() + b.get_width() / 2, v - 1.6, f"{v:+.1f} mm",
             ha="center", va="top", fontsize=11, weight="bold", color="white",
             path_effects=[pe.withStroke(linewidth=2.6, foreground=INK)])
axB.axhline(0, color=INK, lw=1.6)
axB.set_ylabel("offset  [mm]   (negative = reads short)")
axB.set_ylim(-31, 5)
axB.set_title("All three far outside 3 × SEM\n→ systematic, not noise", fontsize=12, weight="bold", loc="left")
axB.text(0.5, -0.30, r"correction:   $d_{corr} = d_{meas} - \mathrm{offset}_k$   (per sensor, every range)",
         transform=axB.transAxes, ha="center", fontsize=11, color=GREEN, weight="bold",
         bbox=dict(boxstyle="round,pad=0.45", fc="#E8F3EC", ec=GREEN, lw=1.2))
d = ABLATION["steps"][0][1]
axB.text(0.5, 1.02, f"ABLATION DELTA:  {d:+.0f} mm", transform=axB.transAxes, ha="center",
         va="bottom", fontsize=11.5, weight="bold", color=RED if PLACEHOLDER else GREEN,
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=RED if PLACEHOLDER else GREEN, lw=1.4))
if PLACEHOLDER:
    axB.text(0.5, 1.14, "[ PLACEHOLDER — fill from ablation ]", transform=axB.transAxes,
             ha="center", va="bottom", fontsize=8.5, color=RED, style="italic")
save(fig, "slide08_fix1_sensor_offsets")

# ============================================================================
# SLIDE 9 — ★ Fix 2: hybrid differencing stencil
# ============================================================================
fig = plt.figure(figsize=(13, 5.9))
gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1], wspace=0.28)

t = np.linspace(0, 1.0, 400)
y = 0.4 + 3.2 * t - 4.9 * t ** 2 * 1.0
x = 2.6 * t
axA = fig.add_subplot(gs[0])
axA.plot(x, y, color=GREY, lw=2.4, zorder=1, label="true (curved) arc")
tk = np.linspace(0.06, 0.80, 5)
xk, yk = 2.6 * tk, 0.4 + 3.2 * tk - 4.9 * tk ** 2
axA.plot(xk, yk, "o", ms=10, color=TEAL_D, zorder=4, label="triplets  $k = 1 … N$")
for i, (xx, yy) in enumerate(zip(xk, yk)):
    axA.annotate(str(i + 1), (xx, yy), textcoords="offset points", xytext=(0, 12),
                 ha="center", fontsize=9.5, color=TEAL_D, weight="bold")

def seg(i, j, col, dy, lab):
    axA.annotate("", xy=(xk[j], yk[j] + dy), xytext=(xk[i], yk[i] + dy),
                 arrowprops=dict(arrowstyle="<|-|>", color=col, lw=2.2))
    axA.text((xk[i] + xk[j]) / 2, yk[[i, j]].mean() + dy + 0.06, lab,
             ha="center", fontsize=9.2, color=col, weight="bold")

seg(0, 1, GOLD, -0.20, "FORWARD\n(first triplet)")
seg(1, 3, TEAL, 0.22, "CENTRAL  (interior)")
seg(3, 4, GREEN, -0.20, "BACKWARD\n(last triplet)")
axA.plot(xk[-1], yk[-1], "o", ms=16, mfc="none", mec=RED, mew=2.2, zorder=5)
axA.annotate("legacy DISCARDED\nthis triplet", (xk[-1], yk[-1]), textcoords="offset points",
             xytext=(-8, -52), ha="center", fontsize=9, color=RED, weight="bold", linespacing=1.3,
             arrowprops=dict(arrowstyle="-", color=RED, lw=1.0))
axA.set_xlabel("horizontal  [m]"); axA.set_ylabel("height y  [m]")
axA.set_ylim(-0.25, 1.15)
axA.legend(loc="upper left", fontsize=9.5)
axA.set_title("Hybrid stencil on a curved arc — keeps all N triplets",
              fontsize=12, weight="bold", loc="left")

axB = fig.add_subplot(gs[1])
labels = ["Legacy\nforward-only", "Hybrid\n(F / C / B)"]
lo, hi = STENCIL["hybrid_lo"], STENCIL["hybrid_hi"]
vals = [STENCIL["forward"], (lo + hi) / 2]
err = [[0, abs(hi - lo) / 2], [0, abs(hi - lo) / 2]]
bars = axB.bar(labels, vals, color=[RED, GREEN], edgecolor=INK, lw=1.3, width=0.5)
axB.errorbar(labels[1], vals[1], yerr=abs(hi - lo) / 2, fmt="none", ecolor=INK, capsize=8, lw=1.8)
axB.axhline(0, color=INK, lw=1.5)
axB.text(0, STENCIL["forward"] - 1.2, "≈ −24 mm", ha="center", va="top", fontsize=12,
         weight="bold", color="white", path_effects=[pe.withStroke(linewidth=3, foreground=RED)])
axB.text(1, vals[1] - 3.0, "≈ −12 … −15 mm", ha="center", va="top", fontsize=12,
         weight="bold", color="white", path_effects=[pe.withStroke(linewidth=3, foreground=GREEN)])
axB.annotate("", xy=(0.5, vals[1]), xytext=(0.5, vals[0]),
             arrowprops=dict(arrowstyle="-|>", color=GOLD, lw=2.4))
axB.text(0.56, (vals[0] + vals[1]) / 2, "HALVED", fontsize=11, color=GOLD, weight="bold", va="center")
axB.set_ylabel("along-track systematic  [mm]")
axB.set_ylim(-30, 6)
axB.set_title("The payoff of the slide-4 seed", fontsize=12, weight="bold", loc="left")
prov(axB, "SIMULATOR-CHARACTERISED (not campaign-measured)")
d = ABLATION["steps"][1][1]
axB.text(0.5, 1.02, f"ABLATION DELTA:  {d:+.0f} mm", transform=axB.transAxes, ha="center",
         va="bottom", fontsize=11.5, weight="bold", color=RED if PLACEHOLDER else GREEN,
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=RED if PLACEHOLDER else GREEN, lw=1.4))
save(fig, "slide09_fix2_hybrid_stencil")

# ============================================================================
# SLIDE 10 — ★ Fix 3: measurement instant + contact point  (split slide)
# ============================================================================
fig = plt.figure(figsize=(13, 6.0))
gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.26)

# --- LEFT: mid-echo timeline
axA = fig.add_subplot(gs[0])
axA.grid(False)
axA.plot([0, 12], [1, 1], color=INK, lw=2.2)
for tt, lab, col in [(0, "t_TRIG\n(pulse leaves)", TEAL_D),
                     (6, "pulse HITS ball\n= the measurement", RED),
                     (12, "echo returns\n(naive timestamp)", GREY)]:
    axA.plot([tt, tt], [0.86, 1.14], color=col, lw=2.4)
    axA.text(tt, 1.30, lab, ha="center", va="bottom", fontsize=9.3, color=col,
             weight="bold", linespacing=1.35)
axA.add_patch(Rectangle((0, 0.55), 6, 0.16, fc=TEAL_L, ec=TEAL_D, lw=1.0))
axA.add_patch(Rectangle((6, 0.55), 6, 0.16, fc=GREY_L, ec=GREY, lw=1.0))
axA.text(3, 0.63, "outbound", ha="center", va="center", fontsize=9)
axA.text(9, 0.63, "return", ha="center", va="center", fontsize=9)
axA.annotate("", xy=(12, 0.40), xytext=(0, 0.40), arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.4))
axA.text(6, 0.31, "echo ≈ 12 ms  at 2 m range", ha="center", va="top", fontsize=10, weight="bold")
axA.plot(6, 1, "v", ms=15, color=RED, zorder=5)
axA.text(6, 1.86,
         r"$t_{sample} = t_{TRIG} + \dfrac{t_{echo}}{2}$",
         ha="center", fontsize=15, color=RED, weight="bold",
         bbox=dict(boxstyle="round,pad=0.45", fc="white", ec=RED, lw=1.5))
axA.annotate("", xy=(12, 0.18), xytext=(6, 0.18),
             arrowprops=dict(arrowstyle="<|-|>", color=RED, lw=1.6))
axA.text(9, 0.09, "naive timestamp is late by up to ~6 ms\n→ tens of mm at a few m/s",
         ha="center", va="top", fontsize=9.2, color=RED, linespacing=1.35)
axA.set_xlim(-1.6, 13.6); axA.set_ylim(-0.25, 2.35)
axA.axis("off")
axA.set_title("R3 — WHEN the measurement happened", fontsize=12, weight="bold", loc="left")

# --- RIGHT: y = r_ball at contact
axB = fig.add_subplot(gs[1])
axB.grid(False)
axB.plot([-0.1, 1.5], [0, 0], color=INK, lw=2.6)
axB.text(1.48, -0.018, "floor  (y = 0)", ha="right", va="top", fontsize=9.5, color=GREY)
rb = R_BALL_MM / 1000
axB.add_patch(Circle((0.75, rb), rb, fc="#E8843C", ec=INK, lw=1.6, alpha=0.9, zorder=3))
axB.plot(0.75, rb, "+", ms=13, mew=2.2, color=INK, zorder=4)
axB.plot([0.75, 0.75], [0, rb], color=RED, lw=2.2, zorder=4)
axB.annotate("", xy=(0.60, 0), xytext=(0.60, rb), arrowprops=dict(arrowstyle="<|-|>", color=RED, lw=1.6))
axB.text(0.575, rb / 2, f"r_ball\n{R_BALL_MM:.1f} mm", ha="right", va="center",
         fontsize=10, color=RED, weight="bold", linespacing=1.3)
tt = np.linspace(-0.55, 0.30, 200)
yy = rb + 0.55 * (-tt) - 0.9 * tt ** 2 * 0.0
tr_x = 0.75 + tt
tr_y = rb - 1.35 * tt - 0.0 * tt
axB.plot(tr_x, tr_y, color=TEAL_D, lw=2.2, ls="--", zorder=2)
axB.plot(tr_x[tt > 0], tr_y[tt > 0], color=GREY, lw=2.0, ls=":", zorder=2)
axB.text(0.16, 0.96, "fitted trajectory\n= the ball's CENTRE", fontsize=9.6, color=TEAL_D,
         weight="bold", linespacing=1.35, va="top")
axB.plot(0.75 + 0.088, 0.0, "x", ms=12, mew=2.4, color=GREY, zorder=5)
axB.annotate("legacy: solve y = 0\n(over-shoots)", (0.75 + 0.088, 0.0),
             textcoords="offset points", xytext=(58, 26), fontsize=9, color=GREY,
             linespacing=1.3, arrowprops=dict(arrowstyle="-", color=GREY, lw=0.9))
axB.plot(0.75, 0.0, "*", ms=17, color=GREEN, mec=INK, mew=0.8, zorder=6)
axB.annotate("solve y(t*) = r_ball", (0.75, 0.0), textcoords="offset points",
             xytext=(-6, -34), ha="center", fontsize=9.6, color=GREEN, weight="bold",
             arrowprops=dict(arrowstyle="-", color=GREEN, lw=1.0))
axB.text(0.05, -0.20,
         f"landing shift:   MEASURED {CONTACT_SHIFT['measured']:.2f} mm   vs   "
         f"KINEMATIC {CONTACT_SHIFT['kinematic']:.2f} mm   →  2 % agreement",
         fontsize=10, va="top", ha="left", linespacing=1.55, color=INK, weight="bold",
         bbox=dict(boxstyle="round,pad=0.5", fc="#E8F3EC", ec=GREEN, lw=1.3))
axB.set_xlim(0.0, 1.80); axB.set_ylim(-0.50, 1.10)
axB.set_aspect("equal")
axB.axis("off")
axB.set_title("R4 — WHERE contact happens", fontsize=12, weight="bold", loc="left")

fig.suptitle("★ Fix 3 — respecting the physics of the measurement instant and the contact point",
             fontsize=14, weight="bold", x=0.06, ha="left", y=1.02)
fig.text(0.06, -0.03,
         "“Neither of these is a filter or a fit — they just correctly state WHEN and WHERE the measurement actually happened. Free accuracy.”",
         fontsize=9.8, style="italic", color=GOLD, ha="left")
fig.text(0.98, 1.02, f"ABLATION DELTA: {ABLATION['steps'][2][1]:+.0f} mm"
                      + ("   [PLACEHOLDER]" if PLACEHOLDER else ""),
         fontsize=10.5, ha="right", va="top", color=RED if PLACEHOLDER else GREEN, weight="bold")
save(fig, "slide10_fix3_instant_and_contact")

# ============================================================================
# SLIDE 11 — ★ Fix 4: Kalman + track-aligned bias model
# ============================================================================
fig = plt.figure(figsize=(13, 6.0))
gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.28)

rng = np.random.default_rng(3)
tt = np.linspace(0, 0.95, 6)
xt = 2.4 * tt
yt = 0.5 + 3.6 * tt - 4.905 * tt ** 2
xm = xt + rng.normal(0, 0.055, tt.size)
ym = yt + rng.normal(0, 0.070, tt.size)
tf = np.linspace(0, 1.05, 300)
xf, yf = 2.4 * tf, 0.5 + 3.6 * tf - 4.905 * tf ** 2

axA = fig.add_subplot(gs[0])
axA.plot(xf, yf, color=GREEN, lw=2.6, label="Kalman-smoothed track", zorder=3)
axA.plot(xm, ym, "o--", color=RED, ms=8, lw=1.2, alpha=0.85, label="raw trilateration (per triplet)", zorder=4)
axA.plot(xt, yt, "o", ms=5, color=GREY, zorder=2, label="true")
for i in range(tt.size):
    sy = 0.045 + 0.10 * (1 - yt[i] / max(yt))
    axA.add_patch(Ellipse((xm[i], ym[i]), 0.10, 2 * sy, fc=RED, alpha=0.13, ec="none", zorder=1))
axA.axhline(R_BALL_MM / 1000, color=INK, lw=1.4, ls=":")
axA.text(2.55, R_BALL_MM / 1000 + 0.03, "y = r_ball", fontsize=9, color=INK)
axA.set_xlabel("horizontal  [m]"); axA.set_ylabel("height y  [m]")
axA.legend(loc="lower left", fontsize=9.3)
axA.set_title("7-state, variable-dt Kalman filter\nheteroscedastic R:  σ_y ≈ (d / y) · σ_d  → far/low geometry trusted less",
              fontsize=11, weight="bold", loc="left")
axA.text(0.02, 0.06, "shaded = per-triplet measurement\nuncertainty (grows as y falls)",
         transform=axA.transAxes, fontsize=8.8, color=RED, style="italic", linespacing=1.3)

axB = fig.add_subplot(gs[1])
al, cr = CAMPAIGN["along_bias"], CAMPAIGN["cross_bias"]
lo, hi = CAMPAIGN["along_ci"]
clo, chi = CAMPAIGN["cross_ci"]
axB.barh(["along-track\n(throw frame)", "cross-track\n(throw frame)"], [al, cr],
         xerr=[[al - lo, cr - clo], [hi - al, chi - cr]],
         color=[GREEN, GREY], edgecolor=INK, lw=1.2, capsize=8, height=0.45)
axB.axvline(0, color=INK, lw=1.6)
axB.text(al, 0.32, f"{al:.1f} mm\n95 % CI [{lo:.1f}, {hi:.1f}]\nEXCLUDES ZERO", ha="center",
         va="bottom", fontsize=9.6, weight="bold", color=GREEN, linespacing=1.35)
axB.text(cr + 3, 1.30, f"{cr:.1f} mm — not significant", ha="left", va="bottom",
         fontsize=9.4, color=GREY)
axB.set_xlabel("mean residual  [mm]")
axB.set_xlim(-30, 105)
axB.set_title("Bias model is fitted in EACH THROW'S OWN track frame",
              fontsize=11.5, weight="bold", loc="left")
axB.text(0.5, -0.30,
         "CONTROL: the same data fitted in the FIXED ARRAY frame recovers only\n"
         "≈ 83 % of the bias (E[cos φ] at ±60° headings) and corrects WORSE.\n"
         "→ the frame choice is load-bearing, not cosmetic.",
         transform=axB.transAxes, ha="center", va="top", fontsize=9.3, color=RED,
         linespacing=1.5, bbox=dict(boxstyle="round,pad=0.45", fc=RED_L, ec=RED, lw=1.0, alpha=0.7))
prov(axB, f"CAMPAIGN-MEASURED, N = {CAMPAIGN['n_throws']} throws")
d = ABLATION["steps"][3][1]
fig.suptitle("★ Fix 4 — Kalman filter + track-aligned bias model", fontsize=14, weight="bold",
             x=0.06, ha="left", y=1.03)
fig.text(0.98, 1.03, f"ABLATION DELTA: {d:+.0f} mm" + ("   [PLACEHOLDER]" if PLACEHOLDER else ""),
         fontsize=10.5, ha="right", va="top", color=RED if PLACEHOLDER else GREEN, weight="bold")
save(fig, "slide11_fix4_kalman_bias")

# ============================================================================
# SLIDE 12 — ★ Fix 5: two-tape → three-tape multilateration
# ============================================================================
fig, axs = plt.subplots(1, 2, figsize=(13, 6.0))
mark = np.array([0.95, 0.55])
refs2 = {"S2": np.array([-0.5, -0.289]), "S3": np.array([0.5, -0.289])}
refs3 = {"centroid": np.array([0.0, 0.0]), "S1": np.array([0.0, 0.577]), "S3": np.array([0.5, -0.289])}

for k, (ax, refs, ttl, ell, col) in enumerate([
        (axs[0], refs2, "LEGACY — two-tape triangulation", (0.30, 0.075, 22), RED),
        (axs[1], refs3, "UPGRADE — three-reference LS multilateration", (0.085, 0.055, 10), GREEN)]):
    V = np.array([[0, 0.577], [-0.5, -0.289], [0.5, -0.289]])
    ax.add_patch(Polygon(V, closed=True, fc=TEAL_L, ec=TEAL_D, lw=1.4, alpha=0.30, zorder=1))
    for nm, p in refs.items():
        d = np.linalg.norm(mark - p)
        ax.add_patch(Circle(p, d, fc="none", ec=col, lw=1.5, ls="--", alpha=0.75, zorder=2))
        ax.plot(*p, "s", ms=11, color=TEAL_D, zorder=4)
        ax.annotate(nm, p, textcoords="offset points", xytext=(0, -20), ha="center",
                    fontsize=10, weight="bold", color=TEAL_D)
        ax.plot([p[0], mark[0]], [p[1], mark[1]], color=col, lw=1.6, zorder=3)
        ax.text((p[0] + mark[0]) / 2, (p[1] + mark[1]) / 2 + 0.045, "tape", fontsize=8.5,
                color=col, ha="center", style="italic")
    ax.add_patch(Ellipse(mark, ell[0], ell[1], angle=ell[2], fc=col, alpha=0.25, ec=col, lw=1.6, zorder=5))
    ax.plot(*mark, "*", ms=16, color=INK, zorder=6)
    ax.annotate("first-contact mark", mark, textcoords="offset points", xytext=(6, 22),
                fontsize=9.5, weight="bold")
    ax.set_xlim(-1.15, 1.75); ax.set_ylim(-0.95, 1.20)
    ax.set_aspect("equal"); ax.grid(False)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_edgecolor(GREY_L)
    ax.set_title(ttl, fontsize=12, weight="bold", loc="left", color=col)

axs[0].text(0.5, -0.10, "shallow intersection angle\n→ manual mark-measurement error is AMPLIFIED\n"
                        "no redundancy → no self-check",
            transform=axs[0].transAxes, ha="center", va="top", fontsize=9.6, color=RED,
            linespacing=1.5, bbox=dict(boxstyle="round,pad=0.45", fc=RED_L, ec=RED, lw=1.0))
axs[1].text(0.5, -0.10, "3 references, 2 unknowns → 1 redundancy\n"
                        "least-squares solve + stored RESIDUAL as a per-measurement self-check\n"
                        f"5 mm tape σ → ≈ 4 mm ground-truth position σ",
            transform=axs[1].transAxes, ha="center", va="top", fontsize=9.6, color=GREEN,
            linespacing=1.5, bbox=dict(boxstyle="round,pad=0.45", fc="#E8F3EC", ec=GREEN, lw=1.0))
fig.suptitle("★ Fix 5 — Ground truth: you cannot claim mm-level prediction error without mm-level truth",
             fontsize=13.5, weight="bold", x=0.06, ha="left", y=1.02)
fig.text(0.98, 1.02, f"ABLATION DELTA: {ABLATION['steps'][4][1]:+.0f} mm"
                     + ("   [PLACEHOLDER]" if PLACEHOLDER else ""),
         fontsize=10.5, ha="right", va="top", color=RED if PLACEHOLDER else GREEN, weight="bold")
fig.text(0.06, -0.15, "shaded ellipse = propagated position uncertainty (schematic, to scale in ratio)",
         fontsize=8.6, color=GREY, style="italic")
save(fig, "slide12_fix5_ground_truth")

# ============================================================================
# SLIDE 13 — Full correction inventory table
# ============================================================================
rows = [
    ("★ 1", "Estimation", "Per-sensor offset calibration", "bench n=200; −25.5 / −22.5 / −12.9 mm", f"{ABLATION['steps'][0][1]:+.0f} mm"),
    ("★ 2", "Timing",     "Hybrid differencing stencil",   "F / C / B; keeps all N triplets", f"{ABLATION['steps'][1][1]:+.0f} mm"),
    ("★ 3", "Physics",    "Mid-echo sampling instant + y = r_ball", "t_TRIG + echo/2;  19.13 vs 19.48 mm", f"{ABLATION['steps'][2][1]:+.0f} mm"),
    ("★ 4", "Estimation", "Kalman + track-aligned bias model", "7-state, hetero-R; along +67.5 mm", f"{ABLATION['steps'][3][1]:+.0f} mm"),
    ("★ 5", "Ground truth", "Three-tape LS multilateration", "redundancy → residual self-check", f"{ABLATION['steps'][4][1]:+.0f} mm"),
    ("", "Physical",     "Temperature-based speed of sound", "c(T) formula, logged per session", "—"),
    ("", "Physical",     "Ball-radius range correction", "echo returns from the SURFACE", "—"),
    ("", "Timing & geom.", "Sensor-height correction", "sensors are not at floor level", "—"),
    ("", "Timing & geom.", "Heteroscedastic noise model", "σ_y ≈ (d/y)·σ_d", "—"),
    ("", "Estimation",   "Time-parameterized fit", "x(t), z(t) linear · y(t) quadratic — avoids ill-conditioning", "—"),
    ("", "Data integrity", "Background band rule + ceiling-ghost", "static ghost subtracted by the rigid schedule", "—"),
    ("", "Data integrity", "d_max gate + pulse timeout 15000 → 12500 µs", "protects the 18 ms slot", "—"),
    ("", "Data integrity", "Degenerate-fit guards", "concave-down check; NaN guard", "—"),
]
fig, ax = plt.subplots(figsize=(13.6, 7.4))
ax.axis("off"); ax.grid(False)
cols = ["", "Group", "Correction", "Basis / value", "Δ error"]
cw = [0.045, 0.115, 0.295, 0.375, 0.11]
x = np.concatenate([[0.01], 0.01 + np.cumsum(cw)])
ytop, rh = 0.830, 0.055
ax.add_patch(Rectangle((0.01, ytop), sum(cw), rh, fc=TEAL_D, ec="none", transform=ax.transAxes))
for i, c in enumerate(cols):
    ax.text(x[i] + 0.008, ytop + rh / 2, c, transform=ax.transAxes, va="center",
            fontsize=10.5, weight="bold", color="white")
for j, r in enumerate(rows):
    y = ytop - (j + 1) * rh
    star = r[0] != ""
    ax.add_patch(Rectangle((0.01, y), sum(cw), rh, transform=ax.transAxes,
                           fc="#FDF6E3" if star else ("white" if j % 2 else GREY_L),
                           ec=GREY_L, lw=0.6))
    for i, cell in enumerate(r):
        ax.text(x[i] + 0.008, y + rh / 2, cell, transform=ax.transAxes, va="center",
                fontsize=9.3 if i != 4 else 9.6,
                weight="bold" if star and i in (0, 2, 4) else "normal",
                color=(GOLD if i == 0 else (RED if (star and i == 4 and PLACEHOLDER) else INK)))
ybot = ytop - (len(rows) + 1) * rh
ax.add_patch(FancyBboxPatch((0.01, ybot - 0.115), sum(cw), 0.10,
                            boxstyle="round,pad=0.004", transform=ax.transAxes,
                            fc=RED_L, ec=RED, lw=1.3))
ax.text(0.02, ybot - 0.065, "CONSIDERED AND REJECTED — empirical speed-of-sound self-calibration:\n"
                            "targets a ~0.1–0.3 % (mm-level) error, i.e. BELOW the uncertainty budget. Mechanism real; magnitude irrelevant.",
        transform=ax.transAxes, va="center", fontsize=9.4, color=RED, weight="bold", linespacing=1.5)
ax.text(0.01, 0.985, "The full correction inventory", transform=ax.transAxes,
        fontsize=15, weight="bold", va="top")
ax.text(0.01, 0.945, "★ = headline fix with a quantified delta  ·  everything else is one line — the contrast is what makes the five look big",
        transform=ax.transAxes, fontsize=9.5, color=GREY, va="top")
if PLACEHOLDER:
    ax.text(0.955, 0.985, "Δ column = PLACEHOLDER — fill from ablation re-run", transform=ax.transAxes,
            ha="right", va="top", fontsize=9, color=RED, weight="bold", style="italic")
save(fig, "slide13_correction_inventory")
