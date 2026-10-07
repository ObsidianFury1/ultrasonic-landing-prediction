"""Section 9 acceptance gate: the full offline pipeline over synthetic sessions.

Design notes (all measured, see the Step-8 report to the user):
- Drag-ON sessions use drag_k = 5x the realistic value: with the realistic
  coefficient the along-track bias (~8 mm) is far below the ~20 mm landing
  scatter and 12 sessions have no statistical power (the section 11 R9
  formula); 5x gives ~50 mm bias ([D6] measured 54 mm) and the gate accepts at
  n=12. [D6] "realistic value" is the basketball -- simulator.default_drag_k is
  within ~1% of the former tennis value, so K_SCALE carries over unchanged.
- Processing uses the PRODUCTION config unchanged. As of v2.2 (D1) that means
  the HYBRID temporal stencil (config corrections.central_difference: true) —
  the gate was re-validated under it and all criteria still hold (the hybrid
  ~-12..-15 mm self-systematic sits between forward's -24 mm and pure-central's
  -10 mm; drag-OFF still returns 'none' at n=12, measured below).
- Headline gate fixtures keep beam_cone_enabled OFF (D2): the over-produced
  ~14-22 triplets are the conservative regime the thresholds were calibrated
  against. The realistic cone-ON regime (~5-6 triplets) is covered by the
  dedicated test_gate_density_realistic_cone, which guards the D1xD2 interaction
  (hybrid retains all N triplets so cone-thinned data still clears the fit).
- The landing-accuracy criterion and the negative controls run on the
  DRAG-OFF set: on drag-ON data the deliberate ~50 mm drag overshoot masks
  (R3) or partially cancels (R2 pulls landings short) the correction-removal
  effects.
- [D6] R2 is the load-bearing e2e must-fail control: disabling it explodes the
  landing error to ~160 mm (probed: 34.5 -> 159.6 mm; the surface->centre
  correction is now ~119 mm, not the tennis ~33.5 mm). R4 (sensor_height) is NO
  LONGER an e2e must-fail at the basketball radius -- at the higher y = r_ball
  ~119 mm contact height the omitted 45 mm offset maps to only ~4 mm of landing
  error (34.5 -> 38.6 mm), below the e2e floor -- so it is pinned (not asserted
  as a failure) and its correctness is guarded by the radius-independent unit
  control in test_trilateration.py. (Was tennis: 47 -> 81 mm R2, 47 -> 65 mm R4.)
- The R3 (mid-echo) control CANNOT fail any honest end-to-end criterion:
  measured on landing error (paired delta +0.1 mm), on aligned-range
  residuals at sigma = 8 mm (identical medians), and on noise-free twins
  (identical to +-0.2 mm) — the differential timing error is averaged out by
  the landing fit and swamped by the zenith-curvature residual everywhere
  else. The correction is exact and free (kept), but its load-bearing proof
  is the unit-level negative control in test_corrections.py (17,000x error
  inflation in the isolating regime). The e2e variant below PINS DOWN the
  below-noise-floor finding instead of asserting a failure that physics does
  not produce. This is a measured deviation from the section 9 expectation,
  reported to and accepted by the project owner at Step 8.
- Sessions whose throws never populate the overlap column (or starve the fit,
  n_points < 8) are regenerated — in the live campaign those are re-thrown
  (section 11); a success-rate guard keeps real breakage visible.

Runtime: ~1-2 minutes (it is the acceptance gate, not a unit suite).
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy import stats

from pipeline.bias import (
    CorrectionModel,
    ThrowRecord,
    apply_correction,
    calibrate_with_validation,
)
from pipeline.geometry import ArrayGeometry
from pipeline.process_throw import process_session
from pipeline.simulator import (
    G,
    ThrowParams,
    default_drag_k,
    generate_session,
    random_throw,
)
from tests.session_factory import write_session_dir

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

N_SESSIONS = 12
K_SCALE = 5.0                 # drag truth for the drag-ON set (see docstring)
NOISE_MM = 8.0
MEAN_TOLERANCE_M = 0.055      # [D6] drag-OFF baseline mean 34.5 mm; must-fail R2-off 159.6 mm
                             #      (unchanged from 0.055: wide margin both ways; R4 demoted, see docstring)
PER_SESSION_CAP_M = 0.12      # [D6] drag-OFF baseline max 60.5 mm


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_set(config, drag, root, master_seed=11):
    """Generate N_SESSIONS detectable sessions; return [(folder, truth)]."""
    master = np.random.default_rng(master_seed)
    k = K_SCALE * default_drag_k(config["ball"]["radius_m"]) \
        if drag == "quadratic" else 0.0
    out, attempts = [], 0
    while len(out) < N_SESSIONS:
        attempts += 1
        assert attempts < 8 * N_SESSIONS, "session factory success rate collapsed"
        seed = int(master.integers(0, 2**32))
        rng = np.random.default_rng(seed)
        throw = random_throw(rng, heading_range_deg=60.0, drag=drag, drag_k=k)
        # ~2/3 static reflector at 1.95 m (band rule active), ~1/3 open air
        # (timeout-dominated background, the R1 disable path).
        bgd = 1.95 if len(out) % 3 != 2 else None
        n_drop = int(rng.integers(1, 3))            # 1-2 dropouts (spec)
        session = generate_session(config, throw, temperature_c=20.0,
                                   noise_mm=NOISE_MM, rng=rng,
                                   n_dropouts=n_drop, background_distance_m=bgd)
        probe = write_session_dir(root / "_probe", session, 20.0)
        try:
            r = process_session(probe, config)
            ok = r.prediction["raw"]["n_points"] >= 8
        except ValueError:
            ok = False
        shutil.rmtree(probe)
        if not ok:
            continue
        folder = write_session_dir(root / f"{drag}_{len(out):02d}", session, 20.0)
        out.append(folder)
    return out


def process_set(folders, config, control=None):
    """Process every folder (clones when a control is active, so baseline
    artifacts stay intact); return per-session result dicts."""
    results = []
    for folder in folders:
        target = folder
        if control is not None:
            target = folder.parent / f"{folder.name}__{control}"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(folder, target)
        process_session(target, config, _negative_control=control)
        meta = json.loads((target / "session.json").read_text())
        results.append(meta)
    return results


def landing_errors(metas):
    out = []
    for m in metas:
        raw = m["prediction"]["raw"]
        t = m["truth"]["landing"]
        out.append(float(np.hypot(raw["x_m"] - t["x_m"], raw["z_m"] - t["z_m"])))
    return np.array(out)


@pytest.fixture(scope="module")
def drag_on(config, tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e_on")
    folders = build_set(config, "quadratic", root)
    metas = process_set(folders, config)
    return folders, metas


@pytest.fixture(scope="module")
def drag_off(config, tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e_off")
    folders = build_set(config, "none", root, master_seed=11)
    metas = process_set(folders, config)
    return folders, metas


# ---------------------------------------------------------------------------
# 1. Segmentation: exactly one throw, arming triplets included (R5)
# ---------------------------------------------------------------------------

class TestSegmentationE2E:
    def test_every_session_one_throw(self, drag_on, drag_off):
        for _, metas in (drag_on, drag_off):
            for m in metas:
                gs = m["gate_summary"]
                assert gs["throw_end"] > gs["throw_start"]
                assert gs["n_triplets_used"] >= 8
                # In-throw block is a single contiguous window.
                assert (gs["n_triplets_in_throw"]
                        == gs["throw_end"] - gs["throw_start"] + 1)

    def test_arming_triplets_in_buffer_R5(self, config, drag_on):
        """R5 guarantees the ARMING triplets (the first arm_M-consecutive
        valid run) open the buffer retroactively. An isolated earlier valid
        blip is a false start that correctly never armed."""
        folders, _ = drag_on
        arm_m = config["gates"]["arm_M"]
        for folder in folders:
            rows = (folder / "triplets_raw.csv").read_text().splitlines()[1:]
            cells = [r.split(",") for r in rows[::3]]
            t_valid = np.array([int(c[7]) for c in cells], dtype=bool)
            in_throw = np.array([int(c[8]) for c in cells], dtype=bool)
            # First index where arm_M consecutive triplets are valid.
            runs = np.convolve(t_valid.astype(int), np.ones(arm_m, int), "valid")
            arming_start = int(np.flatnonzero(runs == arm_m)[0])
            assert in_throw[arming_start:arming_start + arm_m].all()
            # And the throw starts exactly at the arming run (retroactive).
            assert int(np.flatnonzero(in_throw)[0]) == arming_start

    def test_both_background_regimes_present(self, drag_on):
        _, metas = drag_on
        enabled = [all(m["gate_summary"]["background_enabled"]) for m in metas]
        disabled = [not any(m["gate_summary"]["background_enabled"]) for m in metas]
        assert any(enabled)       # static reflector: band rule active
        assert any(disabled)      # open air: timeout-dominated (R1) path


# ---------------------------------------------------------------------------
# 2. Landing accuracy (drag-OFF: unbiased baseline) + negative controls
# ---------------------------------------------------------------------------

class TestLandingAccuracy:
    def test_baseline_within_noise_tolerance(self, drag_off):
        _, metas = drag_off
        errs = landing_errors(metas)
        assert errs.mean() < MEAN_TOLERANCE_M
        assert errs.max() < PER_SESSION_CAP_M

    @pytest.mark.parametrize("control", ["ball_radius"])
    def test_negative_control_fails_accuracy(self, config, drag_off, control):
        """R2 disabled -> the baseline criterion MUST fail (section 9).
        [D6] R2 off now explodes to ~160 mm (was ~80 mm at the tennis radius:
        the surface->centre correction is ~119 mm, not ~33.5 mm), so this is the
        load-bearing e2e must-fail control. R4 (sensor_height) is NO LONGER an
        e2e must-fail at the basketball radius -- see
        test_negative_control_sensor_height_below_floor below -- so it was
        removed from this parametrize; its correctness stays guarded by the
        radius-independent unit control test_negative_control_R4_height_offset_bites
        in test_trilateration.py. Probed [D6]: baseline 34.5 mm -> R2 off 159.6 mm."""
        folders, metas = drag_off
        base = landing_errors(metas)
        ctl = landing_errors(process_set(folders, config, control=control))
        assert base.mean() < MEAN_TOLERANCE_M          # baseline passes
        assert ctl.mean() > MEAN_TOLERANCE_M           # control fails
        assert ctl.mean() > base.mean()

    def test_negative_control_sensor_height_below_floor(self, config, drag_off):
        """R4 (sensor_height) disabled: at the [D6] basketball radius this is
        BELOW the e2e detection floor, not a landing-criterion failure. The
        y = r_ball contact target rose from 33.5 mm (tennis) to ~119 mm, and at
        that higher contact height the omitted 45 mm sensor-height offset maps to
        only ~4 mm of landing error (measured: baseline 34.5 mm -> 38.6 mm),
        which no MEAN_TOLERANCE can separate from baseline. This pins the finding
        down (mirroring the R3/mid_echo below-floor pin above); R4's load-bearing
        negative control is unit-level (test_trilateration.py, radius-independent,
        wrong y_floor by exactly S_height_m)."""
        folders, metas = drag_off
        base = landing_errors(metas)
        ctl = landing_errors(process_set(folders, config, control="sensor_height"))
        paired = ctl - base
        # MEAN shift is small & positive (~+4 mm measured): R4-off nudges
        # landings slightly long on average. Per-session it swings both ways
        # (measured max |delta| ~31 mm) but never near a would-be must-fail.
        assert 0.0 < paired.mean() < 0.015             # small, positive, sub-floor
        assert np.abs(paired).max() < 0.04

    def test_negative_control_mid_echo_below_noise_floor(self, config, drag_off):
        """R3 disabled: measured to be UNDETECTABLE end-to-end (see module
        docstring) — the variant runs and this test pins the finding down;
        R3's load-bearing negative control is unit-level (test_corrections)."""
        folders, metas = drag_off
        base = landing_errors(metas)
        ctl = landing_errors(process_set(folders, config, control="mid_echo"))
        paired = ctl - base
        assert abs(paired.mean()) < 0.005              # below the noise floor
        assert np.abs(paired).max() < 0.02


