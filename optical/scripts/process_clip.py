"""Process one throw clip -> optical_gt.json + landing_overlay.png (+ manifest).

I/O orchestrator (§5, §5.6, §9): the pure pipeline modules do the maths; this script
loads the clip, runs detect -> track -> descent -> contact -> uncertainty, builds the
frozen-schema optical_gt, writes it atomically, renders the overlay, prints the
terminal summary, and appends the manifest entry.

Usage:
  .\\venv\\Scripts\\python.exe scripts\\process_clip.py ^
      --session data\\optical\\2026-07-18_T03 --calib calib\\homography_2026-07-18_A.yaml ^
      --intrinsics calib\\intrinsics_720p480.yaml --mode 720p480 --in 120 --out 180

The testable core is `run_clip_pipeline` (frames in -> optical_gt dict out, headless).
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical import calibration as cal          # noqa: E402
from optical import io_session                  # noqa: E402
from optical import overlay as ov               # noqa: E402
from optical import uncertainty as unc          # noqa: E402
from optical.contact import fit_contact         # noqa: E402
from optical.detect import HsvDetector          # noqa: E402
from optical.errors import OpticalConfigError, OpticalDataError  # noqa: E402
from optical.geometry import CameraGeometry, load_config  # noqa: E402
from optical.track import build_track, find_descent       # noqa: E402


def _quality_flags(track, descent, contact, ambiguous_threshold: int = 2) -> list:
    """Map pipeline state onto the §5.6 quality.flags vocabulary.

    FAIL-LOUD (WO-OPT-3 Stage 3, Decision D12): producer flags from `descent`/`contact` are
    passed through UNFILTERED — the old `if f in io_session.FLAG_VOCAB` filter silently dropped
    an out-of-vocabulary flag (a future producer typo would just vanish). `build_optical_gt` is
    now the SOLE authority: it raises `ValueError` on any unknown flag at write time, so a typo
    kills the run loudly instead of being lost."""
    flags = set()
    if any(s in ("none", "jump_rejected") for s in track.status):
        flags.add("detection_gaps")
    # Persistent detection AMBIGUITY within the descent window (>1 plausible blob on a
    # frame, §5.2) also degrades the landing feature. A single ambiguous frame is common
    # (a transient reflection), so flag only a SUSTAINED run (>= ambiguous_threshold, default
    # 2) — and reuse `detection_gaps` rather than invent a flag (Stage 6.3).
    if descent is not None:
        amb = sum(track.status[i] == "ambiguous" for i in descent.indices
                  if 0 <= i < len(track.status))
        if amb >= ambiguous_threshold:
            flags.add("detection_gaps")
    if descent is not None:
        flags.update(descent.flags)
    if contact is not None:
        flags.update(contact.flags)
    return sorted(flags)


def run_clip_pipeline(frames, times, config, H_px2floor, camera: CameraGeometry,
                      *, clip_meta: dict, calib_meta: dict, session_id: str,
                      notes: str = "", extra_flags=None) -> tuple[dict, object, object]:
    """Headless core (fully unit-tested). Returns (optical_gt, track, contact).
    On no-prediction (no ball / no descent / < min_fit_points), returns a valid
    FAILURE-mode optical_gt (landing null, 'no_prediction' flag) — never raises for a
    data-shape problem, so a bad clip still produces a readable artifact.

    extra_flags: quality.flags determined by the CALLER (main) rather than the pipeline
    itself — e.g. `fps_mismatch` (§3.2, decided from the container/nominal/CLI rates in
    main). Merged into the output flags; must be in io_session.FLAG_VOCAB."""
    r_ball = float(config["ball"]["radius_m"])
    ucfg = unc.read_uncertainty_config(config)   # hard error if the block is missing (M1)
    scfg = unc.read_survey_sigma(config)         # hard error if markers.survey_sigma_m malformed
                                                 # (WO-OPT-3 Stage 3 / D11); folds into the
                                                 # unmeasured-component machinery below
    detector = HsvDetector.from_config(config)
    detections = [detector.detect(f) if f is not None else None for f in frames]
    track = build_track(detections, times,
                        max_jump_px=float(config["track"]["max_jump_px"]))

    method = {"detector": "hsv", "parallax": "analytic_centroid"}
    contact = None
    descent = None
    landing_xz = None
    try:
        descent = find_descent(track, window=int(config["track"]["descent_window_frames"]),
                               min_rise=int(config["track"].get("min_rise", 2)))
        contact = fit_contact(track, descent, H_px2floor, r_ball,
                              float(clip_meta["fps_measured"]), camera=camera)
        landing_xz = contact.landing_xz
        method["parallax"] = contact.method
    except OpticalDataError as exc:
        # ONLY a legitimate data-shape failure becomes 'no prediction'. An
        # OpticalConfigError (degenerate homography, camera-below-point, etc.) is NOT
        # caught here — it propagates and kills the run rather than masquerading as an
        # empty clip (WO-OPT-1 Stage 5.1 / audit Moderate).
        notes = (notes + " | " if notes else "") + f"no prediction: {exc}"

    if landing_xz is not None:
        land_uv = _floor_to_pixel(H_px2floor, landing_xz)
        # Pre-parallax mapped point (what validate_static passes to build_budget): invert
        # the §5.4 correction  landing = P_mapped - (h/C_y)(P_mapped - C_ground), h = r_ball,
        # so P_mapped = (landing - k*C_ground)/(1 - k) with k = r_ball/C_y. Matches the
        # validate_static call site; C_y > r_ball is guaranteed (fit_contact already applied
        # parallax_correct, whose own guard would have raised otherwise).
        k = r_ball / float(camera.C[1])
        C_ground = np.array([float(camera.C[0]), float(camera.C[2])])
        parallax_P_mapped = (np.asarray(landing_xz, dtype=float) - k * C_ground) / (1.0 - k)
        budget = unc.build_budget(
            landing_xz=landing_xz, landing_uv=land_uv, H_px2floor=H_px2floor,
            marker_survey_m=scfg["value"],
            reproj_rms_px=float(calib_meta.get("reproj_rms_px", 0.0)),
            check_point_err_m=float(calib_meta.get("check_point_err_m", 0.0)),
            sigma_px=float(ucfg["pixel_sigma_px"]),
            parallax_P_mapped=parallax_P_mapped, r_ball=r_ball, camera_C=camera.C,
            sigma_h_m=float(ucfg["sigma_h_m"]),
            sigma_C_m=tuple(float(v) for v in ucfg["sigma_C_m"]),
            vel_xz=contact.vel_xz, sigma_t_s=contact.sigma_t_s,
            rolling_shutter_m=float(ucfg["rolling_shutter_m"]))
        contact_block = {"t_frame": int(contact.t_frame),
                         "t_subframe": round(float(contact.t_subframe), 3),
                         "n_descent_frames": int(contact.n_descent_frames)}
        flags = _quality_flags(track, descent, contact)
        # WO-OPT-3 Stage 3 (D11): the survey sigma placeholder joins the four uncertainty-block
        # placeholders in the SAME unmeasured-component machinery (flag + warning + notes echo).
        unmeasured = list(ucfg["unmeasured"]) + scfg["unmeasured"]
        if unmeasured:
            flags = sorted(set(flags) | {"unmeasured_uncertainty_components"})
            warnings.warn(
                f"UNMEASURED UNCERTAINTY COMPONENTS {unmeasured}: the budget for "
                f"session '{session_id}' uses placeholder config values, not measurements "
                f"(section 7). Flip the named config entries' measured=true after C6.",
                UserWarning, stacklevel=2)
            notes = ((notes + " | " if notes else "")
                     + f"unmeasured uncertainty components: {unmeasured}")
    else:
        budget = {"sigma_x_m": None, "sigma_z_m": None, "sigma_r_m": None,
                  "sigma_theta_deg": None, "components": {}}
        contact_block = {"t_frame": None, "t_subframe": None,
                         "n_descent_frames": 0}
        flags = sorted(set(_quality_flags(track, descent, contact)) | {"no_prediction"})

    if extra_flags:
        flags = sorted(set(flags) | set(extra_flags))

    optical_gt = io_session.build_optical_gt(
        session_id=session_id, clip=clip_meta, calibration=calib_meta, method=method,
        landing_xz=landing_xz, uncertainty=budget, contact=contact_block,
        n_tracked_frames=track.n_valid, flags=flags, notes=notes)
    return optical_gt, track, contact


def _floor_to_pixel(H_px2floor, xz):
    from optical.calibration import apply_homography
    return apply_homography(np.linalg.inv(H_px2floor), xz)[0]


# --------------------------------------------------------------------------- #
# Homography stability re-check (§5.1 step 5; audit M3)                        #
# --------------------------------------------------------------------------- #

def check_point_xz(config, cp_id):
    """Surveyed floor (x, z) of the held-out check point from config, or None. Looks in
    markers.fit_points (by id) then markers.reference_marks (by label). Public so the
    validate_static gate runner reuses the same lookup (Stage 5.3)."""
    markers = config.get("markers", {}) or {}
    for entry in markers.get("fit_points", []) or []:
        if entry.get("id") == cp_id:
            return np.asarray(entry["xz"], dtype=float)
    marks = markers.get("reference_marks", {}) or {}
    if cp_id in marks:
        return np.asarray(marks[cp_id], dtype=float)
    return None


def evaluate_stability(frames, calib, config):
    """Run the section-5.1 step-5 re-check across the session: re-detect the held-out check
    point in the first and last usable frames and evaluate BOTH guards through the session's H
    (WO-OPT-3 Stage 1, Major 4.1) — drift (start-vs-end) AND absolute error (each frame vs the
    surveyed position), both against check_point_tol_m.

    Returns (flags, message): a LIST that may contain 'homography_drift' and/or
    'stability_abs_fail' (both already warned loudly inside cal.stability_check),
    ['stability_unchecked'] when the check could not be run (reported, never skipped
    silently), or [] when clean. Never raises."""
    usable = [f for f in frames if f is not None]
    if not usable:
        return ["stability_unchecked"], "no usable frames for the re-check"
    dict_name = (config.get("markers", {}) or {}).get("aruco_dict", "DICT_4X4_50")
    cp_xz = check_point_xz(config, calib.check_point_id)
    result, reason = cal.stability_between_frames(
        calib.H, usable[0], usable[-1], calib.check_point_id, cp_xz,
        float(calib.tol_m), dict_name)
    if reason is not None:
        return ["stability_unchecked"], reason
    flags = []
    if result.drifted:                         # cal.stability_check already warned loudly
        flags.append("homography_drift")
    if result.abs_fail:                        # cal.stability_check already warned loudly
        flags.append("stability_abs_fail")
    if not flags:
        return [], None
    msg = (f"check point: drift {result.drift_m * 1000:.1f} mm, abs err start "
           f"{result.err_start_m * 1000:.1f} / end {result.err_end_m * 1000:.1f} mm "
           f"across the session (tol {calib.tol_m * 1000:.1f} mm)")
    return flags, msg


# --------------------------------------------------------------------------- #
# Clip loading / trimming / manifest                                          #
# --------------------------------------------------------------------------- #

def read_container_fps(video_path):
    """Container-delivered frame rate via cv2.CAP_PROP_FPS (§3.2/§9). Returns a float, or
    None if unavailable — file won't open, or the read is non-positive / NaN (some OpenCV
    builds report 0 or garbage for certain codecs). Non-positive is treated as 'unavailable'
    rather than crashing, per the Stage 2 spec."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    finally:
        cap.release()
    if not np.isfinite(fps) or fps <= 0:
        return None
    return fps


