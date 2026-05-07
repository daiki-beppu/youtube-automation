"""Issue #137: intro skill の `yt-skills sync` 自動列挙と config 配布 (I 節)。

`pyproject.toml` の force-include は `.claude/skills` を自動同梱するため
新規ディレクトリ追加に追加設定は不要だが、配布失敗の早期検出として
新規 intro skill が `_list_entries` に拾われ、`_default_path("intro")` で
config.default.yaml が解決可能であることを検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.cli import skills_sync
from youtube_automation.cli.skills_sync import _asset_root, _list_entries
from youtube_automation.utils import skill_config

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def real_skills_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """test_skills_sync.py の fake_repo を使わず、実 .claude/skills/ を見る fixture。

    editable fallback が `_editable_root() = repo_root` を返す前提を維持して
    実際にリポジトリ配下の `.claude/skills/intro/` がスキルとして列挙されるかを確認する。
    """
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: _REPO_ROOT)
    return _REPO_ROOT


# ---------- I-1: yt-skills sync が新規 intro skill を列挙する ----------


def test_list_entries_includes_intro_skill(real_skills_root: Path) -> None:
    """Given .claude/skills/intro/ ディレクトリが追加されている
    When yt-skills sync の自動列挙ロジック (_list_entries) を呼ぶ
    Then `intro` がリストに含まれる (= wheel 同梱経路で自動配布される)。
    """
    root = _asset_root("skills")
    entries = _list_entries(root)
    assert "intro" in entries, (
        f"`intro` が _list_entries の結果に無い (skill ディレクトリが未配置): "
        f"{entries}"
    )


# ---------- I-2: skill_config._default_path("intro") で config.default.yaml が解決される ----------


def test_intro_config_default_yaml_is_discoverable() -> None:
    """Given upstream に同梱される `intro/config.default.yaml`
    When skill_config._default_path("intro") を呼ぶ
    Then config.default.yaml の Path が返り、ファイルが存在する
        (wheel / editable いずれでも解決可能であること)。
    """
    path = skill_config._default_path("intro")
    assert path.exists(), f"intro/config.default.yaml が解決できない: {path}"
    assert path.name == "config.default.yaml"
