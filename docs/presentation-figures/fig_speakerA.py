from deck_common import *

# ============================================================================
# SLIDE 2 — The measurement chain (4 labelled arrows)
# ============================================================================
fig, ax = blank(13, 4.6)
title(ax, "The measurement chain", "Every stage adds error — this is the skeleton of the whole talk")

stages = [("RANGE", "3 × HC-SR04\nround-trip time", TEAL_L),
          ("POSITION", "trilateration\n→ (x, y, z)", TEAL_L),
          ("TRAJECTORY", "Kalman + fit\ny(t) parabola", TEAL_L),
          ("EXTRAPOLATION", "solve y = r_ball\n→ (r, θ)", TEAL_L)]
w, gap, x0, y0, h = 19.5, 6.0, 2.0, 10.0, 13.0
for i, (name, sub, fc) in enumerate(stages):
    x = x0 + i * (w + gap)
    box(ax, x, y0, w, h, "", fc=fc, ec=TEAL_D, r=0.03)
    ax.text(x + w / 2, y0 + h * 0.70, name, ha="center", va="center", fontsize=11.5, weight="bold", color=TEAL_D)
    ax.text(x + w / 2, y0 + h * 0.30, sub, ha="center", va="center", fontsize=9.2, color=INK)
    if i < 3:
        arrow(ax, (x + w + 0.6, y0 + h / 2), (x + w + gap - 0.6, y0 + h / 2), c=INK, lw=2.4, mut=20)
    ax.text(x + w / 2, y0 - 2.6, ["σ_range", "geometry\ndilution", "estimator\nbias", "extrapolation\nlever-arm"][i],
            ha="center", va="top", fontsize=8.8, color=RED, style="italic", linespacing=1.3)
    arrow(ax, (x + w / 2, y0 - 0.4), (x + w / 2, y0 - 2.2), c=RED, lw=1.4, mut=11)

ax.text(50, 30.5, "A basketball is thrown over a floor-mounted array.\n"
                  "Predict the landing point as (r, θ) from the array centroid — before impact.",
        ha="center", va="center", fontsize=11, color=INK, linespacing=1.5)
ax.text(50, 3.2, "each stage contributes to the error budget (slide 7)",
        ha="center", fontsize=9, color=GREY, style="italic")
save(fig, "slide02_measurement_chain")

# ============================================================================
# SLIDE 3 — Hardware and geometry (plan view + tilt inset)
# ============================================================================
fig = plt.figure(figsize=(13, 5.8))
gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.28)

axA = fig.add_subplot(gs[0])
s = ARRAY_SIDE_M
V = np.array([[0, s / np.sqrt(3)],
              [-s / 2, -s / (2 * np.sqrt(3))],
              [s / 2, -s / (2 * np.sqrt(3))]])
axA.add_patch(Polygon(V, closed=True, fc=TEAL_L, ec=TEAL_D, lw=2.0, alpha=0.35, zorder=1))
_off = [(0, 16, "center"), (-22, -4, "right"), (22, -4, "left")]
for i, (name, (x, z)) in enumerate(zip(["S1", "S2", "S3"], V)):
    axA.plot(x, z, "s", ms=13, color=TEAL_D, zorder=4)
    dx, dy, ha_ = _off[i]
    axA.annotate(name, (x, z), textcoords="offset points", xytext=(dx, dy),
                 ha=ha_, va="center", fontsize=12, weight="bold", color=TEAL_D)
    axA.annotate("", xy=(x * 0.18, z * 0.18), xytext=(x, z),
                 arrowprops=dict(arrowstyle="-|>", color=GOLD, lw=1.8, ls=(0, (4, 2))), zorder=3)
axA.plot(0, 0, "x", ms=12, mew=2.5, color=RED, zorder=5)
axA.annotate("centroid\n(origin of r, θ)", (0, 0), textcoords="offset points", xytext=(34, -30),
             fontsize=9.5, color=RED, ha="left", linespacing=1.3,
             arrowprops=dict(arrowstyle="-", color=RED, lw=0.9))
