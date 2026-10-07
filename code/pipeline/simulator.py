"""Synthetic throw generator — the validation backbone (CLAUDE.md section 6).

Generates, for a specified throw:
  1. the TRUE trajectory (drag-free closed form, or quadratic-drag RK4),
  2. sensor ranges sampled at the physically correct staggered instants
     (fixed-point solve of t_hit = t_trig + range/v_sound, one-way — R3),
  3. raw measurements corrupted exactly as hardware would produce them:
     surface ranging (R2), Gaussian noise, integer echo microseconds at the
     session temperature, timeouts, background padding, optional dropouts.

Output is in-memory only (serial lines + truth); writing session folders is
the job of scripts/simulate_session.py. No I/O here.

The drag coefficient default below is a *simulation truth* parameter (the
thing bias.py will later try to detect), not a measurement-system constant,
which is why it lives here and not in config.yaml; it is overridable per throw.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from pipeline.corrections import speed_of_sound  # noqa: F401  (canonical home: section 5.2)
from pipeline.geometry import ArrayGeometry, cart_to_polar

G = 9.81  # m/s^2; same value the Kalman F matrix uses (section 8.4)

# Basketball truth defaults for the quadratic-drag model: k = rho*Cd*A / (2m).
# [D6, 2026-07-09] was tennis (Cd 0.55, m 0.0577 kg); now the approved basketball,
# mass MEASURED at 0.620 kg (Stage 1 D-register), Cd ~0.47 (smooth-sphere estimate,
# per CHANGES.md D6 Stage 4 -- APPROXIMATE; refine if a drag measurement is taken).
# The area feeds via radius_m from config["ball"]["radius_m"] (the caller passes it),
# so only the mass/Cd truth lives here (a simulation-truth parameter, not a
# measurement-system constant -- see the module docstring for why it is not in
# config.yaml). Near-invariance this restores (verified: 0.02080 vs tennis 0.02058,
# +1.0%): basketball A/m (~0.072 m^2/kg) is ~18% above tennis (~0.061), but its lower
# Cd (0.47 vs 0.55) nearly cancels it, so default_drag_k(config radius) lands within
# ~1% of the old tennis value -- which is why the drag-tuned test scales (K_SCALE=5,
# k_scale=3) carry over unchanged under D6.
_AIR_DENSITY_KG_M3 = 1.225
_BASKETBALL_CD = 0.47
_BASKETBALL_MASS_KG = 0.620


def default_drag_k(radius_m: float,
                   mass_kg: float = _BASKETBALL_MASS_KG,
                   cd: float = _BASKETBALL_CD,
                   rho: float = _AIR_DENSITY_KG_M3) -> float:
    """Quadratic-drag constant k [1/m] so that a_drag = -k*|v|*v."""
    area = np.pi * radius_m**2
    return 0.5 * rho * cd * area / mass_kg


def sensor_aim_axes(geometry: ArrayGeometry, tilt_deg: float) -> np.ndarray:
    """(D2) Per-sensor beam aim axes: (3, 3) unit vectors in the floor frame.

    Each sensor points radially inward (horizontal component from its vertex
    toward the array centroid) elevated tilt_deg above horizontal — derived
    entirely from the configured vertex coordinates, never hardcoded.
    """
    tilt = np.radians(tilt_deg)
    axes = np.empty((3, 3))
    for i, (vx, vz) in enumerate(geometry.vertices_xz):
        horiz = np.hypot(vx, vz)
        if horiz < 1e-9:
            raise ValueError(f"sensor {i + 1} sits at the centroid; "
                             "its inward aim direction is undefined")
        u = np.array([-vx, -vz]) / horiz          # toward the centroid
        axes[i] = (np.cos(tilt) * u[0], np.sin(tilt), np.cos(tilt) * u[1])
    return axes


def angle_from_axis_deg(point, sensor_pos, axis) -> float:
    """(D2) Angle [deg] between (point - sensor_pos) and the sensor aim axis."""
    vec = np.asarray(point, dtype=float) - np.asarray(sensor_pos, dtype=float)
    norm = np.linalg.norm(vec)
    if norm < 1e-12:
        return 0.0
    cosang = np.clip(vec @ np.asarray(axis, dtype=float) / norm, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosang)))


def session_directory_names(config: dict, n_sessions: int, when) -> list:
    """(D4) Unique synthetic session directory names for one batch.

    Names come from `simulator.session_name_scheme` (default
    "{prefix}_{date}_{time}_S{idx:02d}" -> e.g. sim_2026-06-12_143052_S03).
    `when` is ONE datetime captured at batch start and shared by the whole
    batch (this module is pure — it never calls datetime.now() itself): the
    HHMMSS time makes same-day re-runs disjoint, the 1-based S{idx} counter
    makes sessions created within the same second disjoint.
    """
    sim_cfg = config.get("simulator", {})
    prefix = sim_cfg.get("session_prefix", "sim")
    scheme = sim_cfg.get("session_name_scheme", "{prefix}_{date}_{time}_S{idx:02d}")
    date = when.strftime("%Y-%m-%d")
    time_str = when.strftime("%H%M%S")
    return [scheme.format(prefix=prefix, date=date, time=time_str, idx=i + 1)
            for i in range(n_sessions)]


# ---------------------------------------------------------------------------
# Throw definition and true trajectory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThrowParams:
    """Initial state of one throw, in the floor frame of section 0.1."""
    x0: float
    y0: float
    z0: float
    vx: float
    vy: float
    vz: float
    drag: str = "none"            # "none" | "quadratic"
    drag_k: float = 0.0           # used only when drag == "quadratic"

    def __post_init__(self):
        if self.drag not in ("none", "quadratic"):
            raise ValueError(f"drag must be 'none' or 'quadratic', got {self.drag!r}")

    @property
    def p0(self) -> np.ndarray:
        return np.array([self.x0, self.y0, self.z0])

    @property
    def v0(self) -> np.ndarray:
        return np.array([self.vx, self.vy, self.vz])

    def as_dict(self) -> dict:
        return asdict(self)


def ballistic_position(throw: ThrowParams, t) -> np.ndarray:
    """Closed-form drag-free position at time(s) t since release (test reference)."""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    pos = throw.p0[None, :] + throw.v0[None, :] * t[:, None]
    pos[:, 1] -= 0.5 * G * t**2
    return pos.squeeze()


@dataclass(frozen=True)
class Trajectory:
    """True trajectory on a fine time grid, ending exactly at floor contact."""
    t: np.ndarray            # (n,) seconds since release
    pos: np.ndarray          # (n, 3) ball-CENTRE positions, floor frame
    vel: np.ndarray          # (n, 3)
    t_land: float            # time of y_centre == ball_radius, vy < 0
    landing_xz: np.ndarray   # (2,) true landing (x, z)
    apex_y: float

    def position(self, t) -> np.ndarray:
        """Linear interpolation on the fine grid (clamped to [0, t_land])."""
        t = np.clip(np.asarray(t, dtype=float), 0.0, self.t_land)
        cols = [np.interp(t, self.t, self.pos[:, k]) for k in range(3)]
        return np.stack(cols, axis=-1)


def simulate_trajectory(throw: ThrowParams, ball_radius_m: float,
                        dt: float = 1e-3, t_max: float = 10.0) -> Trajectory:
    """Integrate the true trajectory until the ball centre reaches y = radius.

    RK4 throughout; with drag 'none' the acceleration is constant and RK4 is
    exact, so a single code path covers both modes.
    """
    k = throw.drag_k if throw.drag == "quadratic" else 0.0

    def accel(v: np.ndarray) -> np.ndarray:
        a = np.array([0.0, -G, 0.0])
        if k > 0.0:
            a -= k * np.linalg.norm(v) * v
        return a

    def deriv(state: np.ndarray) -> np.ndarray:
        return np.concatenate([state[3:], accel(state[3:])])

    state = np.concatenate([throw.p0, throw.v0])
    if state[1] <= ball_radius_m:
        raise ValueError("throw starts at or below floor contact height")

    ts, states = [0.0], [state]
    t = 0.0
    while t < t_max:
        k1 = deriv(state)
        k2 = deriv(state + 0.5 * dt * k1)
        k3 = deriv(state + 0.5 * dt * k2)
        k4 = deriv(state + dt * k3)
        state = state + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        t += dt
        ts.append(t)
        states.append(state)
        if state[1] <= ball_radius_m and state[4] < 0.0:
            break
    else:
        raise ValueError(f"ball did not land within t_max = {t_max} s")

    arr = np.array(states)
    t_arr = np.array(ts)

    # Linear interpolation of the floor-contact crossing inside the last step.
    y_prev, y_cur = arr[-2, 1], arr[-1, 1]
    frac = (y_prev - ball_radius_m) / (y_prev - y_cur)
    t_land = t_arr[-2] + frac * dt
    landing_state = arr[-2] + frac * (arr[-1] - arr[-2])
    landing_state[1] = ball_radius_m

    t_arr[-1] = t_land
    arr[-1] = landing_state
    apex_y = float(arr[:, 1].max())
    return Trajectory(
        t=t_arr, pos=arr[:, :3], vel=arr[:, 3:],
        t_land=float(t_land), landing_xz=landing_state[[0, 2]].copy(),
        apex_y=apex_y,
    )


def random_throw(rng: np.random.Generator,
                 speed_range: tuple[float, float] = (3.0, 4.0),
                 heading_range_deg: float = 60.0,
                 drag: str = "none",
                 drag_k: float = 0.0,
                 r0_range: tuple[float, float] = (1.3, 1.8),
                 y0_range: tuple[float, float] = (0.7, 1.0)) -> ThrowParams:
    """Random throw aimed to arc over the array.

    Heading phi ~ U(-heading_range, +heading_range) about +x; entry point
    upstream of the centroid on the -phi side; loft chosen so the (drag-free)
    apex sits above the centroid (apex ~ 1.4-1.9 m for the defaults).
    """
    phi = np.radians(rng.uniform(-heading_range_deg, heading_range_deg))
    v_h = rng.uniform(*speed_range)
    r0 = rng.uniform(*r0_range)
    y0 = rng.uniform(*y0_range)
    t_to_centroid = r0 / v_h
    return ThrowParams(
        x0=-r0 * np.cos(phi), y0=y0, z0=-r0 * np.sin(phi),
        vx=v_h * np.cos(phi), vy=G * t_to_centroid, vz=v_h * np.sin(phi),
        drag=drag, drag_k=drag_k,
    )


# ---------------------------------------------------------------------------
# Sensor sampling + measurement corruption
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SyntheticSession:
    """One simulated throw, in the exact raw format hardware would produce."""
    serial_lines: list            # str lines: fw header first, then CSV rows
    readings: list                # per-reading truth dicts (see generate_session)
    trajectory: Trajectory
    truth: dict                   # summary truth block for session.json

    def serial_bytes(self) -> bytes:
        """The byte stream as the Arduino would send it (CRLF line endings)."""
        return b"".join(line.encode("ascii") + b"\r\n" for line in self.serial_lines)

    def triplet_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Readings as (N, 3) arrays: echo_us, t_trig_us, plus an (N,) mask of
        triplets whose three readings all hit the ball (test convenience)."""
        n = len(self.readings) // 3
        echo = np.array([r["echo_us"] for r in self.readings]).reshape(n, 3)
        t_trig = np.array([r["t_trig_us"] for r in self.readings]).reshape(n, 3)
        target = np.array([r["target"] for r in self.readings]).reshape(n, 3).all(axis=1)
        return echo, t_trig, target


