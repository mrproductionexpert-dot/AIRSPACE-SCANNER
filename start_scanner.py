"""Portable launcher that ensures project root is on sys.path."""

from __future__ import annotations

import pathlib
import sys


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.main import main as app_main

    app_main()


if __name__ == "__main__":
    main()

