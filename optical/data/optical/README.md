# Optical footage (not tracked in git)

The raw iPhone 15 Pro Max clips (1080p at 240 fps) are about 1 GB and are excluded from the repository.

| Folder | Contents | In git? |
|---|---|---|
| `static_gate/Static-1 .. Static-10/` | `point.yaml` (surveyed floor position of each static ball point) and `raw.mp4` | `point.yaml` only |
| `Static/` | the original `Static-*.MOV` captures | no |
| `homography/` | calibration/survey clips (`IMG_1877/1878/1880.MOV`, `Survey-*.MOV`) | no |

Footage download: **[ADD LINK HERE, e.g. a GitHub Release asset or a shared drive]**

To re-run the gate yourself, place the clips back in the layout above and run `scripts/validate_static.py`
(see `../../scripts/`). Note: that script currently loads whole clips into memory, which crashed a laptop on
the ten real clips; see the follow-ups in `IMPLEMENTATION_NOTES_OPTICAL.md`.