# ---------------------------------------------------------------------------
# 3. Bias chain over the drag-ON set (the real calibrate_bias.py script)
# ---------------------------------------------------------------------------

class TestBiasChain:
    @pytest.fixture(scope="class")
    def model_path(self, drag_on, tmp_path_factory):
        folders, _ = drag_on
        out = tmp_path_factory.mktemp("model") / "correction_model.json"
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "calibrate_bias.py"),
             "--sessions", *[str(f) for f in folders],
             "--config", str(CONFIG_PATH), "--model-out", str(out),
             "--seed", "0"],
            capture_output=True, text=True, cwd=PROJECT_ROOT)
        assert result.returncode == 0, result.stderr
        return out

    def test_significant_along_track_model(self, model_path):
        model = CorrectionModel.from_dict(json.loads(model_path.read_text()))
        assert model.mode == "scalar"
        assert model.frame == "track"
        assert model.offset_along_m > 0.02             # probed [D6]: 54 mm
        assert model.along.ci_low > 0
        d = model.diagnostics
        assert d["verdict"].startswith("accepted")
        assert d["val_error_after_m"] < d["val_error_before_m"]

    def test_corrected_beats_raw_on_drag_on_set(self, drag_on, model_path):
        _, metas = drag_on
        model = CorrectionModel.from_dict(json.loads(model_path.read_text()))
        raw_errs, corr_errs = [], []
        for m in metas:
            raw = m["prediction"]["raw"]
            t = m["truth"]["landing"]
            raw_errs.append(np.hypot(raw["x_m"] - t["x_m"], raw["z_m"] - t["z_m"]))
            c = apply_correction(model, raw["x_m"], raw["z_m"],
                                 raw["heading_deg"], raw["v_h_m_s"])
            corr_errs.append(np.hypot(c["x_m"] - t["x_m"], c["z_m"] - t["z_m"]))
        assert np.mean(corr_errs) < np.mean(raw_errs)
        assert np.mean(corr_errs) < 0.045              # probed: ~34 mm

    def test_drag_off_gate_returns_none(self, config, drag_off):
        _, metas = drag_off
        records = [ThrowRecord(
            x_pred=m["prediction"]["raw"]["x_m"],
            z_pred=m["prediction"]["raw"]["z_m"],
            x_actual=m["truth"]["landing"]["x_m"],
            z_actual=m["truth"]["landing"]["z_m"],
            heading_deg=m["prediction"]["raw"]["heading_deg"],
            v_h_m_s=m["prediction"]["raw"]["v_h_m_s"]) for m in metas]
        model = calibrate_with_validation(records, config["bias"]["alpha"],
                                          rng=np.random.default_rng(0))
        assert model.mode == "none"
        assert "rejected" in model.diagnostics["verdict"]


