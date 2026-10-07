"""Tests for pipeline.reporting.plot_session — pure plotting over a written session.

Reuses tests/session_factory.write_session_dir; process_session is CALLED (not
modified) to populate the trajectory/triplets CSVs the plots read.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline import reporting
from pipeline.process_throw import process_session
from pipeline.simulator import ThrowParams, generate_session
from tests.session_factory import write_session_dir

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
# A throw proven detectable in test_process_throw (with a 1.95 m static reflector).
THROW = ThrowParams(x0=-1.5, y0=0.8, z0=0.2, vx=3.2, vy=4.0, vz=-0.5)


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_plots_written(config, tmp_path):
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(0), background_distance_m=1.95)
    folder = write_session_dir(tmp_path / "S", session, 20.0)
    process_session(folder, config)            # populates trajectory.csv + triplets_raw.csv

    paths = reporting.plot_session(folder, config)

    assert len(paths) == 2
    assert {p.name for p in paths} == {"trajectory_fit.png", "range_vs_time.png"}
    for p in paths:
        assert p.exists() and p.stat().st_size > 0
    assert (folder / "plots" / "trajectory_fit.png").is_file()
    assert (folder / "plots" / "range_vs_time.png").is_file()


def test_missing_trajectory_skips(config, tmp_path, capsys):
    session = generate_session(config, THROW, temperature_c=20.0, noise_mm=8.0,
                               rng=np.random.default_rng(1), background_distance_m=1.95)
    folder = write_session_dir(tmp_path / "S2", session, 20.0)  # NOT processed

    paths = reporting.plot_session(folder, config)              # must not raise

    assert paths == []
    assert "trajectory.csv" in capsys.readouterr().out
    assert not (folder / "plots" / "trajectory_fit.png").exists()
