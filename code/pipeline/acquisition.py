"""Live serial acquisition: raw lines -> assembled triplets (CLAUDE.md section 5.1).

This is the I/O-layer twin of the offline parse path in process_throw.py. It is
deliberately thin GLUE: it reads serial byte-lines, logs every one VERBATIM to
raw_serial.log BEFORE parsing (raw data is sacred, section 0.4), and reuses the
already-tested helpers `parse_serial_lines`, `unwrap_micros`, `assemble_triplets`
from process_throw and `mid_echo_sample_time_us` from corrections. It does NOT
duplicate any parsing/unwrap/assembly logic, and it does NOT gate or decide
IDLE/ACTIVE/CLOSING — that belongs to run_session.py + segmentation.ThrowDetector.

`stream_triplets` is a generator yielding one `Triplet` at a time as it arrives,
so the live loop can drive the state machine in real time. The input is any
iterable of raw byte-lines (the live port wrapped by `serial_byte_lines`, or a
list in tests), which keeps the module fully testable without hardware.

The authoritative post-CLOSING processing always re-runs from raw_serial.log via
process_throw.process_session; this module only captures that log and feeds the
live stop-trigger.
"""

from dataclasses import dataclass

import numpy as np

from pipeline.corrections import mid_echo_sample_time_us
from pipeline.process_throw import (
    assemble_triplets,
    parse_serial_lines,
    unwrap_micros,
)

# Below this many valid-looking CSV rows seen with no '# fw=' header, assume a
# headerless stream (e.g. a replayed log) rather than waiting forever. Real
# auto-reset garbage is not valid CSV, so it never trips this.
_HEADERLESS_AFTER = 6


def _default_warn(msg: str) -> None:
    print(f"ACQ WARNING: {msg}")


@dataclass(frozen=True)
class Triplet:
    """One assembled S1->S2->S3 triplet as it arrives off the wire."""
    index: int                # 0-based triplet counter within the session
    echo_us: np.ndarray       # (3,) int echo widths [us], 0 = timeout
    t_trig_us: np.ndarray     # (3,) TRIG timestamps [us], micros() rollover unwrapped
    t_sample_us: np.ndarray   # (3,) mid-echo sample instants t_trig + echo/2 (R3)


def log_and_decode(byte_lines, log_fh):
    """Write each raw byte-line VERBATIM to the open binary log, yield it decoded.

    The single verbatim-logging primitive (section 0.4): the log is flushed per
    line so a Ctrl-C mid-throw still leaves a complete, faithful capture on disk.
    """
    for raw in byte_lines:
        if isinstance(raw, str):
            raw = raw.encode("ascii", errors="replace")
        log_fh.write(raw)
        log_fh.flush()
        yield raw.decode("ascii", errors="replace")