def generate_session(config: dict,
                     throw: ThrowParams,
                     temperature_c: float,
                     noise_mm: float,
                     rng: np.random.Generator,
                     n_bg_pre: int | None = None,
                     n_bg_post: int = 12,
                     n_dropouts: int = 0,
                     background_distance_m: float | None = None,
                     beam_cone_enabled: bool = False,
                     beam_half_angle_deg: float | None = None) -> SyntheticSession:
    """Simulate one full session: background padding, throw, background tail.

    Per reading the interrogation instant is solved by fixed-point iteration
    (t_hit = t_trig + range/v_sound, one-way), the range is taken to the ball
    SURFACE (R2), Gaussian noise is added, and the result is encoded as the
    integer echo time the firmware would print. Echoes longer than
    pulse_timeout_us become the timeout sentinel 0. With
    background_distance_m=None the empty room is open air (all timeouts);
    otherwise a static reflector at that distance is simulated.

    (D2) beam_cone_enabled gates ball detections to the transducer cone: a
    ball further than beam_half_angle_deg (default from
    config["simulator"]["beam_half_angle_deg"]) off the sensor's aim axis at
    the interrogation instant yields a timeout, as real hardware would —
    this reproduces the realistic ~5-6 flight triplets instead of the ~20-22
    the unconstrained model over-produces. Simplification, per the work
    order: a cone-gated reading is a plain timeout even when a static
    background reflector is configured. The kwarg deliberately defaults to
    False (legacy) so existing validation suites keep characterizing the
    over-producing regime; generation entry points that should honor
    config["simulator"]["beam_cone_enabled"] (simulate_session.py, the
    acceptance gate's density test) pass it explicitly.
    """
    geom = ArrayGeometry.from_config(config)
    acq = config["acquisition"]
    slot_s = acq["slot_ms"] * 1e-3
    triplet_s = acq["triplet_ms"] * 1e-3
    timeout_us = acq["pulse_timeout_us"]
    radius = config["ball"]["radius_m"]
    v_sound = speed_of_sound(temperature_c)
    sigma_m = noise_mm * 1e-3

    if n_bg_pre is None:
        n_bg_pre = config["gates"]["bg_n_triplets"] + 10

    aim_axes = cos_half = None
    if beam_cone_enabled:
        aim_axes = sensor_aim_axes(geom, config["array"]["tilt_deg"])
        if beam_half_angle_deg is None:
            beam_half_angle_deg = config["simulator"]["beam_half_angle_deg"]
        cos_half = np.cos(np.radians(beam_half_angle_deg))

    traj = simulate_trajectory(throw, radius)
    t_launch = n_bg_pre * triplet_s
    t_end = t_launch + traj.t_land
    n_flight = int(np.ceil(traj.t_land / triplet_s)) + 1
    n_total = n_bg_pre + n_flight + n_bg_post

    flight_triplets = np.arange(n_bg_pre, n_bg_pre + n_flight)
    dropout_set = set()
    if n_dropouts > 0:
        # Drop interior triplets only, so the throw is not shortened at the ends.
        interior = flight_triplets[1:-1]
        n_drop = min(n_dropouts, len(interior))
        dropout_set = set(rng.choice(interior, size=n_drop, replace=False).tolist())

    sensors = geom.vertices_3d
    header = (f"# fw=05,slot_ms={acq['slot_ms']},"
              f"timeout_us={acq['pulse_timeout_us']}")
    serial_lines = [header]
    readings = []

    def encode_echo(distance_m: float) -> int:
        echo = int(round(2.0 * distance_m / v_sound * 1e6))
        if echo <= 0 or echo > timeout_us:
            return 0
        return echo

    for n in range(n_total):
        for s_idx in range(3):
            t_trig = n * triplet_s + s_idx * slot_s
            t_trig_us = int(round(t_trig * 1e6))

            d_centre = np.nan
            t_hit = t_trig
            target = False
            cone_gated = False
            if t_launch <= t_trig <= t_end and n not in dropout_set:
                # Fixed-point solve of the interrogation instant (one-way).
                for _ in range(3):
                    pos = traj.position(t_hit - t_launch)
                    d_centre = float(np.linalg.norm(pos - sensors[s_idx]))
                    t_hit = t_trig + d_centre / v_sound
                target = t_hit <= t_end
                if target and beam_cone_enabled:
                    # (D2) ball outside this sensor's cone at the
                    # interrogation instant -> no detection.
                    vec = pos - sensors[s_idx]
                    if vec @ aim_axes[s_idx] < cos_half * np.linalg.norm(vec):
                        target = False
                        cone_gated = True

            if target:
                d_surface = d_centre - radius
                d_meas = d_surface + rng.normal(0.0, sigma_m) if sigma_m > 0 else d_surface
                echo_us = encode_echo(d_meas)
            elif cone_gated:
                echo_us = 0           # (D2) out-of-cone: plain timeout
            elif background_distance_m is not None and n not in dropout_set:
                d_meas = background_distance_m + (rng.normal(0.0, sigma_m) if sigma_m > 0 else 0.0)
                echo_us = encode_echo(d_meas)
            else:
                echo_us = 0

            serial_lines.append(f"{s_idx + 1},{echo_us},{t_trig_us}")
            readings.append({
                "sensor_id": s_idx + 1,
                "triplet": n,
                "t_trig_s": t_trig,
                "t_trig_us": t_trig_us,
                "echo_us": echo_us,
                "target": target,
                "t_hit_s": t_hit if target else None,
                "d_centre_m": d_centre if target else None,
                "dropout": n in dropout_set,
                "cone_gated": cone_gated,
            })

    r_true, theta_true = cart_to_polar(*traj.landing_xz)
    truth = {
        "throw": throw.as_dict(),
        "temperature_c": temperature_c,
        "v_sound_m_s": v_sound,
        "noise_mm": noise_mm,
        "t_launch_s": t_launch,
        "t_land_s": t_end,
        "flight_time_s": traj.t_land,
        "apex_y_m": traj.apex_y,
        "landing": {
            "x_m": float(traj.landing_xz[0]),
            "z_m": float(traj.landing_xz[1]),
            "r_m": r_true,
            "theta_deg": theta_true,
        },
        "n_triplets": {
            "background_pre": n_bg_pre,
            "flight": n_flight,
            "background_post": n_bg_post,
            "dropouts": sorted(int(i) for i in dropout_set),
        },
    }
    return SyntheticSession(serial_lines=serial_lines, readings=readings,
                            trajectory=traj, truth=truth)
