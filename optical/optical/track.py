"""Tracking and descent segmentation (Optical.md §5.3).

Nearest-neighbour association across frames — one ball, high frame rate, nothing
heavier needed — with a max-jump gate, then identification of the final descent
segment ending at the FIRST vertical-motion reversal (bounce) or track end (the
ball leaves the scene / vanishes at contact).

Per-frame status is recorded, never silently dropped (§5.2):
  'ok'            - detection accepted into the track
  'none'          - detector returned None (gap)
  'jump_rejected' - detection exceeded the (gap-scaled) max-jump gate
  'ambiguous'     - accepted, but >1 plausible blob was present that frame
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical.detect import Detection
from optical.errors import OpticalDataError


@dataclass
class Track:
    times: np.ndarray          # (N,) seconds
    centroid_px: np.ndarray    # (N,2), NaN on gaps
    lowest_px: np.ndarray      # (N,2), NaN on gaps
    status: list               # (N,) per-frame status strings (see module docstring)
    radius_px: np.ndarray | None = None   # (N,), NaN on gaps; size range cue (§5.5)

    def __post_init__(self):
        if self.radius_px is None:
            self.radius_px = np.full(len(self.times), np.nan)

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.centroid_px[:, 0])

    @property
    def n_valid(self) -> int:
        return int(self.valid.sum())


def build_track(detections: list, times, max_jump_px: float) -> Track:
    """Associate per-frame detections into one track.

    The jump gate scales with the gap length: after g missed frames the ball may
    legitimately have moved ~g times farther, so the gate is max_jump_px * (g + 1).
    A rejected detection is recorded as 'jump_rejected' and treated as a gap
    (the anchor position is kept — a single flier cannot steal the track).
    """
    times = np.asarray(times, dtype=float)
    n = len(detections)
    if n != len(times):
        raise ValueError(f"{n} detections vs {len(times)} timestamps")

    centroids = np.full((n, 2), np.nan)
    lowests = np.full((n, 2), np.nan)
    radii = np.full(n, np.nan)
    status: list[str] = []
    last_pos: np.ndarray | None = None
    last_idx = -1

    for i, det in enumerate(detections):
        if det is None:
            status.append("none")
            continue
        if not isinstance(det, Detection):
            raise TypeError(f"frame {i}: expected Detection | None, got {type(det)}")
        if last_pos is not None:
            gap = i - last_idx
            if np.linalg.norm(det.centroid_px - last_pos) > max_jump_px * gap:
                status.append("jump_rejected")
                continue
        centroids[i] = det.centroid_px
        lowests[i] = det.lowest_px
        radii[i] = det.radius_px
        status.append("ambiguous" if det.n_candidates > 1 else "ok")
        last_pos = det.centroid_px
        last_idx = i

    return Track(times=times, centroid_px=centroids, lowest_px=lowests,
                 status=status, radius_px=radii)


@dataclass
class DescentSegment:
    indices: np.ndarray        # frame indices of the descent window, ascending
    end_reason: str            # 'reversal' (bounce seen) | 'track_end' (ball gone)
    flags: list
    reversal_index: int | None = None   # frame index of the image-v maximum (contact)
    apex_indices: np.ndarray | None = None  # valid frames bracketing the reversal, for
                                            # the sub-frame v-apex contact fit (§5.5)


def _reversal_confirmed(v: np.ndarray, k: int, min_rise: int) -> bool:
    """A candidate reversal at step k (v[k] <= v[k-1] after a rising run) is CONFIRMED
    only if the next `min_rise` steps (k .. k+min_rise-1) are all non-increasing AND the
    net change over them is a strict decrease (rejects a flat noise plateau). A single
    noisy non-increase inside a genuine descent fails confirmation and must not end the
    window (WO-OPT-1 Stage 4.4)."""
    if k + min_rise - 1 > len(v) - 1:
        return False                      # not enough frames left to confirm
    steps = [v[j] <= v[j - 1] for j in range(k, k + min_rise)]
    return all(steps) and v[k + min_rise - 1] < v[k - 1]


def find_descent(track: Track, window: int, min_run: int = 3,
                 apex_half: int = 4, min_rise: int = 2) -> DescentSegment:
    """Find the final descent: the last `window` valid frames of monotonically
    increasing image-v (image-down = physically descending) before the FIRST
    CONFIRMED vertical-motion reversal or the end of the track (§5.3). When a
    reversal (bounce) is seen, also return `apex_indices` — a symmetric window of
    valid frames around the image-v maximum — for the §5.5 sub-frame contact solve.

    min_rise (config `track.min_rise`, default 2): a reversal is declared only after
    `min_rise` consecutive non-increasing image-v steps with a net strict decrease —
    a single-frame noise dip cannot fake a touchdown (WO-OPT-1 Stage 4.4). Default 2:
    a genuine rebound at 240-480 fps descends in image-v for many frames, so two
    consecutive confirmations cost nothing real while single-frame noise (the only
    plausible false trigger at the ~5-15 px/frame near-contact image speeds) is ruled
    out.

    Raises ValueError (clean failure, no fabricated landing) when there is no
    usable descending run — e.g. the no-ball negative control.
    """
    vidx = np.flatnonzero(track.valid)
    if len(vidx) < min_run + 1:
        raise OpticalDataError(f"no ball track: only {len(vidx)} valid detections - "
                               f"cannot segment a descent (no landing is reported)")

    v = track.centroid_px[vidx, 1]

    # First CONFIRMED reversal AFTER a rising run of >= min_run steps (first
    # touchdown, not any later bounce apex; §5.3 takes the FIRST reversal).
    end_k = len(vidx) - 1
    reason = "track_end"
    rising = 0
    for k in range(1, len(vidx)):
        if v[k] > v[k - 1]:
            rising += 1
        else:
            if rising >= min_run and _reversal_confirmed(v, k, min_rise):
                end_k = k - 1
                reason = "reversal"
                break
            rising = 0

    # Walk back from the descent end while v is rising; tolerate an ISOLATED
    # single-frame dip (v[start_k] > v[start_k-2] steps over it) so one noisy
    # non-increase partway through a genuine descent does not truncate the window
    # (WO-OPT-1 Stage 4.4/4.5).
    start_k = end_k
    while start_k > 0:
        if v[start_k] > v[start_k - 1]:
            start_k -= 1
        elif start_k > 1 and v[start_k] > v[start_k - 2]:
            start_k -= 2
        else:
            break
    run = vidx[start_k:end_k + 1]
    if len(run) < min_run + 1:
        raise OpticalDataError(f"no usable descent: longest final descending run has "
                               f"{len(run)} frames (need >= {min_run + 1})")

    flags = []
    if len(run) > window:
        run = run[-window:]
    else:
        flags.append("low_frame_count")

    reversal_index = None
    apex_indices = None
    if reason == "reversal":
        reversal_index = int(vidx[end_k])
        lo, hi = max(end_k - apex_half, 0), min(end_k + apex_half + 1, len(vidx))
        apex_indices = vidx[lo:hi]

    return DescentSegment(indices=run, end_reason=reason, flags=flags,
                          reversal_index=reversal_index, apex_indices=apex_indices)
