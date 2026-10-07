"""Typed errors for the optical module (WO-OPT-1 Stage 5, audit Moderate finding).

Two failure classes must be distinguished so the pipeline never mistakes a
misconfiguration for an ordinary empty clip:

  * OpticalDataError  — the clip/data legitimately yields no landing (no ball, no
    trackable descent, too few frames). `run_clip_pipeline` CATCHES this and still writes
    a valid failure-mode artifact (`landing: null`, `no_prediction`).
  * OpticalConfigError — a configuration / calibration / camera-geometry failure (missing
    config block, degenerate homography, camera below the point, unreadable calibration
    file). This must PROPAGATE and kill the run — never be reported as a no-ball outcome.

Both subclass ValueError so existing callers and `pytest.raises(ValueError)` sites remain
valid; the distinction is which subclass is caught where.
"""

from __future__ import annotations


class OpticalError(ValueError):
    """Base for optical-module errors (subclasses ValueError for back-compatibility)."""


class OpticalDataError(OpticalError):
    """The data cannot yield a landing for a legitimate reason (no ball / no descent /
    too few frames). Caught by run_clip_pipeline as 'no prediction'."""


class OpticalConfigError(OpticalError):
    """A config / calibration / camera-geometry failure. Must propagate and kill the run,
    never be silently reported as an ordinary no-ball outcome."""
