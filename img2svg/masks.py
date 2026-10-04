"""Binary mask helpers.  A mask is a bytearray of 0/1, row-major, w*h."""

from __future__ import annotations

__all__ = ["mask_for", "bbox", "restrict", "crop", "despeckle"]


def mask_for(labels, index):
    """Mask of every pixel whose label equals ``index`` (byte translate = fast)."""
    table = bytes(1 if i == index else 0 for i in range(256))
    return labels.translate(table)


def bbox(mask, w, h):
    """Tight inclusive ``(x0, y0, x1, y1)`` box of set pixels, or ``None``."""
    xs0, ys0, xs1, ys1 = w, h, -1, -1
    for y in range(h):
        row = mask[y * w:(y + 1) * w]
        a = row.find(1)
        if a < 0:
            continue
        b = row.rfind(1)
        if a < xs0:
            xs0 = a
        if b > xs1:
            xs1 = b
        if y < ys0:
            ys0 = y
        ys1 = y
    if xs1 < 0:
        return None
    return xs0, ys0, xs1, ys1


def restrict(mask, w, h, x0, y0, x1, y1):
    """Copy of ``mask`` with everything outside the inclusive box cleared."""
    out = bytearray(len(mask))
    for y in range(max(0, y0), min(h - 1, y1) + 1):
        row = y * w
        for x in range(max(0, x0), min(w - 1, x1) + 1):
            if mask[row + x]:
                out[row + x] = 1
    return out


def despeckle(mask, w, h, min_size):
    """Zero out connected foreground components smaller than ``min_size`` pixels.

    Quantised photos carry colour noise that would otherwise trace into
    thousands of hairline contours.
    """
    if min_size <= 1:
        return mask
    seen = bytearray(len(mask))
    stack = []
    for start in range(len(mask)):
        if mask[start] == 0 or seen[start]:
            continue
        seen[start] = 1
        stack.append(start)
        comp = []
        while stack:
            i = stack.pop()
            comp.append(i)
            x = i % w
            y = i // w
            if x > 0:
                j = i - 1
                if mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
            if x + 1 < w:
                j = i + 1
                if mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
            if y > 0:
                j = i - w
                if mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
            if y + 1 < h:
                j = i + w
                if mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        if len(comp) < min_size:
            for i in comp:
                mask[i] = 0
    return mask


def crop(mask, w, x0, y0, cw, ch):
    """Extract a ``cw x ch`` window at ``(x0, y0)``; outside reads as 0."""
    out = bytearray(cw * ch)
    for y in range(ch):
        sy = y0 + y
        if sy < 0:
            continue
        srow = sy * w
        drow = y * cw
        for x in range(cw):
            sx = x0 + x
            if 0 <= sx < w and mask[srow + sx]:
                out[drow + x] = 1
    return out
