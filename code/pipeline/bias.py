"""Throw-aligned empirical drag correction (CLAUDE.md section 8.6).

Residuals are calibrated in a per-throw TRACK-ALIGNED frame: throws are
deliberately spread in heading, and the drag overshoot rotates with the
heading, so averaging in the fixed array frame cancels real bias. Per
calibration throw with heading phi:

    (r_x, r_z) = (x_pred - x_actual, z_pred - z_actual)
    r_along =  r_x*cos(phi) + r_z*sin(phi)      # expect mean > 0 (overshoot)
    r_cross = -r_x*sin(phi) + r_z*cos(phi)      # expect mean ~ 0 (Magnus shows here)

The significance gate keeps an offset only if its 95% CI excludes zero, with
the CI built from scipy.stats.t.ppf (NEVER a hardcoded 1.96). Application
rotates the track-frame offsets back by the NEW throw's heading and subtracts
in Cartesian; (r, theta) only at the output (section 0.2).

Discipline (structural, not advisory): never calibrate and validate on the
same throws; never touch the Kalman filter (this module does not import it).

Pure logic: JSON (de)serialization lives here, file I/O in
scripts/calibrate_bias.py.
"""

import datetime
from dataclasses import asdict, dataclass, field, replace

import numpy as np
from scipy import stats

from pipeline.geometry import cart_to_polar


@dataclass(frozen=True)
class ThrowRecord:
    """One calibration throw: raw prediction + ground truth + heading."""
    x_pred: float
    z_pred: float
    x_actual: float
    z_actual: float
    heading_deg: float
    v_h_m_s: float


def to_track(r_x, r_z, heading_deg):
    """Array-frame residual -> (r_along, r_cross) in the throw's track frame."""
    phi = np.radians(heading_deg)
    return (r_x * np.cos(phi) + r_z * np.sin(phi),
            -r_x * np.sin(phi) + r_z * np.cos(phi))


def from_track(r_along, r_cross, heading_deg):
    """Track-frame offset -> array-frame (x, z) components."""
    phi = np.radians(heading_deg)
    return (r_along * np.cos(phi) - r_cross * np.sin(phi),
            r_along * np.sin(phi) + r_cross * np.cos(phi))


@dataclass(frozen=True)
class AxisStats:
    """Per-axis calibration statistics (scalar mode)."""
    mean: float
    std: float            # ddof=1
    sem: float
    ci_low: float
    ci_high: float
    significant: bool     # CI excludes zero

    @classmethod
    def from_samples(cls, samples: np.ndarray, alpha: float) -> "AxisStats":
        n = len(samples)
        mean = float(np.mean(samples))
        std = float(np.std(samples, ddof=1))
        sem = float(std / np.sqrt(n))
        t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, n - 1))   # never 1.96
        lo, hi = mean - t_crit * sem, mean + t_crit * sem
        return cls(mean=mean, std=std, sem=sem, ci_low=lo, ci_high=hi,
                   significant=bool(lo > 0.0 or hi < 0.0))


@dataclass(frozen=True)
class CorrectionModel:
    mode: str                       # 'none' | 'scalar' | 'linear'
    frame: str                      # always 'track' for applied models
    offset_along_m: float
    offset_cross_m: float
    linear_slope: float             # r_along ~ slope*v_h + intercept (mode='linear')
    linear_intercept: float
    n_throws: int
    alpha: float
    along: AxisStats
    cross: AxisStats
    diagnostics: dict = field(default_factory=dict)
    created: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CorrectionModel":
        d = dict(d)
        d["along"] = AxisStats(**d["along"])
        d["cross"] = AxisStats(**d["cross"])
        return cls(**d)


def _residuals(records, frame: str):
    r_x = np.array([t.x_pred - t.x_actual for t in records])
    r_z = np.array([t.z_pred - t.z_actual for t in records])
    if frame == "track":
        phi = np.array([t.heading_deg for t in records])
        return to_track(r_x, r_z, phi)
    if frame == "array":
        # TEST-ONLY control path: fixed array axes. Spread headings make the
        # rotating drag bias partially cancel here — the design rationale for
        # the track frame. Never used for an applied model.
        return r_x, r_z
    raise ValueError(f"frame must be 'track' or 'array', got {frame!r}")


def calibrate(records, alpha: float, frame: str = "track",
              allow_linear: bool = True) -> CorrectionModel:
    """Fit the scalar (and optionally linear) track-frame correction."""
    if len(records) < 3:
        raise ValueError("need at least 3 calibration throws")
    r_along, r_cross = _residuals(records, frame)
    along = AxisStats.from_samples(r_along, alpha)
    cross = AxisStats.from_samples(r_cross, alpha)

    offset_along = along.mean if along.significant else 0.0
    offset_cross = cross.mean if cross.significant else 0.0
    mode = "scalar" if (along.significant or cross.significant) else "none"

    slope = intercept = 0.0
    if allow_linear and mode == "scalar" and along.significant:
        v_h = np.array([t.v_h_m_s for t in records])
        if np.std(v_h) > 1e-9:
            reg = stats.linregress(v_h, r_along)
            scatter_linear = float(np.std(
                r_along - (reg.slope * v_h + reg.intercept), ddof=1))
            if reg.pvalue < alpha and scatter_linear < along.std:
                mode = "linear"
                slope, intercept = float(reg.slope), float(reg.intercept)

    return CorrectionModel(
        mode=mode, frame=frame,
        offset_along_m=offset_along, offset_cross_m=offset_cross,
        linear_slope=slope, linear_intercept=intercept,
        n_throws=len(records), alpha=alpha, along=along, cross=cross,
        diagnostics={}, created=datetime.datetime.now().isoformat(timespec="seconds"),
    )


