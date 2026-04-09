"""後方互換 shim — `from utils.xxx import` を youtube_automation.utils.xxx に転送する。

このディレクトリは git submodule 経由で automation/ を取り込んでいる
downstream repo (goa, rjn など) のために残されている。

新規利用者は `from youtube_automation.utils.xxx import ...` を使うこと。
"""

import importlib
import pkgutil
import sys
from pathlib import Path

# pip install されていない (submodule 形態) 場合に備えて src/ を sys.path に追加
_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import youtube_automation.utils as _real  # noqa: E402

# `utils` 自身を youtube_automation.utils の alias にする。
sys.modules[__name__] = _real

# 全サブモジュールも `utils.<name>` で参照できるよう alias 登録する。
# (`from utils.channel_config import X` のような import を維持するため)
for _info in pkgutil.iter_modules(_real.__path__):
    _full = f"youtube_automation.utils.{_info.name}"
    _alias = f"utils.{_info.name}"
    if _alias not in sys.modules:
        sys.modules[_alias] = importlib.import_module(_full)
