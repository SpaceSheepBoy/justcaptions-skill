"""Asset location for both the installed wheel and the plain skill checkout."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / 'assets'
if not ASSETS.is_dir():
    ASSETS = Path(__file__).resolve().parents[2] / 'assets'
