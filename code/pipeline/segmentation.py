"""One-throw state machine (CLAUDE.md section 5.5, R5).

IDLE/ARMED -> ACTIVE when arm_M consecutive triplets are VALID; the arming
triplets are retroactively part of the throw (R5 — with only ~5-6 triplets
per throw and the last one consumed by the temporal correction, discarding
them would starve the fit). ACTIVE -> CLOSING when close_K consecutive
triplets are INVALID; the trailing K invalid triplets are stripped. One
session = one throw (section 0.3): scanning stops at the first close.

Mid-throw invalid triplets stay inside the buffer, flagged — never deleted
(section 0.4). The same ThrowDetector drives the live loop in run_session.py.

Pure logic, no I/O.
"""

from dataclasses import dataclass

import numpy as np

IDLE = "IDLE"
ACTIVE = "ACTIVE"
CLOSED = "CLOSED"


class ThrowDetector:
    """Incremental detector; feed per-triplet validity, read back the state."""

    def __init__(self, arm_M: int, close_K: int):
        if arm_M < 1 or close_K < 1:
            raise ValueError("arm_M and close_K must be >= 1")
        self.arm_M = arm_M
        self.close_K = close_K
        self.state = IDLE
        self.start: int | None = None    # first arming triplet (R5)
        self.end: int | None = None      # last triplet BEFORE the closing run
        self._n = 0
        self._valid_run = 0
        self._invalid_run = 0

    def update(self, valid: bool) -> str:
        if self.state == CLOSED:
            return self.state            # one throw only; ignore the rest
        idx = self._n
        self._n += 1
        if valid:
            self._valid_run += 1
            self._invalid_run = 0
        else:
            self._invalid_run += 1
            self._valid_run = 0

        if self.state == IDLE and self._valid_run >= self.arm_M:
            self.state = ACTIVE
            self.start = idx - self.arm_M + 1     # retroactive arming (R5)
        elif self.state == ACTIVE and self._invalid_run >= self.close_K:
            self.state = CLOSED
            self.end = idx - self.close_K         # strip the trailing K
        return self.state

    def flush(self) -> None:
        """End of stream: a still-ACTIVE throw closes at the last triplet
        (minus any trailing invalid run shorter than close_K)."""
        if self.state == ACTIVE:
            self.state = CLOSED
            self.end = self._n - 1 - self._invalid_run


@dataclass(frozen=True)
class ThrowSegment:
    start: int               # index of the first arming triplet (R5)
    end: int                 # index of the last in-throw triplet (inclusive)
    in_throw: np.ndarray     # (N,) bool flags over the full stream

    @property
    def n_triplets(self) -> int:
        return self.end - self.start + 1


def segment_throw(triplet_valid, arm_M: int, close_K: int) -> ThrowSegment | None:
    """Batch segmentation of one stream of per-triplet validity flags.

    Returns the single throw (R5 arming triplets included; mid-throw invalid
    triplets inside, flagged by the caller's validity array) or None when no
    throw was detected.
    """
    flags = np.asarray(triplet_valid, dtype=bool)
    det = ThrowDetector(arm_M, close_K)
    for v in flags:
        if det.update(bool(v)) == CLOSED:
            break
    det.flush()
    if det.state != CLOSED or det.start is None or det.end < det.start:
        return None
    in_throw = np.zeros(len(flags), dtype=bool)
    in_throw[det.start:det.end + 1] = True
    return ThrowSegment(start=det.start, end=det.end, in_throw=in_throw)
