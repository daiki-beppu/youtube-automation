"""skill 配下の Python スクリプトをモジュールとしてロードするヘルパー。

`.claude/skills/<skill>/references/<script>.py` は package 配下に置かれていない
ため、通常の `from youtube_automation...` 形式では import できない。
本ヘルパーは Issue #137 で追加される `intro` / `masterup` の references スクリプト
を unit test から import するためだけに使う。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"


def load_skill_script(skill: str, script_name: str) -> ModuleType:
    """`.claude/skills/<skill>/references/<script>` を import する。

    Args:
        skill: スキル名 (例: "intro" / "masterup")
        script_name: 拡張子なしのスクリプトファイル名 (例: "generate_intro")

    Returns:
        ロード済みモジュール
    """
    script_path = _SKILLS_DIR / skill / "references" / f"{script_name}.py"
    if not script_path.exists():
        raise FileNotFoundError(script_path)
    module_name = f"_skill_{skill}_{script_name}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to build spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
