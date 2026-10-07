"""Tests for pipeline.kalman (CLAUDE.md section 8.4; R3, R6).

Data comes through the real chain: simulator -> corrections -> trilateration,
with truth from the simulator's trajectory. Thresholds are set from measured
behaviour (probe runs), not guessed.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.corrections import correct_triplets
from pipeline.geometry import ArrayGeometry
from pipeline.kalman import G, FilterResult, build_F, filter_trajectory
from pipeline.simulator import ThrowParams, generate_session
from pipeline.trilateration import trilaterate

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def rms(err) -> float:
    return float(np.sqrt(np.mean(np.asarray(err) ** 2)))


def chain(config, seed, noise_mm=8.0, n_dropouts=0):
    """simulator -> corrections -> trilateration -> used triplets + truth."""
    geom = ArrayGeometry.from_config(config)
    session = generate_session(
        config, THROW, temperature_c=20.0, noise_mm=noise_mm,
        rng=np.random.default_rng(seed), n_bg_pre=2, n_bg_post=2,
        n_dropouts=n_dropouts)
    echo, t_trig, target = session.triplet_arrays()
    cor = correct_triplets(echo, t_trig, 20.0, config["ball"]["radius_m"])
    tri = trilaterate(cor.d_aligned, geom, config["kalman"]["sigma_pos_m"])
    idx = np.flatnonzero(cor.usable & target & tri.valid)
    t_s = cor.t_sample_us[idx, 0] * 1e-6
    xyz = np.column_stack([tri.x[idx], tri.y_floor[idx], tri.z[idx]])
    sigma_y = tri.sigma_y[idx]
    t_rel = t_s - session.truth["t_launch_s"]
    truth_pos = session.trajectory.position(t_rel)
    traj = session.trajectory
    truth_vel = np.stack(
        [np.interp(t_rel, traj.t, traj.vel[:, k]) for k in range(3)], axis=-1)
    return t_s, xyz, sigma_y, truth_pos, truth_vel


def run(config, t_s, xyz, sigma_y, hetero=True) -> FilterResult:
    kal = config["kalman"]
    return filter_trajectory(t_s, xyz, sigma_y,
                             sigma_pos_m=kal["sigma_pos_m"],
                             q_scale=kal["q_scale"], hetero_R=hetero)


# ---------------------------------------------------------------------------
# F matrix structure: gravity only, via the bias state
# ---------------------------------------------------------------------------

class TestBuildF:
    @pytest.mark.parametrize("dt", [0.054, 0.108, 0.1612])
    def test_matches_spec_matrix(self, dt):
        expected = np.array([
            [1, 0, 0, dt, 0, 0, 0],
            [0, 1, 0, 0, dt, 0, -0.5 * G * dt**2],
            [0, 0, 1, 0, 0, dt, 0],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, -G * dt],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
        ])
        assert np.array_equal(build_F(dt), expected)

    def test_propagates_ballistic_state_exactly(self):
        dt = 0.054
        state = np.array([0.1, 1.2, -0.3, 3.0, 2.0, -0.5, 1.0])
        nxt = build_F(dt) @ state
        assert nxt[1] == pytest.approx(1.2 + 2.0 * dt - 0.5 * G * dt**2)
        assert nxt[4] == pytest.approx(2.0 - G * dt)
        assert nxt[6] == 1.0


# ---------------------------------------------------------------------------
# Accuracy on noisy simulator data
# ---------------------------------------------------------------------------

class TestAccuracy:
    def test_filtered_rms_below_raw_rms(self, config):
        """Measured (probe): raw ~20-27 mm, filtered ~16-21 mm per seed."""
        for seed in (0, 1, 2):
            t_s, xyz, sigma_y, truth_pos, _ = chain(config, seed)
            f = run(config, t_s, xyz, sigma_y)
            assert rms(f.pos - truth_pos) < 0.95 * rms(xyz - truth_pos)

    def test_velocities_within_tolerance(self, config):
        """Post-convergence (2nd half) velocity RMS measured at 0.03-0.08 m/s."""
        for seed in (0, 1, 2):
            t_s, xyz, sigma_y, _, truth_vel = chain(config, seed)
            f = run(config, t_s, xyz, sigma_y)
            half = len(t_s) // 2
            assert rms(f.vel[half:] - truth_vel[half:]) < 0.15

    def test_hetero_R_on_off_both_run_and_comparable(self, config):
        t_s, xyz, sigma_y, truth_pos, _ = chain(config, 0)
        f_on = run(config, t_s, xyz, sigma_y, hetero=True)
        f_off = run(config, t_s, xyz, None, hetero=False)
        r_on, r_off = rms(f_on.pos - truth_pos), rms(f_off.pos - truth_pos)
        # hetero_R must not degrade accuracy (spec); measured: slightly better.
        assert r_on <= 1.05 * r_off
        assert 0.5 < r_on / r_off < 1.5

    def test_bias_state_never_modified(self, config):
        t_s, xyz, sigma_y, _, _ = chain(config, 0)
        f = run(config, t_s, xyz, sigma_y)
        assert np.abs(f.bias - 1.0).max() < 1e-6


# ---------------------------------------------------------------------------
# Variable dt: rejected-triplet gaps (the point of rebuilding F)
# ---------------------------------------------------------------------------

class TestVariableDt:
    def gap_data(self, config):
        """Gate-style rejection of one mid-flight used triplet -> 108 ms gap."""
        t_s, xyz, sigma_y, truth_pos, _ = chain(config, 0)
        keep = np.ones(len(t_s), bool)
        keep[8] = False
        return (t_s[keep], xyz[keep], sigma_y[keep], truth_pos[keep])

    def test_108ms_gap_processed_correctly(self, config):
        t_s, xyz, sigma_y, truth_pos = self.gap_data(config)
        gaps = np.diff(t_s)
        assert 0.100 < gaps.max() < 0.115          # the 108 ms gap is there
        f = run(config, t_s, xyz, sigma_y)
        # Accuracy preserved across the gap (probe: 16 mm vs 22 mm raw).
        assert rms(f.pos - truth_pos) < 0.95 * rms(xyz - truth_pos)
        assert rms(f.pos - truth_pos) < 0.025

    def test_negative_control_fixed_dt_fails_across_gap(self, config):
        """Falsified uniform 54 ms timestamps on the same data: the gravity
        propagation across the real 108 ms gap is wrong, so the y error at
        the gap-crossing point blows up (probe: 2.2 mm -> 17.5 mm). This is
        what proves F is rebuilt from the MEASURED dt."""
        t_s, xyz, sigma_y, truth_pos = self.gap_data(config)
        k = int(np.argmax(np.diff(t_s))) + 1       # first point after the gap
        f_real = run(config, t_s, xyz, sigma_y)
        t_fake = t_s[0] + np.arange(len(t_s)) * 0.054
        f_fake = run(config, t_fake, xyz, sigma_y)
        y_err_real = abs(f_real.pos[k, 1] - truth_pos[k, 1])
        y_err_fake = abs(f_fake.pos[k, 1] - truth_pos[k, 1])
        assert y_err_real < 0.5 * y_err_fake
        assert rms(f_real.pos[k:] - truth_pos[k:]) < rms(f_fake.pos[k:] - truth_pos[k:])

    def test_natural_simulator_dropout_162ms(self, config):
        """The simulator's own dropout injection (seed chosen so it lands
        mid-flight) produces the 162 ms variant (dropout + its forward-
        difference predecessor); the filter coasts through it."""
        t_s, xyz, sigma_y, truth_pos, _ = chain(config, 1, n_dropouts=1)
        gaps = np.diff(t_s)
        assert 0.150 < gaps.max() < 0.170
        f = run(config, t_s, xyz, sigma_y)
        assert rms(f.pos - truth_pos) < 0.03


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_non_monotonic_t_raises(self, config):
        with pytest.raises(ValueError, match="increasing"):
            filter_trajectory([0.0, 0.1, 0.05], np.zeros((3, 3)), np.ones(3),
                              sigma_pos_m=0.01, q_scale=1e-4, hetero_R=True)

    def test_too_few_points_raises(self, config):
        with pytest.raises(ValueError, match="at least 2"):
            filter_trajectory([0.0], np.zeros((1, 3)), np.ones(1),
                              sigma_pos_m=0.01, q_scale=1e-4, hetero_R=True)

    def test_nan_input_raises(self, config):
        xyz = np.zeros((3, 3))
        xyz[1, 1] = np.nan
        with pytest.raises(ValueError, match="finite"):
            filter_trajectory([0.0, 0.05, 0.11], xyz, np.ones(3),
                              sigma_pos_m=0.01, q_scale=1e-4, hetero_R=True)

    def test_hetero_requires_sigma_y(self, config):
        with pytest.raises(ValueError, match="sigma_y"):
            filter_trajectory([0.0, 0.05], np.zeros((2, 3)), None,
                              sigma_pos_m=0.01, q_scale=1e-4, hetero_R=True)
