"""PC-side timing gate for firmware sketch 05 (CLAUDE.md S4, sketch 05).

This is sketch 05's actual test. Flash 05_timing_verify.ino, run this against the
serial stream, and it asserts the flight timing is exact:

  1. per-sensor period   = 54.000 ms +/- 50 us
  2. intra-triplet offset: S2 - S1 = 18 ms and S3 - S1 = 36 ms, each +/- 50 us
  3. timestamps strictly monotonic AFTER unwrapping the micros() 32-bit rollover
  4. zero parse errors

Each check prints a clear PASS/FAIL line; the process exits 0 only if all pass.

The parse / unwrap / triplet-assembly logic is REUSED from the pipeline
(pipeline/process_throw.py) — nothing here reimplements it.

Usage (from the project root, Windows):
    # live serial against a flashed Arduino (port defaults to config.yaml):
    .\\venv\\Scripts\\python.exe scripts\\verify_timing.py --port COM5

    # offline self-test against a captured / simulated raw_serial.log
    # (the simulator emits the identical sensor_id,echo_us,timestamp_us format):
    .\\venv\\Scripts\\python.exe scripts\\verify_timing.py ^
        --replay data\\sessions\\<session_id>\\raw_serial.log
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.process_throw import (
    assemble_triplets,
    parse_serial_lines,
    unwrap_micros,
)

# Timing targets (CLAUDE.md S2/S4): one 18 ms slot per sensor, 54 ms per triplet.
SLOT_US = 18000
TRIPLET_US = 54000
TOL_US = 50          # +/- 50 us pass band (CLAUDE.md S4, sketch 05)
DEFAULT_MIN_LINES = 1000
DEFAULT_SKIP_LINES = 20   # auto-reset boot-garbage window fallback (CLAUDE.md S5.1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--port", default=None,
                     help="serial port (default: acquisition.port from config)")
    src.add_argument("--replay", type=Path, default=None,
                     help="read a captured/simulated raw_serial.log instead of serial")
    p.add_argument("--baud", type=int, default=None,
                   help="serial baud (default: acquisition.baud from config)")
    p.add_argument("--min-lines", type=int, default=DEFAULT_MIN_LINES,
                   help="minimum data lines to collect/expect (default 1000)")
    p.add_argument("--skip-lines", type=int, default=DEFAULT_SKIP_LINES,
                   help="boot-garbage lines to drop when no '# fw=' header is found")
    p.add_argument("--max-seconds", type=float, default=120.0,
                   help="safety cap on the serial read loop [s]")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    return p.parse_args()


def read_file_lines(path: Path) -> list[str]:
    """Read a captured raw_serial.log verbatim (one decoded line per element)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def read_serial_lines(port: str, baud: int, min_lines: int,
                      skip_lines: int, max_seconds: float) -> list[str]:
    """Read from the live serial port until enough data lines are seen or timeout.

    pyserial is imported lazily so the --replay path works without it installed.
    """
    try:
        import serial  # pyserial (listed in requirements.txt)
    except ImportError:
        sys.exit("ERROR: pyserial not installed; use --replay <logfile> or "
                 "`.\\venv\\Scripts\\python.exe -m pip install pyserial`.")

    target = min_lines + skip_lines      # collect enough to survive the boot drop
    lines: list[str] = []
    data_seen = 0
    deadline = time.monotonic() + max_seconds
    print(f"reading from {port} @ {baud} baud "
          f"(need ~{target} lines, {max_seconds:.0f}s cap)...")
    with serial.Serial(port, baud, timeout=1.0) as ser:
        while data_seen < target and time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue                 # read timeout; keep waiting until deadline
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                data_seen += 1
    if data_seen < target:
        print(f"WARNING: collected only {data_seen} data lines before the "
              f"{max_seconds:.0f}s cap (wanted ~{target}).")
    return lines


def select_usable(lines: list[str], skip_lines: int):
    """Drop pre-header boot garbage. Keep from the first '# fw=' header onward;
    if no header is present, fall back to dropping the first ``skip_lines``."""
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#") and "fw=" in s:
            return lines[i:]
    return lines[skip_lines:]


