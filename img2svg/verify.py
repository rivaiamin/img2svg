"""Objective fidelity check: rasterise the produced SVG with headless Chrome and
compare its foreground mask against the source mask (intersection over union)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .pixels import Raster, RasterError, _parse_ppm, imagemagick

__all__ = ["chrome_binary", "render_svg", "iou"]


def chrome_binary():
    """Path to a Chrome/Chromium binary, or ``None``."""
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def render_svg(svg_text, w, h):
    """Rasterise ``svg_text`` at exactly ``w x h`` through headless Chrome."""
    chrome = chrome_binary()
    if chrome is None:
        raise RasterError("no Chrome/Chromium on PATH - cannot --verify")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:#fff}"
        "svg{display:block}</style></head><body>%s</body></html>" % svg_text
    )
    with tempfile.TemporaryDirectory() as tmp:
        html_path = os.path.join(tmp, "page.html")
        png_path = os.path.join(tmp, "render.png")
        with open(html_path, "w") as fh:
            fh.write(html)
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "--screenshot=" + png_path, "--window-size=%d,%d" % (w, h),
             "file://" + html_path],
            capture_output=True, timeout=180,
        )
        if not os.path.exists(png_path):
            raise RasterError("Chrome produced no screenshot")
        proc = subprocess.run(
            imagemagick() + [png_path, "-resize", "%dx%d!" % (w, h),
                             "-colorspace", "sRGB", "-depth", "8", "ppm:-"],
            capture_output=True,
        )
    if proc.returncode != 0:
        raise RasterError("could not decode the Chrome screenshot")
    rw, rh, px = _parse_ppm(proc.stdout)
    return Raster(rw, rh, px, source="<render>")


def iou(svg_text, ref_mask, w, h, tolerance=30):
    """Intersection-over-union between the rendered SVG and ``ref_mask``.

    The SVG is rendered over white, so any pixel that differs from white counts as
    foreground.  That works for dark monochrome fills and for light multi-colour
    palettes alike (a luminance cut-off would misjudge pale colours).
    """
    render = render_svg(svg_text, w, h)
    inter = union = 0
    for y in range(h):
        row = y * w
        for x in range(w):
            r, g, b = render.rgb(x, y)
            fg = (255 - r) + (255 - g) + (255 - b) > tolerance
            a = ref_mask[row + x] != 0
            if a and fg:
                inter += 1
            if a or fg:
                union += 1
    return (inter / union) if union else 1.0
