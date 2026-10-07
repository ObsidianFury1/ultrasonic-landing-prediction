"""Tests for pipeline.bias (CLAUDE.md section 8.6) + calibrate_bias.py smoke test.

Calibration records are manufactured through the REAL chain (simulator ->
corrections -> trilateration -> kalman -> landing) with two deliberate test
choices, both probed and documented:
- drag_k is 3x the realistic value: with the realistic k the along-track
  bias at 3-4 m/s is only ~8 mm against ~20 mm landing scatter, needing ~60
  throws for power (the section 11 R9 formula in action). The machinery under
  test is identical; Step 8 revisits realism. [D6] "realistic value" is now the
  basketball: simulator.default_drag_k is within ~1% of the former tennis value
  (larger A/m offset by lower Cd), so the x3 knob and these magnitudes carry over.
- corrections run in central-difference mode (A4 upgrade): the forward-
  difference curvature residual leaves a ~-24 mm along-track PIPELINE
  systematic that the gate would (correctly) detect on drag-free data,
  breaking the drag-off negative control. With central differences the
  drag-free pipeline is unbiased enough; a small residual systematic remains
  ([D6] ~-8 mm; was ~-10 mm at the tennis radius -- the shorter extrapolation
  to y = r_ball = ~119 mm accumulates less curvature), which the full-set
  scalar gate flags but the held-out validation stage correctly rejects (no
  confirmed accuracy gain) -> mode='none'.

Measured [D6] (probe, n=30 each): drag-ON track along = 46.1 mm CI (43.0, 49.2),
cross null; array-frame control |bias| = 34.3 mm; errors 47.2 -> 11.9 mm
(track) vs 15.5 mm (array); drag-OFF validated mode='none'.
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy import stats

import pipeline.bias as bias_module
from pipeline.bias import (
    AxisStats,
    CorrectionModel,
    ThrowRecord,
    apply_correction,
    calibrate,
    calibrate_with_validation,
    evaluate,
    from_track,
    to_track,
)
from pipeline.corrections import correct_triplets
from pipeline.geometry import ArrayGeometry, cart_to_polar
from pipeline.kalman import filter_trajectory
from pipeline.landing import predict_landing
from pipeline.simulator import default_drag_k, generate_session, random_throw
from pipeline.trilateration import trilaterate

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_records(config, drag, n=30, master_seed=7, k_scale=3.0):
    """Throw records through the real chain; see module docstring for the
    k_scale and central-difference choices."""
    geom = ArrayGeometry.from_config(config)
    radius = config["ball"]["radius_m"]
    kal = config["kalman"]
    master = np.random.default_rng(master_seed)
    drag_k = k_scale * default_drag_k(radius) if drag == "quadratic" else 0.0
    out = []
    while len(out) < n:
        seed = int(master.integers(0, 2**32))
        rng = np.random.default_rng(seed)
        throw = random_throw(rng, heading_range_deg=60.0, drag=drag, drag_k=drag_k)
        try:
            s = generate_session(config, throw, temperature_c=20.0, noise_mm=8.0,
                                 rng=rng, n_bg_pre=2, n_bg_post=2)
            echo, ttrig, target = s.triplet_arrays()
            cor = correct_triplets(echo, ttrig, 20.0, radius,
                                   central_difference=True)
            tri = trilaterate(cor.d_aligned, geom, kal["sigma_pos_m"])
            idx = np.flatnonzero(cor.usable & target & tri.valid)
            t = cor.t_sample_us[idx, 0] * 1e-6
            xyz = np.column_stack([tri.x[idx], tri.y_floor[idx], tri.z[idx]])
            f = filter_trajectory(t, xyz, tri.sigma_y[idx],
                                  sigma_pos_m=kal["sigma_pos_m"],
                                  q_scale=kal["q_scale"], hetero_R=True)
            p = predict_landing(f, ball_radius_m=radius,
                                min_fit_points=config["landing"]["min_fit_points"])
        except ValueError:
            continue
        if p.n_points < 8:      # starved fits give outlier extrapolations
            continue
        tl = s.truth["landing"]
        out.append(ThrowRecord(x_pred=p.x, z_pred=p.z, x_actual=tl["x_m"],
                               z_actual=tl["z_m"], heading_deg=p.heading_deg,
                               v_h_m_s=p.v_h_m_s))
    return out


@pytest.fixture(scope="module")
def records_on(config):
    return make_records(config, "quadratic")


@pytest.fixture(scope="module")
def records_off(config):
    return make_records(config, "none")


# ---------------------------------------------------------------------------
# Drag-ON: the track-aligned model finds and removes the bias
# ---------------------------------------------------------------------------

class TestDragOn:
    def test_significant_positive_along_track_bias(self, config, records_on):
        m = calibrate(records_on, config["bias"]["alpha"], allow_linear=False)
        assert m.mode == "scalar"
        assert m.along.significant
        assert m.along.ci_low > 0           # CI excludes zero on the + side
        assert m.offset_along_m > 0.02      # probe: ~49 mm
        # Cross-track: no Magnus in the simulator -> offset stays null.
        assert m.offset_cross_m == 0.0 or abs(m.offset_cross_m) < 0.015

    def test_validation_accepts_and_error_decreases(self, config, records_on):
        m = calibrate_with_validation(records_on, config["bias"]["alpha"],
                                      rng=np.random.default_rng(0))
        assert m.mode in ("scalar", "linear")
        d = m.diagnostics
        assert d["verdict"].startswith("accepted")
        assert d["val_error_after_m"] < d["val_error_before_m"]
        assert d["val_p_one_sided"] < config["bias"]["alpha"]

    def test_design_rationale_array_frame_control(self, config, records_on):
        """Test-only fixed-frame path: at +/-60 deg spread the rotating drag
        bias partially cancels (E[cos phi] ~ 0.83; full cancellation would
        need +/-180 deg), so the array-frame recovered bias must be WEAKER —
        and, decisively, correcting with it must validate WORSE than the
        track-aligned model (large cross-track leftovers at extreme
        headings). This is why the track frame is necessary."""
        alpha = config["bias"]["alpha"]
        m_track = calibrate(records_on, alpha, frame="track", allow_linear=False)
        m_array = calibrate(records_on, alpha, frame="array", allow_linear=False)
        array_mag = np.hypot(m_array.along.mean, m_array.cross.mean)
        assert array_mag < 0.85 * m_track.along.mean      # probe [D6]: 34.3 vs 46.1
        e_track = evaluate(m_track, records_on)
        e_array = evaluate(m_array, records_on)
        assert e_track["after"].mean() < e_array["after"].mean()
        assert e_track["after"].mean() < e_track["before"].mean()


# ---------------------------------------------------------------------------
# Drag-OFF: the gate refuses to invent a correction
# ---------------------------------------------------------------------------

class TestDragOff:
    def test_gate_returns_mode_none_on_unbiased_data(self, config):
        """The spec's null control of the GATE itself: records whose residuals
        are pure zero-mean noise (no real throw-aligned bias of any origin)
        must yield mode='none' — the gate never invents a correction."""
        rng = np.random.default_rng(3)
        records = []
        for _ in range(30):
            phi = rng.uniform(-60, 60)
            xa, za = rng.uniform(1.0, 2.0), rng.uniform(-0.8, 0.8)
            records.append(ThrowRecord(
                x_pred=xa + rng.normal(0, 0.02), z_pred=za + rng.normal(0, 0.02),
                x_actual=xa, z_actual=za, heading_deg=phi, v_h_m_s=3.5))
        m = calibrate_with_validation(records, config["bias"]["alpha"],
                                      rng=np.random.default_rng(0))
        assert m.mode == "none"
        assert "rejected" in m.diagnostics["verdict"]
        # And applying it is a passthrough.
        c = apply_correction(m, 1.0, 0.5, 30.0)
        assert (c["x_m"], c["z_m"]) == (1.0, 0.5)

    def test_gate_detects_real_pipeline_systematic(self, config, records_off):
        """Drag-free PIPELINE records are not unbiased: the central-difference
        chain leaves a small real along-track systematic (the A4 curvature
        residual propagated to the landing). [D6] At the basketball radius that
        systematic SHRANK to ~-8 mm (was ~-10 mm at the tennis radius): the
        landing extrapolates only to y = r_ball = ~119 mm, not ~33.5 mm, so less
        arc curvature is accumulated past the last measurement. It is therefore
        two genuine, separable facts, both asserted here:
          (1) the systematic IS real and measurable on the FULL n=30 set --
              calibrate finds a significant negative (undershoot) along-track
              bias whose CI excludes zero;
          (2) the VALIDATED gate (calibrate/validate split) is correctly
              CONSERVATIVE at n=30 for a systematic this small -- it returns
              'none' rather than commit a correction the held-out half cannot
              confirm. (Bumping n is seed-fragile right at this boundary, which
              is exactly why the split-half gate stays cautious.)
        This is consistent with the e2e drag-OFF gate also returning 'none' at
        its n=12 power (test_end_to_end_synthetic)."""
        alpha = config["bias"]["alpha"]
        # (1) real & measurable on the full set
        m_full = calibrate(records_off, alpha, frame="track", allow_linear=False)
        assert m_full.along.mean < 0            # undershoot: curvature residual
        assert m_full.along.ci_high < 0         # CI excludes zero -> significant
        assert abs(m_full.along.mean) < 0.02    # small, ~-8 mm
        # (2) but the validated gate is conservative at this n / systematic size
        m_val = calibrate_with_validation(records_off, alpha,
                                          rng=np.random.default_rng(0))
        assert m_val.mode == "none"


# ---------------------------------------------------------------------------
# Statistics machinery
# ---------------------------------------------------------------------------

class TestStats:
    def test_ci_uses_scipy_t_not_196(self):
        samples = np.array([0.01, 0.03, 0.02, 0.04, 0.015])   # n = 5
        st = AxisStats.from_samples(samples, alpha=0.05)
        t_crit = stats.t.ppf(0.975, 4)                        # 2.776, not 1.96
        assert st.ci_high - st.mean == pytest.approx(t_crit * st.sem, rel=1e-9)
        assert st.ci_high - st.mean > 1.3 * 1.96 * st.sem

    def test_track_frame_rotation_roundtrip(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            rx, rz, phi = rng.normal(size=3) * [0.1, 0.1, 90.0]
            al, cr = to_track(rx, rz, phi)
            assert from_track(al, cr, phi) == pytest.approx((rx, rz))


# ---------------------------------------------------------------------------
# Application geometry
# ---------------------------------------------------------------------------

def hand_model(along=0.0, cross=0.0, mode="scalar"):
    st = AxisStats(mean=along, std=0.01, sem=0.005, ci_low=along - 0.01,
                   ci_high=along + 0.01, significant=True)
    return CorrectionModel(mode=mode, frame="track", offset_along_m=along,
                           offset_cross_m=cross, linear_slope=0.0,
                           linear_intercept=0.0, n_throws=10, alpha=0.05,
                           along=st, cross=st, diagnostics={}, created="test")


class TestApplyCorrection:
    def test_along_offset_rotates_with_heading(self):
        b = 0.05
        m = hand_model(along=b)
        c0 = apply_correction(m, 1.0, 0.0, heading_deg=0.0)
        assert (c0["x_m"], c0["z_m"]) == pytest.approx((1.0 - b, 0.0))
        c90 = apply_correction(m, 0.0, 1.0, heading_deg=90.0)
        assert (c90["x_m"], c90["z_m"]) == pytest.approx((0.0, 1.0 - b))

    def test_cross_offset_geometry(self):
        c = 0.03
        m = hand_model(cross=c)
        out = apply_correction(m, 1.0, 1.0, heading_deg=0.0)
        assert (out["x_m"], out["z_m"]) == pytest.approx((1.0, 1.0 - c))

    def test_polar_output_consistent(self):
        m = hand_model(along=0.05)
        out = apply_correction(m, 1.2, -0.4, heading_deg=20.0)
        r, theta = cart_to_polar(out["x_m"], out["z_m"])
        assert out["r_m"] == pytest.approx(r)
        assert out["theta_deg"] == pytest.approx(theta)

    def test_linear_mode_requires_vh(self):
        m = hand_model(along=0.05, mode="linear")
        with pytest.raises(ValueError, match="v_h"):
            apply_correction(m, 1.0, 0.0, heading_deg=0.0)


# ---------------------------------------------------------------------------
# Discipline: split separation, no Kalman coupling, persistence
# ---------------------------------------------------------------------------

class TestDiscipline:
    def test_calibrate_validate_sets_disjoint(self, config, records_on):
        m = calibrate_with_validation(records_on, config["bias"]["alpha"],
                                      rng=np.random.default_rng(1))
        d = m.diagnostics
        assert not set(d["cal_indices"]) & set(d["val_indices"])
        assert d["n_cal"] + d["n_val"] == len(records_on)
        assert d["n_cal"] >= 3 and d["n_val"] >= 3

    def test_bias_never_touches_kalman(self):
        """Structural: bias.py must not import (and so cannot modify) the
        Kalman layer. The docstring may legitimately MENTION the rule."""
        imports = [line.strip() for line
                   in inspect.getsource(bias_module).splitlines()
                   if line.strip().startswith(("import ", "from "))]
        assert imports                          # sanity: we did find imports
        assert not any("kalman" in line for line in imports)

    def test_model_json_roundtrip(self, config, records_on):
        m = calibrate(records_on, config["bias"]["alpha"])
        d = json.loads(json.dumps(m.to_dict()))        # through real JSON
        m2 = CorrectionModel.from_dict(d)
        assert m2 == m
        assert m2.frame == "track"


# ---------------------------------------------------------------------------
# calibrate_bias.py smoke test (the I/O path; full exercise comes in Step 8)
# ---------------------------------------------------------------------------

class TestScript:
    def test_script_end_to_end_on_synthetic_sessions(self, tmp_path):
        rng = np.random.default_rng(0)
        b = 0.05
        for i in range(10):
            phi = rng.uniform(-60, 60)
            xa, za = rng.uniform(1.0, 2.0), rng.uniform(-0.5, 0.5)
            dx, dz = from_track(b + rng.normal(0, 0.005),
                                rng.normal(0, 0.005), phi)
            folder = tmp_path / f"S{i:02d}"
            folder.mkdir()
            meta = {
                "session_id": f"S{i:02d}",
                "prediction": {"raw": {"x_m": xa + dx, "z_m": za + dz,
                                       "heading_deg": phi, "v_h_m_s": 3.5}},
                "ground_truth": {"x_m": xa, "z_m": za},
            }
            with open(folder / "session.json", "w", newline="",
                      encoding="utf-8") as f:
                json.dump(meta, f)

        model_out = tmp_path / "correction_model.json"
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "calibrate_bias.py"),
             "--sessions", str(tmp_path / "S*"),
             "--config", str(CONFIG_PATH),
             "--model-out", str(model_out), "--seed", "0"],
            capture_output=True, text=True, cwd=PROJECT_ROOT)
        assert result.returncode == 0, result.stderr
        assert model_out.is_file()
        model = CorrectionModel.from_dict(json.loads(model_out.read_text()))
        assert model.mode in ("none", "scalar", "linear")
        report = json.loads(
            (tmp_path / "correction_model_report.json").read_text())
        assert report["n_sessions"] == 10

    def test_power_note_reads_below_threshold(self, tmp_path):
        """(D3) A small set with a TINY along-track bias (3 mm) buried in
        ~20 mm scatter -> gate returns 'none' (unresolvable at N=12), and the
        report/stdout state the finite power-N (~hundreds) and flag the null
        as underpowered ('drag below noise floor'), not a failure."""
        rng = np.random.default_rng(3)
        b = 0.003                              # 3 mm: real but far below noise
        for i in range(12):
            phi = rng.uniform(-60, 60)
            xa, za = rng.uniform(1.0, 2.0), rng.uniform(-0.8, 0.8)
            dx, dz = from_track(b + rng.normal(0, 0.020),
                                rng.normal(0, 0.020), phi)
            folder = tmp_path / f"S{i:02d}"
            folder.mkdir()
            meta = {
                "session_id": f"S{i:02d}",
                "prediction": {"raw": {"x_m": xa + dx, "z_m": za + dz,
                                       "heading_deg": phi, "v_h_m_s": 3.5}},
                "ground_truth": {"x_m": xa, "z_m": za},
            }
            with open(folder / "session.json", "w", newline="",
                      encoding="utf-8") as f:
                json.dump(meta, f)

        model_out = tmp_path / "correction_model.json"
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "calibrate_bias.py"),
             "--sessions", str(tmp_path / "S*"),
             "--config", str(CONFIG_PATH),
             "--model-out", str(model_out), "--seed", "0"],
            capture_output=True, text=True, cwd=PROJECT_ROOT)
        assert result.returncode == 0, result.stderr
        report = json.loads(
            (tmp_path / "correction_model_report.json").read_text())
        assert report["mode"] == "none"
        # Finite power-N (hundreds) far above N=12, reported in stdout + JSON,
        # and the underpowered-null message present.
        assert "Statistical power note" in result.stdout
        assert report["power_n"] is not None
        assert report["power_n"] > report["n_sessions"]
        assert report["underpowered_null"] is True
        assert "below noise floor" in result.stdout
        assert "below noise floor" in report["underpowered_null_note"]
