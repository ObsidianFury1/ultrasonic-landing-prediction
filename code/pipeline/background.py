"""Background calibration and validity gate (CLAUDE.md sections 5.3-5.4, R1, A2).

Works in the distance domain: (N, 3) arrays of one-way distances [m] with NaN
for timeouts (produced by corrections.echo_us_to_m). Per sensor i over the
calibration block:
  - f0_i        timeout fraction
  - n_valid_i   non-timeout count
  - mu_i, sigma_i (ddof=1) over non-timeout readings
  - R1 gate-enable: the band rule is DISABLED when f0 > bg_timeout_skip
    (open-air background) or n_valid < bg_min_samples (too sparse to
    characterize); else band half-width w = max(bg_k_sigma*sigma, d_min_band_m)
    (the floor stops a quantization-level sigma from closing the gate).

Validity (section 5.4): a reading is VALID iff (1) not a timeout (NaN),
(2) d <= d_max_m, (3) |d - mu| > w — rule 3 only where the band is enabled.
A triplet is VALID iff all three readings are. Flags, never deletions.

A2: ceiling wrap-around ghost prediction for --background-only — a static
ceiling reflector whose echo exceeds one slot returns during the NEXT slot
and is timestamped as a short apparent range that can pass the d_max gate;
being static, it is captured by this same band rule (which is why the
firmware schedule stays rigid).

Pure logic, no I/O (background.json is written by callers from to_dict()).
"""

from dataclasses import asdict, dataclass

import numpy as np

from pipeline.corrections import speed_of_sound


@dataclass(frozen=True)
class SensorBackground:
    f0: float          # timeout fraction
    n_valid: int       # non-timeout sample count
    mu: float          # NaN when uncharacterizable
    sigma: float       # ddof=1; NaN when n_valid < 2
    w: float           # band half-width [m]; NaN when disabled
    enabled: bool      # R1 gate-enable flag for the band rule


