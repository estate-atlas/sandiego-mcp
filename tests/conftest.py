"""Shared test fixtures."""
import sys
from pathlib import Path

# Make src/ importable without an install step (handy for CI)
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
