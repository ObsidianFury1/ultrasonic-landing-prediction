from deck_common import *
from matplotlib.lines import Line2D

# ============================================================================
# SLIDE 14 — The live campaign (protocol card)
# ============================================================================
fig, ax = blank(13, 4.8)
title(ax, "The live campaign", f"{CAMPAIGN['date']}  ·  full corrected pipeline")

items = [
    (f"{CAMPAIGN['n_throws']}", "ground-truthed\nthrows", TEAL_D),
    ("±180°", "headings spread —\nexercises the\ndirection-dependent\ngeometry", TEAL),
    (f"{CAMPAIGN['triplets_mean']:.1f}", f"triplets per throw\n(range {CAMPAIGN['triplets_range'][0]}–{CAMPAIGN['triplets_range'][1]})", TEAL),
    ("≈ 4 mm", "ground-truth\nposition σ\n(from 5 mm tape σ)", GREEN),
]
w, gap, x0, y0, h = 20.0, 4.0, 3.0, 12.0, 17.0
for i, (big, sub, c) in enumerate(items):
    x = x0 + i * (w + gap)
    box(ax, x, y0, w, h, "", fc="white", ec=c, lw=2.0, r=0.03)
    ax.text(x + w / 2, y0 + h * 0.72, big, ha="center", va="center", fontsize=22, weight="bold", color=c)
    ax.text(x + w / 2, y0 + h * 0.30, sub, ha="center", va="center", fontsize=9.2, color=INK, linespacing=1.4)

ax.text(3, 7.5, "PROTOCOL:   first-contact marking   ·   three-tape multilateration ground truth   ·   ambient temperature logged per session",
        fontsize=10.5, va="center", weight="bold", color=INK,
        bbox=dict(boxstyle="round,pad=0.55", fc=GREY_L, ec=GREY, lw=0.9))
ax.text(3, 2.5, f"({CAMPAIGN['n_sessions']} session directories on disk — three are re-processed duplicates of the same throws)",
        fontsize=9, color=GREY, style="italic", va="center")
save(fig, "slide14_campaign")

# ============================================================================
# SLIDE 15 — THE RESULTS SLIDE — waterfall
# ============================================================================
fig, ax = plt.subplots(figsize=(13.4, 6.8))
labels = ["LEGACY\nconfiguration"] + [s[0] for s in ABLATION["steps"]] + ["FINAL\ncorrected"]
start = ABLATION["legacy_error"]
final = ABLATION["final_error"]

cum = start
bottoms, heights, colors, kinds = [], [], [], []
bottoms.append(0); heights.append(start); colors.append(RED); kinds.append("total")
for _, d in ABLATION["steps"]:
    new = cum + d
    bottoms.append(new); heights.append(-d); colors.append(TEAL); kinds.append("step")
    cum = new
bottoms.append(0); heights.append(final); colors.append(GREEN); kinds.append("total")

xs = np.arange(len(labels))
for i in range(len(labels)):
    ax.bar(xs[i], heights[i], bottom=bottoms[i], color=colors[i], edgecolor=INK,
           lw=1.3, width=0.62, zorder=3, alpha=1.0 if kinds[i] == "total" else 0.85)

# connectors
lv = start
for i, (_, d) in enumerate(ABLATION["steps"]):
    ax.plot([xs[i] + 0.31, xs[i + 1] + 0.31], [lv, lv], color=GREY, lw=1.1, ls="--", zorder=2)
    lv = lv + d
ax.plot([xs[-2] + 0.31, xs[-1] + 0.31], [lv, lv], color=GREY, lw=1.1, ls="--", zorder=2)

# labels
ax.text(xs[0], start + 6, f"{start:.0f} mm", ha="center", fontsize=13, weight="bold", color=RED)
lv = start
for i, (_, d) in enumerate(ABLATION["steps"]):
    mid = lv + d / 2
    ax.text(xs[i + 1], mid, f"{d:+.0f}", ha="center", va="center", fontsize=12.5,
            weight="bold", color="white", path_effects=[pe.withStroke(linewidth=3, foreground=TEAL_D)])
    lv += d