@dataclass(frozen=True)
class BackgroundModel:
    sensors: tuple     # (SensorBackground, SensorBackground, SensorBackground)
    k_sigma: float
    d_max_m: float

    def to_dict(self) -> dict:
        return {
            "sensors": [asdict(s) for s in self.sensors],
            "k_sigma": self.k_sigma,
            "d_max_m": self.d_max_m,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackgroundModel":
        return cls(sensors=tuple(SensorBackground(**s) for s in d["sensors"]),
                   k_sigma=d["k_sigma"], d_max_m=d["d_max_m"])


def calibrate_background(d_bg, gates_cfg: dict) -> BackgroundModel:
    """Characterize the empty room from (N, 3) background distances (NaN = timeout)."""
    d = np.asarray(d_bg, dtype=float)
    if d.ndim != 2 or d.shape[1] != 3:
        raise ValueError(f"expected (N, 3) distances, got {d.shape}")
    n = len(d)
    if n == 0:
        raise ValueError("empty background block")

    sensors = []
    for i in range(3):
        col = d[:, i]
        valid = col[np.isfinite(col)]
        f0 = float(1.0 - len(valid) / n)
        n_valid = int(len(valid))
        mu = float(np.mean(valid)) if n_valid >= 1 else float("nan")
        sigma = float(np.std(valid, ddof=1)) if n_valid >= 2 else float("nan")
        # R1 enable logic: open-air or too-sparse backgrounds cannot be
        # characterized -> band rule off, any non-timeout echo within d_max
        # is treated as signal.
        enabled = bool(f0 <= gates_cfg["bg_timeout_skip"]
                       and n_valid >= gates_cfg["bg_min_samples"])
        w = (max(gates_cfg["bg_k_sigma"] * sigma, gates_cfg["d_min_band_m"])
             if enabled else float("nan"))
        sensors.append(SensorBackground(f0=f0, n_valid=n_valid, mu=mu,
                                        sigma=sigma, w=w, enabled=enabled))
    return BackgroundModel(sensors=tuple(sensors),
                           k_sigma=gates_cfg["bg_k_sigma"],
                           d_max_m=gates_cfg["d_max_m"])


def disabled_background(gates_cfg: dict) -> BackgroundModel:
    """A BackgroundModel with every band DISABLED (the R1 open-air equivalent).

    For a session where background calibration is intentionally SKIPPED (open
    ground / no static reflector to subtract): every non-timeout echo within
    d_max is treated as signal, exactly as an open-air calibration (f0 = 1, band
    disabled) would yield — but WITHOUT the ~11 s calibration wait. Persisting
    this as background.json makes the offline process_session gate identically
    to the live path (it loads the file instead of recalibrating from the log,
    which in a skipped-calibration capture has no background padding).
    """
    s = SensorBackground(f0=1.0, n_valid=0, mu=float("nan"),
                         sigma=float("nan"), w=float("nan"), enabled=False)
    return BackgroundModel(sensors=(s, s, s),
                           k_sigma=gates_cfg["bg_k_sigma"],
                           d_max_m=gates_cfg["d_max_m"])


def sanity_warnings(model: BackgroundModel, lo_m: float = 0.5) -> list:
    """Section 5.3 warn-don't-abort: enabled bands inside the ball's working
    range [lo_m, d_max] will eat real ball readings near that distance."""
    out = []
    for i, s in enumerate(model.sensors):
        if not s.enabled:
            continue
        band_lo, band_hi = s.mu - s.w, s.mu + s.w
        if band_hi >= lo_m and band_lo <= model.d_max_m:
            out.append(
                f"WARNING S{i + 1}: background band [{band_lo:.3f}, "
                f"{band_hi:.3f}] m overlaps the ball range [{lo_m}, "
                f"{model.d_max_m}] m — gating will eat real ball readings "
                "near that distance; reconsider the array/room geometry.")
    return out


def reading_valid(d, model: BackgroundModel) -> np.ndarray:
    """Section 5.4 per-reading validity over (N, 3) distances (NaN = timeout)."""
    d = np.asarray(d, dtype=float)
    if d.ndim != 2 or d.shape[1] != 3:
        raise ValueError(f"expected (N, 3) distances, got {d.shape}")
    valid = np.isfinite(d) & (d <= model.d_max_m)          # rules 1 + 2
    for i, s in enumerate(model.sensors):
        if s.enabled:                                      # rule 3 (R1-gated)
            with np.errstate(invalid="ignore"):
                valid[:, i] &= np.abs(d[:, i] - s.mu) > s.w
    return valid


def triplet_valid(d, model: BackgroundModel) -> np.ndarray:
    """(N,) triplet validity: all three readings valid (section 5.4)."""
    return reading_valid(d, model).all(axis=1)


def ceiling_ghost_apparent_range(config: dict, t_celsius: float):
    """(A2) Predicted wrap-around ghost apparent range per sensor [m], or None.

    A ping that travels to the ceiling and back takes longer than one slot;
    its echo is captured in the NEXT sensor's window and timestamped as
    apparent range = true slant - v*slot/2. Returns per-sensor values plus a
    flag for whether each lands inside the gateable window [0.5, d_max] —
    static, so the band rule subtracts it (the reason the schedule is rigid).

    A SINGLE value is returned (not one per sensor): under the surveyed
    equal-height (S_height_m) and common-tilt (tilt_deg) assumption every pod
    has the identical slant to the ceiling, so the predicted ghost range is the
    same for S1/S2/S3. If those pod assumptions are ever broken, this would need
    to become per-sensor.
    """
    ceiling = config["acquisition"].get("ceiling_height_m")
    if ceiling is None:
        return None
    h = config["array"]["S_height_m"]
    tilt = np.radians(config["array"]["tilt_deg"])
    v = speed_of_sound(t_celsius)
    slot_s = config["acquisition"]["slot_ms"] * 1e-3
    slant = (ceiling - h) / np.sin(tilt)
    apparent = slant - v * slot_s / 2.0
    d_max = config["gates"]["d_max_m"]
    return {
        "slant_m": float(slant),
        "apparent_m": float(apparent),
        "inside_gate_window": bool(0.5 <= apparent <= d_max),
    }
