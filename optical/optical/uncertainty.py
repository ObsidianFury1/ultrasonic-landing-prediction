"""Per-throw uncertainty budget (Optical.md §7).

Five components, each measured or propagated — never assumed:
  1. marker_survey_m      - survey sigma from config (§3.3), through the fit.
  2. homography_m         - reprojection RMS + check-point error as the empirical
                            proxy for map error at working distance.
  3. pixel_localisation_m - measured detector scatter (px), converted through the
                            LOCAL pixel scale at the landing pixel (the scale varies
                            across the oblique image - §7 item 3).
  4. parallax_residual_m  - sigma of the effective contact height (ball compression
                            surrogate) and camera-position uncertainty through the
                            §5.4 closed form, analytically.
  5. temporal_m           - contact-fit sigma_t times the floor velocity, plus the
                            rolling-shutter term characterised at commissioning
                            (bounded or included, never assumed away).

Combined in quadrature per axis -> (sigma_x, sigma_z) -> propagated to
(sigma_r, sigma_theta). Component magnitudes are also reported as scalars in the
frozen §5.6 `uncertainty.components` block.
"""

from __future__ import annotations

import numpy as np

from optical.calibration import apply_homography
from optical.errors import OpticalConfigError

_UNC_REQUIRED = ("pixel_sigma_px", "sigma_h_m", "sigma_C_m", "rolling_shutter_m")


# --------------------------------------------------------------------------- #
# Uncertainty config parsing (§7; WO-OPT-1 Stage 1 — no silent defaults)       #
# --------------------------------------------------------------------------- #

def read_uncertainty_config(config: dict) -> dict:
    """Extract the §7 uncertainty inputs from `config['uncertainty']`, each stored as a
    `{value, measured}` pair. Returns a dict with the four values plus `unmeasured`
    (the list of component names whose `measured` flag is False).

    Raises ValueError — a HARD error, never a silent default (WO-OPT-1 Stage 1 / audit
    M1) — if the block or any required key is missing or malformed. A placeholder
    (`measured: false`) is allowed to be consumed, but it is surfaced via `unmeasured`
    so the caller can flag it (`unmeasured_uncertainty_components`, §5.6)."""
    if "uncertainty" not in config or config["uncertainty"] is None:
        raise OpticalConfigError(
            "config.yaml is missing the required 'uncertainty:' block (Optical.md section 7 / "
            "WO-OPT-1 Stage 1). Uncertainty inputs must be configured explicitly and are "
            "never silently defaulted.")
    u = config["uncertainty"]
    out: dict = {}
    unmeasured: list[str] = []
    for key in _UNC_REQUIRED:
        if key not in u:
            raise OpticalConfigError(f"config.yaml uncertainty block is missing required "
                                     f"key '{key}' (Optical.md section 7).")
        entry = u[key]
        if not isinstance(entry, dict) or "value" not in entry or "measured" not in entry:
            raise OpticalConfigError(f"config.yaml uncertainty['{key}'] must be a "
                                     f"{{value, measured}} mapping, got {entry!r}.")
        out[key] = entry["value"]
        if not entry["measured"]:
            unmeasured.append(key)
    out["unmeasured"] = unmeasured
    return out


SURVEY_SIGMA_COMPONENT = "markers.survey_sigma_m"


def read_survey_sigma(config: dict) -> dict:
    """Extract `config['markers']['survey_sigma_m']` as a `{value, measured}` pair (§7 item 1 /
    WO-OPT-3 Stage 3, Moderate 5.2, Decision D11). SIBLING of `read_uncertainty_config`: the
    survey sigma lives in the `markers:` block, not the `uncertainty:` block, so it is parsed
    separately — this keeps `read_uncertainty_config` (and the minimal-config tests that call it
    without a `markers:` block) untouched.

    Returns `{'value': float, 'measured': bool, 'unmeasured': [SURVEY_SIGMA_COMPONENT] or []}`.
    Same posture as the four uncertainty-block components: HARD error (never a silent default)
    on a missing key or malformed shape; a `measured: false` placeholder is consumed but
    surfaced via `unmeasured` so the caller folds it into `unmeasured_uncertainty_components`
    (§5.6). The numeric value is unchanged from the pre-WO-OPT-3 bare number (0.0025)."""
    markers = config.get("markers")
    if not isinstance(markers, dict) or "survey_sigma_m" not in markers:
        raise OpticalConfigError(
            "config.yaml is missing markers.survey_sigma_m (Optical.md section 7 item 1 / "
            "WO-OPT-3 Stage 3). It must be a {value, measured} mapping; no silent default.")
    entry = markers["survey_sigma_m"]
    if not isinstance(entry, dict) or "value" not in entry or "measured" not in entry:
        raise OpticalConfigError(
            f"config.yaml markers.survey_sigma_m must be a {{value, measured}} mapping "
            f"(WO-OPT-3 Stage 3), got {entry!r}.")
    return {"value": float(entry["value"]), "measured": bool(entry["measured"]),
            "unmeasured": [] if entry["measured"] else [SURVEY_SIGMA_COMPONENT]}


# --------------------------------------------------------------------------- #
# Local pixel scale                                                            #
# --------------------------------------------------------------------------- #

def local_floor_jacobian(H_px2floor: np.ndarray, uv, delta_px: float = 1.0
                         ) -> np.ndarray:
    """2x2 Jacobian d(floor x,z)/d(pixel u,v) [m/px] at pixel uv, by central
    differences through the homography (exact enough: H is smooth)."""
    uv = np.asarray(uv, dtype=float)
    J = np.zeros((2, 2))
    for k, e in enumerate(np.eye(2) * delta_px):
        p = apply_homography(H_px2floor, uv + e)[0]
        m = apply_homography(H_px2floor, uv - e)[0]
        J[:, k] = (p - m) / (2.0 * delta_px)
    return J


