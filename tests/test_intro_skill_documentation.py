"""Issue #137: SKILL.md / CLAUDE.md ドキュメント整合性テスト (H 節)。

`/intro` 自動登録、`/masterup` Step 5.5、`/videoup` Intro 統合モード、
project root CLAUDE.md の主要モジュール表、version 整合 (pyproject.toml /
__version__) — 利用者の到達経路と運用契約を担保するドキュメント側の検証。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

INTRO_SKILL_MD = _SKILLS_DIR / "intro" / "SKILL.md"
MASTERUP_SKILL_MD = _SKILLS_DIR / "masterup" / "SKILL.md"
VIDEOUP_SKILL_MD = _SKILLS_DIR / "videoup" / "SKILL.md"
PROJECT_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"
PYPROJECT_TOML = _REPO_ROOT / "pyproject.toml"
PACKAGE_INIT = _REPO_ROOT / "src" / "youtube_automation" / "__init__.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    """SKILL.md の先頭 frontmatter (`---` 区切り) のみ抽出する。"""
    match = re.match(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md frontmatter (--- ... ---) が見つかりません")
    return match.group(1)


# ---------- H-1: intro/SKILL.md frontmatter ----------


def test_intro_skill_md_exists() -> None:
    """Given Issue #137 で追加される intro skill
    When .claude/skills/intro/SKILL.md を探す
    Then ファイルが存在する。
    """
    assert INTRO_SKILL_MD.exists(), f"{INTRO_SKILL_MD} が存在しない (intro skill 未配置)"


def test_intro_skill_md_declares_name_intro() -> None:
    """Given intro/SKILL.md
    When frontmatter を読む
    Then `name: intro` が宣言されている (/intro Claude command 自動登録の入口)。
    """
    fm = _frontmatter(_read(INTRO_SKILL_MD))
    assert re.search(r"^name:\s*intro\s*$", fm, flags=re.MULTILINE), (
        f"frontmatter に `name: intro` が無い:\n{fm}"
    )


# ---------- H-2: intro/SKILL.md 4-step 手順 ----------


def test_intro_skill_md_describes_4_step_flow() -> None:
    """Given intro/SKILL.md 本文
    When 4-step 手順を探す
    Then Gemini 静止画 → Veo loop → 雫 PNG → intro.mp4 ビルドの 4 段階に
        対応するキーワードが揃っている。
    """
    text = _read(INTRO_SKILL_MD)
    # 必須キーワード (大文字小文字無視)
    needles = ["Gemini", "Veo", "droplet", "intro.mp4"]
    missing = [n for n in needles if n.lower() not in text.lower()]
    assert not missing, f"intro/SKILL.md に欠落したキーワード: {missing}"


# ---------- H-3: masterup/SKILL.md Step 5.5 ----------


def test_masterup_skill_md_adds_step_5_5_finalize_master() -> None:
    """Given masterup/SKILL.md
    When 既存 Step 5 の後ろを探す
    Then `Step 5.5` セクションが追加され、`finalize_master.py` を案内する。
    """
    text = _read(MASTERUP_SKILL_MD)
    assert re.search(r"Step\s*5\.5", text), (
        "masterup/SKILL.md に `Step 5.5` セクションが無い"
    )
    assert "finalize_master.py" in text, (
        "masterup/SKILL.md が `finalize_master.py` を案内していない"
    )


def test_masterup_skill_md_step_5_5_appears_after_step_5() -> None:
    """Given masterup/SKILL.md
    When Step 番号の出現順を確認
    Then `Step 5` の後に `Step 5.5` が出現する (順序リグレッション防止)。
    """
    text = _read(MASTERUP_SKILL_MD)
    pos5 = text.find("Step 5")
    pos55 = text.find("Step 5.5")
    assert pos5 != -1, "`Step 5` が見つからない"
    assert pos55 != -1, "`Step 5.5` が見つからない"
    assert pos55 > pos5, "`Step 5.5` は `Step 5` の後に来るべき"


# ---------- H-4: videoup/SKILL.md Intro 統合モード ----------


def test_videoup_skill_md_declares_intro_mode_section() -> None:
    """Given videoup/SKILL.md
    When Intro 統合モード節を探す
    Then `branding/intro.mp4` 検知の説明が含まれる。
    """
    text = _read(VIDEOUP_SKILL_MD)
    # "Intro 統合モード" or "intro mode" のいずれかを許容 (実装の表記ゆれを吸収)
    assert re.search(r"(Intro\s*統合モード|intro\s*mode)", text, flags=re.IGNORECASE), (
        "videoup/SKILL.md に Intro 統合モード節が無い"
    )
    assert "branding/intro.mp4" in text, (
        "videoup/SKILL.md が `branding/intro.mp4` 検知の前提条件を明記していない"
    )


def test_videoup_skill_md_separates_audio_video_responsibility() -> None:
    """Given videoup/SKILL.md Intro 統合モード節
    When 責務分界の記述を探す
    Then 「音声合成は finalize_master.py / videoup は pure concat (video のみ)」の
        意図が読み取れる (音声 mix を videoup が担当しないことの明示)。
    """
    text = _read(VIDEOUP_SKILL_MD)
    assert "finalize_master" in text, (
        "videoup/SKILL.md に finalize_master.py 側の責務分界が書かれていない"
    )


# ---------- H-5: project CLAUDE.md ----------


def test_claude_md_lists_intro_skill_in_main_modules() -> None:
    """Given project root の CLAUDE.md 「主要モジュール」表
    When intro skill のエントリを探す
    Then `/intro` (もしくは intro skill) が明示的に列挙されている。
    """
    text = _read(PROJECT_CLAUDE_MD)
    # intro skill への言及があること (他 skill 一覧と同じ流儀で書かれているはず)
    assert re.search(r"`?/?intro`?", text), (
        "CLAUDE.md に intro skill への言及が無い"
    )
    # 設計 D / 30s intro の言及で、単なる文字列衝突 (e.g. "introduction") を排除
    has_design_d = "設計 D" in text or "10s afade-in" in text
    has_30s = "30s" in text or "30 秒" in text
    assert has_design_d or has_30s, (
        "CLAUDE.md に設計 D もしくは 30s intro の言及が無い (単なる文字列衝突の可能性)"
    )


# ---------- H-6: version 整合性 ----------


def _pyproject_version() -> str:
    with PYPROJECT_TOML.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _package_version() -> str:
    """`__version__ = "x.y.z"` を AST 経由で取得 (import を避ける)。"""
    text = _read(PACKAGE_INIT)
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', text, flags=re.MULTILINE)
    if not match:
        raise AssertionError("__init__.py に `__version__ = '...'` が見つからない")
    return match.group(1)


def test_version_bumped_to_5_5_0() -> None:
    """Given Issue #137 の plan
    When pyproject.toml と __version__ を読む
    Then どちらも `5.5.0` に bump されている。
    """
    assert _pyproject_version() == "5.5.0", (
        f"pyproject.toml の version が 5.5.0 でない: {_pyproject_version()!r}"
    )
    assert _package_version() == "5.5.0", (
        f"src/youtube_automation/__init__.py の __version__ が 5.5.0 でない: {_package_version()!r}"
    )


def test_pyproject_version_matches_package_version() -> None:
    """Given CLAUDE.md:113-114 の規約 (両方を更新する)
    When 両ファイルを読む
    Then 値が完全一致する。
    """
    assert _pyproject_version() == _package_version(), (
        f"version 不整合: pyproject.toml={_pyproject_version()!r}, "
        f"__version__={_package_version()!r}"
    )


# ---------- 補助: 修正対象ファイル一覧の sanity check ----------


@pytest.mark.parametrize(
    "path",
    [INTRO_SKILL_MD, MASTERUP_SKILL_MD, VIDEOUP_SKILL_MD, PROJECT_CLAUDE_MD],
    ids=["intro/SKILL.md", "masterup/SKILL.md", "videoup/SKILL.md", "CLAUDE.md"],
)
def test_target_documentation_files_exist(path: Path) -> None:
    """前提: 本テスト対象のドキュメントファイルが存在すること。"""
    assert path.exists(), f"{path} が存在しない"
