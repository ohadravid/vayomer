#!/usr/bin/env python3
from __future__ import annotations

try:
    from data_processing.rebuild import main
except ModuleNotFoundError:
    from rebuild import main  # type: ignore[no-redef]


if __name__ == "__main__":
    raise SystemExit(main())