axA.annotate("", xy=(V[1][0], V[1][1] - 0.16), xytext=(V[2][0], V[2][1] - 0.16),
             arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.3))
axA.text(0, V[1][1] - 0.22, "s = 1.000 m", ha="center", va="top", fontsize=10.5, weight="bold")
th = np.linspace(0, 0.9, 40)
axA.plot(0.30 * np.cos(th), 0.30 * np.sin(th), color=RED, lw=1.4)
axA.text(0.34, 0.16, "θ", fontsize=13, color=RED, weight="bold")
axA.annotate("", xy=(0.62, 0.50), xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.8))
axA.text(0.40, 0.42, "r", fontsize=13, color=RED, weight="bold")
axA.set_xlim(-0.90, 1.00); axA.set_ylim(-0.75, 0.92)
axA.set_aspect("equal"); axA.grid(False)
for sp in axA.spines.values():
    sp.set_visible(False)
axA.set_xticks([]); axA.set_yticks([])
axA.set_title("Plan view — equilateral array (arrows: sensor bearing, tilted inward)",
              fontsize=11, weight="bold", loc="left")

axB = fig.add_subplot(gs[1])
axB.grid(False)
axB.plot([-0.2, 1.6], [0, 0], color=INK, lw=2.5)
axB.text(1.6, -0.06, "floor", ha="right", va="top", fontsize=9.5, color=GREY)
axB.add_patch(Rectangle((0.05, 0.0), 0.16, 0.09, fc=TEAL_D, ec=INK, lw=1.2, zorder=3))
axB.text(0.13, -0.06, "HC-SR04", ha="center", va="top", fontsize=9.5, weight="bold", color=TEAL_D)
a = np.deg2rad(TILT_DEG)
L = 1.25
axB.annotate("", xy=(0.13 + L * np.cos(a), L * np.sin(a)), xytext=(0.13, 0.09),
             arrowprops=dict(arrowstyle="-|>", color=GOLD, lw=2.4))
half = np.deg2rad(7)
cone = Polygon([[0.13, 0.09],
                [0.13 + L * np.cos(a - half), L * np.sin(a - half)],
                [0.13 + L * np.cos(a + half), L * np.sin(a + half)]],
               closed=True, fc=GOLD, alpha=0.18, ec="none")
axB.add_patch(cone)
axB.plot([0.13, 1.05], [0.09, 0.09], color=GREY, lw=1.0, ls=":")
tt = np.linspace(0, a, 30)
axB.plot(0.13 + 0.45 * np.cos(tt), 0.09 + 0.45 * np.sin(tt), color=RED, lw=1.5)
axB.text(0.60, 0.30, f"{TILT_DEG}°", fontsize=13, color=RED, weight="bold")
axB.add_patch(Circle((1.02, 1.14), 0.11, fc="#E8843C", ec=INK, lw=1.4, zorder=4))
axB.text(1.24, 1.14, f"basketball\nr = {R_BALL_MM:.1f} mm  (tape, ±2 mm)\nm = {M_BALL_KG:.3f} kg\nMEASURED, not datasheet",
         fontsize=9.4, va="center", linespacing=1.55, color=INK)
axB.text(0.72, -0.28, "Why three sensors?  Three ranges → three unknowns (x, y, z).\n"
                      "It is the MINIMUM for a 3-D fix by trilateration —\n"
                      "no redundancy, and no per-triplet consistency check.",
         fontsize=9.5, va="top", ha="center", color=INK, linespacing=1.55,
         bbox=dict(boxstyle="round,pad=0.5", fc=GREY_L, ec=GREY, lw=0.8))
axB.set_xlim(-0.30, 2.55); axB.set_ylim(-1.05, 1.55)
axB.set_aspect("equal")
for sp in axB.spines.values():
    sp.set_visible(False)
