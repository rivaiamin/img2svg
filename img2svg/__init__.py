"""img2svg - raster image to SVG vector converter.

Pipeline: decode (ImageMagick) -> mask/palette -> pixel-crack contour tracing
-> Chaikin smoothing -> Ramer-Douglas-Peucker -> single SVG path per colour.
"""

from .pixels import Raster, RasterError, load
from .trace import chaikin, loop_area, loops_to_d, rdp, trace_mask

__version__ = "1.0.0"

__all__ = [
    "Raster",
    "RasterError",
    "load",
    "trace_mask",
    "chaikin",
    "rdp",
    "loop_area",
    "loops_to_d",
    "__version__",
]