def pixel_sigma_to_floor(J: np.ndarray, sigma_px: float) -> np.ndarray:
    """Isotropic pixel sigma through the local Jacobian -> per-axis floor sigma [m]:
    cov_floor = sigma_px^2 * J J^T."""
    cov = (sigma_px ** 2) * (J @ J.T)
    return np.sqrt(np.diag(cov))


# --------------------------------------------------------------------------- #
# Parallax residual (analytic, §5.4 formula)                                   #
# --------------------------------------------------------------------------- #

def parallax_sigma(P_mapped, h: float, C, sigma_h: float,
                   sigma_C=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Per-axis sigma [m] of the corrected point from sigma(h) and sigma(C) through
    P_floor = P - (h/C_y)(P - C_ground). Partials:
      dP/dh    = -(P - C_ground)/C_y
      dP/dC_y  =  h (P - C_ground)/C_y^2
      dP/dC_gx =  (h/C_y) e_x ,  dP/dC_gz = (h/C_y) e_z
    Combined in quadrature per axis (independent inputs)."""
    P = np.asarray(P_mapped, dtype=float)
    C = np.asarray(C, dtype=float)
    d = P - np.array([C[0], C[2]])
    var = (sigma_h * d / C[1]) ** 2 \
        + (sigma_C[1] * h * d / C[1] ** 2) ** 2 \
        + (np.array([sigma_C[0], sigma_C[2]]) * h / C[1]) ** 2
    return np.sqrt(var)


# --------------------------------------------------------------------------- #
# Polar propagation                                                            #
# --------------------------------------------------------------------------- #

def polar_sigma(x: float, z: float, sigma_x: float, sigma_z: float
                ) -> tuple[float, float]:
    """(sigma_x, sigma_z) -> (sigma_r [m], sigma_theta [deg]) at the point (x, z),
    first-order (independent axes):
      r = sqrt(x^2+z^2):        sigma_r^2     = (x sx)^2 + (z sz)^2, over r^2
      theta = atan2(z, x):      sigma_th^2    = (z sx)^2 + (x sz)^2, over r^4
    """
    r = float(np.hypot(x, z))
    if r < 1e-9:
        raise ValueError("polar uncertainty undefined at r = 0")
    sr = np.sqrt((x * sigma_x) ** 2 + (z * sigma_z) ** 2) / r
    st = np.sqrt((z * sigma_x) ** 2 + (x * sigma_z) ** 2) / r ** 2
    return float(sr), float(np.degrees(st))


# --------------------------------------------------------------------------- #
# Budget assembly (frozen §5.6 component names)                                #
# --------------------------------------------------------------------------- #

def build_budget(*, landing_xz, landing_uv, H_px2floor,
                 marker_survey_m: float,
                 reproj_rms_px: float, check_point_err_m: float,
                 sigma_px: float,
                 parallax_P_mapped, r_ball: float, camera_C,
                 sigma_h_m: float, sigma_C_m=(0.0, 0.0, 0.0),
                 vel_xz, sigma_t_s: float,
                 rolling_shutter_m: float = 0.0) -> dict:
    """Assemble the §5.6 `uncertainty` block. Per-axis where direction exists
    (pixel localisation via the local Jacobian, parallax via the §5.4 partials,
    temporal via the velocity vector); isotropic for survey and homography (scalar
    empirical proxies). Component scalars = per-axis norms/values for the report.
    """
    x, z = float(landing_xz[0]), float(landing_xz[1])
    J = local_floor_jacobian(H_px2floor, landing_uv)

    # per-axis pieces
    survey_ax = np.array([marker_survey_m, marker_survey_m])
    scale = np.linalg.svd(J, compute_uv=False)          # m/px singular values
    homography_m = float(np.hypot(reproj_rms_px * float(scale[0]),
                                  check_point_err_m))
    homography_ax = np.array([homography_m, homography_m]) / np.sqrt(2.0)
    pixel_ax = pixel_sigma_to_floor(J, sigma_px)
    if camera_C is not None:
        parallax_ax = parallax_sigma(parallax_P_mapped, r_ball, camera_C,
                                     sigma_h_m, sigma_C_m)
    else:
        # fallback method: no analytic correction; charge sigma_h directly as the
        # bound on the un-modelled bottom-point geometry
        parallax_ax = np.array([sigma_h_m, sigma_h_m])
    v = np.asarray(vel_xz, dtype=float)
    temporal_ax = np.sqrt((v * sigma_t_s) ** 2 + rolling_shutter_m ** 2)

    var = (survey_ax ** 2 + homography_ax ** 2 + pixel_ax ** 2
           + parallax_ax ** 2 + temporal_ax ** 2)
    sigma_x, sigma_z = np.sqrt(var)
    sigma_r, sigma_theta = polar_sigma(x, z, float(sigma_x), float(sigma_z))

    return {
        "sigma_x_m": round(float(sigma_x), 6),
        "sigma_z_m": round(float(sigma_z), 6),
        "sigma_r_m": round(float(sigma_r), 6),
        "sigma_theta_deg": round(float(sigma_theta), 4),
        "components": {
            "marker_survey_m": round(float(marker_survey_m), 6),
            "homography_m": round(homography_m, 6),
            "pixel_localisation_m": round(float(np.linalg.norm(pixel_ax)
                                                / np.sqrt(2.0)), 6),
            "parallax_residual_m": round(float(np.linalg.norm(parallax_ax)
                                               / np.sqrt(2.0)), 6),
            "temporal_m": round(float(np.linalg.norm(temporal_ax)
                                      / np.sqrt(2.0)), 6),
        },
    }
