"""Landing extrapolation and per-throw uncertainty (CLAUDE.md section 8.5, R7).

TIME-parameterized variant (explicitly sanctioned by the spec as the more
robust choice): x(t), z(t) degree-1, y(t) degree-2, fitted to the Kalman-
filtered states; solve y(t*) = ball.radius_m (the ball CENTRE at floor
contact — the trajectory tracks the centre, so contact is at y = radius, not
y = 0) on the DESCENDING branch; landing point = (x(t*), z(t*)).
Rationale vs the x-parameterized default: the +/-60 deg heading spread
shrinks the x-span by up to 2x and a steep throw makes x-parameterization
ill-conditioned, while t always advances monotonically — the degenerate
x-span abort path disappears entirely. The covariance propagation (R7) maps
directly.

Covariance: explicit Vandermonde least squares with C = (RSS/dof)*(V^T V)^-1
— the same estimate numpy.polyfit(cov=True) returns, computed manually
because polyfit refuses M < order + 3, which would contradict
min_fit_points = 4 (dof = M - 3 = 1 is legal and is exactly the small-sample
case the R7 caveat warns about). Propagation to the landing point couples x
and z through the shared root time t*; polar conversion happens ONLY at the
output (section 0.2).

Pure logic, no I/O: the mandatory small-sample caveat is returned as a
string field; run_session.py prints it once per session.
"""

from dataclasses import dataclass, field

import numpy as np

from pipeline.geometry import cart_to_polar
from pipeline.kalman import FilterResult

ABORT_MESSAGE = ("throw too short for a landing fit ({m} usable triplets < "
                 "min_fit_points = {need}) — throw slower/loftier so more "
                 "triplets land in the overlap column")

CAVEAT_TEMPLATE = (
    "R7 small-sample caveat: the landing covariance rests on only {dof} "
    "degree(s) of freedom ({m} fitted points, 3 parabola parameters), so the "
    "uncertainty ellipse is itself highly uncertain — treat (sigma_r, "
    "sigma_theta) as indicative, not as a calibrated confidence region.")


@dataclass(frozen=True)
class LandingPrediction:
    x: float                 # landing point, floor frame [m]
    z: float
    r: float                 # polar output [m]
    theta_deg: float         # (-180, 180], CCW from +x
    sigma_r: float           # R7 per-throw uncertainty [m]
    sigma_theta_deg: float   # [deg]
    cov_xz: np.ndarray       # 2x2 landing covariance [m^2]
    t_land_s: float          # absolute time of floor contact [s]
    heading_deg: float       # phi = atan2(mean vz, mean vx), for bias.py
    v_h_m_s: float           # horizontal speed, for bias.py
    n_points: int
    dof: int                 # n_points - 3 (the y-fit dominates)
    caveat: str = field(repr=False)


def _fit_poly(t: np.ndarray, values: np.ndarray, deg: int):
    """Least-squares polynomial fit with the textbook coefficient covariance.

    Returns (coeffs highest-power-first, covariance). dof = M - (deg+1) must
    be >= 1; with zero residual (noise-free data) the covariance is ~0.
    """
    V = np.vander(t, deg + 1)
    coeffs, _, _, _ = np.linalg.lstsq(V, values, rcond=None)
    resid = values - V @ coeffs
    dof = len(t) - (deg + 1)
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(V.T @ V)
    return coeffs, cov


