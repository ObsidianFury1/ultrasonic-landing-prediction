"""Ball detection — HSV baseline behind a swappable interface (Optical.md §5.2).

The interface is FROZEN: `detect(frame) -> Detection | None`. The Phase 6a/6b ML detector
(`optical/detect_ml.py`) plugs in behind the same signature without touching anything
downstream. This HSV baseline is permanent: it is also the diagnostic tool and the control
arm of the Phase 6a/6b comparison (Optical.md §10, split per Decision O17).

Chain: HSV threshold (basketball orange band, config-tunable) ->   # [v1.5/WO-OPT-4 D18]
morphological open/close -> contour extraction -> area band + circularity filter ->
largest plausible blob -> centroid + bounding box + lowest-pixel point.

Frames with no/ambiguous detection return None; the TRACK layer records these as
gaps with per-frame status flags — nothing is silently dropped (§5.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np


@dataclass
class Detection:
    """One per-frame ball detection."""
    centroid_px: np.ndarray      # (2,) intensity centroid of the accepted blob
    bbox: tuple                  # (x, y, w, h)
    lowest_px: np.ndarray        # (2,) lowest point of the blob (max image-v)
    radius_px: float             # min-enclosing-circle radius (size range cue, §5.5)
    area_px: float
    circularity: float           # 4*pi*A / P^2
    n_candidates: int            # blobs that passed the plausibility filters;
                                 # >1 = ambiguous scene, recorded as a confidence flag
    confidence: float | None = None
                                 # native detector confidence in [0,1] when the detector
                                 # produces one (the ML/Zone-2 detector, §10 Phase 6a).
                                 # None for the HSV baseline, which has no probabilistic
                                 # score. ADDITIVE, defaulted field (WO-OPT-2 Stage 1):
                                 # backward-compatible with every existing Detection(...)
                                 # call site, which uses keyword args and omits it.


class Detector(Protocol):
    """The swappable detector interface (§5.2). The Phase 6a/6b ML detector implements
    this too (`optical/detect_ml.py`)."""

    def detect(self, frame: np.ndarray) -> Detection | None: ...


class HsvDetector:
    """HSV-threshold baseline detector (§5.2).

    Optional second (hsv_lower2, hsv_upper2) range (checklist C6, 2026-07-11 real-footage
    finding): OpenCV hue is circular (0-179, red at both ends), and the REAL basketball's
    hue turned out to straddle that wraparound point (measured cluster: ~85% of bright
    pixels in [0,10), ~15% in [170,180), essentially none between) -- a single hsv_lower/
    upper range cannot express that band. When hsv_lower2 is given, the mask is the UNION
    of both ranges. None (default) preserves the original single-range behaviour exactly,
    so every existing call site/config is unaffected."""

    def __init__(self, hsv_lower, hsv_upper, min_area_px: float, max_area_px: float,
                 min_circularity: float, hsv_lower2=None, hsv_upper2=None):
        self.hsv_lower = np.asarray(hsv_lower, dtype=np.uint8)
        self.hsv_upper = np.asarray(hsv_upper, dtype=np.uint8)
        self.hsv_lower2 = np.asarray(hsv_lower2, dtype=np.uint8) if hsv_lower2 is not None else None
        self.hsv_upper2 = np.asarray(hsv_upper2, dtype=np.uint8) if hsv_upper2 is not None else None
        self.min_area_px = float(min_area_px)
        self.max_area_px = float(max_area_px)
        self.min_circularity = float(min_circularity)

    @classmethod
    def from_config(cls, config: dict) -> "HsvDetector":
        d = config["detect"]
        return cls(d["hsv_lower"], d["hsv_upper"], d["min_area_px"],
                   d["max_area_px"], d["min_circularity"],
                   hsv_lower2=d.get("hsv_lower2"), hsv_upper2=d.get("hsv_upper2"))

    def mask(self, frame: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
        if self.hsv_lower2 is not None:
            m2 = cv2.inRange(hsv, self.hsv_lower2, self.hsv_upper2)
            m = cv2.bitwise_or(m, m2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        return m

    def detect(self, frame: np.ndarray) -> Detection | None:
        mask = self.mask(frame)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        candidates = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (self.min_area_px <= area <= self.max_area_px):
                continue
            # Circularity is measured on the CONVEX HULL, not the raw contour (C7 field
            # finding, 2026-07-11): a real basketball's dark seam lines and a shadowed
            # underside carve concave notches into the mask, which inflate the raw
            # contour's perimeter and can crater circularity below any reasonable
            # threshold for a genuinely round, correctly-detected ball (measured case:
            # raw circ 0.44 vs hull circ 0.98 on the same 13.5k-px^2 blob). The hull
            # recovers the true round-object shape while remaining sensitive to
            # genuinely non-round blobs (elongated smudges, multi-blob merges).
            hull = cv2.convexHull(c)
            hull_perim = cv2.arcLength(hull, closed=True)
            if hull_perim <= 0:
                continue
            hull_area = cv2.contourArea(hull)
            circularity = 4.0 * np.pi * hull_area / (hull_perim * hull_perim)
            if circularity < self.min_circularity:
                continue
            candidates.append((area, circularity, c))
        if not candidates:
            return None

        area, circularity, contour = max(candidates, key=lambda t: t[0])
        m = cv2.moments(contour)
        if m["m00"] <= 0:
            return None
        centroid = np.array([m["m10"] / m["m00"], m["m01"] / m["m00"]])
        pts = contour.reshape(-1, 2)
        v_max = pts[:, 1].max()
        bottom = pts[pts[:, 1] == v_max]
        lowest = np.array([bottom[:, 0].mean(), float(v_max)])
        (_, _), radius = cv2.minEnclosingCircle(contour)
        return Detection(centroid_px=centroid,
                         bbox=tuple(cv2.boundingRect(contour)),
                         lowest_px=lowest, radius_px=float(radius),
                         area_px=float(area), circularity=float(circularity),
                         n_candidates=len(candidates))


def localisation_scatter(frames: list[np.ndarray], detector: Detector) -> dict:
    """Detector characterisation on static-ball frames (§7 item 3, checklist C6):
    per-axis scatter (ddof=1) of the detected centroid, in px, plus detection rate.
    Feeds the pixel-localisation term of the uncertainty budget."""
    centroids = []
    for frame in frames:
        det = detector.detect(frame)
        if det is not None:
            centroids.append(det.centroid_px)
    if len(centroids) < 2:
        return {"n_frames": len(frames), "n_detected": len(centroids),
                "sigma_u_px": float("nan"), "sigma_v_px": float("nan"),
                "sigma_px": float("nan")}
    arr = np.array(centroids)
    su = float(np.std(arr[:, 0], ddof=1))
    sv = float(np.std(arr[:, 1], ddof=1))
    return {"n_frames": len(frames), "n_detected": len(centroids),
            "sigma_u_px": su, "sigma_v_px": sv,
            "sigma_px": float(np.sqrt(0.5 * (su * su + sv * sv)))}