def fmt(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> None:
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    acq = config["acquisition"]

    # --- acquire the raw line stream (replay file or live serial) ---
    if args.replay is not None:
        if not args.replay.exists():
            sys.exit(f"ERROR: replay file not found: {args.replay}")
        lines = read_file_lines(args.replay)
        print(f"replay: {args.replay} ({len(lines)} lines)")
    else:
        port = args.port if args.port is not None else acq["port"]
        baud = args.baud if args.baud is not None else acq["baud"]
        lines = read_serial_lines(port, baud, args.min_lines,
                                  args.skip_lines, args.max_seconds)

    usable = select_usable(lines, args.skip_lines)
    header, rows, n_malformed = parse_serial_lines(usable)

    print(f"header: {header!r}")
    n_data = len(rows)
    print(f"data lines parsed: {n_data}  (malformed: {n_malformed})")
    if n_data < args.min_lines:
        print(f"NOTE: fewer than --min-lines ({args.min_lines}) data lines; "
              f"checks run on what was collected.")

    # --- unwrap the micros() rollover (REUSED), then assemble S1->S2->S3 triplets ---
    results: list[tuple[bool, str]] = []

    if n_data == 0:
        results.append((False, "Per-sensor period 54 ms: no data lines parsed"))
        results.append((False, "Intra-triplet offsets 18/36 ms: no data lines parsed"))
        results.append((False, "Timestamps strictly monotonic: no data lines parsed"))
    else:
        raw_t = np.asarray([r[2] for r in rows], dtype=np.int64)
        t_unwrapped = unwrap_micros(raw_t)
        # A micros() rollover shows up as a backward step in the raw stream; that
        # is exactly what unwrap_micros corrects by adding 2**32.
        n_rollovers = int(np.count_nonzero(np.diff(raw_t) < 0))

        # Check 3 — strictly monotonic after unwrap (full received-order stream).
        diffs = np.diff(t_unwrapped)
        mono_ok = bool(diffs.size > 0 and np.all(diffs > 0))
        results.append((mono_ok,
                        f"Timestamps strictly monotonic after unwrap: "
                        f"{'all increasing' if mono_ok else 'non-monotonic step found'} "
                        f"({n_rollovers} rollover(s) unwrapped)"))

        # Assemble triplets on the UNWRAPPED timestamps for the timing checks.
        rows_unwrapped = [(r[0], r[1], int(t)) for r, t in zip(rows, t_unwrapped)]
        _echo, t_trig, n_dropped = assemble_triplets(rows_unwrapped)
        n_trip = t_trig.shape[0]
        print(f"triplets assembled: {n_trip}  (readings dropped on resync: {n_dropped})")

        # Check 1 — per-sensor period = 54.000 ms +/- 50 us (each sensor column).
        if n_trip >= 2:
            worst = 0
            for k in range(3):
                gaps = np.diff(t_trig[:, k])
                worst = max(worst, int(np.max(np.abs(gaps - TRIPLET_US))))
            period_ok = worst <= TOL_US
            results.append((period_ok,
                            f"Per-sensor period 54.000 ms +/- {TOL_US} us: "
                            f"worst deviation {worst} us"))
        else:
            results.append((False, "Per-sensor period 54 ms: need >= 2 triplets "
                                   f"(got {n_trip})"))

        # Check 2 — intra-triplet offsets S2-S1 = 18 ms, S3-S1 = 36 ms (+/- 50 us).
        if n_trip >= 1:
            off2 = int(np.max(np.abs((t_trig[:, 1] - t_trig[:, 0]) - SLOT_US)))
            off3 = int(np.max(np.abs((t_trig[:, 2] - t_trig[:, 0]) - 2 * SLOT_US)))
            offsets_ok = off2 <= TOL_US and off3 <= TOL_US
            results.append((offsets_ok,
                            f"Intra-triplet offsets S2-S1=18ms, S3-S1=36ms "
                            f"+/- {TOL_US} us: worst S2 {off2} us, worst S3 {off3} us"))
        else:
            results.append((False, "Intra-triplet offsets 18/36 ms: no triplets "
                                   "assembled"))

    # Check 4 — zero parse errors.
    results.append((n_malformed == 0,
                    f"Zero parse errors: {n_malformed} malformed row(s)"))

    # --- report ---
    print("-" * 64)
    for ok, msg in results:
        print(f"[{fmt(ok)}] {msg}")
    overall = all(ok for ok, _ in results)
    print("-" * 64)
    print(f"OVERALL: {fmt(overall)}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