def predict_landing(filt: FilterResult, *, ball_radius_m: float,
                    min_fit_points: int,
                    target_y_m: float | None = None) -> LandingPrediction:
    """Fit the filtered trajectory and extrapolate to floor contact.

    target_y_m overrides the solve target (default: ball_radius_m); used by
    the y = r_ball vs y = 0 test and nothing else.
    """
    t_abs = np.asarray(filt.t_s, dtype=float)
    pos = np.asarray(filt.pos, dtype=float)
    vel = np.asarray(filt.vel, dtype=float)
    m = len(t_abs)
    if m < min_fit_points:
        raise ValueError(ABORT_MESSAGE.format(m=m, need=min_fit_points))
    if not (np.isfinite(t_abs).all() and np.isfinite(pos).all()):
        raise ValueError("filtered states must be finite")
    if min_fit_points < 4:
        raise ValueError("min_fit_points must be >= 4 (y-fit has 3 parameters)")

    t = t_abs - t_abs[0]                      # conditioning: small t values
    ax, Cx = _fit_poly(t, pos[:, 0], 1)       # x(t) = ax0*t + ax1
    az, Cz = _fit_poly(t, pos[:, 2], 1)
    ay, Cy = _fit_poly(t, pos[:, 1], 2)       # y(t) = ay0*t^2 + ay1*t + ay2

    target = ball_radius_m if target_y_m is None else target_y_m

    # Descending-branch root of y(t) = target. A real arc is concave-down
    # (a ~ -g/2); a flat or upward-curving fit has no ballistic descent and
    # would otherwise yield an absurd far-future root (numerical tolerance,
    # not a physical constant).
    a, b, c = ay[0], ay[1], ay[2] - target
    if a >= -1e-6:
        raise ValueError("fitted y(t) is not concave-down — no ballistic arc "
                         "to extrapolate (degenerate or rising-only segment)")
    disc = b**2 - 4 * a * c
    if disc < 0:
        raise ValueError("fitted parabola never reaches the floor-contact "
                         "height — fit unusable (check the throw segmentation)")
    sq = np.sqrt(disc)
    roots = np.array([(-b - sq) / (2 * a), (-b + sq) / (2 * a)])
    descending = roots[2 * a * roots + b < 0]  # ydot(t*) < 0
    if len(descending) == 0:
        raise ValueError("no descending floor-contact root — trajectory does "
                         "not come down within the fitted model")
    t_star = float(descending[0])
    ydot = 2 * a * t_star + b                 # < 0 by construction

    x_land = float(np.polyval(ax, t_star))
    z_land = float(np.polyval(az, t_star))

    # --- R7 covariance propagation -------------------------------------
    # t* depends on the y coefficients: dt*/da_y = -[t*^2, t*, 1] / ydot.
    g_y = np.array([t_star**2, t_star, 1.0])
    dt_day = -g_y / ydot
    vx, vz = ax[0], az[0]                     # dx/dt*, dz/dt*
    g_x = np.array([t_star, 1.0])             # dx/da_x
    var_t = float(dt_day @ Cy @ dt_day)       # variance of t* from the y-fit
    var_x = float(g_x @ Cx @ g_x) + vx**2 * var_t
    var_z = float(g_x @ Cz @ g_x) + vz**2 * var_t
    cov_xz_term = vx * vz * var_t             # x and z share the t* error
    cov = np.array([[var_x, cov_xz_term], [cov_xz_term, var_z]])

    # Polar Jacobian at the predicted point (degrees only at the interface).
    r, theta_deg = cart_to_polar(x_land, z_land)
    if r < 1e-12:
        raise ValueError("landing at the origin — polar uncertainty undefined")
    J = np.array([[x_land / r, z_land / r],
                  [-z_land / r**2, x_land / r**2]])   # rows: dr, dtheta [rad]
    pol = J @ cov @ J.T
    sigma_r = float(np.sqrt(pol[0, 0]))
    sigma_theta_deg = float(np.degrees(np.sqrt(pol[1, 1])))

    # Heading export for bias.py (track-aligned drag model).
    v_mean = vel[:, [0, 2]].mean(axis=0)
    heading_deg = float(np.degrees(np.arctan2(v_mean[1], v_mean[0])))
    v_h = float(np.hypot(*v_mean))

    dof = m - 3
    return LandingPrediction(
        x=x_land, z=z_land, r=r, theta_deg=theta_deg,
        sigma_r=sigma_r, sigma_theta_deg=sigma_theta_deg, cov_xz=cov,
        t_land_s=float(t_abs[0] + t_star),
        heading_deg=heading_deg, v_h_m_s=v_h,
        n_points=m, dof=dof,
        caveat=CAVEAT_TEMPLATE.format(dof=dof, m=m),
    )