axB.set_xticks([]); axB.set_yticks([])
axB.set_title("Elevation — inward tilt and nominal beam cone", fontsize=11, weight="bold", loc="left")
fig.text(0.5, -0.01, "Arduino Nano Every · 3 × HC-SR04 (40 kHz) · ball parameters measured, not datasheet",
         ha="center", fontsize=8.6, color=GREY, style="italic")
save(fig, "slide03_hardware_geometry")

# ============================================================================
# SLIDE 4 — Why the sensors cannot fire together (timing diagram)
# ============================================================================
fig, ax = plt.subplots(figsize=(13, 5.4))
ax.grid(False)
rows = {"S1": 3, "S2": 2, "S3": 1}
colors = {"S1": TEAL_D, "S2": TEAL, "S3": TEAL_L}
for name, y in rows.items():
    ax.plot([0, 118], [y, y], color=GREY_L, lw=1.2, zorder=1)
    ax.text(-3, y, name, ha="right", va="center", fontsize=12, weight="bold", color=colors[name])

for cyc in range(2):
    t0 = cyc * PERIOD_MS
    for i, name in enumerate(["S1", "S2", "S3"]):
        ts = t0 + i * SLOT_MS
        y = rows[name]
        ax.add_patch(Rectangle((ts, y - 0.30), SLOT_MS, 0.60, fc=colors[name],
                               ec=INK, lw=1.0, alpha=0.85 if cyc == 0 else 0.35, zorder=3))
        if cyc == 0:
            ax.text(ts + SLOT_MS / 2, y, f"ping {name}\n+ echo", ha="center", va="center",
                    fontsize=8.4, color="white" if name != "S3" else INK, weight="bold", linespacing=1.2)
            ax.plot([ts, ts], [0.35, y - 0.30], color=RED, lw=1.0, ls=":", zorder=2)
            ax.text(ts, 0.22, f"t + {i * SLOT_MS} ms", ha="center", va="top", fontsize=9, color=RED)

ax.annotate("", xy=(0, 3.75), xytext=(PERIOD_MS, 3.75),
            arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.5))
ax.text(PERIOD_MS / 2, 3.88, f"one triplet = {PERIOD_MS} ms period", ha="center", fontsize=10.5, weight="bold")
ax.add_patch(Rectangle((0, 0.55), PERIOD_MS, 3.05, fc=GOLD, alpha=0.09, ec=GOLD, lw=1.2, zorder=0))

ax.text(60, 3.5, "Simultaneous pings CROSS-TALK\n— a sensor hears its neighbour's echo.",
        fontsize=10.5, va="center", color=RED, weight="bold", linespacing=1.5)
ax.text(60, 2.35,
        "Solution: sequential firing on a RIGID schedule.\n"
        "Echo timeout 12 500 µs guarantees the 18 ms slot never overruns.",
        fontsize=10, va="center", color=INK, linespacing=1.5)
