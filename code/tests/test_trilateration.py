"""Tests for pipeline.trilateration (CLAUDE.md section 8.3; R4, R6, R10a).

Exactness tests feed exact SIMULTANEOUS ranges (one shared instant per
triplet, computed from the simulator's true trajectory) — time alignment is
corrections.py's job (Step 3), so trilateration is tested in isolation per
the layer discipline of section 0.5.
"""

import copy
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.geometry import ArrayGeometry
from pipeline.simulator import ThrowParams, simulate_trajectory
from pipeline.trilateration import trilaterate

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def geom(config):
    return ArrayGeometry.from_config(config)


@pytest.fixture(scope="module")
def arc_points(config):
    """~40 true ball-centre positions along a noise-free simulated arc,
    restricted to the region above the array where y_plane is healthy."""
    traj = simulate_trajectory(THROW, config["ball"]["radius_m"])
    t = np.linspace(0.05, traj.t_land - 0.05, 40)
    pts = traj.position(t)
    return pts[pts[:, 1] > 0.5]


def exact_ranges(points: np.ndarray, geom: ArrayGeometry) -> np.ndarray:
    """(N, 3) exact simultaneous ranges sensor acoustic centre -> ball centre."""
    return np.linalg.norm(points[:, None, :] - geom.vertices_3d[None, :, :], axis=2)


# ---------------------------------------------------------------------------
# Exact recovery and the R4 height convention
# ---------------------------------------------------------------------------

class TestExactRecovery:
    def test_noise_free_recovery_below_1e9(self, config, geom, arc_points):
        d = exact_ranges(arc_points, geom)
        res = trilaterate(d, geom, config["kalman"]["sigma_pos_m"])
        assert res.valid.all()
        assert np.abs(res.x - arc_points[:, 0]).max() < 1e-9
        assert np.abs(res.z - arc_points[:, 2]).max() < 1e-9
        assert np.abs(res.y_floor - arc_points[:, 1]).max() < 1e-9
        # Sensor-plane height relates to floor height exactly by S_height_m (R4).
        assert np.allclose(res.y_floor - res.y_plane, geom.s_height_m)

    def test_negative_control_R4_height_offset_bites(self, config, geom, arc_points):
        """Ranges from sensors at h = 0.045 m, pipeline told h = 0: the
        recovered floor-frame height must be wrong by exactly h."""
        h = geom.s_height_m
        assert h == pytest.approx(0.045)
        d = exact_ranges(arc_points, geom)        # truth: sensors at h

        cfg_h0 = copy.deepcopy(config)
        cfg_h0["array"]["S_height_m"] = 0.0
        geom_h0 = ArrayGeometry.from_config(cfg_h0)
        res = trilaterate(d, geom_h0, config["kalman"]["sigma_pos_m"])

        assert res.valid.all()
        y_err = arc_points[:, 1] - res.y_floor
        # Fails the exactness criterion, and by the expected ~h amount.
        assert y_err.min() > 1e-9
        assert np.allclose(y_err, h, atol=1e-9)
        # (x, z) are untouched: equal heights cancel in the 2x2 reduction.
        assert np.abs(res.x - arc_points[:, 0]).max() < 1e-9
        assert np.abs(res.z - arc_points[:, 2]).max() < 1e-9


# ---------------------------------------------------------------------------
# Consistency residual q (R10a) and noise behaviour
# ---------------------------------------------------------------------------

class TestConsistencyResidual:
    def test_q_zero_noise_free(self, config, geom, arc_points):
        res = trilaterate(exact_ranges(arc_points, geom), geom,
                          config["kalman"]["sigma_pos_m"])
        assert np.nanmax(res.q) < 1e-9

    def test_q_identically_zero_even_with_noise(self, config, geom, arc_points):
        """R10a finding (documented in trilateration.py): the 2x2 solve IS the
        equality of the three radicands, so q == 0 by construction for ANY
        ranges — the spec's expectation that q grows with noise is
        mathematically impossible (3 ranges, 3 unknowns, no redundancy).
        This test pins down that algebraic fact."""
        d = exact_ranges(arc_points, geom)
        rng = np.random.default_rng(1)
        for sigma in (0.002, 0.008):
            for _ in range(20):
                res = trilaterate(d + rng.normal(0, sigma, d.shape), geom,
                                  config["kalman"]["sigma_pos_m"])
                if res.valid.any():
                    assert np.nanmax(res.q[res.valid]) < 1e-9
        # Even for arbitrary (non-physical) range triples.
        res = trilaterate(rng.uniform(0.5, 2.0, (500, 3)), geom,
                          config["kalman"]["sigma_pos_m"])
        assert np.nanmax(res.q[res.valid]) < 1e-9

    def test_gdop_sanity(self, config, geom, arc_points):
        """sigma = 5 mm range noise -> horizontal RMS error consistent with
        GDOP ~ 2.3 (loose band; spec section 8.3)."""
        d = exact_ranges(arc_points, geom)
        sigma = 0.005
        rng = np.random.default_rng(2)
        errs = []
        for _ in range(200):
            res = trilaterate(d + rng.normal(0, sigma, d.shape), geom, sigma)
            ok = res.valid
            errs.append(np.hypot(res.x[ok] - arc_points[ok, 0],
                                 res.z[ok] - arc_points[ok, 2]))
        rms = np.sqrt(np.mean(np.concatenate(errs) ** 2))
        assert 1.5 * sigma < rms < 3.5 * sigma


