"""Allow ``python -m sdl`` to run the command line."""

from __future__ import annotations

from sdl.cli.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
