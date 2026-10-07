"""Synthetic scene renderer with exact, known ground truth (Optical.md §6).

Everything here is ANALYTIC first: the camera model, the floor homography and the
ball trajectory are constructed in closed form, and only then are frames rasterised
to match them. The tests validate the rasterisation against the analytic projections
to sub-pixel precision, so downstream phases may treat the truth fields of
`SimulationResult` as exact ground truth.

Conventions:
  * World frame = the array frame of Optical.md §2 (origin at centroid on the floor,
    +x toward S1, +y up, +z completing the right-handed set).
  * Camera frame = OpenCV convention (+Z along the optical axis, +X image-right,
    +Y image-down).
  * The floor homography H maps homogeneous floor coordinates (x, z, 1) -> pixel
    (u, v, 1). For a world point p = (x, 0, z):  p_cam = R p + t = x R[:,0] + z R[:,2] + t,
    hence H = K [R[:,0] | R[:,2] | t].

Rasterisation notes (judgment calls, recorded in IMPLEMENTATION_NOTES_OPTICAL.md):
  * Discs/circles are drawn with OpenCV's fixed-point `shift` parameter so centres are
    placed with 1/16-px resolution; the centroid of a drawn disc is its analytic centre
    to well under 0.1 px.
  * The ball (a sphere) is drawn as a filled circle of radius f*r_ball/depth centred at
    the projection of the sphere centre. The true perspective image of a sphere is a
    slightly offset ellipse; the discrepancy is far sub-pixel at this geometry and the
    recorded truth is, by definition, what was drawn.
  * After first contact the ball is not drawn (no bounce is modelled in v1); the truth
    arrays carry NaN there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import yaml

GRAVITY = 9.81           # m/s^2
FLOOR_GRAY = 110         # background floor intensity (uint8)
SHADOW_GRAY = 60         # shadow blob intensity
_SHIFT = 4               # cv2 fixed-point sub-pixel shift (1/16 px)

ARUCO_DICT_NAME = "DICT_4X4_50"   # Optical.md §3.3


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("cannot normalize a zero vector")
    return v / n


_REPO_ROOT = Path(__file__).resolve().parents[1]

# Preferred synthetic saturation/value. Carried over unchanged from the tennis-era
# constant (S=200, V=230): the WO-OPT-1 Stage 6.5 invariant is about HUE, and the old
# band's S/V range (60-255) was never centred either. They are clamped into the config
# band below, so narrowing `detect.hsv_lower/upper` can never silently push the drawn
# ball out of the band it is supposed to sit inside.
_PREFERRED_SV = (200, 230)


@lru_cache(maxsize=None)
def _config(path: str | None = None) -> dict:
    """Load config.yaml once. Path is resolved from THIS file, not the cwd, so the
    simulator renders identically no matter where pytest is invoked from."""
    p = Path(path) if path is not None else _REPO_ROOT / "config.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def config_r_ball() -> float:
    """Ball radius [m] from config.yaml (`ball.radius_m`).

    [AMENDED v1.5 / WO-OPT-4 Stage 2 — Decision D17; was: a hardcoded 0.0335 default on
    `Scenario.r_ball` and on `render_static_scene`.] Reading it from config is what makes
    the substitution take effect in the simulator at all: the drawn radius is
    f*r_ball/depth, so a hardcoded default would have kept rendering a tennis ball into
    a basketball-configured pipeline."""
    return float(_config()["ball"]["radius_m"])


def basketball_bgr() -> tuple[int, int, int]:
    """Basketball orange as BGR, derived from the config.yaml detection band so it sits
    DEAD-CENTRE of that band in hue by construction.

    [AMENDED v1.5 / WO-OPT-4 Stage 2 — Decision D18; was: `basketball_bgr()`, a
    hardcoded HSV (35, 200, 230) matching the old yellow-green band H 25-45.] The hue is
    now COMPUTED from `detect.hsv_lower/upper` rather than hardcoded, so the invariant
    cannot silently rot the next time the band is retuned (e.g. at commissioning C6).

    NOTE (WO-OPT-1 Stage 6.5, preserved): this synthetic hue sits DEAD-CENTRE of the
    config HSV band by construction, so detection rates/scatter measured against
    synthetic frames are optimistic relative to real footage. Real HSV threshold tuning
    (against sun/shadow/ball wear) is a C6 commissioning task, not a software-correctness
    question (§5.2). This is exactly the "HSV-optimism caveat" the Phase 6a report must
    carry (§10) — it remains true for the orange band for the same structural reason it
    was true for the yellow-green one."""
    det = _config()["detect"]
    lo, hi = det["hsv_lower"], det["hsv_upper"]
    lo2, hi2 = det.get("hsv_lower2"), det.get("hsv_upper2")
    if lo2 is not None:
        # [AMENDED WO-OPT-4/C6 2026-07-11] Real-footage measurement found the basketball's
        # true hue straddles OpenCV's circular hue wraparound (0/179): the two-range band
        # [lo,hi] U [lo2,hi2] (e.g. [0,10] U [170,179]) has its centre INSIDE the wrap, not
        # at the arithmetic mean of lo[0]/hi[0] (which would land on the opposite side of
        # the hue wheel). Centre = midpoint of the combined arc, treating [lo2[0],179] U
        # [0,hi[0]] as one contiguous span of (179-lo2[0]+1)+(hi[0]+1) steps.
        span_low = lo2[0] - 180   # e.g. 170 -> -10
        span_high = hi[0]         # e.g. 10
        h = int(round((span_low + span_high) / 2.0)) % 180
        in_band = (lo2[0] <= h <= 179) or (0 <= h <= hi[0])
    else:
        # Exact band centre in hue; rounded to the nearest integer OpenCV hue step. For the
        # shipped band [5, 20] the centre is 12.5 -> H=12 (0.5 step off centre, the closest
        # an integer hue can sit; harmless, and the band edges are 7.5 steps away).
        h = int(round((lo[0] + hi[0]) / 2.0))
        in_band = lo[0] <= h <= hi[0]
    s = int(min(max(_PREFERRED_SV[0], lo[1]), hi[1]))
    v = int(min(max(_PREFERRED_SV[1], lo[2]), hi[2]))
    if not (in_band and lo[1] <= s <= hi[1] and lo[2] <= v <= hi[2]):
        raise ValueError(                        # unreachable for any sane band; loud if not
            f"synthetic ball HSV ({h}, {s}, {v}) falls outside the config detection band "
            f"{lo}-{hi}"
            f"{f' / {lo2}-{hi2}' if lo2 is not None else ''}. The WO-OPT-1 Stage 6.5 "
            f"invariant (synthetic hue dead-centre of the band) is violated; fix "
            f"config.yaml `detect.hsv_lower/upper` (or hsv_lower2/upper2).")
    bgr = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


# --------------------------------------------------------------------------- #
# Camera model                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class CameraModel:
    """Pinhole camera: K intrinsics, R/t world->camera extrinsics, C = centre in world."""
    K: np.ndarray
    R: np.ndarray
    t: np.ndarray
    C: np.ndarray
    resolution: tuple[int, int]   # (width, height)


def make_camera(cam_pos, target, resolution, hfov_deg) -> CameraModel:
    """Build a look-at pinhole camera.

    fx = fy from the horizontal FOV; principal point at the image centre.
    Rotation rows are the camera axes expressed in world coordinates:
      z_cam = forward (toward target), x_cam = image-right, y_cam = image-down,
    right-handed (x_cam x y_cam = z_cam). If forward is parallel to world-up
    (nadir/zenith view), world +z is used as the fallback up reference.
    """
    C = np.asarray(cam_pos, dtype=float)
    target = np.asarray(target, dtype=float)
    w, h = resolution

    fx = (w / 2.0) / np.tan(np.radians(hfov_deg) / 2.0)
    K = np.array([[fx, 0.0, w / 2.0],
                  [0.0, fx, h / 2.0],
                  [0.0, 0.0, 1.0]])

    z_cam = _normalize(target - C)
    up = np.array([0.0, 1.0, 0.0])
    if np.linalg.norm(np.cross(z_cam, up)) < 1e-8:
        up = np.array([0.0, 0.0, 1.0])
    x_cam = _normalize(np.cross(z_cam, up))
    y_cam = np.cross(z_cam, x_cam)   # unit by construction

    R = np.vstack([x_cam, y_cam, z_cam])
    t = -R @ C
    return CameraModel(K=K, R=R, t=t, C=C, resolution=(w, h))


def project_points(cam: CameraModel, pts_world) -> np.ndarray:
    """Project (N,3) world points to (N,2) pixel coordinates (float)."""
    pts = np.atleast_2d(np.asarray(pts_world, dtype=float))
    p_cam = pts @ cam.R.T + cam.t
    if np.any(p_cam[:, 2] <= 1e-9):
        raise ValueError("point at or behind the camera plane")
    uvw = p_cam @ cam.K.T
    return uvw[:, :2] / uvw[:, 2:3]


def point_depth(cam: CameraModel, p_world) -> float:
    """Depth (camera-frame Z) of a single world point."""
    return float((cam.R @ np.asarray(p_world, dtype=float) + cam.t)[2])


def floor_homography(cam: CameraModel) -> np.ndarray:
    """Analytic floor-plane homography: (x, z, 1) on the floor -> (u, v, 1) pixels."""
    H = cam.K @ np.column_stack([cam.R[:, 0], cam.R[:, 2], cam.t])
    if abs(H[2, 2]) > 1e-12:
        H = H / H[2, 2]
    return H


def floor_to_pixel(H: np.ndarray, xz) -> np.ndarray:
    """Map (N,2) floor points (x, z) [m] through H to (N,2) pixels."""
    xz = np.atleast_2d(np.asarray(xz, dtype=float))
    ones = np.ones((xz.shape[0], 1))
    uvw = np.hstack([xz, ones]) @ H.T
    return uvw[:, :2] / uvw[:, 2:3]


def pixel_to_floor(H: np.ndarray, uv) -> np.ndarray:
    """Map (N,2) pixels through H^-1 back to (N,2) floor points (x, z) [m]."""
    uv = np.atleast_2d(np.asarray(uv, dtype=float))
    ones = np.ones((uv.shape[0], 1))
    xzw = np.hstack([uv, ones]) @ np.linalg.inv(H).T
    return xzw[:, :2] / xzw[:, 2:3]


# --------------------------------------------------------------------------- #
# Ball trajectory                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class Trajectory:
    """Drag-free parabolic flight of the ball CENTRE: p(t) = p0 + v0 t - 0.5 g t^2 y_hat."""
    p0: np.ndarray
    v0: np.ndarray
    g: float = GRAVITY

    def __post_init__(self):
        self.p0 = np.asarray(self.p0, dtype=float)
        self.v0 = np.asarray(self.v0, dtype=float)

    def pos(self, t):
        t = np.asarray(t, dtype=float)
        acc = np.array([0.0, -self.g, 0.0])
        if t.ndim == 0:
            return self.p0 + self.v0 * float(t) + 0.5 * acc * float(t) ** 2
        return (self.p0[None, :] + np.outer(t, self.v0)
                + 0.5 * np.outer(t ** 2, acc))

    def contact_time(self, r_ball: float) -> float:
        """First contact: centre height reaches r_ball on the DESCENDING branch."""
        # p0y + v0y t - 0.5 g t^2 = r_ball
        a = -0.5 * self.g
        b = self.v0[1]
        c = self.p0[1] - r_ball
        disc = b * b - 4 * a * c
        if disc < 0:
            raise ValueError("trajectory never reaches contact height")
        roots = sorted([(-b + np.sqrt(disc)) / (2 * a), (-b - np.sqrt(disc)) / (2 * a)])
        t_star = roots[-1]   # later root = descending branch
        if t_star < 0:
            raise ValueError("contact lies in the past for this trajectory")
        return float(t_star)

    def contact_point_xz(self, r_ball: float) -> np.ndarray:
        p = self.pos(self.contact_time(r_ball))
        return np.array([p[0], p[2]])


# --------------------------------------------------------------------------- #
# Scenario description                                                         #
# --------------------------------------------------------------------------- #

@dataclass
class Scenario:
    """Complete description of a synthetic capture; factories live in scenarios.py."""
    name: str
    cam_pos: tuple = (3.5, 1.5, 0.0)
    cam_target: tuple = (0.4, 0.0, 0.0)
    resolution: tuple[int, int] = (640, 360)
    hfov_deg: float = 62.0
    fps_nominal: float = 480.0
    fps_measured: float = 479.82
    t_start: float = 0.0
    t_end: float = 0.2
    traj: Trajectory | None = None
    # [AMENDED v1.5 / WO-OPT-4 Stage 2 — D17; was: a hardcoded default of 0.0335.]
    # Config-driven so the simulator tracks `ball.radius_m` automatically. Still an
    # ordinary field: tests may pass r_ball= explicitly to pin a value.
    r_ball: float = field(default_factory=config_r_ball)
    restitution: float = 0.0         # first-bounce coefficient. DEFAULT 0.0 = the ball
                                     # is not drawn past first contact (the tracked
                                     # feature stops at touchdown; end_reason
                                     # 'track_end'). >0 renders a rebound arc (a
                                     # 'reversal'); see IMPLEMENTATION_NOTES Phase 3 for
                                     # why the reversal-apex is NOT used for sub-frame
                                     # timing (oblique image-v peak != world contact).
    markers_true: dict[int, tuple[float, float]] = field(default_factory=dict)
    survey_offsets: dict[int, tuple[float, float]] = field(default_factory=dict)
    held_out_id: int | None = None
    marker_size_m: float = 0.20
    fiducial_style: str = "aruco"        # "aruco" | "disc"
    noise_sigma: float = 0.0
    blur_len_px: int = 0
    shadow: bool = False
    contrast_alpha: float = 1.0          # 1.0 = nominal; <1 = low contrast
    dropout_frames: frozenset[int] = frozenset()
    seed: int = 0

    def markers_surveyed(self) -> dict[int, np.ndarray]:
        """Surveyed marker positions = true + injected survey error (negative control)."""
        out = {}
        for mid, xz in self.markers_true.items():
            off = self.survey_offsets.get(mid, (0.0, 0.0))
            out[mid] = np.array([xz[0] + off[0], xz[1] + off[1]])
        return out


# --------------------------------------------------------------------------- #
# Rasterisation                                                                #
# --------------------------------------------------------------------------- #

def ball_world_position(scenario: "Scenario", t: float) -> np.ndarray | None:
    """Ball CENTRE world position at time t, including the FIRST bounce (§5.3): the
    descending parabola until first contact, then the reflected arc (vy *= -e). Returns
    None once the ball reaches its SECOND contact (it has left the scene of interest) -
    the caller then stops drawing it, so the track exhibits exactly one clean reversal.
    """
    traj = scenario.traj
    tc = traj.contact_time(scenario.r_ball)
    if t <= tc:
        return traj.pos(t)
    p_c = traj.pos(tc)
    vy_impact = traj.v0[1] - traj.g * tc          # < 0 (descending)
    vyp = -scenario.restitution * vy_impact       # > 0 (rebound up)
    tau = t - tc
    y = scenario.r_ball + vyp * tau - 0.5 * traj.g * tau ** 2
    if y < scenario.r_ball and tau > 0:           # reached the second contact
        return None
    return np.array([p_c[0] + traj.v0[0] * tau, y, p_c[2] + traj.v0[2] * tau])


def _fixed(v: float) -> int:
    return int(round(v * (1 << _SHIFT)))


def _draw_disc(img, center_uv, radius_px, color):
    cv2.circle(img, (_fixed(center_uv[0]), _fixed(center_uv[1])),
               _fixed(max(radius_px, 1.0)), color, thickness=-1,
               lineType=cv2.LINE_AA, shift=_SHIFT)


def _aruco_dictionary():
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, ARUCO_DICT_NAME))


def _marker_floor_corners(xz, size_m, scale=1.0):
    """Floor-plane corners of a square of side size_m*scale centred at xz.
    Order: (-,-), (+,-), (+,+), (-,+) in (x, z)."""
    hx = size_m * scale / 2.0
    x, z = xz
    return np.array([[x - hx, z - hx], [x + hx, z - hx],
                     [x + hx, z + hx], [x - hx, z + hx]])


def _draw_aruco_marker(img, H, mid, xz, size_m):
    """Warp a real DICT_4X4_50 bitmap (with a white quiet zone) onto the floor plane."""
    marker_px = 96
    quiet = 24                      # white quiet zone so detection works on gray floor
    total = marker_px + 2 * quiet
    bitmap = cv2.aruco.generateImageMarker(_aruco_dictionary(), mid, marker_px)
    padded = np.full((total, total), 255, np.uint8)
    padded[quiet:quiet + marker_px, quiet:quiet + marker_px] = bitmap

    scale = total / marker_px       # quiet zone scales the floor footprint
    dst_floor = _marker_floor_corners(xz, size_m, scale=scale)
    dst_px = floor_to_pixel(H, dst_floor).astype(np.float32)
    src_px = np.array([[0, 0], [total - 1, 0],
                       [total - 1, total - 1], [0, total - 1]], np.float32)
    M = cv2.getPerspectiveTransform(src_px, dst_px)

    h_img, w_img = img.shape[:2]
    warped = cv2.warpPerspective(padded, M, (w_img, h_img),
                                 flags=cv2.INTER_LINEAR, borderValue=0)
    mask = cv2.warpPerspective(np.full((total, total), 255, np.uint8), M,
                               (w_img, h_img), flags=cv2.INTER_NEAREST, borderValue=0)
    sel = mask > 127
    for ch in range(3):
        img[:, :, ch][sel] = warped[sel]


def _draw_disc_fiducial(img, H, cam, xz, size_m):
    """Symmetric white disc centred at the marker's floor point (pure-projection gate)."""
    uv = floor_to_pixel(H, np.asarray(xz))[0]
    depth = point_depth(cam, np.array([xz[0], 0.0, xz[1]]))
    radius_px = max(cam.K[0, 0] * (size_m / 4.0) / depth, 4.0)
    _draw_disc(img, uv, radius_px, (255, 255, 255))