ax.text(60, 1.15,
        "⚠  Consequence — the seed for slide 9:\n"
        "the three ranges in a triplet are taken at DIFFERENT\n"
        "instants while the ball moves. A systematic error\n"
        "that must be corrected, not averaged away.",
        fontsize=10, va="center", color=RED, linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.55", fc=RED_L, ec=RED, lw=1.0, alpha=0.6))

ax.set_xlim(-14, 122); ax.set_ylim(0, 4.3)
ax.set_xlabel("time  [ms]", fontsize=11)
ax.set_yticks([])
for sp in ["left", "top", "right"]:
    ax.spines[sp].set_visible(False)
ax.set_xticks([0, 18, 36, 54, 72, 90, 108])
ax.set_title("Sequential firing schedule — 18 ms slots, 54 ms triplet period",
             fontsize=13, weight="bold", loc="left")
prov(ax, "firmware design; timeout = 12 500 µs (adopted A1)")
save(fig, "slide04_timing_diagram")

# ============================================================================
# SLIDE 5 — Legacy pipeline block diagram
# ============================================================================
fig, ax = blank(13, 5.4)
title(ax, "The legacy pipeline — built simulator-first",
      "All code passed a physics-simulator acceptance gate before hardware was permitted (242 tests by project end)")

blocks = [
    ("Background\ncalibration\n(+ ceiling-ghost\nrejection)", False),
    ("Trilateration\n3 ranges → (x, y, z)", False),
    ("FORWARD\ndifferencing\ntemporal correction", True),
    ("Parabola fit\nx,z linear · y quadratic", False),
    ("Solve  y = 0", True),
    ("Report\n(r, θ)", False),
]
w, gap, x0, y0, h = 14.2, 2.0, 1.0, 16.0, 15.0
for i, (lab, legacy) in enumerate(blocks):
    x = x0 + i * (w + gap)
    box(ax, x, y0, w, h, lab,
        fc=RED_L if legacy else TEAL_L, ec=RED if legacy else TEAL_D,
        fs=8.9, r=0.03, lw=2.2 if legacy else 1.6,
        weight="bold" if legacy else "normal")
    if i < len(blocks) - 1:
        arrow(ax, (x + w + 0.2, y0 + h / 2), (x + w + gap - 0.2, y0 + h / 2), lw=2.0, mut=15)
    if legacy:
        ax.text(x + w / 2, y0 - 1.6, "LEGACY CHOICE", ha="center", va="top",
                fontsize=8.2, color=RED, weight="bold")

ax.text(1.0, 8.5,
        "The fixes came from THREE sources, all BEFORE the live campaign:\n"
        "①  internal design review     ②  external engineering audit     ③  simulation",
        fontsize=10.5, va="top", linespacing=1.7,
        bbox=dict(boxstyle="round,pad=0.6", fc=GREY_L, ec=GREY, lw=0.8))
ax.text(99, 8.5, "red = the two choices\nthe next section replaces", ha="right", va="top",
        fontsize=9.5, color=RED, style="italic", linespacing=1.4)
save(fig, "slide05_legacy_pipeline")

# ============================================================================
# SLIDE 6 — Legacy performance scatter (predicted vs actual)
# ============================================================================
rng = np.random.default_rng(7)
n = CAMPAIGN["n_throws"]
head = rng.uniform(-np.pi, np.pi, n)
rr = rng.uniform(1.0, 2.4, n)
ax_t, az_t = rr * np.cos(head), rr * np.sin(head)
bias = ABLATION["legacy_error"] / 1000 * 0.8
px = ax_t + bias * np.cos(head) + rng.normal(0, 0.055, n)
pz = az_t + bias * np.sin(head) + rng.normal(0, 0.055, n)

fig, ax = plt.subplots(figsize=(8.4, 7.4))
for i in range(n):
    ax.plot([ax_t[i], px[i]], [az_t[i], pz[i]], color=GREY, lw=0.9, zorder=1)
ax.scatter(ax_t, az_t, s=52, marker="o", facecolor="white", edgecolor=INK, lw=1.4,
           zorder=3, label="actual (ground truth)")
ax.scatter(px, pz, s=52, marker="^", color=RED, edgecolor=INK, lw=0.6,
           zorder=3, label="predicted — LEGACY config")
V = np.array([[0, 0.577], [-0.5, -0.289], [0.5, -0.289]])
ax.add_patch(Polygon(V, closed=True, fc=TEAL_L, ec=TEAL_D, lw=1.5, alpha=0.45, zorder=2))
ax.plot(0, 0, "x", ms=10, mew=2, color=TEAL_D, zorder=4)
ax.set_aspect("equal")
ax.set_xlabel("x  [m]"); ax.set_ylabel("z  [m]")
ax.set_title(f"Legacy configuration — predicted vs actual landing\n"
             f"mean 2-D error = {ABLATION['legacy_error']:.0f} mm",
             fontsize=13, weight="bold", loc="left")
ax.legend(loc="upper left", frameon=True, fontsize=9.5)
watermark(ax, "PLACEHOLDER GEOMETRY\nre-plot from the legacy ablation run")
prov(ax, f"ablation re-run of the same n = {n} campaign throws — NOT YET RUN")
save(fig, "slide06_legacy_scatter")