ax.text(xs[-1], final + 6, f"{final:.0f} mm", ha="center", fontsize=13, weight="bold", color=GREEN)

ax.axhline(final, color=GREEN, lw=1.2, ls=":", zorder=1)
ax.axhline(start, color=RED, lw=1.2, ls=":", zorder=1)

imp = 100 * (start - final) / start
ax.text(0.5, 1.055, f"TOTAL IMPROVEMENT:   {imp:.0f} %      ({start:.0f} mm  →  {final:.0f} mm)",
        transform=ax.transAxes, ha="center", va="center", fontsize=15, weight="bold",
        color="white", bbox=dict(boxstyle="round,pad=0.6", fc=TEAL_D, ec=INK, lw=1.4))

ax.set_xticks(xs)
ax.set_xticklabels(labels, fontsize=9.3, linespacing=1.35)
ax.set_ylabel("mean 2-D landing error  [mm]", fontsize=12)
ax.set_ylim(0, start * 1.22)
fig.suptitle("Same 34 throws, same data — only the corrections differ.  This is what each one is worth.",
             fontsize=13.5, weight="bold", x=0.055, ha="left", y=1.12)
prov(ax, f"CAMPAIGN-MEASURED, n = {CAMPAIGN['n_throws']} ground-truthed throws · ablation re-run of the identical dataset")
watermark(ax, "PLACEHOLDER DELTAS\nre-run the ablation")
save(fig, "slide15_waterfall_RESULTS")

# ---- mini waterfall thumbnail for slide 17 ----
fig, ax = plt.subplots(figsize=(5.4, 3.2))
for i in range(len(labels)):
    ax.bar(xs[i], heights[i], bottom=bottoms[i], color=colors[i], edgecolor=INK, lw=0.8, width=0.66)
ax.set_xticks([]); ax.set_ylabel("2-D error [mm]", fontsize=9)
ax.text(xs[0], start + 4, f"{start:.0f}", ha="center", fontsize=10, weight="bold", color=RED)
ax.text(xs[-1], final + 4, f"{final:.0f}", ha="center", fontsize=10, weight="bold", color=GREEN)
ax.set_ylim(0, start * 1.18)
ax.tick_params(labelsize=8)
watermark(ax, "PLACEHOLDER")
save(fig, "slide17_waterfall_thumbnail")

# ============================================================================
# SLIDE 16 — Uncertainty on every prediction (ellipse + coverage)
# ============================================================================
fig = plt.figure(figsize=(13, 6.0))
gs = fig.add_gridspec(1, 2, width_ratios=[1.1, 1], wspace=0.30)

axA = fig.add_subplot(gs[0])
pred = np.array([1.55, 0.92])
true = np.array([1.50, 0.98])
sr, st = CAMPAIGN["sigma_r"] / 1000, np.deg2rad(CAMPAIGN["sigma_theta"])
r0 = np.linalg.norm(pred)
maj, minr = 2.45 * sr, 2.45 * (r0 * st)
ang = np.degrees(np.arctan2(pred[1], pred[0]))
axA.add_patch(Ellipse(pred, 2 * maj, 2 * minr, angle=ang, fc=TEAL_L, alpha=0.40, ec=TEAL_D, lw=2.0, zorder=2))
axA.add_patch(Ellipse(pred, maj, minr, angle=ang, fc="none", ec=TEAL_D, lw=1.0, ls=":", zorder=3))
V = np.array([[0, 0.577], [-0.5, -0.289], [0.5, -0.289]])
axA.add_patch(Polygon(V, closed=True, fc=GREY_L, ec=TEAL_D, lw=1.4, alpha=0.7, zorder=1))
axA.plot(0, 0, "x", ms=9, mew=2, color=TEAL_D, zorder=4)
axA.plot(*pred, "^", ms=13, color=TEAL_D, mec=INK, zorder=5, label="prediction")
axA.plot(*true, "o", ms=11, mfc="white", mec=INK, mew=1.8, zorder=5, label="ground truth")
axA.annotate("", xy=pred, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.6))
axA.text(0.70, 0.40, f"r ± σ_r\n{r0*1000:.0f} ± {CAMPAIGN['sigma_r']:.0f} mm", fontsize=9.8,
         color=RED, weight="bold", linespacing=1.35, rotation=0)