def apply_correction(model: CorrectionModel, x_pred: float, z_pred: float,
                     heading_deg: float, v_h_m_s: float | None = None):
    """Correct one new throw's raw prediction. Returns dict with corrected
    Cartesian and polar coordinates. mode='none' -> passthrough."""
    if model.mode == "none":
        x_c, z_c = x_pred, z_pred
    else:
        along = model.offset_along_m
        if model.mode == "linear":
            if v_h_m_s is None:
                raise ValueError("linear model needs the new throw's v_h")
            along = model.linear_slope * v_h_m_s + model.linear_intercept
        dx, dz = from_track(along, model.offset_cross_m, heading_deg)
        x_c, z_c = x_pred - dx, z_pred - dz
    r, theta = cart_to_polar(x_c, z_c)
    return {"x_m": x_c, "z_m": z_c, "r_m": r, "theta_deg": theta}


def evaluate(model: CorrectionModel, records) -> dict:
    """Per-throw 2D landing errors before and after applying the model."""
    before, after = [], []
    for t in records:
        before.append(np.hypot(t.x_pred - t.x_actual, t.z_pred - t.z_actual))
        c = apply_correction(model, t.x_pred, t.z_pred, t.heading_deg, t.v_h_m_s)
        after.append(np.hypot(c["x_m"] - t.x_actual, c["z_m"] - t.z_actual))
    return {"before": np.array(before), "after": np.array(after)}


def calibrate_with_validation(records, alpha: float, split_frac: float = 0.5,
                              rng: np.random.Generator | None = None,
                              frame: str = "track",
                              allow_linear: bool = False) -> CorrectionModel:
    """Split -> calibrate -> validate -> accept/reject (section 8.6 mandatory).

    The calibration and validation sets are DISJOINT by construction. The
    correction is accepted only if the held-out errors improve significantly
    (one-sided paired t-test, p < alpha); otherwise mode='none' with the
    reason recorded in diagnostics ("say so"). On acceptance the offsets are
    refit on all throws; the validation verdict and before/after statistics
    are kept in diagnostics.

    allow_linear defaults to False here (unlike plain calibrate): on a small
    calibration half the in-sample linear criteria overfit easily — measured:
    a 6-throw linear candidate failed held-out validation that the scalar
    model passes. Enable deliberately when the throw count supports it.
    """
    records = list(records)
    n = len(records)
    if n < 6:
        raise ValueError("need at least 6 throws for a calibrate/validate split")
    rng = rng or np.random.default_rng()
    order = rng.permutation(n)
    n_cal = max(3, int(round(n * split_frac)))
    n_cal = min(n_cal, n - 3)
    cal_idx, val_idx = sorted(order[:n_cal].tolist()), sorted(order[n_cal:].tolist())
    assert not set(cal_idx) & set(val_idx)          # split discipline, structural
    cal = [records[i] for i in cal_idx]
    val = [records[i] for i in val_idx]

    candidate = calibrate(cal, alpha, frame=frame, allow_linear=allow_linear)
    diag = {
        "cal_indices": cal_idx, "val_indices": val_idx,
        "n_cal": len(cal), "n_val": len(val),
    }

    if candidate.mode == "none":
        diag["verdict"] = ("rejected: no significant track-frame bias on the "
                           "calibration set")
        return replace(candidate, diagnostics=diag)

    errs = evaluate(candidate, val)
    t_stat, p_two = stats.ttest_rel(errs["before"], errs["after"])
    p_one = p_two / 2.0 if t_stat > 0 else 1.0 - p_two / 2.0
    diag.update({
        "val_error_before_m": float(errs["before"].mean()),
        "val_error_after_m": float(errs["after"].mean()),
        "val_p_one_sided": float(p_one),
    })

    if p_one < alpha and errs["after"].mean() < errs["before"].mean():
        final = calibrate(records, alpha, frame=frame, allow_linear=allow_linear)
        diag["verdict"] = ("accepted: validation error improved "
                           f"{errs['before'].mean():.3f} -> "
                           f"{errs['after'].mean():.3f} m (p = {p_one:.4f}); "
                           "offsets refit on all throws")
        return replace(final, diagnostics=diag)

    diag["verdict"] = (f"rejected: held-out improvement not significant "
                       f"(p = {p_one:.4f}) — correction disabled (mode='none')")
    return CorrectionModel(
        mode="none", frame=frame, offset_along_m=0.0, offset_cross_m=0.0,
        linear_slope=0.0, linear_intercept=0.0, n_throws=n, alpha=alpha,
        along=candidate.along, cross=candidate.cross,
        diagnostics=diag, created=candidate.created)
