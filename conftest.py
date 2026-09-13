"""Ensures the kit root (this file's directory) is importable as-is, so
tests can `import run`, `import config`, `from pipeline...`, and
`from erp import erp_book` regardless of the pytest invocation directory."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
