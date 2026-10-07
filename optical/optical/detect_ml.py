"""Zero-shot ML ball detector — Zone 2 ONLY (Optical.md §10, Phase 6a/6b, Decision O17).

A second `Detector` (§5.2) behind the FROZEN `detect(frame) -> Detection | None` interface,
so it drops into the comparison harness and the downstream chain with ZERO changes anywhere
else. It uses a small pretrained YOLO-family model (config `ml_detector.model`, default
`yolo11n.pt`) via `ultralytics`, keeping only the COCO "sports ball" class (id 32) — genuine
zero-shot detection, no training and no labelling (§10).

ZONE DISCIPLINE (binding, §10): this module touches ball detection ONLY. It performs no
geometry/homography/parallax (Zone 1) and no contact/bounce identification (Zone 3); it emits
the same `Detection` the HSV baseline does and hands off to the identical downstream code.

DEPENDENCY GUARD (§0.1): `ultralytics`/`torch` are the one optional, gated dependency
(`requirements-ml.txt`). They are imported LAZILY, inside the constructor — importing THIS
module never imports them, so no core module is dragged into PyTorch at load time. If the
dependency is absent, instantiation raises a clear `MLDetectorUnavailable`, never a bare
`ImportError` surfacing from deep in a call stack.
"""

from __future__ import annotations

import numpy as np

from optical.detect import Detection

# COCO "sports ball" class id, per the standard 80-class COCO label map. Verified at runtime
# against `model.names` in the constructor (a clear error is raised on mismatch).
COCO_SPORTS_BALL = 32


class MLDetectorUnavailable(RuntimeError):
    """Raised when the optional ML stack (`ultralytics`/`torch`) is not installed, or the
    requested weights/class are unusable. Carries an actionable message (install
    `requirements-ml.txt`), so the failure is never a cryptic deep ImportError."""


class YoloDetector:
    """Zero-shot YOLO ball detector implementing the §5.2 `Detector` interface.

    Parameters
    ----------
    model : str
        Weights name/path passed to `ultralytics.YOLO` (default `models/yolo11n.pt`, a
        regenerable artifact — see the config comment). Configurable; auto-downloaded on first
        use if absent (ultralytics fetches the base weights by name).
    sports_ball_class : int
        COCO class id to keep (32 = "sports ball").
    conf : float
        Confidence threshold in [0, 1]; boxes below it are discarded.
    imgsz : int
        Inference image size (640 = YOLO11 training size; best on our frames — see config).
    """

    def __init__(self, model: str = "models/yolo11n.pt",
                 sports_ball_class: int = COCO_SPORTS_BALL,
                 conf: float = 0.25, imgsz: int = 640):
        try:
            from ultralytics import YOLO   # LAZY: absent -> caught -> clear error below
        except ImportError as exc:         # pragma: no cover - exercised via import-guard subprocess
            raise MLDetectorUnavailable(
                "The optional ML detector requires the `ultralytics` package (and PyTorch). "
                "Install it with:  .\\venv\\Scripts\\python.exe -m pip install -r requirements-ml.txt "
                "(Optical.md section 0.1/section 10). The core pipeline does not need it."
            ) from exc

        self.sports_ball_class = int(sports_ball_class)
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        try:
            self._model = YOLO(model)
        except Exception as exc:
            raise MLDetectorUnavailable(
                f"Failed to load ML weights '{model}': {exc}"
            ) from exc

        names = getattr(self._model, "names", {}) or {}
        if self.sports_ball_class in names and names[self.sports_ball_class] != "sports ball":
            raise MLDetectorUnavailable(
                f"class id {self.sports_ball_class} maps to '{names[self.sports_ball_class]}', "
                f"not 'sports ball', in weights '{model}' — check ml_detector.sports_ball_class."
            )
        self.model_name = model

    @classmethod
    def from_config(cls, config: dict) -> "YoloDetector":
        d = config["ml_detector"]
        return cls(model=d["model"], sports_ball_class=d["sports_ball_class"],
                   conf=d["conf"], imgsz=d["imgsz"])

    def detect(self, frame: np.ndarray) -> Detection | None:
        """Detect the ball in one BGR frame. Returns the highest-confidence sports-ball
        detection above the threshold, or None if there is none. `n_candidates` records how
        many sports-ball boxes cleared the threshold (>1 = ambiguous scene, mirroring HSV)."""
        results = self._model(frame, verbose=False, conf=self.conf, imgsz=self.imgsz,
                              classes=[self.sports_ball_class])
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        xyxy = boxes.xyxy.cpu().numpy()          # (n, 4) x1,y1,x2,y2
        confs = boxes.conf.cpu().numpy()         # (n,)
        n_candidates = int(len(confs))
        best = int(np.argmax(confs))
        x1, y1, x2, y2 = (float(v) for v in xyxy[best])
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            return None

        centroid = np.array([0.5 * (x1 + x2), 0.5 * (y1 + y2)])
        # Bottom-centre of the box ~ the drawn silhouette bottom the HSV lowest_px recovers
        # (box height ~ 2*r_px for a ball), keeping the parallax/contact feed detector-agnostic.
        lowest = np.array([0.5 * (x1 + x2), y2])
        radius = 0.25 * (w + h)                  # mean half-extent; ~ ball radius for a ~square box
        return Detection(
            centroid_px=centroid,
            bbox=(int(round(x1)), int(round(y1)), int(round(w)), int(round(h))),
            lowest_px=lowest,
            radius_px=float(radius),
            area_px=float(w * h),
            circularity=float("nan"),            # box detector has no contour; unused downstream
            n_candidates=n_candidates,
            confidence=float(confs[best]),
        )
