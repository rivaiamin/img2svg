"""Pixel-crack contour tracing: a raster mask becomes closed vector loops.

Every boundary between a foreground and a background pixel is emitted as a
directed unit edge with the foreground pixel on its left.  Following those
edges with a "straightest continuation" rule always yields closed loops -
outer contours and holes alike - with no saddle ambiguity (the failure mode of
marching squares).
"""

from __future__ import annotations

import math

__all__ = ["trace_mask", "chaikin", "rdp", "loop_area", "loops_to_d", "fmt"]


def trace_mask(mask, w, h, min_area=20.0, min_pts=4):
    """Trace ``mask`` (``w*h`` bytes, nonzero = foreground) into closed loops.

    Returns a list of loops; each loop is a list of ``(x, y)`` points in
    pixel-corner coordinates.  Holes are returned as their own loops, so render
    the result with ``fill-rule="evenodd"``.
    """
    edges = []
    add = edges.append
    for gy in range(h):
        row = gy * w
        for gx in range(w):
            if mask[row + gx] == 0:
                continue
            if gx + 1 >= w or mask[row + gx + 1] == 0:
                add(((gx + 1, gy), (gx + 1, gy + 1)))
            if gx == 0 or mask[row + gx - 1] == 0:
                add(((gx, gy + 1), (gx, gy)))
            if gy == 0 or mask[row - w + gx] == 0:
                add(((gx, gy), (gx + 1, gy)))
            if gy + 1 >= h or mask[row + w + gx] == 0:
                add(((gx + 1, gy + 1), (gx, gy + 1)))

    out_at = {}
    for i, (p, _) in enumerate(edges):
        out_at.setdefault(p, []).append(i)

    used = bytearray(len(edges))
    limit = 4 * len(edges) + 16
    loops = []
    for i0, (p, q) in enumerate(edges):
        if used[i0]:
            continue
        used[i0] = 1
        loop = [p, q]
        prev, cur = p, q
        guard = 0
        while cur != p:
            guard += 1
            if guard > limit:
                break
            d1x = cur[0] - prev[0]
            d1y = cur[1] - prev[1]
            best = None
            best_score = None
            for e in out_at.get(cur, ()):
                if used[e]:
                    continue
                w2 = edges[e][1]
                d2x = w2[0] - cur[0]
                d2y = w2[1] - cur[1]
                dot = d1x * d2x + d1y * d2y
                cross = d1x * d2y - d1y * d2x
                score = (dot, -cross)  # straightest; left turn breaks ties
                if best_score is None or score > best_score:
                    best_score = score
                    best = (w2, e)
            if best is None:
                break
            w2, e = best
            used[e] = 1
            prev, cur = cur, w2
            loop.append(cur)
        if len(loop) >= min_pts:
            loops.append(loop)

    # Outer contours below min_area are specks; holes are kept even when small,
    # otherwise a shape with a small window would be filled solid.
    kept = []
    for loop in loops:
        a = loop_area(loop)
        if a < 0.0:
            if abs(a) > 1.0:
                kept.append(loop)
        elif a > min_area:
            kept.append(loop)
    return kept


def loop_area(loop):
    """Signed area of a closed polyline (positive = clockwise in y-down space)."""
    s = 0.0
    n = len(loop)
    for i in range(n):
        xa, ya = loop[i]
        xb, yb = loop[(i + 1) % n]
        s += xa * yb - xb * ya
    return s / 2.0


def chaikin(pts, iters=2):
    """Corner-cutting on a closed polyline; removes the pixel staircase."""
    for _ in range(iters):
        n = len(pts)
        if n < 6:
            return pts
        out = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = out
    return pts


def rdp(pts, eps):
    """Ramer-Douglas-Peucker simplification (iterative, no recursion limit)."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = bytearray(n)
    keep[0] = keep[n - 1] = 1
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = pts[i]
        bx, by = pts[j]
        dx = bx - ax
        dy = by - ay
        den = dx * dx + dy * dy
        dm = -1.0
        im = -1
        for k in range(i + 1, j):
            px, py = pts[k]
            if den == 0:
                dd = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / den
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                dd = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if dd > dm:
                dm = dd
                im = k
        if dm > eps:
            keep[im] = 1
            stack.append((i, im))
            stack.append((im, j))
    return [p for p, k in zip(pts, keep) if k]


def fmt(value, precision=1):
    """Format a coordinate, trimming trailing zeros."""
    s = "%.*f" % (precision, value)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def loops_to_d(loops, dx=0.0, dy=0.0, precision=1):
    """Serialise loops into an SVG path ``d`` string (one subpath per loop)."""
    parts = []
    for loop in loops:
        if len(loop) < 3:
            continue
        seg = ["M", fmt(loop[0][0] + dx, precision), fmt(loop[0][1] + dy, precision)]
        for x, y in loop[1:]:
            seg.append("L")
            seg.append(fmt(x + dx, precision))
            seg.append(fmt(y + dy, precision))
        seg.append("Z")
        parts.append(" ".join(seg))
    return " ".join(parts)
