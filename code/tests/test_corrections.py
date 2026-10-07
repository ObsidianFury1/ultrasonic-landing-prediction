"""Tests for pipeline.corrections (CLAUDE.md section 8.2, R2, R3, A4).

Two complementary data sources:
- LINEAR-range synthetic data (constant range-rate, sampled with the exact
  implicit timing): the regime where Option A's model holds exactly. Here the
  chain must be sub-mm accurate and the R2/R3 negative controls show their
  pure, uncontaminated magnitudes.
- Noise-free SIMULATOR throws: realistic curved arcs, where the residual is
  curvature-limited (the A4 effect, cm-scale, bounded) and must still be much
  smaller than applying no temporal correction at all.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.corrections import (
    add_ball_radius,
    apply_sensor_offset,
    correct_triplets,
    echo_us_to_m,
    mid_echo_sample_time_us,
    speed_of_sound,
    temporal_correction,
    temporal_residual_vs_speed,
)
from pipeline.geometry import ArrayGeometry
from pipeline.simulator import ThrowParams, generate_session

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def radius(config):
    return config["ball"]["radius_m"]


@pytest.fixture(scope="module")
def sim_session(config):
    """Noise-free simulated throw + its (N, 3) triplet arrays."""
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=0.0,
                               rng=np.random.default_rng(0), n_bg_pre=2, n_bg_post=2)
    echo, t_trig, target = session.triplet_arrays()
    return session, echo, t_trig, target


def sim_errors(config, session, res, target, reference_us):
    """Per usable in-flight triplet: |d_aligned - d_true| for S2/S3, where the
    truth is evaluated at the run's own S1 reference instant (reference_us)."""
    geom = ArrayGeometry.from_config(config)
    sensors = geom.vertices_3d
    t_launch = session.truth["t_launch_s"]
    errors = []
    for n in np.flatnonzero(res.usable & target):
        pos = session.trajectory.position(reference_us[n, 0] * 1e-6 - t_launch)
        d_true = np.linalg.norm(sensors - pos, axis=1)
        errors.append(np.abs(res.d_aligned[n, 1:] - d_true[1:]))
    return np.array(errors)


# ---------------------------------------------------------------------------
# Linear-range synthetic data (exact implicit-timing sampling, float echoes)
# ---------------------------------------------------------------------------

V_SOUND_20C = speed_of_sound(20.0)
LIN_D0 = np.array([0.6, 1.2, 1.8])     # spread ranges -> large differential echo/2
LIN_B = np.array([2.5, -3.0, 2.0])     # range rates [m/s]


def linear_session(n_triplets=10, slot_s=0.018):
    """Readings from d_i(t) = d0_i + b_i*t with the exact implicit timing:
    t_hit = (t_trig + d0/v) / (1 - b/v). Float echoes (no quantization), so
    any residual is purely algorithmic."""
    echo = np.zeros((n_triplets, 3))
    t_trig = np.zeros((n_triplets, 3))
    for k in range(n_triplets):
        for i in range(3):
            tt = k * 3 * slot_s + i * slot_s
            t_hit = (tt + LIN_D0[i] / V_SOUND_20C) / (1.0 - LIN_B[i] / V_SOUND_20C)
            d_hit = LIN_D0[i] + LIN_B[i] * t_hit
            echo[k, i] = 2.0 * d_hit / V_SOUND_20C * 1e6
            t_trig[k, i] = tt * 1e6
    return echo, t_trig


def linear_truth(t_ref_s):
    return LIN_D0 + LIN_B * t_ref_s


# ---------------------------------------------------------------------------
# (a) temperature, t_sample, (b) radius — unit behaviour
# ---------------------------------------------------------------------------

