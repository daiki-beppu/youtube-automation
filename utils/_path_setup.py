"""automation/ ディレクトリを sys.path に追加するセットアップモジュール。

Usage:
    import utils._path_setup  # noqa: F401, E402
"""

import sys
from pathlib import Path

_automation_dir = str(Path(__file__).resolve().parent.parent)
if _automation_dir not in sys.path:
    sys.path.insert(0, _automation_dir)
