"""Console entry point for the ``kan`` CLI (also ``python -m pandan_cli``)."""
from __future__ import annotations

import sys

from .cli import run


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