class TestElementaryCorrections:
    def test_echo_to_distance_known_values(self):
        # 20 C: v = 343.52 m/s; 2 m round trip in t = 2*2/343.52 s.
        echo = 2.0 * 2.0 / speed_of_sound(20.0) * 1e6
        assert echo_us_to_m(echo, 20.0) == pytest.approx(2.0, abs=1e-12)
        echo5 = 2.0 * 2.0 / speed_of_sound(5.0) * 1e6
        assert echo_us_to_m(echo5, 5.0) == pytest.approx(2.0, abs=1e-12)
        # Same echo decoded at the wrong temperature is measurably off.
        assert abs(echo_us_to_m(echo, 5.0) - 2.0) > 0.02

    def test_timeout_is_nan(self):
        assert np.isnan(echo_us_to_m(0, 20.0))
        out = echo_us_to_m(np.array([[5000, 0, 7000]]), 20.0)
        assert np.isnan(out[0, 1]) and np.isfinite(out[0, 0])

    def test_mid_echo_sample_time(self):
        t = mid_echo_sample_time_us(np.array([1000.0, 2000.0]), np.array([500.0, 0.0]))
        assert t[0] == 1250.0          # t_trig + echo/2
        assert t[1] == 2000.0          # timeout -> t_trig

    def test_ball_radius_added(self, radius):
        assert add_ball_radius(1.0, radius) == pytest.approx(1.0 + radius)
        out = add_ball_radius(np.array([np.nan, 0.5]), radius)
        assert np.isnan(out[0]) and out[1] == pytest.approx(0.5 + radius)

    def test_sensor_offset_subtracts_per_sensor(self):
        # (Phase 5, S4D) corrected = measured - offset; a NEGATIVE offset (reads
        # short) ADDS distance. Broadcasts (3,) across (N,3); NaN-transparent.
        offset = [-0.0255, -0.0225, -0.0129]
        d = np.array([[1.000, 1.000, 1.000],
                      [np.nan, 0.500, 0.800]])
        out = apply_sensor_offset(d, offset)
        assert out[0] == pytest.approx([1.0255, 1.0225, 1.0129])
        assert np.isnan(out[1, 0])
        assert out[1, 1:] == pytest.approx([0.5225, 0.8129])

    def test_sensor_offset_none_is_noop(self):
        d = np.array([1.0, 2.0, 3.0])
        assert apply_sensor_offset(d, None) == pytest.approx(d)

    def test_sensor_offset_bad_length_raises(self):
        with pytest.raises(ValueError):
            apply_sensor_offset(np.ones((2, 3)), [0.01, 0.02])


# ---------------------------------------------------------------------------
# Headline accuracy (section 8.2 test): < 1 mm where Option A's model holds
# ---------------------------------------------------------------------------

