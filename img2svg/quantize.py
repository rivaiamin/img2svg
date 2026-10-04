"""Palette extraction and per-colour labels for multi-colour tracing."""

from __future__ import annotations

from collections import Counter

__all__ = ["quantize", "merge_minor", "merge_near", "background_index",
           "background_set", "nearest_index"]


def quantize(raster):
    """Group a quantised raster into a palette plus per-pixel labels.

    Returns ``(palette, labels)`` where ``palette`` is a list of ``(r, g, b)``
    tuples ordered by descending pixel count and ``labels`` is a bytearray of
    palette indices, one per pixel.  Feed the raster through
    :func:`img2svg.pixels.load` with ``colors=N`` first so the image already has
    at most N distinct colours.
    """
    counts = Counter()
    px = raster.px
    n = raster.w * raster.h
    for i in range(n):
        o = i * 3
        counts[(px[o], px[o + 1], px[o + 2])] += 1
    palette = [c for c, _ in counts.most_common()]
    if len(palette) > 255:
        raise ValueError(
            "image has %d distinct colours - reduce --colors" % len(palette)
        )
    index = {c: i for i, c in enumerate(palette)}
    labels = bytearray(n)
    for i in range(n):
        o = i * 3
        labels[i] = index[(px[o], px[o + 1], px[o + 2])]
    return palette, labels


def merge_minor(labels, palette, min_pixels):
    """Fold palette entries smaller than ``min_pixels`` into their nearest
    neighbour, in place.

    Antialiasing and JPEG ringing produce a long tail of near-duplicate shades;
    left alone each becomes its own hairline contour.  Merging them keeps the
    palette honest and the path count sane.
    """
    counts = [0] * len(palette)
    for v in labels:
        counts[v] += 1
    keep = [i for i, c in enumerate(counts) if c >= min_pixels]
    if not keep or len(keep) == len(palette):
        return labels, palette, counts
    remap = {}
    for i in range(len(palette)):
        if i in keep:
            continue
        remap[i] = min(
            keep,
            key=lambda j: sum((palette[i][c] - palette[j][c]) ** 2 for c in range(3)),
        )
    for k in range(len(labels)):
        v = labels[k]
        if v in remap:
            labels[k] = remap[v]
    counts = [0] * len(palette)
    for v in labels:
        counts[v] += 1
    return labels, palette, counts


def merge_near(labels, palette, tolerance):
    """Fold palette entries that sit within ``tolerance`` RGB distance of a more
    common entry into that entry, in place.

    JPEG ringing splits one visual colour into several near-identical shades.
    Left separate, each shade's mask is riddled with holes where its twin sits,
    so a single logo explodes into hundreds of interleaved contours.
    """
    if tolerance <= 0 or len(palette) < 2:
        return labels, palette
    counts = [0] * len(palette)
    for v in labels:
        counts[v] += 1
    order = sorted(range(len(palette)), key=lambda i: -counts[i])
    remap = {}
    kept = []
    for i in order:
        target = None
        for j in kept:
            if sum((palette[i][c] - palette[j][c]) ** 2 for c in range(3)) <= tolerance * tolerance:
                target = j
                break
        if target is None:
            kept.append(i)
        else:
            remap[i] = target
    if not remap:
        return labels, palette
    for k in range(len(labels)):
        v = labels[k]
        if v in remap:
            labels[k] = remap[v]
    return labels, palette


def background_index(raster, labels, k):
    """Guess the background colour index from the pixels on the image border.

    Takes the *most common* border colour (not just the corner-most pixel), so a
    photographic edge or a stray dark pixel cannot hijack the choice.
    """
    w, h = raster.w, raster.h
    votes = [0] * k
    last = (h - 1) * w
    for x in range(w):
        votes[labels[x]] += 1
        votes[labels[last + x]] += 1
    for y in range(h):
        row = y * w
        votes[labels[row]] += 1
        votes[labels[row + w - 1]] += 1
    return max(range(k), key=lambda i: votes[i])


def background_set(palette, bg, tolerance):
    """Indices to drop: ``bg`` plus every palette entry within ``tolerance`` RGB
    distance of it.  Backgrounds are rarely a single flat colour - photos have a
    gradient band, JPEG adds a halo - so near-duplicates must go together."""
    if tolerance <= 0:
        return {bg}
    base = palette[bg]
    out = {bg}
    for i, c in enumerate(palette):
        if sum((c[j] - base[j]) ** 2 for j in range(3)) <= tolerance * tolerance:
            out.add(i)
    return out


def nearest_index(palette, color):
    """Index of the palette entry closest to ``color`` (squared RGB distance)."""
    return min(
        range(len(palette)),
        key=lambda i: sum((palette[i][c] - color[c]) ** 2 for c in range(3)),
    )
