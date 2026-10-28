"""Run the FlashRouter diagnostic without installing the package.

Examples:
    python scripts/diagnose_openrouter.py --model openrouter/auto
    python scripts/diagnose_openrouter.py --model openrouter/auto \
        --via-url http://127.0.0.1:8787/v1
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flashrouter.diagnostics import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
