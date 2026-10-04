# img2svg

Convert raster images (PNG, JPEG, WebP, …) into clean, scalable SVG vectors.

Pure Python + ImageMagick for decoding, **no `potrace`/`autotrace` needed** and no
Python imaging libraries (no Pillow, no NumPy). Headless Chrome is used only for
the optional `--verify` fidelity check.

```
┌──────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────┐   ┌────────┐
│ decode   │ → │ mask / palette│ → │ pixel-crack  │ → │ smooth +   │ → │ SVG    │
│ (convert)│   │ (Otsu/quant)  │   │ contour trace│   │ RDP        │   │ path   │
└──────────┘   └───────────────┘   └──────────────┘   └────────────┘   └────────┘
```

## How it works

1. **Decode** – ImageMagick (`magick`/`convert`) streams a raw P6 PPM; Python parses it.
2. **Mask** – monochrome mode thresholds luminance (Otsu by default); colour mode
   quantises to N colours and treats one or more of them as background.
3. **Trace** – pixel-crack boundary following. Every foreground/background pixel
   boundary becomes a directed unit edge with the foreground on its left; edges are
   walked by a *straightest-continuation* rule, which always closes into loops
   (outer contours **and** holes) with no marching-squares saddle ambiguity.
4. **Simplify** – Chaikin corner-cutting removes the pixel staircase, then
   Ramer–Douglas–Peucker drops redundant points.
5. **Emit** – one `<path fill-rule="evenodd">` per colour, holes and all.

## Install

Nothing to install for the library itself; just make sure the tools are present:

```sh
# Debian/Ubuntu
sudo apt install imagemagick          # required (decoder)
sudo apt install chromium             # optional, for --verify
```

Run it straight from the checkout:

```sh
./bin/img2svg input.png -o output.svg

# or add to PATH
ln -s "$PWD/bin/img2svg" ~/.local/bin/img2svg
```

Optionally install the package (provides the `img2svg` console script):

```sh
python3 -m pip install --user -e .
```

## Usage

```sh
img2svg logo.png                        # -> logo.svg, monochrome, tight crop
img2svg logo.png --color --colors 6     # one path per colour
img2svg emblem.jpg --crop 184,100,852,810 --fill '#393e41' --verify
img2svg icon.png --threshold 128 --invert
img2svg photo.jpg --color --max-size 900 --min-size 30
```

Common options:

| Flag | Meaning |
|------|---------|
| `-o, --output` | output SVG (default: input with `.svg`) |
| `-c, --color` | multi-colour mode: quantise, trace one path per colour |
| `--colors N` | palette size for `--color` (default 6) |
| `--threshold V` | luminance cut-off, or `auto` for Otsu (default `auto`) |
| `--invert` | treat light pixels as foreground |
| `--fill COLOR` | monochrome fill (default: mean foreground colour) |
| `--background auto\|keep\|COLOR` | colour dropped in `--color` mode |
| `--bg-tolerance RGB` | also drop background colours within this RGB distance (default 40) |
| `--merge-tolerance RGB` | fold near-duplicate palette colours into one (default 48) |
| `--eps F` | RDP tolerance in px (default 1.0; larger = fewer points) |
| `--smooth N` | Chaikin passes (default 2; 0 = keep pixel steps) |
| `--min-area F` | drop contours below this px² (default 20) |
| `--min-size N` | drop connected colour blobs below N px (default 12) |
| `--pad N` / `--no-crop` | margin, or keep the full canvas |
| `--crop x0,y0,x1,y1` | ignore everything outside this box (e.g. drop text) |
| `--resize` / `--max-size N` | downscale before tracing (default 1400 px longest side) |
| `--verify` | render with headless Chrome and report IoU vs the source |

## Fidelity check

`--verify` rasterises the produced SVG with headless Chrome at the exact output
size and reports intersection-over-union against the source mask. Correct traces
land around **0.98**; anything below ~0.9 means the mask or threshold is wrong.

```sh
$ img2svg emblem.jpg --crop 184,100,852,810 --fill '#393e41' --verify
wrote emblem.svg | 1 path(s) | 386 points | viewBox 184 102 667 705 | threshold 145 | IoU 0.9838
```

## Tips

- **Photos** need `--color`; monochrome mode on a photo traces the whole dark half.
- **Line art / logos**: default monochrome mode with Otsu gives the cleanest result.
- **Dithering** is off by default — it multiplies contour count. Enable `--dither`
  only if you actually want a halftone look.
- **Too many points?** Raise `--eps` (1.5–2.5) and/or `--smooth`.
- **Missing thin strokes?** Lower `--min-size` (it is `N//2+1` in monochrome mode).
- **Text under a logo**: `--crop` to the emblem, or `--no-crop` to keep the canvas.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Unit tests need only Python; integration tests run when ImageMagick is present and
the IoU test runs when Chrome is present (skipped otherwise).

## Layout

```
img2svg/
  pixels.py    decode via ImageMagick, Raster + luminance
  masks.py     mask_for / bbox / restrict / crop / despeckle
  trace.py     pixel-crack tracing, Chaikin, RDP, path serialisation
  quantize.py  palette + labels, background detection
  verify.py    headless-Chrome render + IoU
  cli.py       argument parsing and the conversion pipeline
bin/img2svg    run from the checkout without installing
tests/         unit + integration self-checks
```

## License

MIT
