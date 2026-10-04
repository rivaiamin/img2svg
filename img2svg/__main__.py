"""Allow ``python3 -m img2svg``."""

import sys

from .cli import main

sys.exit(main())
