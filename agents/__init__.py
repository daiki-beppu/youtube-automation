"""後方互換 shim — `from agents.xxx import` を youtube_automation.agents.xxx に転送する。"""

import importlib
import pkgutil
import sys
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import youtube_automation.agents as _real  # noqa: E402

sys.modules[__name__] = _real

for _info in pkgutil.iter_modules(_real.__path__):
    _full = f"youtube_automation.agents.{_info.name}"
    _alias = f"agents.{_info.name}"
    if _alias not in sys.modules:
        sys.modules[_alias] = importlib.import_module(_full)
