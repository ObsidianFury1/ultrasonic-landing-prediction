"""Generate printable ArUco markers and a checkerboard for physical commissioning
(Optical.md sect 3.3 marker survey / O4, sect 3.4 intrinsic calibration / O5).

Usage (defaults match the spec's recommendations):
  .\\venv\\Scripts\\python.exe scripts\\generate_calibration_targets.py

  .\\venv\\Scripts\\python.exe scripts\\generate_calibration_targets.py ^
      --n-markers 8 --marker-size-mm 100 --pattern 9x6 --square-size-mm 25

Outputs, under calib/targets/ (regenerable artifacts -- not sacred data, Optical.md
sect 5 "Regenerable vs sacred"):
  calib/targets/aruco_markers.pdf              - one DICT_4X4_50 marker per page, IDs 0..n-1
  calib/targets/checkerboard_<nx>x<ny>.pdf     - the intrinsics checkerboard, one page
  calib/targets/aruco_marker_<id>.jpg          - same markers, one JPEG per ID, DPI-tagged
  calib/targets/checkerboard_<nx>x<ny>.jpg     - same checkerboard, DPI-tagged

PRINTING -- READ THIS:
  Two sizing conventions are supported because printers differ in which one they expose:

  * PDF path -- print at 100% / "Actual size". NEVER "Fit to page" or "Shrink oversized
    pages"; either setting silently rescales the physical target.
  * JPEG path -- for printers/photo-print dialogs that have NO "actual size" option and
    instead print "as per image resolution" (i.e. they compute physical size from the
    image's embedded DPI tag: size = pixels / DPI), use the .jpg files. They are saved
    at --dpi (default 300) with that DPI baked into the file's own metadata, so the
    computed size should come out correct with no dialog choice needed on your end
    beyond selecting "actual/native resolution" rather than "fit to page". If your
    printer's photo pipeline ignores embedded DPI and defaults to a different value
    (a real risk with some drivers/kiosks), pass --dpi to match whatever it assumes.

  Every sheet (PDF and JPEG) carries a scale bar in BOTH directions -- a HORIZONTAL one
  and a VERTICAL one, each nominally 100 mm -- for exactly this reason: after printing,
  measure BOTH with a rule. If either disagrees with 100 mm, the print pipeline rescaled
  the page; measuring both axes separately catches anisotropic scaling (some print
  paths stretch/compress X and Y differently) and tells you exactly how much: e.g. a
  measured 97 mm on a nominal 100 mm bar means that axis printed at 97% -- divide any
  nominal size on that axis by that ratio to get the true printed size.

  The checkerboard square size is ALWAYS measured with a rule after printing and fed
  to scripts/calibrate_intrinsics.py --square-size-m regardless of the scale-bar
  check (Optical.md sect 3.4: "square size measured with a rule and recorded" -- the
  nominal value here is a print target, never a measurement). The ArUco marker size
  is not consumed by the homography fit (marker floor POSITIONS are surveyed and
  clicked/detected in pixels; the fit never uses the printed marker's physical size),
  so it only needs to be legible and flat, not metrologically exact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optical.calibration import ARUCO_DICT_NAME  # noqa: E402

PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
}
SCALE_BAR_MM = 100.0
MM_PER_IN = 25.4


def mm_to_in(mm: float) -> float:
    return mm / MM_PER_IN


def page_size_in(page_size: str) -> tuple[float, float]:
    w_mm, h_mm = PAGE_SIZES_MM[page_size.upper()]
    return mm_to_in(w_mm), mm_to_in(h_mm)


def generate_marker_image(marker_id: int, dict_name: str = ARUCO_DICT_NAME,
                           pixels: int = 800) -> np.ndarray:
    """Render one ArUco marker (DICT_4X4_50 by default) as a square uint8 image."""
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    return cv2.aruco.generateImageMarker(dictionary, marker_id, pixels)


def _draw_scale_bar_h(ax, x0_mm: float, y0_mm: float, length_mm: float = SCALE_BAR_MM) -> None:
    """Horizontal 100 mm reference bar with 10 mm ticks -- print-scale sanity check
    (independent of the vertical bar so anisotropic X/Y print scaling is caught)."""
    ax.plot([x0_mm, x0_mm + length_mm], [y0_mm, y0_mm], color="black", linewidth=1.2)
    for i in range(0, int(length_mm) + 1, 10):
        tick_h = 3.0 if i % 50 == 0 else 1.5
        ax.plot([x0_mm + i, x0_mm + i], [y0_mm, y0_mm + tick_h], color="black", linewidth=0.8)
    ax.text(x0_mm, y0_mm + 5.5, f"H scale bar: measure this line, must be {length_mm:.0f} mm",
            fontsize=6, va="bottom", ha="left")


def _draw_scale_bar_v(ax, x0_mm: float, y0_mm: float, length_mm: float = SCALE_BAR_MM) -> None:
    """Vertical 100 mm reference bar with 10 mm ticks -- catches anisotropic print
    scaling that a horizontal-only bar would miss (X and Y often scale independently)."""
    ax.plot([x0_mm, x0_mm], [y0_mm, y0_mm + length_mm], color="black", linewidth=1.2)
    for i in range(0, int(length_mm) + 1, 10):
        tick_w = 3.0 if i % 50 == 0 else 1.5
        ax.plot([x0_mm, x0_mm + tick_w], [y0_mm + i, y0_mm + i], color="black", linewidth=0.8)
    ax.text(x0_mm + 5.5, y0_mm, f"V scale bar: {length_mm:.0f} mm",
            fontsize=6, va="top", ha="left", rotation=90)


def _build_marker_figure(marker_id: int, dict_name: str, marker_size_mm: float,
                          page_w_in: float, page_h_in: float, page_w_mm: float,
                          page_h_mm: float):
    """One marker, centred on a page-sized figure, labelled with ID/dictionary/size."""
    img = generate_marker_image(marker_id, dict_name, pixels=800)
    fig = plt.figure(figsize=(page_w_in, page_h_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, page_w_mm)
    ax.set_ylim(0, page_h_mm)
    ax.invert_yaxis()
    ax.axis("off")

    cx, cy = page_w_mm / 2, page_h_mm / 2 - 10
    half = marker_size_mm / 2
    ax.imshow(img, cmap="gray", vmin=0, vmax=255,
              extent=(cx - half, cx + half, cy + half, cy - half))
    ax.add_patch(plt.Rectangle((cx - half, cy - half), marker_size_mm, marker_size_mm,
                                fill=False, edgecolor="black", linewidth=0.5))
    ax.text(cx, cy + half + 8,
            f"{dict_name}  ID {marker_id}  ({marker_size_mm:.0f} x {marker_size_mm:.0f} mm)",
            fontsize=9, ha="center", va="top")
    ax.text(cx, cy + half + 15,
            "Optical.md sect 3.3 -- floor marker.",
            fontsize=7, ha="center", va="top", color="dimgray")
    _draw_scale_bar_h(ax, x0_mm=10, y0_mm=page_h_mm - 15)
    v_length = min(SCALE_BAR_MM, marker_size_mm)
    _draw_scale_bar_v(ax, x0_mm=10, y0_mm=cy - v_length / 2)
    return fig


def save_aruco_pdf(ids: list[int], dict_name: str, marker_size_mm: float,
                    page_size: str, out_path: Path) -> Path:
    """One marker per page, centred, labelled with ID/dictionary/nominal size.
    Print at 100% / Actual size (this is the PDF, page-based, sizing convention)."""
    page_w_in, page_h_in = page_size_in(page_size)
    page_w_mm, page_h_mm = page_w_in * MM_PER_IN, page_h_in * MM_PER_IN

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_path) as pdf:
        for marker_id in ids:
            fig = _build_marker_figure(marker_id, dict_name, marker_size_mm,
                                        page_w_in, page_h_in, page_w_mm, page_h_mm)
            pdf.savefig(fig)
            plt.close(fig)
    return out_path


def save_aruco_jpegs(ids: list[int], dict_name: str, marker_size_mm: float,
                      page_size: str, dpi: float, quality: int,
                      out_dir: Path) -> list[Path]:
    """One DICT_4X4_50 marker per JPEG, DPI-tagged so pixels/DPI = the page's physical
    size -- for printers that size photos from the embedded DPI tag rather than
    offering an 'actual size' page option."""
    page_w_in, page_h_in = page_size_in(page_size)
    page_w_mm, page_h_mm = page_w_in * MM_PER_IN, page_h_in * MM_PER_IN

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for marker_id in ids:
        fig = _build_marker_figure(marker_id, dict_name, marker_size_mm,
                                    page_w_in, page_h_in, page_w_mm, page_h_mm)
        path = out_dir / f"aruco_marker_{marker_id}.jpg"
        fig.savefig(path, dpi=dpi, pil_kwargs={"quality": quality})
        plt.close(fig)
        paths.append(path)
    return paths


def _checkerboard_page_layout(pattern: tuple[int, int], square_size_mm: float,
                               page_size: str) -> tuple[float, float, float, float]:
    """Resolve (page_w_in, page_h_in, page_w_mm, page_h_mm), picking landscape/portrait
    to fit the board; raises if it fits neither orientation."""
    nx, ny = pattern
    sq_x, sq_y = nx + 1, ny + 1  # squares = inner corners + 1, per axis
    board_w_mm, board_h_mm = sq_x * square_size_mm, sq_y * square_size_mm

    page_w_in, page_h_in = page_size_in(page_size)
    page_w_mm, page_h_mm = page_w_in * MM_PER_IN, page_h_in * MM_PER_IN
    if board_w_mm > page_w_mm or board_h_mm > page_h_mm:
        if board_h_mm <= page_w_mm and board_w_mm <= page_h_mm:
            page_w_in, page_h_in = page_h_in, page_w_in
            page_w_mm, page_h_mm = page_h_mm, page_w_mm
        else:
            raise ValueError(
                f"checkerboard {board_w_mm:.0f}x{board_h_mm:.0f} mm does not fit on "
                f"{page_size} ({page_w_mm:.0f}x{page_h_mm:.0f} mm) in either orientation -- "
                f"reduce --square-size-mm or choose a larger --page-size")
    return page_w_in, page_h_in, page_w_mm, page_h_mm


def _build_checkerboard_figure(pattern: tuple[int, int], square_size_mm: float,
                                page_w_in: float, page_h_in: float, page_w_mm: float,
                                page_h_mm: float):
    nx, ny = pattern
    sq_x, sq_y = nx + 1, ny + 1
    board_w_mm, board_h_mm = sq_x * square_size_mm, sq_y * square_size_mm

    px_per_mm = 8
    board_px = np.zeros((int(sq_y * square_size_mm * px_per_mm),
                          int(sq_x * square_size_mm * px_per_mm)), np.uint8)
    sq_px = int(square_size_mm * px_per_mm)
    for r in range(sq_y):
        for c in range(sq_x):
            if (r + c) % 2 == 0:
                board_px[r * sq_px:(r + 1) * sq_px, c * sq_px:(c + 1) * sq_px] = 255

    fig = plt.figure(figsize=(page_w_in, page_h_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, page_w_mm)
    ax.set_ylim(0, page_h_mm)
    ax.invert_yaxis()
    ax.axis("off")

    cx, cy = page_w_mm / 2, page_h_mm / 2
    x0, y0 = cx - board_w_mm / 2, cy - board_h_mm / 2
    ax.imshow(board_px, cmap="gray", vmin=0, vmax=255,
              extent=(x0, x0 + board_w_mm, y0 + board_h_mm, y0))
    ax.add_patch(plt.Rectangle((x0, y0), board_w_mm, board_h_mm,
                                fill=False, edgecolor="black", linewidth=0.5))
    ax.text(cx, max(y0 - 6, 6),
            f"Checkerboard {nx}x{ny} inner corners, nominal square = {square_size_mm:.1f} mm "
            "-- MEASURE actual printed square size with a rule (Optical.md sect 3.4) "
            "and pass it to calibrate_intrinsics.py --square-size-m",
            fontsize=7, ha="center", va="top")
    _draw_scale_bar_h(ax, x0_mm=10, y0_mm=page_h_mm - 12)
    v_length = min(SCALE_BAR_MM, board_h_mm)
    _draw_scale_bar_v(ax, x0_mm=10, y0_mm=cy - v_length / 2)
    return fig


def save_checkerboard_pdf(pattern: tuple[int, int], square_size_mm: float,
                           page_size: str, out_path: Path) -> Path:
    """9x6-inner-corner (default) checkerboard at the given nominal square size.
    Print at 100% / Actual size (this is the PDF, page-based, sizing convention)."""
    page_w_in, page_h_in, page_w_mm, page_h_mm = _checkerboard_page_layout(
        pattern, square_size_mm, page_size)
    fig = _build_checkerboard_figure(pattern, square_size_mm,
                                      page_w_in, page_h_in, page_w_mm, page_h_mm)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def save_checkerboard_jpeg(pattern: tuple[int, int], square_size_mm: float,
                            page_size: str, dpi: float, quality: int,
                            out_path: Path) -> Path:
    """Same checkerboard, DPI-tagged (pixels/DPI = the physical page size) for printers
    that size photos from the embedded DPI tag rather than an 'actual size' option."""
    page_w_in, page_h_in, page_w_mm, page_h_mm = _checkerboard_page_layout(
        pattern, square_size_mm, page_size)
    fig = _build_checkerboard_figure(pattern, square_size_mm,
                                      page_w_in, page_h_in, page_w_mm, page_h_mm)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, pil_kwargs={"quality": quality})
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dict-name", default=ARUCO_DICT_NAME,
                    help=f"ArUco dictionary (default {ARUCO_DICT_NAME}, per Optical.md sect 3.3)")
    ap.add_argument("--n-markers", type=int, default=8,
                    help="number of markers, IDs 0..n-1 (sect 3.3 recommends ~6-8)")
    ap.add_argument("--marker-ids", default=None,
                    help="comma-separated explicit IDs, overrides --n-markers")
    ap.add_argument("--marker-size-mm", type=float, default=100.0)
    ap.add_argument("--pattern", default="9x6", help="checkerboard INNER corners, e.g. 9x6")
    ap.add_argument("--square-size-mm", type=float, default=25.0,
                    help="nominal print square size [mm] -- re-measure after printing")
    ap.add_argument("--page-size", default="A4", choices=list(PAGE_SIZES_MM))
    ap.add_argument("--dpi", type=float, default=300.0,
                    help="DPI baked into the JPEG outputs' metadata (default 300, a common "
                         "photo-print resolution) -- match this to whatever your printer's "
                         "'native/image resolution' print path assumes, if you know it")
    ap.add_argument("--jpeg-quality", type=int, default=95,
                    help="JPEG encoder quality 1-100 (default 95 -- high, to keep marker/"
                         "checkerboard edges crisp; JPEG is lossy so avoid re-saving the "
                         "output again before printing)")
    ap.add_argument("--formats", default="both", choices=["pdf", "jpeg", "both"],
                    help="pdf = print at 100%%/Actual size; jpeg = DPI-tagged, for printers "
                         "that size photos from image resolution instead")
    ap.add_argument("--out-dir", default=str(ROOT / "calib" / "targets"))
    args = ap.parse_args(argv)

    if args.marker_ids:
        ids = [int(v) for v in args.marker_ids.split(",")]
    else:
        ids = list(range(args.n_markers))

    nx, ny = (int(v) for v in args.pattern.lower().split("x"))
    out_dir = Path(args.out_dir)
    want_pdf = args.formats in ("pdf", "both")
    want_jpeg = args.formats in ("jpeg", "both")

    if want_pdf:
        aruco_path = save_aruco_pdf(ids, args.dict_name, args.marker_size_mm,
                                     args.page_size, out_dir / "aruco_markers.pdf")
        print(f"ArUco markers (PDF)  : {args.dict_name}, IDs {ids}, "
              f"{args.marker_size_mm:.0f}mm each -> {aruco_path}")

        checker_path = save_checkerboard_pdf(
            (nx, ny), args.square_size_mm, args.page_size,
            out_dir / f"checkerboard_{nx}x{ny}.pdf")
        print(f"Checkerboard (PDF)   : {nx}x{ny} inner corners, nominal "
              f"{args.square_size_mm:.1f}mm square -> {checker_path}")

    if want_jpeg:
        marker_paths = save_aruco_jpegs(ids, args.dict_name, args.marker_size_mm,
                                         args.page_size, args.dpi, args.jpeg_quality, out_dir)
        print(f"ArUco markers (JPEG) : {args.dict_name}, IDs {ids}, "
              f"{args.marker_size_mm:.0f}mm each @ {args.dpi:.0f} DPI -> "
              f"{out_dir}/aruco_marker_<id>.jpg ({len(marker_paths)} files)")

        checker_jpg_path = save_checkerboard_jpeg(
            (nx, ny), args.square_size_mm, args.page_size, args.dpi, args.jpeg_quality,
            out_dir / f"checkerboard_{nx}x{ny}.jpg")
        print(f"Checkerboard (JPEG)  : {nx}x{ny} inner corners, nominal "
              f"{args.square_size_mm:.1f}mm square @ {args.dpi:.0f} DPI -> {checker_jpg_path}")

    print()
    if want_pdf:
        print("PDF files: print at 100% / Actual size (never 'Fit to page').")
    if want_jpeg:
        print(f"JPEG files: printed at {args.dpi:.0f} DPI metadata -- select the printer's "
              "'actual/native/image resolution' option, not 'fit to page'.")
    print("Either way, measure BOTH the horizontal AND vertical scale bars with a rule "
          "after printing -- disagreement between them means the printer scaled X and Y "
          "differently, and tells you the per-axis ratio to correct for. Re-measure the "
          "checkerboard square directly (Optical.md sect 3.4) before running "
          "calibrate_intrinsics.py regardless of what the scale bars show.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
