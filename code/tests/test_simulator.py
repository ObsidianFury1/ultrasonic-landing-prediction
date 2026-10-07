"""Sanity tests for pipeline.simulator (CLAUDE.md section 6).

Internal-consistency checks only — no processing code exists yet. The
simulator is otherwise validated implicitly by every later layer's tests.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline.geometry import ArrayGeometry, cart_to_polar
from pipeline.simulator import (
    ThrowParams,
    ballistic_position,
    default_drag_k,
    generate_session,
    random_throw,
    simulate_trajectory,
    speed_of_sound,
)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def radius(config):
    return config["ball"]["radius_m"]


THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


# ---------------------------------------------------------------------------
# Trajectory integration
# ---------------------------------------------------------------------------

class TestTrajectory:
    def test_drag_free_matches_closed_form(self, radius):
        traj = simulate_trajectory(THROW, radius)
        # Compare at interior grid points against the analytic ballistic arc.
        sel = traj.t[traj.t < traj.t_land][::50]
        expected = ballistic_position(THROW, sel)
        assert np.allclose(traj.position(sel), expected, atol=1e-9)

    def test_landing_at_ball_radius(self, radius):
        traj = simulate_trajectory(THROW, radius)
        assert traj.pos[-1, 1] == pytest.approx(radius, abs=1e-9)
        assert traj.t[-1] == pytest.approx(traj.t_land)
        # Analytic landing time for the drag-free throw.
        t_exp = (THROW.vy + np.sqrt(THROW.vy**2 + 2 * 9.81 * (THROW.y0 - radius))) / 9.81
        assert traj.t_land == pytest.approx(t_exp, abs=1e-6)

    def test_quadratic_drag_lands_short(self, radius):
        drag_k = default_drag_k(radius)
        draggy = ThrowParams(**{**THROW.as_dict(), "drag": "quadratic", "drag_k": drag_k})
        t_free = simulate_trajectory(THROW, radius)
        t_drag = simulate_trajectory(draggy, radius)
        start = THROW.p0[[0, 2]]
        range_free = np.linalg.norm(t_free.landing_xz - start)
        range_drag = np.linalg.norm(t_drag.landing_xz - start)
        assert range_drag < range_free
        # Expected scale: ~cm-level drag shortfall for a basketball at these
        # speeds ([D6] default_drag_k is within ~1% of the old tennis value, so
        # this bound is unchanged; see simulator.default_drag_k).
        assert (range_free - range_drag) > 0.01

    def test_underground_start_raises(self, radius):
        bad = ThrowParams(x0=0, y0=0.01, z0=0, vx=1, vy=1, vz=0)
        with pytest.raises(ValueError, match="floor"):
            simulate_trajectory(bad, radius)

    def test_bad_drag_mode_raises(self):
        with pytest.raises(ValueError, match="drag"):
            ThrowParams(x0=0, y0=1, z0=0, vx=1, vy=1, vz=0, drag="linear")


# ---------------------------------------------------------------------------
# Session generation
# ---------------------------------------------------------------------------

def make_session(config, *, noise_mm=0.0, seed=0, **kwargs):
    rng = np.random.default_rng(seed)
    return generate_session(config, THROW, temperature_c=20.0,
                            noise_mm=noise_mm, rng=rng, **kwargs)


class TestSampling:
    def test_fixed_point_sample_instants(self, config):
        session = make_session(config)
        v = speed_of_sound(20.0)
        hits = [r for r in session.readings if r["target"]]
        assert len(hits) > 0
        for r in hits:
            # t_hit must satisfy the implicit timing equation to < 1 us.
            assert r["t_hit_s"] - r["t_trig_s"] == pytest.approx(
                r["d_centre_m"] / v, abs=1e-6)

    def test_noise_free_echo_decodes_to_surface_range(self, config, radius):
        session = make_session(config, noise_mm=0.0)
        v = speed_of_sound(20.0)
        for r in session.readings:
            if r["target"] and r["echo_us"] > 0:
                d_decoded = v * r["echo_us"] * 1e-6 / 2.0
                # Surface range (R2): centre range minus ball radius,
                # within the 1 us echo quantization (~0.2 mm).
                assert d_decoded == pytest.approx(
                    r["d_centre_m"] - radius, abs=v * 1e-6)

    def test_open_air_background_is_all_timeouts(self, config):
        session = make_session(config)
        n_pre = session.truth["n_triplets"]["background_pre"]
        pre = [r for r in session.readings if r["triplet"] < n_pre]
        assert len(pre) == 3 * n_pre
        assert all(r["echo_us"] == 0 for r in pre)

    def test_static_background_distance(self, config):
        session = make_session(config, background_distance_m=1.4)
        v = speed_of_sound(20.0)
        n_pre = session.truth["n_triplets"]["background_pre"]
        pre = [r for r in session.readings if r["triplet"] < n_pre]
        d = np.array([v * r["echo_us"] * 1e-6 / 2.0 for r in pre])
        assert np.allclose(d, 1.4, atol=1e-3)

    def test_dropouts_force_whole_triplet_timeouts(self, config):
        session = make_session(config, noise_mm=8.0, n_dropouts=2, seed=7)
        dropped = session.truth["n_triplets"]["dropouts"]
        assert len(dropped) == 2
        for n in dropped:
            rows = [r for r in session.readings if r["triplet"] == n]
            assert all(r["echo_us"] == 0 for r in rows)

    def test_truth_landing_consistent_with_polar(self, config):
        session = make_session(config)
        landing = session.truth["landing"]
        r, theta = cart_to_polar(landing["x_m"], landing["z_m"])
        assert landing["r_m"] == pytest.approx(r)
        assert landing["theta_deg"] == pytest.approx(theta)


class TestSerialFormat:
    def test_header_first_and_from_config(self, config):
        session = make_session(config)
        acq = config["acquisition"]
        assert session.serial_lines[0] == (
            f"# fw=05,slot_ms={acq['slot_ms']},timeout_us={acq['pulse_timeout_us']}")

    def test_all_rows_parse_and_slot_offsets(self, config):
        session = make_session(config)
        slot_us = config["acquisition"]["slot_ms"] * 1000
        rows = [tuple(int(v) for v in line.split(","))
                for line in session.serial_lines[1:]]
        assert all(len(row) == 3 for row in rows)
        sids = [row[0] for row in rows]
        assert sids == [1, 2, 3] * (len(rows) // 3)
        for triplet_start in range(0, len(rows), 3):
            t1, t2, t3 = (rows[triplet_start + k][2] for k in range(3))
            assert t2 - t1 == slot_us
            assert t3 - t1 == 2 * slot_us

    def test_timestamps_strictly_monotonic(self, config):
        session = make_session(config)
        ts = [int(line.split(",")[2]) for line in session.serial_lines[1:]]
        assert all(b > a for a, b in zip(ts, ts[1:]))

    def test_serial_bytes_crlf(self, config):
        session = make_session(config)
        raw = session.serial_bytes()
        assert raw.count(b"\r\n") == len(session.serial_lines)

    def test_reproducibility(self, config):
        a = make_session(config, noise_mm=8.0, seed=42)
        b = make_session(config, noise_mm=8.0, seed=42)
        c = make_session(config, noise_mm=8.0, seed=43)
        assert a.serial_lines == b.serial_lines
        assert a.serial_lines != c.serial_lines


# ---------------------------------------------------------------------------
# (D2) Beam-cone visibility model
# ---------------------------------------------------------------------------

def overlap_throw(config, v_h, t_up=0.35, heading_deg=0.0):
    """Throw whose apex sits exactly at the cone-overlap centre — derived
    from geometry (centroid column at y = h + R_c*tan(tilt)), no magic
    numbers. Only such lobs are detectable with the 7-deg default cone:
    measured, a campaign-speed 3.2 m/s throw yields ZERO cone-on triplets
    (it crosses y~0.87 m far from the centroid and transits the ~0.25 m
    overlap in ~1 triplet) — the 7-deg estimate and the spec's '~5-6
    triplets at 3-4 m/s' are mutually inconsistent; beam_half_angle_deg
    must be tuned against the section 7 static data (config says so)."""
    from pipeline.geometry import ArrayGeometry
    from pipeline.simulator import G
    geom = ArrayGeometry.from_config(config)
    r_c = float(np.hypot(*geom.vertices_xz[0]))
    y_overlap = (config["array"]["S_height_m"]
                 + r_c * np.tan(np.radians(config["array"]["tilt_deg"])))
    phi = np.radians(heading_deg)
    return ThrowParams(
        x0=-v_h * t_up * np.cos(phi), y0=y_overlap - 0.5 * G * t_up**2,
        z0=-v_h * t_up * np.sin(phi),
        vx=v_h * np.cos(phi), vy=G * t_up, vz=v_h * np.sin(phi))


class TestBeamConeD2:
    def test_cone_axis_from_geometry(self, config):
        """Aim axes must be the tilt_deg-elevated inward unit vectors derived
        from the configured vertices (guards against a hardcoded axis)."""
        from pipeline.geometry import ArrayGeometry
        from pipeline.simulator import sensor_aim_axes
        geom = ArrayGeometry.from_config(config)
        tilt = np.radians(config["array"]["tilt_deg"])
        axes = sensor_aim_axes(geom, config["array"]["tilt_deg"])
        for i, (vx, vz) in enumerate(geom.vertices_xz):
            u = -np.array([vx, vz]) / np.hypot(vx, vz)
            expected = np.array([np.cos(tilt) * u[0], np.sin(tilt),
                                 np.cos(tilt) * u[1]])
            assert np.allclose(axes[i], expected, atol=1e-12)
            assert np.linalg.norm(axes[i]) == pytest.approx(1.0)

    def test_cone_gates_offaxis(self, config):
        """Geometric: points built at half_angle -/+ 0.5 deg off the aim axis
        measure under/over the threshold. Integration: every cone-gated
        reading is a timeout whose (cone-off twin) ball position is outside
        the cone; every cone-on detection is inside."""
        from pipeline.geometry import ArrayGeometry
        from pipeline.simulator import angle_from_axis_deg, sensor_aim_axes
        geom = ArrayGeometry.from_config(config)
        half = config["simulator"]["beam_half_angle_deg"]
        axes = sensor_aim_axes(geom, config["array"]["tilt_deg"])
        p1, a1 = geom.vertices_3d[0], axes[0]
        w = np.cross(a1, [0.0, 1.0, 0.0])
        w /= np.linalg.norm(w)                      # perpendicular to the axis
        for theta, outside in ((half - 0.5, False), (half + 0.5, True)):
            point = p1 + 1.0 * (np.cos(np.radians(theta)) * a1
                                + np.sin(np.radians(theta)) * w)
            angle = angle_from_axis_deg(point, p1, a1)
            assert angle == pytest.approx(theta, abs=1e-9)
            assert (angle > half) == outside

        # Integration through generate_session: reading geometry (t_hit,
        # flags) is rng-independent, so the cone-off run is an exact twin.
        kw = dict(temperature_c=20.0, noise_mm=8.0, n_bg_pre=2, n_bg_post=2)
        on = generate_session(config, THROW, rng=np.random.default_rng(0),
                              beam_cone_enabled=True, **kw)
        off = generate_session(config, THROW, rng=np.random.default_rng(0),
                               beam_cone_enabled=False, **kw)
        t_launch = on.truth["t_launch_s"]
        gated = [k for k, r in enumerate(on.readings) if r["cone_gated"]]
        assert len(gated) > 0
        for k in gated:
            r_on, r_off = on.readings[k], off.readings[k]
            assert r_on["echo_us"] == 0
            assert r_off["target"]                  # ball was detectable sans cone
            pos = on.trajectory.position(r_off["t_hit_s"] - t_launch)
            sensor = geom.vertices_3d[r_on["sensor_id"] - 1]
            assert angle_from_axis_deg(pos, sensor,
                                       axes[r_on["sensor_id"] - 1]) > half
        for r in on.readings:
            if r["target"]:
                pos = on.trajectory.position(r["t_hit_s"] - t_launch)
                sensor = geom.vertices_3d[r["sensor_id"] - 1]
                assert angle_from_axis_deg(
                    pos, sensor, axes[r["sensor_id"] - 1]) <= half + 0.3

    def test_cone_reduces_triplet_count(self, config):
        """Overlap-aimed lob: cone-on lands in the realistic band (probed:
        3 at v_h = 1.0 with the default 7 deg), cone-off vastly more (14)."""
        throw = overlap_throw(config, v_h=1.0)
        counts = {}
        for cone in (True, False):
            s = generate_session(config, throw, temperature_c=20.0,
                                 noise_mm=8.0, rng=np.random.default_rng(0),
                                 n_bg_pre=2, n_bg_post=2,
                                 beam_cone_enabled=cone)
            _, _, target = s.triplet_arrays()
            counts[cone] = int(target.sum())
        assert 3 <= counts[True] <= 10
        assert counts[False] >= 2 * counts[True]

    def test_cone_disabled_matches_legacy(self, config):
        """beam_cone_enabled=False must be byte-identical to the default
        (legacy) path — no silent behaviour change when off."""
        kw = dict(temperature_c=20.0, noise_mm=8.0, n_bg_pre=2, n_bg_post=2)
        default = generate_session(config, THROW,
                                   rng=np.random.default_rng(42), **kw)
        explicit_off = generate_session(config, THROW,
                                        rng=np.random.default_rng(42),
                                        beam_cone_enabled=False, **kw)
        assert default.serial_lines == explicit_off.serial_lines
        assert not any(r["cone_gated"] for r in explicit_off.readings)


# ---------------------------------------------------------------------------
# (D4) Unique session directory names
# ---------------------------------------------------------------------------

class TestSessionNamingD4:
    WHEN = __import__("datetime").datetime(2026, 6, 12, 14, 30, 52)

    def test_session_names_unique_in_batch(self, config):
        from pipeline.simulator import session_directory_names
        names = session_directory_names(config, 12, self.WHEN)
        assert len(names) == 12
        assert len(set(names)) == 12               # S## counter disambiguates

    def test_session_name_format(self, config):
        import re

        from pipeline.simulator import session_directory_names
        names = session_directory_names(config, 3, self.WHEN)
        for name in names:
            assert re.match(r"^sim_\d{4}-\d{2}-\d{2}_\d{6}_S\d{2}$", name), name
        assert names[2] == "sim_2026-06-12_143052_S03"

    def test_session_names_no_overwrite_across_runs(self, config, tmp_path):
        import datetime

        from pipeline.simulator import session_directory_names
        from scripts.simulate_session import create_session_folder

        # Two batches >= 1 s apart: name sets fully disjoint.
        t2 = self.WHEN + datetime.timedelta(seconds=1)
        batch_a = session_directory_names(config, 5, self.WHEN)
        batch_b = session_directory_names(config, 5, t2)
        assert not set(batch_a) & set(batch_b)
        # Same timestamp reproduces the same names (deterministic), so a true
        # re-run collision is possible only on disk — where the guard fires.
        assert session_directory_names(config, 5, self.WHEN) == batch_a
        create_session_folder(tmp_path, batch_a[0])
        with pytest.raises(RuntimeError, match="already exists"):
            create_session_folder(tmp_path, batch_a[0])


# ---------------------------------------------------------------------------
# (D5) Demo sessions land under the demo subtree; demo campaign auto-regens
# ---------------------------------------------------------------------------

class TestDemoStorageD5:
    def test_batch_writes_under_demo_subtree(self, tmp_path, monkeypatch):
        import sys

        from scripts import simulate_session

        out = tmp_path / "sessions"
        monkeypatch.setattr(sys, "argv", [
            "simulate_session.py", "--n-sessions", "3", "--beam-cone", "off",
            "--seed", "11", "--out-dir", str(out)])
        simulate_session.main()

        demo = out / "demo"
        session_dirs = sorted(p for p in demo.iterdir() if p.is_dir())
        # (D5) the 3 session dirs are under demo/, NOT directly under the live root
        assert len(session_dirs) == 3
        assert all((p / "session.json").exists() for p in session_dirs)
        # the live root holds ONLY the demo container -- no sim dirs, no live
        # campaign.html leaked out of the demo subtree
        assert sorted(p.name for p in out.iterdir()) == ["demo"]
        # (D5a) the demo campaign was auto-regenerated at end of batch
        assert (demo / "campaign.html").exists()

    def test_demo_subdir_flag_overrides_config(self, tmp_path, monkeypatch):
        import sys

        from scripts import simulate_session

        out = tmp_path / "sessions"
        monkeypatch.setattr(sys, "argv", [
            "simulate_session.py", "--n-sessions", "2", "--beam-cone", "off",
            "--seed", "7", "--out-dir", str(out), "--demo-subdir", "synthetic"])
        simulate_session.main()

        assert not (out / "demo").exists()             # config default not used
        synth = out / "synthetic"
        assert len([p for p in synth.iterdir() if p.is_dir()]) == 2
        assert (synth / "campaign.html").exists()

    def test_plot_renders_per_throw_report_html(self, tmp_path, monkeypatch):
        """Processed demo sessions get the per-throw report.html by DEFAULT, so the
        demo session has the identical internal layout as a live one (CLAUDE 5.6).
        Processing is now the default (no --plot flag); --no-plot opts out."""
        import sys

        from scripts import simulate_session

        out = tmp_path / "sessions"
        # --drag quadratic keeps these throws inside d_max so they process and a
        # per-throw report is rendered (drag-free at speed 3-4 overshoots ~2.1 m).
        monkeypatch.setattr(sys, "argv", [
            "simulate_session.py", "--n-sessions", "2", "--beam-cone", "off",
            "--drag", "quadratic", "--seed", "20260625", "--out-dir", str(out)])
        simulate_session.main()

        demo = out / "demo"
        session_dirs = sorted(p for p in demo.iterdir() if p.is_dir())
        assert len(session_dirs) == 2
        # each processed session now carries report.html (+ the processed layout)
        for p in session_dirs:
            assert (p / "report.html").is_file()
            assert (p / "trajectory.csv").is_file()
        assert (demo / "campaign.html").exists()


class TestRandomThrow:
    def test_headings_within_range_and_arc_over_array(self, config, radius):
        rng = np.random.default_rng(11)
        for _ in range(20):
            throw = random_throw(rng, heading_range_deg=60.0)
            phi = np.degrees(np.arctan2(throw.vz, throw.vx))
            assert -60.0 <= phi <= 60.0
            traj = simulate_trajectory(throw, radius)
            # The arc must cross the array region: apex reasonably high and
            # the landing downrange of the launch point.
            assert traj.apex_y > 1.0
            assert np.dot(traj.landing_xz - throw.p0[[0, 2]],
                          throw.v0[[0, 2]]) > 0
