"""後方互換 shim — `from auth.oauth_handler import` を youtube_automation.auth.oauth_handler に転送する。

ルート `auth/` ディレクトリには `client_secrets.json`, `client_secrets_template.json`,
`SETUP.md` などの非 Python ファイルも残置されている。
"""

import importlib
import pkgutil
import sys
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import youtube_automation.auth as _real  # noqa: E402

sys.modules[__name__] = _real

for _info in pkgutil.iter_modules(_real.__path__):
    _full = f"youtube_automation.auth.{_info.name}"
    _alias = f"auth.{_info.name}"
    if _alias not in sys.modules:
        sys.modules[_alias] = importlib.import_module(_full)
