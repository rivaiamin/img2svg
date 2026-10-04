"""Raster pixel access through ImageMagick (no Python imaging libraries needed)."""

from __future__ import annotations

import shutil
import subprocess


class RasterError(RuntimeError):
    """Raised when an image cannot be read or written."""


def imagemagick():
    """Return the ImageMagick CLI as an argv prefix (v7 'magick' or v6 'convert')."""
    for name in ("magick", "convert"):
        exe = shutil.which(name)
        if exe:
            return [exe]
    raise RasterError(
        "ImageMagick not found - install it (need 'magick' or 'convert' on PATH)"
    )


class Raster:
    """A decoded RGB image; ``px`` holds ``w*h*3`` bytes."""

    __slots__ = ("w", "h", "px", "source")

    def __init__(self, w, h, px, source=""):
        self.w = w
        self.h = h
        self.px = px
        self.source = source

    def rgb(self, x, y):
        o = (y * self.w + x) * 3
        return self.px[o], self.px[o + 1], self.px[o + 2]

    def lum(self, x, y):
        r, g, b = self.rgb(x, y)
        return (r * 299 + g * 587 + b * 114) // 1000

    def luminance(self):
        """Return a bytearray (w*h) of per-pixel luminance."""
        out = bytearray(self.w * self.h)
        px = self.px
        for i in range(self.w * self.h):
            o = i * 3
            out[i] = (px[o] * 299 + px[o + 1] * 587 + px[o + 2] * 114) // 1000
        return out

    def __repr__(self):
        return "Raster(%dx%d)" % (self.w, self.h)


def _parse_ppm(data):
    """Parse a binary P6 PPM into ``(w, h, bytes)``."""
    n = len(data)
    fields = []
    i = 0
    while len(fields) < 4:
        while i < n and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while i < n and data[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while j < n and not data[j:j + 1].isspace():
            j += 1
        if j == i:
            raise RasterError("malformed PPM header")
        fields.append(data[i:j])
        i = j
    if fields[0] != b"P6":
        raise RasterError("unsupported PPM magic %r" % (fields[0],))
    w, h, maxval = int(fields[1]), int(fields[2]), int(fields[3])
    if maxval > 255:
        raise RasterError("16-bit PPM not supported")
    i += 1  # single whitespace byte after maxval
    px = data[i:i + w * h * 3]
    if len(px) != w * h * 3:
        raise RasterError("truncated PPM data")
    return w, h, px


def load(path, *, resize=None, colors=None, dither=False, background="white",
         depth=8, colorspace="sRGB"):
    """Decode ``path`` into a :class:`Raster` using ImageMagick.

    resize     ImageMagick geometry, e.g. ``"1200x1200"`` or ``"1400x1400>"``.
    colors     quantise to at most N colours (for multi-colour tracing).
    dither     allow dithering during quantisation (default off).
    background colour used to flatten any alpha channel.
    """
    cmd = imagemagick() + [path, "-alpha", "remove", "-background", background]
    if resize:
        cmd += ["-resize", resize]
    if colors:
        if not dither:
            cmd += ["-dither", "None"]
        cmd += ["-colors", str(colors)]
    cmd += ["-colorspace", colorspace, "-depth", str(depth), "ppm:-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RasterError("ImageMagick failed: %s" % (lines[-1] if lines else "unknown error"))
    w, h, px = _parse_ppm(proc.stdout)
    return Raster(w, h, px, source=path)
