#!/usr/bin/env python3
"""Entry point: python3 scripts/jc.py VIDEO [--burn] [--style emoji] ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from justcaptions.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
