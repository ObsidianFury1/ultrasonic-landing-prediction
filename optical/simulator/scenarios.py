"""Scenario library (Optical.md §6): nominal, blurred, shadowed, low-contrast,
grazing camera angle, marker-survey perturbation (negative control), no-ball
(negative control), dropouts.

All scenarios share one marker field and one reference trajectory so results are
directly comparable; each factory perturbs exactly one aspect of the nominal case.
"""

from __future__ import annotations

from dataclasses import replace

from simulator.render import Scenario, Trajectory

# Eight fiducials spread near/far and left/right across the used floor region
# (§3.3: spatial spread conditions the homography fit). Coordinates in array metres.
BASE_MARKERS = {
    0: (0.9, 0.6),
    1: (1.3, -0.4),
    2: (0.5, -0.9),
    3: (-0.3, 0.7),
    4: (-0.6, -0.5),
    5: (1.6, 0.8),
    6: (0.2, -0.2),   # held-out integrity check point (§3.3, §5.1)
    7: (1.0, 1.2),
}
HELD_OUT_ID = 6

# Reference throw: gentle lob landing inside the marker field.
# Contact (centre height = r_ball): t* ~= 0.4743 s, landing ~= (0.664, -0.127) m.
BASE_TRAJ = Trajectory(p0=(0.0, 0.9, 0.3), v0=(1.4, 0.5, -0.9))

# Render only the final descent (~93 frames at 480 fps) to keep memory bounded;
# the full flight adds nothing the pipeline consumes (§5.3 uses the descent).
T_START = 0.30
T_END = 0.50


def _base(name: str, **overrides) -> Scenario:
    sc = Scenario(
        name=name,
        cam_pos=(3.5, 1.5, 0.0),
        cam_target=(0.4, 0.0, 0.0),
        resolution=(640, 360),
        hfov_deg=62.0,
        fps_nominal=480.0,
        fps_measured=479.82,
        t_start=T_START,
        t_end=T_END,
        traj=BASE_TRAJ,
        markers_true=dict(BASE_MARKERS),
        held_out_id=HELD_OUT_ID,
    )
    return replace(sc, **overrides)


def nominal(**overrides) -> Scenario:
    """Clean capture: no noise, blur, shadow, or dropouts. The exactness anchor."""
    return _base("nominal", **overrides)


def blurred(**overrides) -> Scenario:
    """Motion blur along the ball's projected velocity (slow shutter / fast ball)."""
    return _base("blurred", blur_len_px=9, noise_sigma=2.0, **overrides)


def shadowed(**overrides) -> Scenario:
    """Hard sun shadow: dark ellipse offset from the ball's ground projection."""
    return _base("shadowed", shadow=True, noise_sigma=2.0, **overrides)


def low_contrast(**overrides) -> Scenario:
    """Washed-out lighting: contrast compressed toward mid-gray, mild noise."""
    return _base("low_contrast", contrast_alpha=0.45, noise_sigma=3.0, **overrides)


def grazing(**overrides) -> Scenario:
    """Near-grazing camera (§3.1 constraint b violated on purpose): the far field
    compresses and per-pixel floor uncertainty blows up."""
    return _base("grazing", cam_pos=(5.0, 0.55, 0.0), **overrides)


def survey_perturbed(**overrides) -> Scenario:
    """NEGATIVE CONTROL (§6): the surveyed marker positions are corrupted (3-4 cm on
    three fit markers) while the RENDERED scene stays true. A homography fitted to the
    corrupted survey must fail the held-out check-point guard, loudly."""
    return _base(
        "survey_perturbed",
        survey_offsets={0: (0.035, -0.025), 1: (-0.030, 0.030), 3: (0.025, 0.035)},
        **overrides,
    )


def no_ball(**overrides) -> Scenario:
    """NEGATIVE CONTROL (§6): no ball in the scene. The pipeline must report a clean
    'no detection', never a fabricated landing."""
    return _base("no_ball", traj=None, **overrides)


def with_dropouts(frames: frozenset[int] = frozenset({10, 11, 40}), **overrides) -> Scenario:
    """Nominal capture with missing frames (delivery dropouts)."""
    return _base("with_dropouts", dropout_frames=frozenset(frames), **overrides)


def bounce(**overrides) -> Scenario:
    """First bounce with restitution 0.75. [AMENDED v1.5 / WO-OPT-4 Stage 3 — the value was
    previously justified as "physically plausible for a tennis ball on a hard floor".] The
    VALUE IS DELIBERATELY UNCHANGED: it is not metrologically load-bearing — it only needs to
    make the ball physically rebound so the track shows a reversal. A basketball's true
    coefficient of restitution has NOT been verified from a primary source and is NOT guessed
    here (same refusal as Decision D21's contact duration); if a measured value is ever
    wanted it belongs in config.yaml, not in this docstring. Unlike the vanish-at-contact
    default, the track shows a genuine
    image-v REVERSAL at first touchdown, so find_descent takes its `reversal` branch — the
    path REAL footage always takes. (WO-OPT-1 Stage 4 / audit M4.)"""
    return _base("bounce", restitution=0.75, **overrides)


def bounce_oblique(**overrides) -> Scenario:
    """The bounce viewed from a lower, more oblique camera (elev ~12 deg vs nominal ~23 deg) —
    the geometry where the audit predicted the image-v reversal apex sits ~1 frame off true
    world contact. This is the stress case for the descent-end bracket on a real bounce."""
    return _base("bounce_oblique", restitution=0.75, cam_pos=(4.2, 0.9, 0.0), **overrides)


ALL_SCENARIOS = {
    "nominal": nominal,
    "blurred": blurred,
    "shadowed": shadowed,
    "low_contrast": low_contrast,
    "grazing": grazing,
    "survey_perturbed": survey_perturbed,
    "no_ball": no_ball,
    "with_dropouts": with_dropouts,
    "bounce": bounce,
    "bounce_oblique": bounce_oblique,
}
