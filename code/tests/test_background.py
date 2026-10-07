"""Tests for pipeline.background (CLAUDE.md sections 5.3-5.4; R1 edge cases, A2)."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.background import (
    BackgroundModel,
    calibrate_background,
    ceiling_ghost_apparent_range,
    disabled_background,
    reading_valid,
    sanity_warnings,
    triplet_valid,
)
from pipeline.corrections import speed_of_sound

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def gates(config):
    return config["gates"]


def block(n, values=(1.4, 1.5, 1.6), sigma=0.005, timeout_frac=(0, 0, 0), seed=0):
    """(n, 3) background block: Gaussian around per-sensor values, with the
    requested fraction of timeouts (NaN) per sensor."""
    rng = np.random.default_rng(seed)
    d = rng.normal(values, sigma, size=(n, 3))
    for i, frac in enumerate(timeout_frac):
        k = int(round(frac * n))
        if k:
            idx = rng.choice(n, size=k, replace=False)
            d[idx, i] = np.nan
    return d


# ---------------------------------------------------------------------------
# Calibration + R1 edge cases
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_normal_background_enabled_with_k_sigma_band(self, gates):
        # sigma = 10 mm so that k*sigma (~35 mm) clearly exceeds the 25 mm
        # floor and the k*sigma branch is the one under test.
        d = block(200, sigma=0.010)
        m = calibrate_background(d, gates)
        for i, s in enumerate(m.sensors):
            assert s.enabled
            assert s.n_valid == 200
            assert s.f0 == 0.0
            assert s.mu == pytest.approx([1.4, 1.5, 1.6][i], abs=0.003)
            assert s.w == pytest.approx(gates["bg_k_sigma"] * s.sigma)
            assert s.w > gates["d_min_band_m"]

    def test_timeout_dominated_disables_band_no_nan_leakage(self, gates):
        """R1: open-air background (f0 > 0.9) -> band rule OFF; ball echoes
        within d_max must be accepted; no NaN propagates into the gate."""
        d = block(200, timeout_frac=(1.0, 1.0, 1.0))
        m = calibrate_background(d, gates)
        for s in m.sensors:
            assert not s.enabled
            assert s.f0 == 1.0
            assert np.isnan(s.mu)                  # uncharacterizable, flagged
        ball = np.array([[0.9, 1.1, 1.3], [1.0, 1.2, 1.4]])
        v = reading_valid(ball, m)
        assert v.all()                             # accepted as signal
        assert v.dtype == bool                     # no NaN leaked into flags

    def test_sigma_near_zero_floors_band_width(self, gates):
        """R1: quantization-level sigma must not create a uselessly thin band."""
        d = np.tile([1.4, 1.5, 1.6], (200, 1))     # sigma exactly 0
        m = calibrate_background(d, gates)
        for s in m.sensors:
            assert s.enabled
            assert s.sigma == 0.0
            assert s.w == gates["d_min_band_m"]

    def test_sparse_background_disables_cleanly(self, gates):
        """R1: n_valid < bg_min_samples -> band rule OFF even if f0 is low."""
        n = 32                                      # 0.85 timeout -> ~5 valid
        d = block(n, timeout_frac=(0.85, 0.85, 0.85))
        m = calibrate_background(d, gates)
        for s in m.sensors:
            assert s.f0 <= gates["bg_timeout_skip"]
            assert s.n_valid < gates["bg_min_samples"]
            assert not s.enabled
        assert triplet_valid(np.array([[1.0, 1.0, 1.0]]), m).all()

    def test_mixed_per_sensor_enable(self, gates):
        d = block(200, timeout_frac=(0.0, 1.0, 0.95))
        m = calibrate_background(d, gates)
        assert m.sensors[0].enabled
        assert not m.sensors[1].enabled
        assert not m.sensors[2].enabled

    def test_bad_shape_raises(self, gates):
        with pytest.raises(ValueError, match="N, 3"):
            calibrate_background(np.zeros((5, 2)), gates)

    def test_disabled_background_gates_on_dmax_only(self, gates):
        """--no-background: all bands off, so a reading is valid iff it is a
        non-timeout within d_max (rules 1+2 only, rule 3 never applies)."""
        m = disabled_background(gates)
        assert all(not s.enabled for s in m.sensors)
        assert m.d_max_m == gates["d_max_m"]
        # a mid-range echo passes (would be gated by a real band at that range),
        # a NaN timeout and an over-range echo are rejected.
        d = np.array([[1.5, 1.5, 1.5],
                      [np.nan, gates["d_max_m"] + 0.5, 1.0]])
        v = reading_valid(d, m)
        assert v[0].all()
        assert not v[1, 0] and not v[1, 1] and v[1, 2]


# ---------------------------------------------------------------------------
# Validity gate (section 5.4)
# ---------------------------------------------------------------------------

class TestGate:
    def test_three_rules(self, gates):
        m = calibrate_background(block(200), gates)   # bands at 1.4/1.5/1.6
        d = np.array([
            [np.nan, 1.0, 1.0],     # rule 1: timeout
            [2.5, 1.0, 1.0],        # rule 2: beyond d_max = 2.0
            [1.41, 1.0, 1.0],       # rule 3: inside S1's background band
            [0.9, 1.0, 1.2],        # all valid (far from bands)
        ])
        v = reading_valid(d, m)
        assert not v[0, 0] and not v[1, 0] and not v[2, 0]
        assert v[3].all()
        assert triplet_valid(d, m).tolist() == [False, False, False, True]

    def test_band_rejects_background_passes_ball(self, gates):
        m = calibrate_background(block(300, seed=1), gates)
        rng = np.random.default_rng(2)
        bg_echo = rng.normal([1.4, 1.5, 1.6], 0.005, size=(100, 3))
        assert not reading_valid(bg_echo, m).any(axis=1).any()  # all rejected
        ball = rng.normal([0.8, 0.9, 1.0], 0.005, size=(100, 3))
        assert reading_valid(ball, m).all()

    def test_flags_not_deletions(self, gates):
        m = calibrate_background(block(200), gates)
        d = block(50, values=(0.9, 1.0, 1.1), seed=3)
        v = reading_valid(d, m)
        assert v.shape == d.shape                    # one flag per reading


# ---------------------------------------------------------------------------
# Sanity warning (section 5.3) and persistence
# ---------------------------------------------------------------------------

class TestSanityAndPersistence:
    def test_overlap_warning_fires(self, gates):
        m = calibrate_background(block(200), gates)   # bands inside [0.5, 2.0]
        warnings = sanity_warnings(m)
        assert len(warnings) == 3
        assert all("eat real ball readings" in w for w in warnings)

    def test_no_warning_when_bands_outside(self, gates):
        d = block(200, values=(2.4, 2.5, 2.6))        # beyond d_max
        warnings = sanity_warnings(calibrate_background(d, gates))
        assert warnings == []

    def test_dict_roundtrip(self, gates):
        m = calibrate_background(block(200, timeout_frac=(0, 1.0, 0)), gates)
        m2 = BackgroundModel.from_dict(m.to_dict())
        for a, b in zip(m.sensors, m2.sensors):
            for f in ("f0", "n_valid", "w", "enabled"):
                x, y = getattr(a, f), getattr(b, f)
                assert (x == y) or (np.isnan(x) and np.isnan(y))


# ---------------------------------------------------------------------------
# A2 ceiling wrap-around ghost prediction
# ---------------------------------------------------------------------------

class TestCeilingGhost:
    def test_null_config_skips(self, config):
        assert ceiling_ghost_apparent_range(config, 20.0) is None

    def test_arithmetic(self, config):
        import copy
        cfg = copy.deepcopy(config)
        cfg["acquisition"]["ceiling_height_m"] = 3.0
        out = ceiling_ghost_apparent_range(cfg, 20.0)
        h = cfg["array"]["S_height_m"]
        slant = (3.0 - h) / np.sin(np.radians(cfg["array"]["tilt_deg"]))
        v = speed_of_sound(20.0)
        assert out["slant_m"] == pytest.approx(slant)
        assert out["apparent_m"] == pytest.approx(slant - v * 0.018 / 2)
        # 3 m ceiling: slant ~3.6 m, apparent ~0.52 m -> inside the gate
        # window, exactly the dangerous case A2 describes.
        assert out["inside_gate_window"]
