"""Allow ``python -m mc7asm``."""

import sys

from mc7asm.cli import main

if __name__ == "__main__":
    sys.exit(main())