def resolve_fps(fps_nominal, fps_container, fps_measured_arg, tol_pct, refuse_pct=20.0):
    """Decide the frame rate used for ALL timing math, and whether the rate sources
    disagree (§3.2, audit M2 + WO-OPT-3 Major 4.2). Returns (fps_used, mismatch, values).

    Precedence for the USED rate (UNCHANGED): `fps_measured_arg` (the C1 stopwatch-verified
    rate) > `fps_container` (if valid) > refuse. The nominal rate is NEVER used for timing —
    refusing rather than silently falling back to nominal is the whole point of M2.

    Two disagreement bands:
      * HARD REFUSE (`refuse_pct`, default 20 %, Decision D9): if the rate USED for timing
        disagrees with the NOMINAL rate by more than refuse_pct % of their mean, raise
        OpticalConfigError and write NOTHING. Backstop for a playback-rate container (e.g. a
        480 fps capture whose file reports 30 fps): with --fps-measured forgotten the used
        rate is a ~16x-wrong temporal base, and a plausible-looking-but-garbage landing must
        never be produced. A mistyped --fps-measured is caught the same way (it becomes the
        used rate). The comparison is USED-vs-NOMINAL, NOT every available pair: a container
        rate that has been correctly SUPERSEDED by --fps-measured is the EXPECTED slow-mo case
        (comparing it would refuse every real clip), so it only flags (below), never refuses —
        see the WO-OPT-3 Stage 2 judgment-call note in IMPLEMENTATION_NOTES_OPTICAL.md.
      * FLAG-AND-CONTINUE (`tol_pct`, Decision D2, UNCHANGED): mismatch = any two AVAILABLE
        values among {nominal, container, measured_arg} differ by more than tol_pct % of their
        mean -> `fps_mismatch` flag + warning, run completes."""
    values = {"fps_nominal": float(fps_nominal)}
    if fps_container is not None and fps_container > 0:
        values["fps_container"] = float(fps_container)
    if fps_measured_arg is not None and fps_measured_arg > 0:
        values["fps_measured_arg"] = float(fps_measured_arg)

    if "fps_measured_arg" in values:
        fps_used = values["fps_measured_arg"]
    elif "fps_container" in values:
        fps_used = values["fps_container"]
    else:
        raise OpticalConfigError(
            "no usable measured frame rate: pass --fps-measured (the C1 stopwatch-verified "
            "rate) or provide a clip whose container reports a valid fps. The nominal rate "
            "is deliberately NOT used for timing (Optical.md section 3.2 / audit M2).")

    # HARD-REFUSE band (WO-OPT-3 Major 4.2 / D9): the USED rate grossly disagreeing with
    # nominal means the temporal base is wrong (playback-rate container with --fps-measured
    # forgotten, or a mistyped --fps-measured). Refuse BEFORE any output is written.
    nominal = values["fps_nominal"]
    used_vs_nominal_pct = abs(fps_used - nominal) / ((fps_used + nominal) / 2.0) * 100.0
    if used_vs_nominal_pct > refuse_pct:
        raise OpticalConfigError(
            f"REFUSING to process: the frame rate used for timing ({fps_used:.4g} fps) "
            f"disagrees with the nominal rate ({nominal:.4g} fps) by {used_vs_nominal_pct:.1f}%"
            f" (> hard-refuse band {refuse_pct:.0f}%). This usually means a playback-rate "
            f"container (e.g. a 480 fps capture stored as 30 fps) with --fps-measured "
            f"forgotten, or a mistyped --fps-measured. Supply --fps-measured with the verified "
            f"capture rate (field checklist C1). No output has been written.")

    vals = list(values.values())
    mismatch = any(
        abs(vals[i] - vals[j]) / ((vals[i] + vals[j]) / 2.0) * 100.0 > tol_pct
        for i in range(len(vals)) for j in range(i + 1, len(vals)))
    return fps_used, mismatch, values


