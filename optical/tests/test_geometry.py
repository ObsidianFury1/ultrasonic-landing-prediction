"""Unit tests for optical.geometry — polar convention and round-trip accuracy (§2).

Tolerance rationale: all conversions are elementary float trig with no accumulation,
so results are good to machine precision. We assert 1e-12 m / 1e-12 deg, which is
~4 orders of magnitude tighter than any physical quantity in this project (mm-level)
and still comfortably above float64 round-off for the magnitudes involved (~1 m, ~180 deg).
"""

import numpy as np
import pytest

from optical import geometry

TOL = 1e-12


# --------------------------------------------------------------------------- #
# Convention anchors (§2: +x -> 0 deg, +z -> +90 deg, -x -> +180 deg not -180). #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "x, z, r_exp, theta_exp",
    [
        (1.0, 0.0, 1.0, 0.0),      # on +x
        (0.0, 1.0, 1.0, 90.0),     # on +z
        (-1.0, 0.0, 1.0, 180.0),   # on -x  -> +180, NOT -180
        (0.0, -1.0, 1.0, -90.0),   # on -z
        (1.0, 1.0, np.sqrt(2), 45.0),
        (-1.0, -1.0, np.sqrt(2), -135.0),
    ],
)
def test_cart_to_polar_convention(x, z, r_exp, theta_exp):
    r, theta = geometry.cart_to_polar(x, z)
    assert abs(r - r_exp) < TOL
    assert abs(theta - theta_exp) < TOL


def test_minus_x_axis_maps_to_plus_180_from_both_sides():
    # Approaching the -x axis from -z (negative zero) must still give +180, not -180.
    _, theta_pos = geometry.cart_to_polar(-1.0, 0.0)
    _, theta_neg = geometry.cart_to_polar(-1.0, -0.0)
    assert theta_pos == 180.0
    assert theta_neg == 180.0


def test_theta_in_half_open_range():
    thetas = np.linspace(-179.0, 180.0, 360)
    x, z = geometry.polar_to_cart(np.ones_like(thetas), thetas)
    _, theta_back = geometry.cart_to_polar(x, z)
    assert np.all(theta_back > -180.0)
    assert np.all(theta_back <= 180.0)


# --------------------------------------------------------------------------- #
# Round-trip accuracy — the Phase-0 gate.                                       #
# --------------------------------------------------------------------------- #

def test_roundtrip_cart_polar_cart_scalar():
    rng = np.random.default_rng(0)
    for _ in range(1000):
        x = rng.uniform(-3.0, 3.0)
        z = rng.uniform(-3.0, 3.0)
        r, theta = geometry.cart_to_polar(x, z)
        x2, z2 = geometry.polar_to_cart(r, theta)
        assert abs(x2 - x) < TOL
        assert abs(z2 - z) < TOL


def test_roundtrip_polar_cart_polar_scalar():
    rng = np.random.default_rng(1)
    for _ in range(1000):
        r = rng.uniform(0.01, 3.0)          # avoid r=0 where theta is undefined
        theta = rng.uniform(-179.999, 180.0)
        x, z = geometry.polar_to_cart(r, theta)
        r2, theta2 = geometry.cart_to_polar(x, z)
        assert abs(r2 - r) < TOL
        assert abs(theta2 - theta) < TOL


def test_roundtrip_vectorised():
    rng = np.random.default_rng(2)
    x = rng.uniform(-3.0, 3.0, size=5000)
    z = rng.uniform(-3.0, 3.0, size=5000)
    r, theta = geometry.cart_to_polar(x, z)
    x2, z2 = geometry.polar_to_cart(r, theta)
    assert np.max(np.abs(x2 - x)) < TOL
    assert np.max(np.abs(z2 - z)) < TOL


def test_scalar_returns_float_array_returns_ndarray():
    r, theta = geometry.cart_to_polar(1.0, 2.0)
    assert isinstance(r, float) and isinstance(theta, float)
    r_arr, theta_arr = geometry.cart_to_polar(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
    assert isinstance(r_arr, np.ndarray) and isinstance(theta_arr, np.ndarray)


def test_origin_has_zero_radius():
    r, _ = geometry.cart_to_polar(0.0, 0.0)
    assert r == 0.0


# --------------------------------------------------------------------------- #
# Config loading + array-frame accessors.                                      #
# --------------------------------------------------------------------------- #

def test_config_loads_and_array_accessors():
    from pathlib import Path

    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    cfg = geometry.load_config(cfg_path)

    sensors = geometry.sensor_positions(cfg)
    assert set(sensors) == {"S1", "S2", "S3"}
    # S1 lies on +x by construction -> its z is ~0 and it maps to theta ~ 0.
    r1, theta1 = geometry.cart_to_polar(*sensors["S1"])
    assert abs(theta1) < 1e-9
    assert r1 > 0.0

    centroid = geometry.centroid_position(cfg)
    assert np.allclose(centroid, [0.0, 0.0])