class TestTemporalCorrectionLinear:
    def test_chain_sub_mm_on_linear_ranges(self):
        echo, t_trig = linear_session()
        res = correct_triplets(echo, t_trig, 20.0, radius_m=0.0)
        for n in np.flatnonzero(res.usable):
            d_true = linear_truth(res.t_sample_us[n, 0] * 1e-6)
            err = np.abs(res.d_aligned[n] - d_true)
            assert err.max() < 1e-3        # spec: < 1 mm
            assert err.max() < 1e-6        # actually exact up to float math

    def test_negative_control_R3_mid_echo_bites(self):
        """Same data, t_sample replaced by t_trig: measurably larger error."""
        echo, t_trig = linear_session()
        d_centre = echo_us_to_m(echo, 20.0)

        t_sample_us = mid_echo_sample_time_us(t_trig, echo)
        d_ok, usable_ok = temporal_correction(d_centre, t_sample_us * 1e-6)
        d_bad, usable_bad = temporal_correction(d_centre, t_trig * 1e-6)

        err_ok, err_bad = [], []
        for n in np.flatnonzero(usable_ok & usable_bad):
            err_ok.append(np.abs(d_ok[n, 1:] - linear_truth(t_sample_us[n, 0] * 1e-6)[1:]))
            err_bad.append(np.abs(d_bad[n, 1:] - linear_truth(t_trig[n, 0] * 1e-6)[1:]))
        max_ok, max_bad = np.max(err_ok), np.max(err_bad)
        # Correct chain is exact; t_trig chain carries the differential
        # echo/2 misalignment (~|b|*(echo_i - echo_1)/2 ~ several mm here).
        assert max_ok < 1e-6
        assert max_bad > 5e-3
        assert max_bad > 100 * max_ok

    def test_negative_control_R2_radius_bites(self, radius):
        """Chain without add_ball_radius: range bias == the ball radius (R2).
        [D6] config-derived, so it tracks the target: ~119 mm basketball
        (was ~33.5 mm tennis). The assertion below uses the `radius` fixture,
        never a literal."""
        echo, t_trig = linear_session()
        # Encode surface ranges as the hardware would see them.
        echo_surface = echo - 2.0 * radius / V_SOUND_20C * 1e6
        res_no_r2 = correct_triplets(echo_surface, t_trig, 20.0, radius_m=0.0)
        bias = []
        for n in np.flatnonzero(res_no_r2.usable):
            d_true = linear_truth(res_no_r2.t_sample_us[n, 0] * 1e-6)
            bias.append(d_true - res_no_r2.d_aligned[n])
        mean_bias = float(np.mean(bias))
        assert mean_bias == pytest.approx(radius, abs=1e-3)   # == config ball.radius_m

    def test_usable_flags_forward_and_central(self):
        # (D1) central_difference=True is now the HYBRID stencil and keeps ALL
        # N triplets (forward@first / backward@last recover both endpoints that
        # the old pure-central path dropped). Forward mode still drops the last.
        echo, t_trig = linear_session(n_triplets=6)
        res_f = correct_triplets(echo, t_trig, 20.0, 0.0)
        assert res_f.usable.tolist() == [True] * 5 + [False]
        res_c = correct_triplets(echo, t_trig, 20.0, 0.0, central_difference=True)
        assert res_c.usable.tolist() == [True] * 6

    def test_nan_reading_flags_dependent_triplets(self):
        echo, t_trig = linear_session(n_triplets=8)
        echo[3, 1] = 0                      # timeout in triplet 3, sensor S2
        res = correct_triplets(echo, t_trig, 20.0, 0.0)
        # Triplet 3 itself and triplet 2 (whose forward difference needs 3).
        assert not res.usable[2] and not res.usable[3]
        assert res.usable[[0, 1, 4, 5, 6]].all()
        # Unaffected triplets keep finite, exact values (no NaN leakage).
        assert np.isfinite(res.d_aligned[res.usable]).all()

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="N, 3"):
            temporal_correction(np.zeros((4, 3)), np.zeros((5, 3)))


# ---------------------------------------------------------------------------
# Simulator data: curvature-limited residual (A4) — bounded and beneficial
# ---------------------------------------------------------------------------

class TestTemporalCorrectionSimulator:
    def test_chain_bounded_and_better_than_no_correction(self, config, radius,
                                                         sim_session):
        session, echo, t_trig, target = sim_session
        res = correct_triplets(echo, t_trig, 20.0, radius)
        err_corr = sim_errors(config, session, res, target, res.t_sample_us)

        # No temporal correction at all: raw centre ranges vs same instants.
        res_raw = type(res)(d_centre=res.d_centre, d_aligned=res.d_centre,
                            t_sample_us=res.t_sample_us, usable=res.usable)
        err_raw = sim_errors(config, session, res_raw, target, res.t_sample_us)

        # Curvature-limited (A4): cm-scale, bounded, far from the NaN guard,
        # and a clear improvement over leaving ranges unaligned.
        assert err_corr.max() < 0.03
        assert err_corr.max() < 0.5 * err_raw.max()
        assert np.sqrt((err_corr**2).mean()) < 0.6 * np.sqrt((err_raw**2).mean())

    def test_radius_omission_shifts_by_exactly_radius(self, config, radius,
                                                      sim_session):
        """R2 on realistic data: a constant range offset passes through the
        temporal correction untouched (velocities are differences), so
        omitting the radius biases every aligned range by exactly radius."""
        _, echo, t_trig, _ = sim_session
        res = correct_triplets(echo, t_trig, 20.0, radius)
        res_no = correct_triplets(echo, t_trig, 20.0, 0.0)
        both = res.usable & res_no.usable
        diff = res.d_aligned[both] - res_no.d_aligned[both]
        assert np.allclose(diff, radius, atol=1e-12)


