"""Shared test helper: write a SyntheticSession to a session directory in the
same on-disk format scripts/simulate_session.py produces (raw_serial.log +
session.json with the TRUE landing recorded)."""

import json
from pathlib import Path

from pipeline.simulator import SyntheticSession


def write_session_dir(folder: Path, session: SyntheticSession,
                      temperature_c: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "raw_serial.log", "wb") as f:        # W2: binary
        f.write(session.serial_bytes())
    meta = {
        "session_id": folder.name,
        "simulated": True,
        "temperature_c": temperature_c,
        "fw_header": session.serial_lines[0],
        "truth": session.truth,
    }
    with open(folder / "session.json", "w", newline="", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return folder
