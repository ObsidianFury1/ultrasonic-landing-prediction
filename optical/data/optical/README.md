# Optical footage (not tracked in git)

The raw iPhone 15 Pro Max clips (1080p at 240 fps) are about 1 GB and are excluded from the repository.

| Folder | Contents | In git? |
|---|---|---|
| `static_gate/Static-1 .. Static-10/` | `point.yaml` (surveyed floor position of each static ball point) and `raw.mp4` | `point.yaml` only |
| `Static/` | the original `Static-*.MOV` captures | no |
| `homography/` | calibration/survey clips (`IMG_1877/1878/1880.MOV`, `Survey-*.MOV`) | no |

Footage download (1.08 GB): the [v1.0 release](https://github.com/ObsidianFury1/ultrasonic-landing-prediction/releases/tag/v1.0),
asset `optical-footage.zip` (direct link:
[download](https://github.com/ObsidianFury1/ultrasonic-landing-prediction/releases/download/v1.0/optical-footage.zip)).
The zip also contains the raw checkerboard photos (`calib/raw/`) and `calibration-frames/`.
SHA-256: `ec472f6ec31d6652e6d3ac84d721f35be4ca172db8c91a33a543a2710d7c3fb6`

Privacy note: the clips were published with all location, device and timestamp metadata removed. The video
and audio streams and every frame timestamp are bit-for-bit identical to the originals (only the container
metadata was rewritten, no re-encoding). One visible side effect: a container's reported average frame rate
reads exactly 240.0 fps instead of values such as 239.98; pass the measured rate to
`scripts/process_clip.py --fps-measured` as the spec requires.

To restore, unzip it into the **repository root**: its paths start with `optical/`, so every file lands in
the right place.

To re-run the gate yourself, place the clips back in the layout above and run `scripts/validate_static.py`
(see `../../scripts/`). Note: that script currently loads whole clips into memory, which crashed a laptop on
the ten real clips; see the follow-ups in `IMPLEMENTATION_NOTES_OPTICAL.md`.