def load_clip_frames(video_path, in_frame=None, out_frame=None):
    """Read frames [in_frame, out_frame) from a video into a list of BGR arrays."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"could not open clip {video_path}")
    frames = []
    try:
        idx = 0
        start = in_frame or 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        idx = start
        while True:
            if out_frame is not None and idx >= out_frame:
                break
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
            idx += 1
    finally:
        cap.release()
    if not frames:
        raise ValueError(f"no frames read from {video_path} "
                         f"[{in_frame}:{out_frame}]")
    return frames


def write_trimmed(frames, out_path, fps):
    """Write an mp4v clip from (already undistorted) frames — a diagnostic
    `trimmed_undistorted.mp4`, undistorted and lossily re-encoded, NOT a verbatim trim of
    raw.mp4 (§9). raw.mp4 is never touched; prefer processing it directly with --in/--out."""
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()


def append_manifest(manifest_path, entry: dict):
    """Append/replace (by session_id) an entry in a day manifest (§9). The session_id
    already embeds the throw number per the §9 naming convention, so it is the dedup key."""
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"clips": []}
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {"clips": []}
    clips = [c for c in data.get("clips", [])
             if c.get("session_id") != entry.get("session_id")]
    clips.append(entry)
    data["clips"] = clips
    cal.atomic_write_text(manifest_path,
                          yaml.safe_dump(data, default_flow_style=False, sort_keys=False))


def write_session(session_dir, optical_gt, overlay_frame, track, contact, H_px2floor):
    """Write optical_gt.json + landing_overlay.png into the session directory."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    json_path = io_session.write_optical_gt(session_dir / "optical_gt.json", optical_gt)
    overlay_path = ov.save_overlay(session_dir / "landing_overlay.png", overlay_frame,
                                   track, contact, optical_gt, H_px2floor)
    return json_path, overlay_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True, help="session dir with raw.mp4")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--calib", required=True, help="homography_<id>.yaml")
    ap.add_argument("--intrinsics", default=None,
                    help="calib/intrinsics_<mode>.yaml (section 3.4). REQUIRED for a real run; "
                         "omitting it is a hard error unless --allow-fallback-intrinsics.")
    ap.add_argument("--allow-fallback-intrinsics", dest="allow_fallback",
                    action="store_true",
                    help="smoke-testing ONLY: build K from a 60-deg HFOV guess when "
                         "--intrinsics is absent. Emits a warning and flags every throw "
                         "'fallback_intrinsics'. Never use for a campaign.")
    ap.add_argument("--mode", default=None, help="video mode (else config default)")
    ap.add_argument("--in", dest="in_frame", type=int, default=None)
    ap.add_argument("--out", dest="out_frame", type=int, default=None)
    ap.add_argument("--fps-measured", dest="fps_measured", type=float, default=None,
                    help="C1 stopwatch-verified delivered frame rate [fps]; overrides the "
                         "container-read rate for all timing math (section 3.2). The nominal "
                         "is never used for timing.")
    ap.add_argument("--notes", default="")
    ap.add_argument("--manifest-dir", dest="manifest_dir", default=None,
                    help="directory for the day manifest (default: data/manifests under the "
                         "project root). Additive override; omit for the normal location.")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    session_dir = Path(args.session)
    session_id = session_dir.name
    mode = args.mode or config["capture"]["default_mode"]
    fps_nominal = float(config["capture"]["modes"][mode]["fps_nominal"])

    # Real delivered rate (§3.2 / M2): read the container, then apply the precedence
    # --fps-measured > container > refuse. Never copy nominal into fps_measured.
    raw = session_dir / "raw.mp4"
    fps_container = read_container_fps(raw)
    tol_pct = float(config["capture"].get("fps_tol_pct", 0.5))
    refuse_pct = float(config["capture"].get("fps_refuse_pct", 20.0))
    # resolve_fps raises OpticalConfigError on a gross used-vs-nominal gap (WO-OPT-3 Major 4.2):
    # this is upstream of every write, so a refuse leaves no optical_gt.json and no manifest.
    fps_used, fps_mismatch, fps_values = resolve_fps(
        fps_nominal, fps_container, args.fps_measured, tol_pct, refuse_pct)
    extra_flags = []
    if fps_mismatch:
        extra_flags.append("fps_mismatch")
        warnings.warn(
            f"FPS MISMATCH for session '{session_id}': rate sources disagree beyond "
            f"{tol_pct:.2f}% - {fps_values}. Using {fps_used:.4f} fps for timing "
            f"(precedence --fps-measured > container). Verify the transfer did not "
            f"re-encode the clip (Optical.md section 3.2/section 9).", UserWarning, stacklevel=2)

    calib = cal.load_homography_yaml(args.calib)
    intr = cal.load_intrinsics(args.intrinsics) if args.intrinsics else None
    K, fb_flag = resolve_camera_K(intr, args.allow_fallback, config, mode, session_id)
    if fb_flag:
        extra_flags.append(fb_flag)
    camera = CameraGeometry.from_homography(calib.H, K)

    # cond_warn and any other calibration-level flag in the throw vocabulary propagate to
    # every throw made with this calibration (Stage 5.4).
    extra_flags += [f for f in calib.flags if f in io_session.FLAG_VOCAB]

    frames = load_clip_frames(raw, args.in_frame, args.out_frame)
    frames = [cal.undistort_frame(f, intr) for f in frames]
    if args.in_frame is not None:
        # undistorted + lossily re-encoded, NOT a verbatim trim of raw.mp4 (§9): named to
        # say so. raw.mp4 stays sacred; prefer processing it with --in/--out directly.
        write_trimmed(frames, session_dir / "trimmed_undistorted.mp4", fps_used)

    # section-5.1 step-5 re-check (audit M3 + WO-OPT-3 Major 4.1): every run either checks and
    # reports (drift AND absolute check-point error), or explicitly flags that it could not —
    # silent absence of the check is not possible.
    stab_flags, stab_msg = evaluate_stability(frames, calib, config)
    extra_flags += stab_flags
    if "stability_unchecked" in stab_flags:
        warnings.warn(f"STABILITY UNCHECKED for session '{session_id}': {stab_msg} "
                      f"(Optical.md section 5.1 re-check).", UserWarning, stacklevel=2)
    # homography_drift / stability_abs_fail already warned loudly inside cal.stability_check

    times = np.arange(len(frames)) / fps_used
    clip_meta = {"file": "raw.mp4", "mode": mode, "fps_nominal": int(fps_nominal),
                 "fps_measured": fps_used}
    calib_meta = {"calib_id": calib.calib_id, "reproj_rms_px": calib.reproj_rms_px,
                  "check_point_err_m": calib.check_point_err_m,
                  "intrinsics": Path(args.intrinsics).name if args.intrinsics else None}

    optical_gt, track, contact = run_clip_pipeline(
        frames, times, config, calib.H, camera, clip_meta=clip_meta,
        calib_meta=calib_meta, session_id=session_id, notes=args.notes,
        extra_flags=extra_flags)

    overlay_frame = frames[contact.t_frame] if contact is not None else frames[-1]
    write_session(session_dir, optical_gt, overlay_frame, track, contact, calib.H)
    manifest_dir = Path(args.manifest_dir) if args.manifest_dir else ROOT / "data" / "manifests"
    append_manifest(manifest_dir / f"{datetime.now():%Y-%m-%d}_manifest.yaml",
                    {"session_id": session_id, "file": "raw.mp4", "mode": mode,
                     "calib_id": calib.calib_id, "in_frame": args.in_frame,
                     "out_frame": args.out_frame, "notes": args.notes})
    print(ov.summary_text(optical_gt))
    return 0