def _motion_blur_kernel(length_px: int, direction: np.ndarray) -> np.ndarray:
    k = max(int(length_px) | 1, 3)   # odd, >= 3
    kernel = np.zeros((k, k), np.float32)
    d = _normalize(direction) if np.linalg.norm(direction) > 1e-9 else np.array([1.0, 0.0])
    c = (k - 1) / 2.0
    p0 = (int(round(c - d[0] * c)), int(round(c - d[1] * c)))
    p1 = (int(round(c + d[0] * c)), int(round(c + d[1] * c)))
    cv2.line(kernel, p0, p1, 1.0, thickness=1)
    return kernel / kernel.sum()


def render_frame(scenario: Scenario, cam: CameraModel, H: np.ndarray, t: float,
                 rng: np.random.Generator
                 ) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Render one frame at time t.

    Returns (frame_bgr, ball_center_px (2,) or [nan,nan], ball_radius_px or nan,
    ball_bottom_px (2,) or [nan,nan]). `ball_bottom_px` is the PROJECTION OF THE
    SPHERE'S 3D BOTTOM POLE (centre - r_ball*y_hat) - the physically-correct contact
    feature (on the floor exactly at contact), distinct from the DRAWN silhouette
    bottom (centre_px + r_px) the detector recovers. The gap between them is the
    honest silhouette-vs-pole residual the §5.4 chalk cross-check exists to bound.
    Draw order: floor -> fiducials -> shadow -> ball -> contrast -> motion blur -> noise.
    """
    w, h = scenario.resolution
    img = np.full((h, w, 3), FLOOR_GRAY, np.uint8)

    for mid, xz in scenario.markers_true.items():
        if scenario.fiducial_style == "aruco":
            _draw_aruco_marker(img, H, mid, xz, scenario.marker_size_m)
        else:
            _draw_disc_fiducial(img, H, cam, xz, scenario.marker_size_m)

    ball_uv = np.array([np.nan, np.nan])
    ball_r_px = float("nan")
    ball_bottom_uv = np.array([np.nan, np.nan])
    vel_px = np.array([1.0, 0.0])

    if scenario.traj is not None:
        p = ball_world_position(scenario, t)
        if p is not None:
            if scenario.shadow:
                shadow_xz = np.array([p[0] + 0.05, p[2] + 0.05])
                s_uv = floor_to_pixel(H, shadow_xz)[0]
                depth_s = point_depth(cam, np.array([shadow_xz[0], 0.0, shadow_xz[1]]))
                r_s = cam.K[0, 0] * scenario.r_ball / depth_s
                cv2.ellipse(img, (_fixed(s_uv[0]), _fixed(s_uv[1])),
                            (_fixed(r_s * 1.4), _fixed(r_s * 0.7)), 0, 0, 360,
                            (SHADOW_GRAY,) * 3, -1, cv2.LINE_AA, shift=_SHIFT)
            ball_uv = project_points(cam, p)[0]
            depth = point_depth(cam, p)
            ball_r_px = float(cam.K[0, 0] * scenario.r_ball / depth)
            # true 3D bottom pole (touches the floor exactly at contact)
            ball_bottom_uv = project_points(
                cam, p - np.array([0.0, scenario.r_ball, 0.0]))[0]
            _draw_disc(img, ball_uv, ball_r_px, basketball_bgr())
            # projected velocity direction, for the motion-blur kernel
            dt = 1e-3
            p2 = ball_world_position(scenario, t + dt)
            if p2 is not None and point_depth(cam, p2) > 1e-6:
                vel_px = project_points(cam, p2)[0] - ball_uv

    if scenario.contrast_alpha != 1.0:
        img = np.clip(scenario.contrast_alpha * (img.astype(np.float32) - 128.0) + 128.0,
                      0, 255).astype(np.uint8)
    if scenario.blur_len_px > 0:
        img = cv2.filter2D(img, -1, _motion_blur_kernel(scenario.blur_len_px, vel_px))
    if scenario.noise_sigma > 0:
        noise = rng.normal(0.0, scenario.noise_sigma, img.shape)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    return img, ball_uv, ball_r_px, ball_bottom_uv


# --------------------------------------------------------------------------- #
# Sequence rendering                                                           #
# --------------------------------------------------------------------------- #

@dataclass
class SimulationResult:
    """Frames plus EXACT ground truth for every downstream validation."""
    scenario: Scenario
    cam: CameraModel
    H_true: np.ndarray
    frames: list                      # ndarray (h,w,3) or None (dropout)
    times: np.ndarray                 # (N,) seconds, from fps_measured
    ball_center_px: np.ndarray        # (N,2), NaN when ball absent/not drawn
    ball_radius_px: np.ndarray        # (N,), NaN likewise
    ball_bottom_px: np.ndarray        # (N,2), true 3D bottom-pole projection; NaN likewise
    ball_pos_world: np.ndarray        # (N,3), NaN rows likewise
    contact_time_s: float | None
    contact_xz: np.ndarray | None     # (2,) true landing point (x, z)
    markers_true: dict
    markers_surveyed: dict
    held_out_id: int | None


def render_static_scene(*, cam_pos, cam_target, resolution, hfov_deg,
                        ball_xz, r_ball=None, markers=None, marker_size_m=0.20,
                        n_frames=15, noise_sigma=2.0, seed=0, draw_ball=True):
    """Render N frames of a ball RESTING on the floor at ball_xz (centre at height
    r_ball), for the §8 static-point validation. Returns (frames, H_px2floor, cam,
    ball_uv_true). Markers (dict id->(x,z)) are drawn as ArUco fiducials if given.

    [AMENDED v1.5 / WO-OPT-4 Stage 2 — D17; was: `r_ball=0.0335`.] `r_ball=None` now
    means "read `ball.radius_m` from config.yaml". Passing an explicit value still pins
    it. This mattered: the §8 static-point validation is the commissioning GATE, and a
    hardcoded tennis radius here would have silently validated the wrong ball height.

    [ADDED v1.5 / WO-OPT-4 Stage 3.] `draw_ball=False` renders markers only — a HOMOGRAPHY
    CALIBRATION frame. §5.1 never required the ball to be present when fitting H, and the
    basketball (~x3.56 the tennis radius) is large enough to OCCLUDE a floor fiducial: at
    the static-validation layout it hides the held-out check point outright. `ball_uv_true`
    is still returned (the geometry is computed either way), it simply is not drawn."""
    if r_ball is None:
        r_ball = config_r_ball()
    cam = make_camera(cam_pos, cam_target, resolution, hfov_deg)
    H = floor_homography(cam)
    rng = np.random.default_rng(seed)
    centre = np.array([ball_xz[0], r_ball, ball_xz[1]])
    ball_uv = project_points(cam, centre)[0]
    r_px = float(cam.K[0, 0] * r_ball / point_depth(cam, centre))

    frames = []
    for _ in range(n_frames):
        w, h = resolution
        img = np.full((h, w, 3), FLOOR_GRAY, np.uint8)
        if markers:
            for mid, xz in markers.items():
                _draw_aruco_marker(img, H, mid, xz, marker_size_m)
        if draw_ball:
            _draw_disc(img, ball_uv, r_px, basketball_bgr())
        if noise_sigma > 0:
            img = np.clip(img.astype(np.float32)
                          + rng.normal(0, noise_sigma, img.shape), 0, 255).astype(np.uint8)
        frames.append(img)
    return frames, np.linalg.inv(H), cam, ball_uv


def render_sequence(scenario: Scenario) -> SimulationResult:
    """Render the whole scenario. Dropout frames are None; truth arrays stay filled
    (the ball's true state exists whether or not the frame was delivered)."""
    cam = make_camera(scenario.cam_pos, scenario.cam_target,
                      scenario.resolution, scenario.hfov_deg)
    H = floor_homography(cam)
    rng = np.random.default_rng(scenario.seed)

    n = int(round((scenario.t_end - scenario.t_start) * scenario.fps_measured)) + 1
    times = scenario.t_start + np.arange(n) / scenario.fps_measured

    frames: list = []
    centers = np.full((n, 2), np.nan)
    radii = np.full(n, np.nan)
    bottoms = np.full((n, 2), np.nan)
    pos_world = np.full((n, 3), np.nan)

    contact_time = None
    contact_xz = None
    if scenario.traj is not None:
        contact_time = scenario.traj.contact_time(scenario.r_ball)
        contact_xz = scenario.traj.contact_point_xz(scenario.r_ball)

    for i, t in enumerate(times):
        frame, ball_uv, ball_r, ball_bottom = render_frame(
            scenario, cam, H, float(t), rng)
        if scenario.traj is not None:
            p = ball_world_position(scenario, float(t))
            if p is not None:
                pos_world[i] = p
        centers[i] = ball_uv
        radii[i] = ball_r
        bottoms[i] = ball_bottom
        frames.append(None if i in scenario.dropout_frames else frame)

    return SimulationResult(
        scenario=scenario, cam=cam, H_true=H, frames=frames, times=times,
        ball_center_px=centers, ball_radius_px=radii, ball_bottom_px=bottoms,
        ball_pos_world=pos_world,
        contact_time_s=contact_time, contact_xz=contact_xz,
        markers_true={k: np.asarray(v, float) for k, v in scenario.markers_true.items()},
        markers_surveyed=scenario.markers_surveyed(),
        held_out_id=scenario.held_out_id,
    )
