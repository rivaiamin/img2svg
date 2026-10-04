"""Command line interface for img2svg."""

from __future__ import annotations

import argparse
import os
import sys

from . import trace as _trace
from .masks import bbox, crop, despeckle, mask_for, restrict
from .pixels import RasterError, load
from .quantize import (background_index, background_set, merge_minor,
                       merge_near, nearest_index, quantize)
from .verify import iou

DEFAULT_MAX_SIZE = 1400


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def otsu_threshold(hist):
    """Otsu's method: the luminance threshold that best splits the histogram."""
    total = sum(hist)
    if total == 0:
        return 127
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = w_b = 0
    best = -1.0
    thr = 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best = var
            thr = t
    return thr


def foreground_mask(raster, threshold, invert):
    """Binary mask of pixels darker (or lighter, if ``invert``) than ``threshold``."""
    lum = raster.luminance()
    if threshold is None:
        hist = [0] * 256
        for v in lum:
            hist[v] += 1
        threshold = otsu_threshold(hist)
    table = bytes(
        1 if ((v >= threshold) if invert else (v < threshold)) else 0
        for v in range(256)
    )
    return lum.translate(table), threshold


def dominant_color(raster, mask):
    """Mean RGB of the masked pixels (used as the monochrome fill)."""
    px = raster.px
    r = g = b = n = 0
    for i, m in enumerate(mask):
        if m:
            o = i * 3
            r += px[o]
            g += px[o + 1]
            b += px[o + 2]
            n += 1
    if not n:
        return (0, 0, 0)
    return (r // n, g // n, b // n)


def to_hex(color):
    return "#%02x%02x%02x" % tuple(color)


def parse_hex(text):
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise RasterError("bad colour %r" % text)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise RasterError("bad colour %r" % text)


def parse_crop(text):
    try:
        vals = [int(v) for v in text.replace(",", " ").split()]
    except ValueError:
        vals = []
    if len(vals) != 4:
        raise RasterError("bad --crop %r (want x0,y0,x1,y1)" % text)
    return tuple(vals)


def simplify(loops, smooth, eps):
    out = []
    for loop in loops:
        pts = _trace.rdp(_trace.chaikin(loop, smooth), eps)
        if len(pts) >= 3:
            out.append(pts)
    return out


def build_svg(entries, x0, y0, w, h, precision):
    """``entries`` is a list of ``(rgb, loops)`` painted in order."""
    head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d">' % (w, h, w, h))
    body = []
    for color, loops in entries:
        d = _trace.loops_to_d(loops, dx=-x0, dy=-y0, precision=precision)
        if d:
            body.append('<path fill="%s" fill-rule="evenodd" d="%s"/>' % (to_hex(color), d))
    if not body:
        raise RasterError("nothing to draw (empty mask)")
    return head + "\n" + "\n".join(body) + "\n</svg>\n"


# --------------------------------------------------------------------------- #
# conversion
# --------------------------------------------------------------------------- #

def convert(args):
    """Run the full pipeline for parsed ``args``; returns a stats dict."""
    resize = args.resize
    if not resize and args.max_size:
        resize = "%dx%d>" % (args.max_size, args.max_size)

    raster = load(
        args.input,
        resize=resize,
        colors=(args.colors if args.color else None),
        dither=args.dither,
        background=args.flatten,
    )
    w, h = raster.w, raster.h
    region = parse_crop(args.crop) if args.crop else None

    if args.color:
        palette, labels = quantize(raster)
        labels, palette = merge_near(labels, palette, args.merge_tolerance)
        labels, palette, _ = merge_minor(labels, palette, args.min_size)
        k = len(palette)
        if args.background == "auto":
            drop = background_set(palette, background_index(raster, labels, k),
                                  args.bg_tolerance)
        elif args.background == "keep":
            drop = set()
        else:
            drop = background_set(palette, nearest_index(palette, parse_hex(args.background)),
                                  args.bg_tolerance)
        bg = None

        table = bytes(0 if i in drop else 1 for i in range(256))
        ref_mask = labels.translate(table)
        if region:
            ref_mask = restrict(ref_mask, w, h, *region)
        ref_mask = despeckle(ref_mask, w, h, args.min_size)
        if not ref_mask.count(1):
            raise RasterError("no foreground colours left (try --background keep)")

        entries = []
        for i in range(k):
            if i in drop:
                continue
            m = mask_for(labels, i)
            if region:
                m = restrict(m, w, h, *region)
            m = despeckle(m, w, h, args.min_size)
            if not m.count(1):
                continue
            loops = simplify(_trace.trace_mask(m, w, h, args.min_area),
                             args.smooth, args.eps)
            if loops:
                area = sum(abs(_trace.loop_area(l)) for l in loops)
                entries.append((area, palette[i], loops))
        if not entries:
            raise RasterError("no foreground regions found")
        entries.sort(key=lambda e: -e[0])
        threshold = None
    else:
        threshold = None if args.threshold == "auto" else int(args.threshold)
        ref_mask, threshold = foreground_mask(raster, threshold, args.invert)
        if region:
            ref_mask = restrict(ref_mask, w, h, *region)
        # gentle cleanup: remove salt but keep thin 1px strokes intact
        ref_mask = despeckle(ref_mask, w, h, args.min_size // 2 + 1)
        if not ref_mask.count(1):
            raise RasterError("no foreground pixels (try --invert or --threshold)")
        loops = simplify(_trace.trace_mask(ref_mask, w, h, args.min_area),
                         args.smooth, args.eps)
        color = parse_hex(args.fill) if args.fill else dominant_color(raster, ref_mask)
        entries = [(1.0, color, loops)]

    box = bbox(ref_mask, w, h)
    if box is None:
        raise RasterError("empty foreground")
    x0, y0, x1, y1 = box
    if args.no_crop:
        x0, y0, x1, y1 = 0, 0, w - 1, h - 1
    else:
        x0 = max(0, x0 - args.pad)
        y0 = max(0, y0 - args.pad)
        x1 = min(w - 1, x1 + args.pad)
        y1 = min(h - 1, y1 + args.pad)
    cw, ch = x1 - x0 + 1, y1 - y0 + 1

    svg = build_svg([(c, l) for _, c, l in entries], x0, y0, cw, ch, args.precision)

    stats = {
        "svg": svg,
        "paths": len(entries),
        "points": sum(len(l) for _, _, loops in entries for l in loops),
        "bbox": (x0, y0, cw, ch),
        "threshold": threshold,
        "palette": [c for _, c, _ in entries],
        "source_size": (w, h),
    }
    if args.verify:
        stats["iou"] = iou(svg, crop(ref_mask, w, x0, y0, cw, ch), cw, ch)
    return stats


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="img2svg",
        description="Convert a raster image into a clean SVG using pixel-crack "
                    "contour tracing (no potrace required).",
    )
    p.add_argument("input", help="source image (PNG, JPEG, WebP, ...)")
    p.add_argument("-o", "--output", help="output SVG (default: input with .svg)")

    mode = p.add_argument_group("mode")
    mode.add_argument("-c", "--color", action="store_true",
                      help="multi-colour output: quantise and trace one path per colour")
    mode.add_argument("--colors", type=int, default=6,
                      help="palette size for --color (default 6)")
    mode.add_argument("--merge-tolerance", type=int, default=48, metavar="RGB",
                      help="fold near-duplicate palette colours into one before "
                           "tracing (default 48; 0 disables)")
    mode.add_argument("--bg-tolerance", type=int, default=40, metavar="RGB",
                      help="also drop background colours within this RGB distance of "
                           "the detected one (default 40; 0 disables)")
    mode.add_argument("--dither", action="store_true",
                      help="allow dithering during quantisation (default off)")
    mode.add_argument("--threshold", default="auto",
                      help="monochrome luminance threshold, or 'auto' for Otsu (default auto)")
    mode.add_argument("--invert", action="store_true",
                      help="treat light pixels as foreground")
    mode.add_argument("--fill", help="monochrome fill colour, e.g. '#2c3e50' "
                                     "(default: mean of the foreground)")
    mode.add_argument("--background", default="auto", metavar="auto|keep|COLOR",
                      help="which colour to drop in --color mode (default auto: "
                           "the dominant border colour)")
    mode.add_argument("--flatten", default="white", metavar="COLOR",
                      help="colour used to flatten transparency (default white)")

    shape = p.add_argument_group("shape")
    shape.add_argument("--eps", type=float, default=1.0,
                       help="Ramer-Douglas-Peucker tolerance in px (default 1.0)")
    shape.add_argument("--smooth", type=int, default=2,
                       help="Chaikin smoothing passes (default 2)")
    shape.add_argument("--min-area", type=float, default=20.0,
                       help="drop contours smaller than this many px^2 (default 20)")
    shape.add_argument("--min-size", type=int, default=12,
                       help="drop connected colour blobs smaller than this many px "
                            "before tracing, floor(area/2)+1 in monochrome mode "
                            "(default 12)")
    shape.add_argument("--precision", type=int, default=1,
                       help="decimal places in path coordinates (default 1)")
    shape.add_argument("--pad", type=int, default=0,
                       help="margin around the traced content, in px (default 0)")
    shape.add_argument("--no-crop", action="store_true",
                       help="keep the full image canvas instead of the tight bbox")
    shape.add_argument("--crop", metavar="x0,y0,x1,y1",
                       help="ignore everything outside this box (e.g. drop text)")
    shape.add_argument("--resize", metavar="GEOMETRY",
                       help="ImageMagick resize before tracing, e.g. 800x800")
    shape.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE,
                       help="downscale larger images to this longest side first "
                            "(default %d; 0 disables)" % DEFAULT_MAX_SIZE)

    out = p.add_argument_group("output")
    out.add_argument("--verify", action="store_true",
                     help="render the SVG with headless Chrome and report IoU vs the source")
    out.add_argument("-q", "--quiet", action="store_true", help="suppress the summary line")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.output:
        args.output = os.path.splitext(args.input)[0] + ".svg"
    try:
        stats = convert(args)
    except RasterError as exc:
        print("img2svg: error: %s" % exc, file=sys.stderr)
        return 1

    with open(args.output, "w") as fh:
        fh.write(stats["svg"])

    if not args.quiet:
        bits = [
            "wrote %s" % args.output,
            "%d path(s)" % stats["paths"],
            "%d points" % stats["points"],
            "viewBox %d %d %d %d" % stats["bbox"],
        ]
        if stats.get("threshold") is not None:
            bits.append("threshold %d" % stats["threshold"])
        if "iou" in stats:
            bits.append("IoU %.4f" % stats["iou"])
        print(" | ".join(bits))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