def resolve_camera_K(intr, allow_fallback, config, mode, session_id=""):
    """Camera K for CameraGeometry + the flag to attach (Stage 5.2 gating / audit
    Moderate). The HFOV-guess K is smoke-test only: it must be opt-in AND visibly flagged,
    never a silent campaign fallback.

    intr present            -> (measured K, None).
    intr absent, allowed    -> (HFOV-guess K, 'fallback_intrinsics') + a loud warning.
    intr absent, NOT allowed -> hard OpticalConfigError.
    """
    if intr is not None:
        return intr["camera_matrix"], None
    if allow_fallback:
        warnings.warn(
            f"FALLBACK INTRINSICS for session '{session_id}': no --intrinsics supplied; "
            f"using an HFOV-guess K (smoke-testing only). The camera pose and parallax "
            f"correction inherit that guess. Every throw carries 'fallback_intrinsics'. "
            f"Supply the section-3.4 intrinsics for any real run.", UserWarning, stacklevel=2)
        return _fx_only_K(config, mode), "fallback_intrinsics"
    raise OpticalConfigError(
        "no --intrinsics supplied. Pass the section-3.4 intrinsics_<mode>.yaml, or "
        "--allow-fallback-intrinsics for smoke-testing only (never a campaign).")


def _fx_only_K(config, mode):
    """Fallback K from the mode's resolution + a nominal 60-deg HFOV (used only when
    no intrinsics file is supplied; real runs pass --intrinsics)."""
    w, h = config["capture"]["modes"][mode]["resolution"]
    fx = (w / 2.0) / np.tan(np.radians(60.0) / 2.0)
    return np.array([[fx, 0, w / 2.0], [0, fx, h / 2.0], [0, 0, 1.0]])


if __name__ == "__main__":
    raise SystemExit(main())
