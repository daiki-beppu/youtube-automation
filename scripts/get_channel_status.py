#!/usr/bin/env python3
"""後方互換 wrapper — youtube_automation.scripts.get_channel_status:main に委譲する。"""

import sys
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from youtube_automation.scripts.get_channel_status import main  # noqa: E402

if __name__ == "__main__":
    main()