# ---------------------------------------------------------------------------
# 4. R7: per-throw uncertainty ellipses have sane coverage
# ---------------------------------------------------------------------------

class TestUncertaintyCoverage:
    def test_ellipse_coverage_sane(self, drag_off):
        _, metas = drag_off
        chi95 = stats.chi2.ppf(0.95, 2)
        covered = 0
        for m in metas:
            raw = m["prediction"]["raw"]
            t = m["truth"]["landing"]
            dv = np.array([raw["x_m"] - t["x_m"], raw["z_m"] - t["z_m"]])
            cov = np.array(raw["cov_xz_m2"])
            covered += float(dv @ np.linalg.inv(cov) @ dv) <= chi95
        # Probed: 9/12. Loose band per the R7 small-sample caveat.
        assert covered >= N_SESSIONS // 2

    def test_caveat_recorded_per_session(self, drag_on):
        _, metas = drag_on
        assert all("degree(s) of freedom" in m["small_sample_caveat"]
                   for m in metas)


# ---------------------------------------------------------------------------
# 5. v2.2 re-validation: D1 hybrid stencil + D1xD2 interaction
# ---------------------------------------------------------------------------

class TestV22Revalidation:
    def test_gate_drag_off_none_hybrid(self, config, drag_off):
        """(D1 re-validation) Under the hybrid stencil (production default) the
        drag-OFF gate must still return mode='none' at n=12: the pipeline's own
        hybrid self-systematic (~-10 to -15 mm along-track curvature residual)
        must remain BELOW detection power at this N.

        Measured (probe): along mean ~-9.3 mm, 95% CI ~[-53, +34] mm (includes
        zero) -> 'none'. The stopping condition (CHANGES.md D1) is therefore NOT
        triggered. If a future change ever resolves the self-systematic at n=12
        the honest response is NOT to silence the gate but to assert the small
        negative scalar as the documented self-systematic — that branch is
        coded below and would fire instead of a bare failure."""
        assert config["corrections"]["central_difference"] is True   # hybrid live
        _, metas = drag_off
        records = [ThrowRecord(
            x_pred=m["prediction"]["raw"]["x_m"],
            z_pred=m["prediction"]["raw"]["z_m"],
            x_actual=m["truth"]["landing"]["x_m"],
            z_actual=m["truth"]["landing"]["z_m"],
            heading_deg=m["prediction"]["raw"]["heading_deg"],
            v_h_m_s=m["prediction"]["raw"]["v_h_m_s"]) for m in metas]
        model = calibrate_with_validation(records, config["bias"]["alpha"],
                                          rng=np.random.default_rng(0))
        if model.mode == "none":
            assert "rejected" in model.diagnostics["verdict"]
            # The self-systematic is present but unresolved at n=12 (CI spans 0).
            assert model.along.ci_low < 0 < model.along.ci_high
        else:
            # Stopping condition: hybrid resolved the self-systematic. Do not
            # silence — assert it IS the small negative pipeline systematic
            # (NOT drag, which would be positive), and document it.
            assert model.mode == "scalar"
            assert -0.020 < model.offset_along_m < 0.0, (
                "drag-OFF gate fired with an offset that is not the expected "
                f"small negative self-systematic: {model.offset_along_m*1000:.1f} mm")

    def test_gate_density_realistic_cone(self, config):
        """(D1xD2 interaction) With the beam cone ON the realistic regime is
        ~3-6 flight triplets. Hybrid (D1) retains ALL N triplets, so a
        cone-thinned 4-triplet throw exactly clears min_fit_points=4 and fits;
        a 3-triplet throw fails CLEANLY with the actionable message. Every
        cone-ON session must do one or the other (never crash, never NaN).

        FINDING surfaced to the user: at the config's 7-deg half-angle a
        campaign-speed throw (3-4 m/s) yields ZERO cone-on triplets — only slow
        apex-at-overlap lobs are admitted, and those give 3-4 triplets, right at
        the fit floor. The 7-deg estimate is inconsistent with both the campaign
        throw profile and the spec's '~5-6 triplets' claim; config.yaml and
        CLAUDE.md already flag beam_half_angle_deg as UNVERIFIED, to be tuned
        against section 7 static data. This test uses the lobs the cone admits."""
        geom = ArrayGeometry.from_config(config)
        r_c = float(np.hypot(*geom.vertices_xz[0]))
        y_overlap = (config["array"]["S_height_m"]
                     + r_c * np.tan(np.radians(config["array"]["tilt_deg"])))
        mfp = config["landing"]["min_fit_points"]

        def lob(v_h, heading_deg, t_up=0.35):
            phi = np.radians(heading_deg)
            return ThrowParams(
                x0=-v_h * t_up * np.cos(phi), y0=y_overlap - 0.5 * G * t_up**2,
                z0=-v_h * t_up * np.sin(phi),
                vx=v_h * np.cos(phi), vy=G * t_up, vz=v_h * np.sin(phi))

        import tempfile
        fitted = raised = 0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            i = 0
            for v_h in (0.7, 0.8, 0.9, 1.0, 1.1):
                for hd in (-40, -15, 15, 40):
                    i += 1
                    s = generate_session(
                        config, lob(v_h, hd), temperature_c=20.0, noise_mm=8.0,
                        rng=np.random.default_rng(i), background_distance_m=1.95,
                        beam_cone_enabled=True)
                    if s.triplet_arrays()[2].sum() == 0:
                        continue          # cone admitted nothing; not a fit case
                    folder = write_session_dir(root / f"c{i}", s, 20.0)
                    try:
                        r = process_session(folder, config)
                        assert r.prediction["raw"]["n_points"] >= mfp
                        fitted += 1
                    except ValueError as e:
                        assert ("min_fit_points" in str(e)
                                or "slower/loftier" in str(e)), str(e)
                        raised += 1
        # The interaction is real (not vacuous): some cone-thinned sessions
        # clear the fit BECAUSE hybrid kept all N triplets, and some fail
        # cleanly. Both arms must be exercised.
        assert fitted >= 1, "no cone-on session cleared the fit — D1xD2 vacuous"
        assert raised >= 1, "no cone-on session hit the clean-failure path"

    def test_hybrid_recovers_last_triplet_for_cone_fit(self, config):
        """Sharp D1xD2 demonstration: a cone-ON throw admitting exactly 4
        triplets FITS under hybrid (all 4 retained) but is REFUSED under forward
        mode (last triplet dropped -> 3 < min_fit_points). This is the precise
        reason hybrid is the production default for cone-thinned data."""
        import copy
        import tempfile
        geom = ArrayGeometry.from_config(config)
        r_c = float(np.hypot(*geom.vertices_xz[0]))
        y_overlap = (config["array"]["S_height_m"]
                     + r_c * np.tan(np.radians(config["array"]["tilt_deg"])))
        throw = ThrowParams(x0=-0.7 * 0.35, y0=y_overlap - 0.5 * G * 0.35**2,
                            z0=0.0, vx=0.7, vy=G * 0.35, vz=0.0)
        forward_cfg = copy.deepcopy(config)
        forward_cfg["corrections"]["central_difference"] = False
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s = generate_session(config, throw, temperature_c=20.0, noise_mm=8.0,
                                 rng=np.random.default_rng(0),
                                 background_distance_m=1.95, beam_cone_enabled=True)
            assert s.triplet_arrays()[2].sum() == 4        # cone admits exactly 4
            hybrid_dir = write_session_dir(root / "hybrid", s, 20.0)
            forward_dir = write_session_dir(root / "forward", s, 20.0)
            # Hybrid: all 4 retained -> fits.
            r = process_session(hybrid_dir, config)
            assert r.prediction["raw"]["n_points"] == 4
            # Forward: last triplet dropped -> 3 -> clean refusal.
            with pytest.raises(ValueError, match="slower/loftier|min_fit_points"):
                process_session(forward_dir, forward_cfg)