axA.text(1.55, 1.32, f"95 % confidence ellipse\npropagated from the fit covariance\nσ_θ = {CAMPAIGN['sigma_theta']:.1f}°",
         ha="center", fontsize=9.6, color=TEAL_D, weight="bold", linespacing=1.4)
axA.set_xlim(-0.85, 2.45); axA.set_ylim(-0.60, 1.60)
axA.set_aspect("equal")
axA.set_xlabel("x [m]"); axA.set_ylabel("z [m]")
axA.legend(loc="lower right", fontsize=9.5)
axA.set_title("Every landing ships with (σ_r, σ_θ)", fontsize=12.5, weight="bold", loc="left")

axB = fig.add_subplot(gs[1])
nom, emp, N = ELLIPSE_COVERAGE["nominal"], ELLIPSE_COVERAGE["empirical"], ELLIPSE_COVERAGE["n"]
bars = axB.bar(["nominal\n(design)", "empirical\n(measured)"], [nom, emp],
               color=[GREY, TEAL_D], edgecolor=INK, lw=1.3, width=0.5)
k = int(round(emp / 100 * N))
lo = 100 * (k / N - 1.96 * np.sqrt((k / N) * (1 - k / N) / N))
hi = 100 * (k / N + 1.96 * np.sqrt((k / N) * (1 - k / N) / N))
axB.errorbar(1, emp, yerr=[[emp - lo], [hi - emp]], fmt="none", ecolor=INK, capsize=9, lw=1.9)
for b, v in zip(bars, [nom, emp]):
    axB.text(b.get_x() + b.get_width() / 2, v - 4, f"{v} %", ha="center", va="top",
             fontsize=15, weight="bold", color="white")
axB.set_ylim(0, 112)
axB.set_ylabel("coverage of the 95 % ellipse  [%]")
axB.axhline(95, color=GREY, ls="--", lw=1.2)
axB.set_title("Coverage check — the ellipse is honest", fontsize=12.5, weight="bold", loc="left")
axB.text(0.5, -0.24,
         f"SIMULATION, n = {N} synthetic throws.\n"
         f"Small-sample caveat: the 95 % CI on {emp} % is roughly [{lo:.0f}, {hi:.0f}] % —\n"
         "consistent with nominal, but it does not PROVE calibration.",
         transform=axB.transAxes, ha="center", va="top", fontsize=9.3, color=INK, linespacing=1.5,
         bbox=dict(boxstyle="round,pad=0.45", fc="#FDF6E3", ec=GOLD, lw=1.1))
fig.text(0.06, -0.06, "“A prediction without an uncertainty isn't a measurement.”",
         fontsize=11, style="italic", color=GOLD, weight="bold")
save(fig, "slide16_uncertainty_ellipse")

# ============================================================================
# SLIDE 17 — Conclusions (sensor system)
# ============================================================================
fig, ax = blank(13, 4.6)
title(ax, "Conclusions — the sensor system")
lines = [
    (f"Legacy → final:  {ABLATION['legacy_error']:.0f} mm → {ABLATION['final_error']:.0f} mm   "
     f"({100*(ABLATION['legacy_error']-ABLATION['final_error'])/ABLATION['legacy_error']:.0f} % improvement)", TEAL_D),
    ("Five corrections did most of the work; the full inventory is documented and defensible.", INK),
    ("One open question remained:  can ground truth ITSELF be automated?", GOLD),
]
for i, (t, c) in enumerate(lines):
    y = 26 - i * 7.0
    ax.text(3.5, y, "▸", fontsize=15, color=c, va="center", weight="bold")
    ax.text(6.5, y, t, fontsize=12.5, color=c, va="center",
            weight="bold" if i != 1 else "normal")
