"""Allow ``python -m mc7``."""

import sys

from mc7.cli import main

if __name__ == "__main__":
    sys.exit(main())