class TestHybridStencilD1:
    """(D1) Hybrid forward@first / central@interior / backward@last stencil."""

    def test_hybrid_stencil_selection_linear(self):
        """On constant-range-rate data all three stencils are exact, so EVERY
        triplet — including the first and last endpoints — is corrected to
        <1e-9 m. Confirms each position uses a defined stencil, never NaN."""
        echo, t_trig = linear_session(n_triplets=7)
        res = correct_triplets(echo, t_trig, 20.0, 0.0, central_difference=True)
        assert res.usable.all()                    # all N usable
        for n in range(len(echo)):
            d_true = linear_truth(res.t_sample_us[n, 0] * 1e-6)
            assert np.abs(res.d_aligned[n] - d_true).max() < 1e-9

    def test_hybrid_retains_all_triplets(self):
        echo, t_trig = linear_session(n_triplets=6)
        res_hybrid = correct_triplets(echo, t_trig, 20.0, 0.0,
                                      central_difference=True)
        res_fwd = correct_triplets(echo, t_trig, 20.0, 0.0,
                                   central_difference=False)
        assert int(res_hybrid.usable.sum()) == 6       # N
        assert int(res_fwd.usable.sum()) == 5          # N-1 (last dropped)

    def test_hybrid_nan_fallback(self):
        # Interior triplet whose PREDECESSOR is a timeout -> central impossible
        # -> falls back to FORWARD (successor still valid) and stays usable.
        echo, t_trig = linear_session(n_triplets=8)
        echo[3, 1] = 0                                 # timeout at n=3, sensor S2
        res = correct_triplets(echo, t_trig, 20.0, 0.0, central_difference=True)
        # n=4 (interior) lost its predecessor's S2 reading -> forward fallback,
        # still corrected exactly on linear data.
        assert res.usable[4]
        d_true = linear_truth(res.t_sample_us[4, 0] * 1e-6)
        assert np.abs(res.d_aligned[4] - d_true).max() < 1e-9
        # n=3 itself has a NaN in its OWN reading -> unusable (not a velocity
        # problem; the triplet's own S2 range is missing).
        assert not res.usable[3]

        # Last triplet still corrected via BACKWARD when a timeout lands
        # elsewhere (its predecessor is intact).
        echo2, t_trig2 = linear_session(n_triplets=8)
        echo2[2, 1] = 0
        res2 = correct_triplets(echo2, t_trig2, 20.0, 0.0,
                                central_difference=True)
        assert res2.usable[-1]                         # backward, predecessor ok

        # BOTH neighbours of an interior triplet invalid -> unusable, and no
        # NaN velocity is silently turned into a finite d_aligned.
        echo3, t_trig3 = linear_session(n_triplets=8)
        echo3[3, 1] = 0
        echo3[5, 1] = 0                                # n=4's predecessor AND successor
        res3 = correct_triplets(echo3, t_trig3, 20.0, 0.0,
                                central_difference=True)
        assert not res3.usable[4]
        assert np.isnan(res3.d_aligned[4, 1])

    def test_hybrid_reduces_interior_residual(self, config):
        out = temporal_residual_vs_speed(config, speeds_m_s=(1.0, 2.0, 3.0, 4.0))
        fwd_int = np.array(out["forward_interior_m"])
        cen_int = np.array(out["central_interior_m"])
        # Interior residual strictly lower in hybrid at every tested speed.
        assert np.all(cen_int < fwd_int)


class TestZenithResidualA4:
    def test_residual_characterized(self, config):
        out = temporal_residual_vs_speed(config, speeds_m_s=(1.0, 2.0, 3.0, 4.0))
        fwd = np.array(out["forward_m"])
        cen = np.array(out["central_m"])
        # Bounded, cm-scale, well below anything that could flip the
        # trilateration radicand (NaN guard at y ~ 0.5 m).
        assert np.all(fwd < 0.03)
        assert np.all(fwd > 1e-3)          # real, non-negligible: must be reported
        # (D1) HYBRID: the WORST residual is never larger than forward, but it
        # can TIE — the worst point sits at an endpoint (forward@first /
        # backward@last), where the stencil is one-sided in both modes. The
        # genuine hybrid gain is on the INTERIOR (central there), asserted
        # strictly below.
        assert np.all(cen <= fwd + 1e-12)
        assert np.all(np.array(out["central_interior_m"])
                      < np.array(out["forward_interior_m"]))


class TestRefactor:
    def test_simulator_reexports_speed_of_sound(self):
        from pipeline.simulator import speed_of_sound as sos
        assert sos(20.0) == speed_of_sound(20.0)