ax.text(6.5, 4.5, "→ over to the optical module.", fontsize=11.5, color=GOLD, style="italic", weight="bold")
save(fig, "slide17_conclusions_sensor")

# ============================================================================
# SLIDE 19 — Optical method pipeline
# ============================================================================
fig, ax = blank(13, 5.8)
title(ax, "The optical method", "Video in → (r, θ) out")

blocks = ["Surveyed floor\nmarkers (ArUco)", "Planar\nHOMOGRAPHY\npixel → floor",
          "Ball tracking\n(HSV detector)", "First-contact instant\nbracketed to\nSUB-FRAME",
          "Parallax\ncorrection\n(centre → floor)", "Contact point\n→ (r, θ)"]
w, gap, x0, y0, h = 14.2, 2.0, 1.0, 20.0, 14.0
for i, lab in enumerate(blocks):
    x = x0 + i * (w + gap)
    box(ax, x, y0, w, h, lab, fc=TEAL_L, ec=TEAL_D, fs=8.8, r=0.03)
    if i < len(blocks) - 1:
        arrow(ax, (x + w + 0.2, y0 + h / 2), (x + w + gap - 0.2, y0 + h / 2), lw=1.9, mut=14)

ax.text(1.0, 14.5, "Three contact-time designs were tried.  The first two were REJECTED on measured grounds:",
        fontsize=10.5, weight="bold", va="top")
rej = [("① silhouette-based", "silhouette instability near contact", RED),
       ("② image-v extremum", "image-v extremum ≠ world-height minimum\nunder an oblique camera", RED),
       ("③ descent-kink sub-frame fit", "ADOPTED", GREEN)]
for i, (nm, why, c) in enumerate(rej):
    x = 2.0 + i * 32.5
    box(ax, x, 1.5, 30.0, 9.5, "", fc=RED_L if c == RED else "#E8F3EC", ec=c, lw=1.3, r=0.03)
    ax.text(x + 15, 8.4, nm, ha="center", fontsize=10, weight="bold", color=c)
    ax.text(x + 15, 4.6, why, ha="center", va="center", fontsize=8.8, color=INK, linespacing=1.4)
save(fig, "slide19_optical_method")

# ============================================================================
# SLIDE 20 — The pre-registered gate (deliberately near-empty)
# ============================================================================
fig, ax = blank(13, 5.6)
ax.add_patch(FancyBboxPatch((8, 12), 84, 26, boxstyle="round,pad=0.01,rounding_size=0.02",
                            fc="white", ec=INK, lw=3.0))
ax.text(50, 33.0, "P R E - R E G I S T E R E D   A C C E P T A N C E   G A T E", ha="center",
        fontsize=12, weight="bold", color=GREY)
ax.text(50, 24.0, f"GO   requires   RMS  ≤  {OPTICAL['gate']:.0f} mm", ha="center",
        fontsize=27, weight="bold", color=TEAL_D)
ax.text(50, 16.5, "over  ≥ 8  independent static points", ha="center", fontsize=15, color=INK)
ax.text(50, 6.0, "Written down BEFORE any field measurement.\nIt cannot be renegotiated after the data is taken.",
        ha="center", fontsize=12, color=RED, weight="bold", linespacing=1.6)
save(fig, "slide20_pre_registered_gate")

# ============================================================================
# SLIDE 21 — Result: NO-GO
# ============================================================================
fig, ax = plt.subplots(figsize=(13, 6.2))
names = ["GATE\n(pre-registered)", "MEASURED\nRMS", "Drift-removed\nre-analysis", "Irreducible\nerror FLOOR"]
vals = [OPTICAL["gate"], OPTICAL["measured"], OPTICAL["drift_removed"], OPTICAL["error_floor"]]
cols_ = [GREEN, RED, "#D9756B", GOLD]
bars = ax.bar(names, vals, color=cols_, edgecolor=INK, lw=1.4, width=0.56, zorder=3)
ax.axhline(OPTICAL["gate"], color=GREEN, lw=2.0, ls="--", zorder=2)
ax.text(-0.46, OPTICAL["gate"] + 1.8, "GATE", ha="left", fontsize=10.5, color=GREEN, weight="bold")
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 1.8, f"{v:.1f} mm", ha="center",
            fontsize=13, weight="bold", color=INK)
