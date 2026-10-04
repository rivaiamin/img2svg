"""Self-checks for img2svg.  Run with:  python3 -m unittest discover -s tests -v

The first block needs nothing but Python.  The integration block at the end runs
only when ImageMagick (and, for the IoU check, Chrome) are available.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from img2svg import trace as T  # noqa: E402
from img2svg.masks import bbox, mask_for, restrict  # noqa: E402
from img2svg.pixels import Raster, RasterError  # noqa: E402


def square_mask(w, h, x0, y0, x1, y1):
    """Inclusive-filled rectangle mask."""
    m = bytearray(w * h)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            m[y * w + x] = 1
    return m


class TraceTests(unittest.TestCase):
    def test_solid_square_single_loop(self):
        m = square_mask(10, 10, 2, 2, 7, 7)
        loops = T.trace_mask(m, 10, 10)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(abs(T.loop_area(loops[0])), 36.0, places=6)

    def test_square_with_hole_yields_two_loops(self):
        m = square_mask(20, 20, 2, 2, 17, 17)
        for y in range(8, 12):
            for x in range(8, 12):
                m[y * 20 + x] = 0
        loops = T.trace_mask(m, 20, 20)
        self.assertEqual(len(loops), 2)
        areas = sorted(T.loop_area(l) for l in loops)
        self.assertLess(areas[0], 0)          # hole winds the other way
        self.assertAlmostEqual(abs(areas[0]), 16.0, places=6)
        # the outer contour encloses the whole square (hole included)
        self.assertAlmostEqual(areas[1], 256.0, places=6)
        # even-odd rendering needs both subpaths in one path
        d = T.loops_to_d(loops)
        self.assertEqual(d.count("Z"), 2)

    def test_disjoint_shapes(self):
        m = square_mask(30, 10, 1, 1, 6, 6)
        m2 = square_mask(30, 10, 20, 2, 27, 7)
        for i, v in enumerate(m2):
            if v:
                m[i] = 1
        self.assertEqual(len(T.trace_mask(m, 30, 10)), 2)

    def test_speck_filtered_by_min_area(self):
        m = square_mask(20, 20, 2, 2, 17, 17)
        m[0] = 1  # lone pixel, area 1
        loops = T.trace_mask(m, 20, 20, min_area=20.0)
        self.assertEqual(len(loops), 1)

    def test_full_frame_shape_closes(self):
        m = bytearray([1] * (8 * 8))
        loops = T.trace_mask(m, 8, 8)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(T.loop_area(loops[0]), 64.0, places=6)


class SimplifyTests(unittest.TestCase):
    def test_rdp_collapses_collinear(self):
        pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 0.0)]
        self.assertEqual(T.rdp(pts, 0.1), [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 0.0)])

    def test_rdp_keeps_corner_within_eps(self):
        pts = [(0.0, 0.0), (1.0, 0.4), (2.0, 0.0)]
        self.assertEqual(len(T.rdp(pts, 0.1)), 3)

    def test_chaikin_doubles_and_stays_closed(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0),
               (0.0, 5.0), (5.0, 5.0)]
        out = T.chaikin(pts, 1)
        self.assertEqual(len(out), 12)
        self.assertNotEqual(out[0], out[-1])
        # convex-ish: every point stays inside the original hull
        for x, y in out:
            self.assertTrue(-0.001 <= x <= 10.001 and -0.001 <= y <= 10.001)

    def test_fmt_trims(self):
        self.assertEqual(T.fmt(3.0), "3")
        self.assertEqual(T.fmt(3.25, 1), "3.2")
        self.assertEqual(T.fmt(-0.0), "0")


class MaskTests(unittest.TestCase):
    def test_bbox_and_restrict(self):
        m = square_mask(12, 9, 3, 2, 7, 5)
        self.assertEqual(bbox(m, 12, 9), (3, 2, 7, 5))
        r = restrict(m, 12, 9, 4, 3, 6, 4)
        self.assertEqual(bbox(r, 12, 9), (4, 3, 6, 4))
        self.assertEqual(r.count(1), 6)

    def test_mask_for(self):
        labels = bytearray([0, 1, 1, 2, 2, 2])
        self.assertEqual(mask_for(labels, 1), bytearray([0, 1, 1, 0, 0, 0]))
        self.assertEqual(mask_for(labels, 2), bytearray([0, 0, 0, 1, 1, 1]))

    def test_despeckle_drops_small_keeps_large(self):
        from img2svg.masks import despeckle
        m = square_mask(30, 30, 2, 2, 21, 21)   # 400 px blob
        m[0] = 1                                 # 1 px speck
        m[10 * 30 + 29] = 1                      # 1 px speck
        despeckle(m, 30, 30, 12)
        self.assertEqual(m.count(1), 400)
        self.assertEqual(m[0], 0)

    def test_despeckle_keeps_thin_line(self):
        from img2svg.masks import despeckle
        m = bytearray(20 * 20)
        for x in range(20):
            m[10 * 20 + x] = 1        # 20 px 1-wide line
        despeckle(m, 20, 20, 12)
        self.assertEqual(m.count(1), 20)


class PaletteTests(unittest.TestCase):
    def test_background_set_merges_near_colors(self):
        from img2svg.quantize import background_set
        pal = [(255, 255, 255), (238, 238, 236), (10, 10, 10), (200, 100, 50)]
        self.assertEqual(background_set(pal, 0, 40), {0, 1})
        self.assertEqual(background_set(pal, 0, 0), {0})
        self.assertEqual(background_set(pal, 2, 40), {2})

    def test_otsu_splits_bimodal(self):
        from img2svg.cli import otsu_threshold
        hist = [0] * 256
        hist[30] = 1000     # dark cluster
        hist[220] = 1000    # light cluster
        thr = otsu_threshold(hist)
        self.assertTrue(30 <= thr < 220)

    def test_foreground_mask_invert(self):
        from img2svg.cli import foreground_mask
        r = Raster(2, 1, bytes([0, 0, 0, 255, 255, 255]))
        m, thr = foreground_mask(r, 128, False)
        self.assertEqual(list(m), [1, 0])
        m, _ = foreground_mask(r, 128, True)
        self.assertEqual(list(m), [0, 1])

    def test_merge_near_folds_duplicate_shades(self):
        from img2svg.quantize import merge_near
        pal = [(10, 10, 10), (14, 12, 11), (240, 240, 240)]
        lab = bytearray([0, 1, 2, 0, 1])
        lab, _ = merge_near(lab, pal, 48)
        self.assertEqual(list(lab), [0, 0, 2, 0, 0])

    def test_merge_near_keeps_distinct_colors(self):
        from img2svg.quantize import merge_near
        pal = [(10, 10, 10), (240, 240, 240)]
        lab = bytearray([0, 1])
        lab, _ = merge_near(lab, pal, 48)
        self.assertEqual(list(lab), [0, 1])

    def test_merge_minor_folds_rare_colors(self):
        from img2svg.quantize import merge_minor
        pal = [(0, 0, 0), (250, 250, 250), (200, 10, 10)]
        lab = bytearray([0] * 50 + [1] * 50 + [2] * 3)
        lab, _, counts = merge_minor(lab, pal, 12)
        self.assertEqual(counts[2], 0)          # 3 px shade folded away
        self.assertEqual(counts[0] + counts[1], 103)


def _write_test_png(path, w, h, draw):
    subprocess.run(
        ["convert", "-size", "%dx%d" % (w, h), "xc:white", "-fill", "black",
         "-draw", draw, path],
        check=True, capture_output=True,
    )


@unittest.skipUnless(shutil.which("convert") or shutil.which("magick"),
                     "ImageMagick not installed")
class IntegrationTests(unittest.TestCase):
    def test_png_to_svg_roundtrip(self):
        from img2svg.cli import build_parser, convert
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "shape.png")
            _write_test_png(png, 120, 120, "circle 60,60 60,20")
            args = build_parser().parse_args([png, "-o", os.path.join(tmp, "out.svg")])
            stats = convert(args)
            self.assertEqual(stats["paths"], 1)
            self.assertTrue(stats["svg"].startswith("<svg "))
            self.assertIn('fill-rule="evenodd"', stats["svg"])
            # a disc of r=40 has area ~5026; traced area should be close
            self.assertGreater(stats["points"], 8)
            # regression: viewBox must be the bbox-relative canvas, so the path
            # coordinates (which are already bbox-relative) land in view
            x0, y0, cw, ch = stats["bbox"]
            self.assertIn('viewBox="0 0 %d %d"' % (cw, ch), stats["svg"])
            self.assertIn('width="%d" height="%d"' % (cw, ch), stats["svg"])
            coords = [float(v) for pair in
                      __import__("re").findall(r"[ML]\s*(-?[\d.]+)\s+(-?[\d.]+)",
                                               stats["svg"]) for v in pair]
            self.assertTrue(coords)
            self.assertTrue(all(-1 <= c <= max(cw, ch) + 1 for c in coords))

    def test_multicolor_two_shapes(self):
        from img2svg.cli import build_parser, convert
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "two.png")
            subprocess.run(
                ["convert", "-size", "200x100", "xc:white",
                 "-fill", "red", "-draw", "rectangle 10,10 60,90",
                 "-fill", "blue", "-draw", "rectangle 120,10 190,90", png],
                check=True, capture_output=True)
            args = build_parser().parse_args([png, "--color", "--colors", "3"])
            stats = convert(args)
            self.assertEqual(stats["paths"], 2)
            fills = {l.split('fill="')[1].split('"')[0]
                     for l in stats["svg"].splitlines() if l.startswith("<path")}
            self.assertEqual(len(fills), 2)

    def test_missing_file_raises(self):
        from img2svg.pixels import load
        with self.assertRaises(RasterError):
            load("/nonexistent/does-not-exist.png")


class VerifyTests(unittest.TestCase):
    def test_iou_of_identity_is_one(self):
        try:
            from img2svg.verify import chrome_binary, iou
        except Exception:  # pragma: no cover
            self.skipTest("verify module unavailable")
        if not chrome_binary():
            self.skipTest("Chrome not installed")
        w = h = 60
        m = square_mask(w, h, 10, 10, 49, 49)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" '
               'viewBox="0 0 60 60"><path fill="#000" d="M10 10 L50 10 L50 50 '
               'L10 50 Z"/></svg>')
        self.assertGreater(iou(svg, m, w, h), 0.98)


if __name__ == "__main__":
    unittest.main(verbosity=2)
