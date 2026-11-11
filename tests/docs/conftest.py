import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# docs/ is a folder of scripts, not a package, so tests import its modules directly.
sys.path.insert(0, str(ROOT / "docs"))