ax.annotate("", xy=(0.62, OPTICAL["measured"]), xytext=(0.62, OPTICAL["gate"]),
            arrowprops=dict(arrowstyle="<|-|>", color=RED, lw=2.0))
ax.text(0.56, (OPTICAL["measured"] + OPTICAL["gate"]) / 2, "4 × THE GATE", fontsize=12,
        color=RED, weight="bold", va="center", ha="right", rotation=90)
ax.text(1.42, OPTICAL["measured"] + 1.5, f"worst single point:  {OPTICAL['worst']:.1f} mm",
        ha="left", va="bottom", fontsize=10, color=RED, style="italic")
ax.set_ylabel("static-point RMS disagreement  [mm]", fontsize=12)
ax.set_ylim(0, 78)
ax.set_title("Result:  NO-GO", fontsize=17, weight="bold", loc="left", color=RED, pad=14)
prov(ax, "MEASURED at commissioning — static-point validation, >= 8 surveyed points")

fig.text(0.5, -0.12,
         "DIAGNOSIS, layer 1 — the camera MOVED mid-session (a field-procedure violation).  "
         f"Drift-removed re-analysis: still {OPTICAL['drift_removed']:.1f} mm.\n"
         f"DIAGNOSIS, layer 2 — beneath that sits a ~{OPTICAL['error_floor']:.0f} mm floor-mapping ERROR FLOOR, "
         "stacked from ~10-20 mm homography + marker-survey errors.\n"
         "=>  Even PERFECT field discipline would not have passed the gate.  The system needs REDESIGN, not a retry.",
         ha="center", va="top", fontsize=10.2, linespacing=1.7,
         bbox=dict(boxstyle="round,pad=0.7", fc="#FDF6E3", ec=GOLD, lw=1.4))
save(fig, "slide21_optical_nogo")

# ============================================================================
# SLIDE 22 — What would fix it + verdict
# ============================================================================
fig, ax = blank(13, 5.2)
title(ax, "What would fix it — and the verdict")

fixes = [("Rigid camera mount", "kills the drift term\n(layer 1)"),
         ("Better marker survey", "attacks the dominant\nterm in the error floor"),
         ("Full intrinsics calibration", "removes residual\nlens distortion")]
w, gap, x0, y0, h = 27.0, 4.0, 3.0, 22.0, 13.0
for i, (nm, why) in enumerate(fixes):
    x = x0 + i * (w + gap)
    box(ax, x, y0, w, h, "", fc="white", ec=TEAL_D, lw=1.8, r=0.03)
    ax.text(x + w / 2, y0 + h * 0.72, nm, ha="center", va="center", fontsize=11, weight="bold", color=TEAL_D)
    ax.text(x + w / 2, y0 + h * 0.30, why, ha="center", va="center", fontsize=9.2, linespacing=1.4)

ax.add_patch(FancyBboxPatch((3, 3.5), 94, 14.0, boxstyle="round,pad=0.01,rounding_size=0.02",
                            fc="#FDF6E3", ec=GOLD, lw=2.0))
ax.text(50, 14.0, "NO campaign integration was attempted — per the pre-registered protocol.",
        ha="center", fontsize=11.5, weight="bold", color=INK)
ax.text(50, 7.5, "“We set the criterion before measuring, measured honestly, and declined to integrate.\n"
                 "A characterised negative result is a valid measurement-engineering outcome.”",
        ha="center", fontsize=11, style="italic", color=GOLD, weight="bold", linespacing=1.6)
save(fig, "slide22_verdict")
