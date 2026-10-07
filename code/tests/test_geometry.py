"""Tests for pipeline.geometry (CLAUDE.md section 8.1).

Covers: vertex construction from config, theta convention, polar round-trips,
the trilateration A/c construction, the two-circle ground-truth solver, and
tape-uncertainty propagation (R8).
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.geometry import (
    ArrayGeometry,
    cart_to_polar,
    ground_truth_landing,
    polar_to_cart,
    recommend_reference_sensors,
)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def geom(config):
    return ArrayGeometry.from_config(config)


# ---------------------------------------------------------------------------
# Frame / vertex construction
# ---------------------------------------------------------------------------

class TestArrayGeometry:
    def test_from_config_shapes(self, geom, config):
        assert geom.vertices_xz.shape == (3, 2)
        assert geom.s_height_m == config["array"]["S_height_m"]

    def test_vertices_3d_heights_equal(self, geom):
        v3d = geom.vertices_3d
        assert v3d.shape == (3, 3)
        assert np.allclose(v3d[:, 1], geom.s_height_m)
        assert np.allclose(v3d[:, [0, 2]], geom.vertices_xz)

    def test_ideal_config_side_length(self, geom):
        # The shipped defaults are the ideal equilateral triangle, side 1.0 m.
        v = geom.vertices_xz
        sides = [np.linalg.norm(v[i] - v[j]) for i, j in [(0, 1), (1, 2), (2, 0)]]
        assert np.allclose(sides, 1.0, atol=2e-4)

    def test_centroid_at_origin(self, geom):
        assert np.allclose(geom.vertices_xz.mean(axis=0), 0.0, atol=2e-4)

    def test_s1_on_positive_x(self, geom):
        # S1 defines the theta = 0 axis (section 0.1).
        s1 = geom.vertices_xz[0]
        assert s1[0] > 0
        assert abs(s1[1]) < 1e-12

    def test_collinear_vertices_raise(self):
        with pytest.raises(ValueError, match="collinear"):
            ArrayGeometry(
                vertices_xz=np.array([[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]),
                s_height_m=0.045,
            )

    def test_bad_shape_raises(self):
        with pytest.raises(ValueError, match="shape"):
            ArrayGeometry(vertices_xz=np.zeros((2, 2)), s_height_m=0.045)


# ---------------------------------------------------------------------------
# Theta convention (section 0.1)
# ---------------------------------------------------------------------------

class TestThetaConvention:
    def test_positive_x_is_zero(self):
        assert cart_to_polar(1.0, 0.0) == pytest.approx((1.0, 0.0))

    def test_positive_z_is_plus_90(self):
        r, theta = cart_to_polar(0.0, 1.0)
        assert theta == pytest.approx(90.0)

    def test_negative_z_is_minus_90(self):
        r, theta = cart_to_polar(0.0, -1.0)
        assert theta == pytest.approx(-90.0)

    def test_negative_x_is_plus_180_not_minus(self):
        # Range is (-180, 180]: the boundary maps to +180.
        r, theta = cart_to_polar(-1.0, 0.0)
        assert theta == pytest.approx(180.0)
        r, theta = cart_to_polar(-1.0, -1e-300)  # atan2 -> -180 exactly
        assert theta == pytest.approx(180.0)

    def test_range_bounds(self):
        rng = np.random.default_rng(0)
        for _ in range(500):
            x, z = rng.uniform(-5, 5, size=2)
            _, theta = cart_to_polar(x, z)
            assert -180.0 < theta <= 180.0


# ---------------------------------------------------------------------------
# Polar round-trips
# ---------------------------------------------------------------------------

class TestPolarRoundTrip:
    def test_polar_cart_polar(self):
        rng = np.random.default_rng(1)
        for _ in range(500):
            r = rng.uniform(0.01, 10.0)
            theta = rng.uniform(-179.999, 180.0)
            x, z = polar_to_cart(r, theta)
            r2, theta2 = cart_to_polar(x, z)
            assert r2 == pytest.approx(r, abs=1e-12)
            assert theta2 == pytest.approx(theta, abs=1e-9)

    def test_cart_polar_cart(self):
        rng = np.random.default_rng(2)
        for _ in range(500):
            x, z = rng.uniform(-5, 5, size=2)
            r, theta = cart_to_polar(x, z)
            x2, z2 = polar_to_cart(r, theta)
            assert x2 == pytest.approx(x, abs=1e-12)
            assert z2 == pytest.approx(z, abs=1e-12)

    def test_origin_no_nan(self):
        r, theta = cart_to_polar(0.0, 0.0)
        assert r == 0.0
        assert theta == 0.0


# ---------------------------------------------------------------------------
# Trilateration system (constant parts; full solve arrives with section 8.3)
# ---------------------------------------------------------------------------

class TestTrilaterationSystem:
    def test_recovers_known_points(self, geom):
        A, c = geom.trilateration_system()
        v3d = geom.vertices_3d
        rng = np.random.default_rng(3)
        for _ in range(50):
            # Ball points in the overlap region above the array.
            ball = np.array(
                [rng.uniform(-0.3, 0.3), rng.uniform(0.5, 1.5), rng.uniform(-0.3, 0.3)]
            )
            d = np.linalg.norm(v3d - ball, axis=1)
            b = c - (d[1:] ** 2 - d[0] ** 2)
            xz = np.linalg.solve(A, b)
            assert np.allclose(xz, ball[[0, 2]], atol=1e-9)

    def test_height_independence(self, geom):
        # Equal sensor heights cancel exactly: any ball height gives the same (x, z).
        A, c = geom.trilateration_system()
        v3d = geom.vertices_3d
        ball_xz = np.array([0.1, -0.15])
        for y in (0.3, 0.8, 1.6):
            ball = np.array([ball_xz[0], y, ball_xz[1]])
            d = np.linalg.norm(v3d - ball, axis=1)
            b = c - (d[1:] ** 2 - d[0] ** 2)
            assert np.allclose(np.linalg.solve(A, b), ball_xz, atol=1e-9)

    def test_matrix_well_conditioned(self, geom):
        A, _ = geom.trilateration_system()
        assert np.linalg.cond(A) < 10.0


# ---------------------------------------------------------------------------
# Multilateration ground-truth solver + sensor recommendation (v2.3 G1)
# (The old two-circle two-tape solver was retired with the G1 migration.)
# ---------------------------------------------------------------------------

def _refs_for(config, mark, names, sigma_tape=None):
    """Build the `refs` list (centroid + 2 sensors) and L_centroid from a true
    mark, with optional Gaussian tape noise applied to all three distances."""
    geom = ArrayGeometry.from_config(config)
    idx = {n: i for i, n in enumerate(("S1", "S2", "S3"))}
    mark = np.asarray(mark, dtype=float)
    noise = (lambda: 0.0) if sigma_tape is None else None
    L_c = float(np.linalg.norm(mark))
    refs = []
    for n in names:
        pos = geom.vertices_xz[idx[n]]
        refs.append({"name": n, "pos": pos, "L": float(np.linalg.norm(mark - pos))})
    return L_c, refs


class TestRecommendReferenceSensors:
    def test_picks_two_nearest(self, config):
        geom = ArrayGeometry.from_config(config)
        # A mark sitting on top of S2 -> S2 nearest; its neighbour is the 2nd.
        mark = geom.vertices_xz[1]
        a, b = recommend_reference_sensors(mark, config)
        assert a == "S2"
        assert b in ("S1", "S3")
        # nearest-first ordering: dist(a) <= dist(b)
        idx = {"S1": 0, "S2": 1, "S3": 2}
        da = np.linalg.norm(geom.vertices_xz[idx[a]] - mark)
        db = np.linalg.norm(geom.vertices_xz[idx[b]] - mark)
        assert da <= db

    def test_deterministic_tie_break(self, config):
        import copy
        # Controlled symmetric layout so the mark is EXACTLY equidistant from
        # S1 and S2 (and farther from S3): the tie must break by index -> S1, S2.
        cfg = copy.deepcopy(config)
        cfg["array"]["S1_xz"] = [1.0, 0.0]
        cfg["array"]["S2_xz"] = [0.0, 1.0]
        cfg["array"]["S3_xz"] = [-1.0, -1.0]
        a, b = recommend_reference_sensors([0.0, 0.0], cfg)
        assert (a, b) == ("S1", "S2")


class TestMultilaterationGroundTruth:
    def test_recovers_synthetic_mark(self, config):
        rng = np.random.default_rng(4)
        for _ in range(100):
            mark = rng.uniform(-1.8, 1.8, size=2)
            names = recommend_reference_sensors(mark, config)
            L_c, refs = _refs_for(config, mark, names)
            res = ground_truth_landing(L_c, refs, config)
            assert (res["x"], res["z"]) == pytest.approx(tuple(mark), abs=1e-7)
            assert res["ls_residual_m"] < 1e-7        # consistent tapes -> ~0

    def test_polar_output_matches_cartesian(self, config):
        mark = np.array([1.2, 0.5])
        L_c, refs = _refs_for(config, mark, recommend_reference_sensors(mark, config))
        res = ground_truth_landing(L_c, refs, config)
        r_exp, theta_exp = cart_to_polar(*mark)
        assert res["r"] == pytest.approx(r_exp)
        assert res["theta_deg"] == pytest.approx(theta_exp)

    def test_residual_grows_with_tape_error(self, config):
        mark = np.array([1.0, 0.8])
        L_c, refs = _refs_for(config, mark, recommend_reference_sensors(mark, config))
        clean = ground_truth_landing(L_c, refs, config)
        # Inject a 3 cm error on one sensor tape -> the 3-distance fit can no
        # longer be satisfied, so the residual rises well above the clean ~0.
        refs[0]["L"] += 0.03
        bad = ground_truth_landing(L_c, refs, config)
        assert clean["ls_residual_m"] < 1e-6
        assert bad["ls_residual_m"] > 0.005

    def test_uncertainty_matches_monte_carlo(self, config):
        mark = np.array([1.0, 0.8])
        names = recommend_reference_sensors(mark, config)
        L_c, refs = _refs_for(config, mark, names)
        sigma = config["ground_truth"]["sigma_tape_m"]
        res = ground_truth_landing(L_c, refs, config)

        rng = np.random.default_rng(5)
        n = 20000
        samples = np.empty((n, 2))
        base_L = [L_c] + [r["L"] for r in refs]
        for i in range(n):
            noisy = [v + rng.normal(0, sigma) for v in base_L]
            nrefs = [{"name": refs[k]["name"], "pos": refs[k]["pos"],
                      "L": noisy[k + 1]} for k in range(2)]
            s = ground_truth_landing(noisy[0], nrefs, config)
            samples[i] = (s["x"], s["z"])
        mc_sigma = samples.std(axis=0, ddof=1)
        assert res["sigma_x"] == pytest.approx(mc_sigma[0], rel=0.06)
        assert res["sigma_z"] == pytest.approx(mc_sigma[1], rel=0.06)

    def test_sigma_scales_linearly_with_tape_sigma(self, config):
        import copy
        mark = np.array([1.0, 0.8])
        L_c, refs = _refs_for(config, mark, recommend_reference_sensors(mark, config))
        c1 = copy.deepcopy(config); c1["ground_truth"]["sigma_tape_m"] = 0.005
        c2 = copy.deepcopy(config); c2["ground_truth"]["sigma_tape_m"] = 0.010
        res1 = ground_truth_landing(L_c, refs, c1)
        res2 = ground_truth_landing(L_c, refs, c2)
        assert res2["sigma_x"] == pytest.approx(2 * res1["sigma_x"])
        assert res2["sigma_z"] == pytest.approx(2 * res1["sigma_z"])

    def test_near_collinear_flags_not_raises(self, config):
        import copy
        # Contrived references whose two sensor positions are nearly collinear
        # with the centroid -> ill-conditioned. Must FLAG, not raise, no NaN.
        cfg = copy.deepcopy(config)
        cfg["array"]["S1_xz"] = [0.6, 0.0]
        cfg["array"]["S2_xz"] = [0.9, 1e-4]      # almost on the same ray as S1
        cfg["array"]["S3_xz"] = [-0.3, 0.5]
        mark = np.array([1.0, 0.2])
        refs = [{"name": "S1", "pos": np.array([0.6, 0.0]),
                 "L": float(np.linalg.norm(mark - np.array([0.6, 0.0])))},
                {"name": "S2", "pos": np.array([0.9, 1e-4]),
                 "L": float(np.linalg.norm(mark - np.array([0.9, 1e-4])))}]
        res = ground_truth_landing(float(np.linalg.norm(mark)), refs, cfg)
        assert res["cond_warn"] is True
        assert np.isfinite(res["x"]) and np.isfinite(res["z"])
        assert np.isfinite(res["sigma_x"]) and np.isfinite(res["sigma_z"])

    def test_well_conditioned_pair_no_flag(self, config):
        # cond_warn config key arrives in Stage 2; geometry falls back to the
        # spec default (1.0e4), so compare against that until then.
        mark = np.array([1.1, -0.4])
        L_c, refs = _refs_for(config, mark, recommend_reference_sensors(mark, config))
        res = ground_truth_landing(L_c, refs, config)
        assert res["cond_warn"] is False
        assert res["cond_number"] < 1.0e4