# ---------------------------------------------------------------------------
# NaN guard and invalid inputs
# ---------------------------------------------------------------------------

class TestNaNGuard:
    def test_impossible_geometry_flagged_not_clamped(self, config, geom, arc_points):
        d = exact_ranges(arc_points[:4], geom)
        d[2] = 0.3                                  # < circumradius: impossible
        res = trilaterate(d, geom, config["kalman"]["sigma_pos_m"])
        assert not res.valid[2]
        # Discarded means NaN — not clamped to 0, not abs()'d into a number.
        assert np.isnan(res.y_plane[2]) and np.isnan(res.y_floor[2])
        assert np.isnan(res.x[2]) and np.isnan(res.q[2]) and np.isnan(res.sigma_y[2])
        # Neighbours in the same batch are untouched.
        assert res.valid[[0, 1, 3]].all()
        assert np.abs(res.y_floor[[0, 1, 3]] - arc_points[[0, 1, 3], 1]).max() < 1e-9

    def test_guard_invariants_on_random_triples(self, config, geom):
        """Arbitrary range triples: the guard must split them cleanly — every
        valid row reconstructs its input ranges exactly (the system is
        exactly determined), every invalid row is all-NaN."""
        rng = np.random.default_rng(3)
        d = rng.uniform(0.5, 2.0, (500, 3))
        res = trilaterate(d, geom, config["kalman"]["sigma_pos_m"])
        assert 0.0 < res.valid.mean() < 1.0        # guard genuinely active
        ok = res.valid
        points = np.column_stack([res.x[ok], res.y_plane[ok] + geom.s_height_m,
                                  res.z[ok]])
        d_back = np.linalg.norm(points[:, None, :] - geom.vertices_3d[None, :, :],
                                axis=2)
        assert np.allclose(d_back, d[ok], atol=1e-9)
        assert np.isnan(res.y_floor[~ok]).all()
        assert np.isnan(res.x[~ok]).all()

    def test_nan_input_row_flagged_without_exception(self, config, geom, arc_points):
        d = exact_ranges(arc_points[:3], geom)
        d[1, 2] = np.nan                            # timeout from corrections
        res = trilaterate(d, geom, config["kalman"]["sigma_pos_m"])
        assert res.valid.tolist() == [True, False, True]
        assert np.isnan(res.x[1])
        assert np.isfinite(res.y_floor[[0, 2]]).all()

    def test_bad_shape_raises(self, config, geom):
        with pytest.raises(ValueError, match="N, 3"):
            trilaterate(np.zeros((3, 4)), geom, config["kalman"]["sigma_pos_m"])


# ---------------------------------------------------------------------------
# Per-triplet vertical noise (R6)
# ---------------------------------------------------------------------------

class TestSigmaY:
    def test_matches_analytic_formula(self, config, geom):
        sigma_pos = config["kalman"]["sigma_pos_m"]
        point = np.array([[0.1, 1.2, -0.05]])
        d = exact_ranges(point, geom)
        res = trilaterate(d, geom, sigma_pos)
        expected = d.mean() / (point[0, 1] - geom.s_height_m) * sigma_pos
        assert res.sigma_y[0] == pytest.approx(expected, rel=1e-9)

    def test_grows_as_ball_nears_floor(self, config, geom):
        sigma_pos = config["kalman"]["sigma_pos_m"]
        high = np.array([[0.0, 1.5, 0.0]])
        low = np.array([[0.0, 0.55, 0.0]])
        res_high = trilaterate(exact_ranges(high, geom), geom, sigma_pos)
        res_low = trilaterate(exact_ranges(low, geom), geom, sigma_pos)
        # d grows with y too (d ~ sqrt(R_c^2 + y^2)), so d/y grows slower than
        # 1/y: the measured ratio here is ~1.41, not 1.5/0.55.
        assert res_low.sigma_y[0] > 1.3 * res_high.sigma_y[0]
        # Both bounded: d/y <~ 3.5 in the visited regime (report sentence).
        assert res_low.sigma_y[0] < 4.0 * sigma_pos

    def test_zero_radicand_row_flagged_not_infinite(self):
        """(Minor-12) A ball exactly on the sensor plane at the array circumcenter
        gives radicand == 0 -> y_plane == 0 -> sigma_y == inf. That row must be
        flagged INVALID (all-NaN), never returned as valid with a non-finite sigma.

        Uses an integer geometry whose circumcenter is exactly the origin with
        R = 5 -- (5,0),(3,4),(3,-4) are all distance 5 from (0,0) -- so d=[5,5,5]
        makes all three radicands exactly 0 in integer arithmetic (no float slop)."""
        geom = ArrayGeometry(
            vertices_xz=np.array([[5.0, 0.0], [3.0, 4.0], [3.0, -4.0]]),
            s_height_m=0.045)
        d = np.array([[5.0, 5.0, 5.0]])
        res = trilaterate(d, geom, sigma_pos_m=0.01)
        assert not res.valid[0]                     # flagged, not silently valid
        assert np.isnan(res.sigma_y[0])             # NaN-filled, never inf
        assert np.isnan(res.x[0]) and np.isnan(res.z[0])
