"""Tests for pipeline.landing (CLAUDE.md section 8.5, R7).

Time-parameterized fit variant (spec-sanctioned; see landing.py docstring).
Data flows through the full chain (simulator -> corrections -> trilateration
-> kalman), drag-free: the drag bias is bias.py's job (Step 7). Thresholds
from measured probe values: landing error mean ~22 mm / max ~37 mm over
seeds, y=r vs y=0 shift within 2% of theory, ellipse coverage 0.93.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy import stats

from pipeline.corrections import correct_triplets
from pipeline.geometry import ArrayGeometry, cart_to_polar
from pipeline.kalman import FilterResult, filter_trajectory
from pipeline.landing import predict_landing
from pipeline.simulator import ThrowParams, generate_session, random_throw
from pipeline.trilateration import trilaterate

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def chain(config, throw, seed, noise_mm=8.0):
    """Full pipeline up to the Kalman filter; returns (session, FilterResult)."""
    geom = ArrayGeometry.from_config(config)
    session = generate_session(config, throw, temperature_c=20.0,
                               noise_mm=noise_mm, rng=np.random.default_rng(seed),
                               n_bg_pre=2, n_bg_post=2)
    echo, t_trig, target = session.triplet_arrays()
    cor = correct_triplets(echo, t_trig, 20.0, config["ball"]["radius_m"])
    tri = trilaterate(cor.d_aligned, geom, config["kalman"]["sigma_pos_m"])
    idx = np.flatnonzero(cor.usable & target & tri.valid)
    t_s = cor.t_sample_us[idx, 0] * 1e-6
    xyz = np.column_stack([tri.x[idx], tri.y_floor[idx], tri.z[idx]])
    filt = filter_trajectory(t_s, xyz, tri.sigma_y[idx],
                             sigma_pos_m=config["kalman"]["sigma_pos_m"],
                             q_scale=config["kalman"]["q_scale"], hetero_R=True)
    return session, filt


def predict(config, filt, **kwargs):
    return predict_landing(filt, ball_radius_m=config["ball"]["radius_m"],
                           min_fit_points=config["landing"]["min_fit_points"],
                           **kwargs)


# ---------------------------------------------------------------------------
# Landing accuracy and output conventions
# ---------------------------------------------------------------------------

class TestLandingAccuracy:
    def test_recovered_within_noise_tolerance(self, config):
        """Probe: mean ~22 mm, max ~37 mm over 10 seeds at sigma = 8 mm."""
        errs = []
        for seed in range(6):
            session, filt = chain(config, THROW, seed)
            pred = predict(config, filt)
            truth = session.truth["landing"]
            errs.append(np.hypot(pred.x - truth["x_m"], pred.z - truth["z_m"]))
            assert abs(pred.r - truth["r_m"]) < 0.06
            assert abs(pred.theta_deg - truth["theta_deg"]) < 2.5
        assert max(errs) < 0.06
        assert np.mean(errs) < 0.04

    def test_polar_output_consistent_with_cartesian(self, config):
        _, filt = chain(config, THROW, 0)
        pred = predict(config, filt)
        r, theta = cart_to_polar(pred.x, pred.z)
        assert pred.r == pytest.approx(r)
        assert pred.theta_deg == pytest.approx(theta)

    def test_heading_and_speed_export_for_bias(self, config):
        _, filt = chain(config, THROW, 0)
        pred = predict(config, filt)
        true_heading = np.degrees(np.arctan2(THROW.vz, THROW.vx))
        true_vh = np.hypot(THROW.vx, THROW.vz)
        assert abs(pred.heading_deg - true_heading) < 5.0
        assert abs(pred.v_h_m_s - true_vh) < 0.15


# ---------------------------------------------------------------------------
# y = r_ball vs y = 0 (the ball-centre contact convention bites)
# ---------------------------------------------------------------------------

class TestContactHeight:
    def test_solve_target_shift_matches_kinematics(self, config):
        """Shift ~ v_h * r_ball / |v_y,impact| (probe: 19.1 vs 19.5 mm)."""
        radius = config["ball"]["radius_m"]
        _, filt = chain(config, THROW, 0)
        pred_r = predict(config, filt)                     # y = radius
        pred_0 = predict(config, filt, target_y_m=0.0)     # y = 0 (wrong)
        shift = np.hypot(pred_0.x - pred_r.x, pred_0.z - pred_r.z)
        vy_impact = np.sqrt(THROW.vy**2 + 2 * 9.81 * (THROW.y0 - radius))
        expected = np.hypot(THROW.vx, THROW.vz) * radius / vy_impact
        assert shift == pytest.approx(expected, rel=0.25)
        # And the y=0 solve lands strictly further downrange.
        assert pred_0.t_land_s > pred_r.t_land_s


# ---------------------------------------------------------------------------
# R7 uncertainty: coverage and small-sample behaviour
# ---------------------------------------------------------------------------

class TestUncertainty:
    def test_ellipse_coverage_over_many_throws(self, config):
        """Probe: 50/54 = 0.93 vs nominal 0.95. Loose band per the R7 caveat."""
        chi95 = stats.chi2.ppf(0.95, 2)
        rng_throws = np.random.default_rng(99)
        covered = total = 0
        for seed in range(60):
            throw = random_throw(rng_throws, heading_range_deg=60.0)
            try:
                session, filt = chain(config, throw, seed)
                pred = predict(config, filt)
            except ValueError:
                continue                       # short/degenerate throws skipped
            truth = session.truth["landing"]
            dv = np.array([pred.x - truth["x_m"], pred.z - truth["z_m"]])
            m2 = dv @ np.linalg.inv(pred.cov_xz) @ dv
            covered += m2 <= chi95
            total += 1
        assert total >= 40                     # enough throws survived
        assert 0.80 <= covered / total <= 1.0

    def test_sigmas_positive_and_caveat_present(self, config):
        _, filt = chain(config, THROW, 0)
        pred = predict(config, filt)
        assert pred.sigma_r > 0 and pred.sigma_theta_deg > 0
        assert "degree(s) of freedom" in pred.caveat
        assert str(pred.dof) in pred.caveat
        assert pred.dof == pred.n_points - 3

    def test_minimum_points_dof1_still_predicts(self, config):
        """M = 4 (dof = 1) is legal and must produce a finite prediction —
        the case numpy.polyfit(cov=True) would refuse."""
        _, filt = chain(config, THROW, 0)
        sl = slice(0, 4)
        small = FilterResult(t_s=filt.t_s[sl], pos=filt.pos[sl],
                             vel=filt.vel[sl], bias=filt.bias[sl])
        pred = predict(config, small)
        assert pred.dof == 1
        assert np.isfinite([pred.r, pred.theta_deg, pred.sigma_r,
                            pred.sigma_theta_deg]).all()


# ---------------------------------------------------------------------------
# Degenerate input rejection
# ---------------------------------------------------------------------------

class TestDegenerateInput:
    def test_too_few_points_rejected_with_actionable_message(self, config):
        _, filt = chain(config, THROW, 0)
        sl = slice(0, 3)                       # below min_fit_points = 4
        short = FilterResult(t_s=filt.t_s[sl], pos=filt.pos[sl],
                             vel=filt.vel[sl], bias=filt.bias[sl])
        with pytest.raises(ValueError, match="slower/loftier"):
            predict(config, short)

    def test_never_descending_fit_rejected(self, config):
        # A rising-only segment: parabola fitted to it never comes down
        # within a sane root, or has no descending root at all.
        t = np.array([0.0, 0.054, 0.108, 0.162])
        pos = np.column_stack([t * 3.0, 0.5 + t * 1.0, t * 0.0])  # linear rise
        vel = np.tile([3.0, 1.0, 0.0], (4, 1))
        filt = FilterResult(t_s=t, pos=pos, vel=vel, bias=np.ones(4))
        with pytest.raises(ValueError):
            predict(config, filt)
