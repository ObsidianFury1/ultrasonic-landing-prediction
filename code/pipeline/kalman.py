"""7-state augmented Kalman filter (CLAUDE.md section 8.4).

State vector [x, y, z, vx, vy, vz, 1]^T in the floor frame (y up). Gravity is
encoded ONLY through the constant 7th (bias) state, via the F columns
-0.5*g*dt^2 (y) and -g*dt (vy). **Never modify F or the bias state to absorb
drag or anything else** — drag is handled empirically downstream by bias.py.

F is rebuilt at EVERY predict step from the measured Delta-t of t_sample
between consecutive USED triplets (R3): rejected triplets create ~108/162 ms
gaps, which simply become larger dt's — the filter coasts and P inflates
correctly. A fixed-dt filter is exactly the design error the audit
disposition record rejects (section 12).

Per-update measurement noise (R6, hetero_R): R = diag(sigma_pos^2,
sigma_y(triplet)^2, sigma_pos^2). The neglected x-y-z cross-correlation of
trilateration noise is a documented simplification (report sentence).

Pure logic, no I/O.
"""

from dataclasses import dataclass

import numpy as np
from filterpy.kalman import KalmanFilter

G = 9.81  # m/s^2; the same constant the simulator integrates with


def build_F(dt: float) -> np.ndarray:
    """Spec state-transition matrix for a measured time step dt [s].

    Gravity only, through the bias-state column. Anything else (drag, wind,
    per-axis fudge factors) is forbidden here by design.
    """
    F = np.eye(7)
    F[0, 3] = dt
    F[1, 4] = dt
    F[2, 5] = dt
    F[1, 6] = -0.5 * G * dt**2
    F[4, 6] = -G * dt
    return F


@dataclass(frozen=True)
class FilterResult:
    """Post-update states at each used-triplet instant."""
    t_s: np.ndarray    # (M,) t_sample of the S1 reading [s]
    pos: np.ndarray    # (M, 3) filtered (x, y, z), floor frame
    vel: np.ndarray    # (M, 3) filtered (vx, vy, vz)
    bias: np.ndarray   # (M,) the 7th state; must stay == 1 (gravity encoding)


def filter_trajectory(t_s, xyz, sigma_y=None, *, sigma_pos_m: float,
                      q_scale: float, hetero_R: bool = True) -> FilterResult:
    """Run the filter over the USED triplets of one throw.

    t_s      : (M,) S1 t_sample instants [s], strictly increasing (gaps from
               rejected triplets are expected and handled via dt).
    xyz      : (M, 3) trilaterated floor-frame positions [m].
    sigma_y  : (M,) per-triplet vertical noise from trilateration (R6);
               required when hetero_R, ignored otherwise.
    """
    t_s = np.asarray(t_s, dtype=float)
    xyz = np.asarray(xyz, dtype=float)
    m = len(t_s)
    if xyz.shape != (m, 3):
        raise ValueError(f"xyz must be ({m}, 3), got {xyz.shape}")
    if m < 2:
        raise ValueError("need at least 2 used triplets to initialise velocity")
    if not np.all(np.diff(t_s) > 0):
        raise ValueError("t_s must be strictly increasing")
    if not (np.isfinite(xyz).all() and np.isfinite(t_s).all()):
        raise ValueError("inputs must be finite (used triplets only)")
    if hetero_R:
        sigma_y = np.asarray(sigma_y, dtype=float)
        if sigma_y.shape != (m,) or not np.isfinite(sigma_y).all():
            raise ValueError("hetero_R needs finite (M,) sigma_y")

    def R_for(n: int) -> np.ndarray:
        if hetero_R:
            return np.diag([sigma_pos_m**2, sigma_y[n]**2, sigma_pos_m**2])
        return np.eye(3) * sigma_pos_m**2

    kf = KalmanFilter(dim_x=7, dim_z=3)
    kf.H = np.hstack([np.eye(3), np.zeros((3, 4))])

    # Init: position from the first used triplet, velocity from the first
    # forward difference, bias = 1 exactly.
    v0 = (xyz[1] - xyz[0]) / (t_s[1] - t_s[0])
    kf.x = np.concatenate([xyz[0], v0, [1.0]])
    P0 = np.zeros((7, 7))
    P0[:3, :3] = R_for(0)
    P0[3:6, 3:6] = np.eye(3) * 25.0          # generous initial velocity P
    P0[6, 6] = 1e-12                         # bias state is (nearly) certain
    kf.P = P0

    Q = np.zeros((7, 7))
    Q[:6, :6] = np.eye(6) * q_scale          # 7th-state process noise = 0
    kf.Q = Q

    pos = np.empty((m, 3))
    vel = np.empty((m, 3))
    bias = np.empty(m)
    pos[0], vel[0], bias[0] = xyz[0], v0, 1.0

    for n in range(1, m):
        dt = t_s[n] - t_s[n - 1]             # measured, never the nominal 54 ms
        kf.F = build_F(dt)
        kf.predict()
        kf.R = R_for(n)
        kf.update(xyz[n])
        pos[n] = kf.x[:3]
        vel[n] = kf.x[3:6]
        bias[n] = kf.x[6]

    return FilterResult(t_s=t_s, pos=pos, vel=vel, bias=bias)