def stream_triplets(byte_lines, log_fh, *, expected_header=None, warn=_default_warn):
    """Yield `Triplet`s from a raw byte-line stream, logging each line verbatim.

    expected_header : substring to verify in the '# fw=...' header (e.g.
        'slot_ms=18,timeout_us=12500'); a mismatch warns, never crashes.

    Header-gated start (the robust form of "discard the first ~20 auto-reset
    lines, then verify the header", section 5.1): everything before the first
    '# fw=' line is discarded; if no header ever appears but valid CSV does, we
    warn once and proceed headerless. Note: while waiting for a header this
    consumes the first `_HEADERLESS_AFTER - 1` valid CSV rows before giving up on
    finding one; this only affects the LIVE stop-trigger stream and has NO effect
    on offline reprocessing, which re-reads the full raw_serial.log separately
    (process_throw.process_session).

    Parsing/unwrap/assembly all reuse the process_throw helpers; assembly is
    keyed on each S1 reading and resynchronizes on the next S1 after an order
    violation (warned), exactly like the offline path.
    """
    pending = []          # list of (sid, echo, t_trig_raw) parsed rows
    raw_t = []            # parallel list of raw t_trig (for the unwrap)
    n_yielded = 0
    last_dropped = 0
    started = False
    data_without_header = 0

    for line in log_and_decode(byte_lines, log_fh):
        if not started:
            header, rows, _ = parse_serial_lines([line])
            if header is not None:
                started = True
                if expected_header is not None and expected_header not in header:
                    warn(f"fw header mismatch: got {header!r}, expected to "
                         f"contain {expected_header!r} — check the flashed firmware")
                continue
            if rows:                       # valid CSV before any header
                data_without_header += 1
                if data_without_header < _HEADERLESS_AFTER:
                    continue               # still hoping for a header
                warn("no '# fw=' header seen; proceeding headerless")
                started = True             # fall through and process THIS line
            else:
                continue                   # auto-reset garbage; discard

        _, rows, _ = parse_serial_lines([line])
        if not rows:
            continue
        pending.append(rows[0])
        raw_t.append(rows[0][2])

        # Only assemble the COMMITTED prefix up to the last S3 in the buffer:
        # assemble_triplets treats a trailing partial triplet (S1, or S1+S2 with
        # no S3 yet) as a dropped stray, so feeding it the in-progress tail would
        # report phantom drops. The committed prefix grows only by whole triplets
        # (plus genuine strays), so its `dropped` count is monotonic and real.
        last_s3 = next((k for k in range(len(pending) - 1, -1, -1)
                        if pending[k][0] == 3), -1)
        if last_s3 < 0:
            continue                       # no triplet can be completed yet

        commit = last_s3 + 1
        # Reuse the canonical unwrap + S1-keyed assembly (no duplicated logic).
        unwrapped = unwrap_micros(raw_t[:commit])
        rows_uw = [(pending[k][0], pending[k][1], int(unwrapped[k]))
                   for k in range(commit)]
        echo_arr, ttrig_arr, dropped = assemble_triplets(rows_uw)
        if dropped > last_dropped:
            warn(f"order violation: dropped {dropped - last_dropped} stray "
                 "reading(s), resyncing on next S1")
            last_dropped = dropped

        while n_yielded < echo_arr.shape[0]:
            e = echo_arr[n_yielded]
            tt = ttrig_arr[n_yielded]
            ts = mid_echo_sample_time_us(tt, e)
            yield Triplet(index=n_yielded, echo_us=e, t_trig_us=tt, t_sample_us=ts)
            n_yielded += 1


def raw_capture(byte_lines, log_fh, *, on_line=None, stop=None):
    """Verbatim-log every line, no parsing/gating (--raw-log; section 5.7).

    Generic enough for characterize_static.py (build item 14) to wrap: pass an
    `on_line(decoded_line)` callback to observe each line as it is logged, and an
    optional `stop()` predicate (checked AFTER each line, so on_line sees it
    first) to end a bounded capture without Ctrl-C. stop=None streams until the
    source is exhausted, which keeps the run_session --raw-log behaviour exact.
    """
    for line in log_and_decode(byte_lines, log_fh):
        if on_line is not None:
            on_line(line)
        if stop is not None and stop():
            break


def open_serial(config, port=None, baud=None):
    """Open the configured serial port (pyserial imported lazily; live-only)."""
    try:
        import serial
    except ImportError as exc:                       # pragma: no cover - hardware path
        raise RuntimeError(
            "pyserial not installed; `.\\venv\\Scripts\\python.exe -m pip install "
            "pyserial`") from exc
    acq = config["acquisition"]
    return serial.Serial(port or acq["port"], baud or acq["baud"], timeout=1.0)


def serial_byte_lines(ser):
    """Infinite generator of non-empty raw lines from a pyserial port.

    Read timeouts (empty reads) are skipped so the stream survives the idle gaps
    between echoes; the consumer decides when to stop (ThrowDetector CLOSED, or
    Ctrl-C). Live-only; tests pass a plain list of byte-lines instead.
    """
    while True:                                      # pragma: no cover - hardware path
        raw = ser.readline()
        if raw:
            yield raw
