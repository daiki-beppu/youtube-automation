"""Issue #1625: lifecycle skills の起動文字列に `bunx tayk` 表記が入らないことを固定する。

経緯:
- Issue #965 で lifecycle skill の起動文字列を `uv run yt-*` → `bunx tayk <cmd>` へ
  一括置換し、本テストの前身（test_lifecycle_skills_no_uv_run.py）が
  `uv run` の残存を禁止していた。
- しかし tayk は次世代版 CLI であり現時点ではまだ運用で使用できない
  （実装は別リポジトリへ分離予定）。スキルを読んだ AI 実行者が実行不能コマンドで
  つまずくため、Issue #1625 で表記を `uv run yt-*` へ戻し、本テストは方針を反転した。
- tayk cutover（運用開始）時には本テストを再度反転し、`uv run yt-*` の残存禁止へ戻すこと。
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_SKILLS_DIR: Final[Path] = _REPO_ROOT / ".claude" / "skills"

_LIFECYCLE_SKILL_NAMES: Final[tuple[str, ...]] = (
    "wf-new",
    "wf-next",
    "suno",
    "suno-lyric",
    "suno-helper",
    "masterup",
    "videoup",
    "video-upload",
    "thumbnail",
    "video-description",
    "analytics-collect",
    "playlist",
    "distrokid-helper",
)

# tayk cutover までは、lifecycle skill の実行手順に tayk 表記
# （`bunx tayk <cmd>` / argv 配列の "tayk" など）を混入させない。
_FORBIDDEN_COMMAND_FRAGMENTS: Final[tuple[str, ...]] = ("tayk",)
_TEXT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".json",
        ".md",
        ".py",
        ".sh",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)


def _lifecycle_skill_dir(skill_name: str) -> Path:
    return _SKILLS_DIR / skill_name


def _text_files_under(skill_dir: Path) -> list[Path]:
    return sorted(path for path in skill_dir.rglob("*") if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES)


def _offending_locations(skill_dir: Path, forbidden_fragment: str) -> list[str]:
    offenders: list[str] = []
    for path in _text_files_under(skill_dir):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if forbidden_fragment in line:
                relative_path = path.relative_to(_REPO_ROOT)
                offenders.append(f"{relative_path}:{line_number}: {line.strip()}")
    return offenders


@pytest.mark.parametrize("skill_name", _LIFECYCLE_SKILL_NAMES)
def test_lifecycle_skill_directory_exists(skill_name: str) -> None:
    """Given lifecycle skill 名
    When `.claude/skills/<name>` を参照する
    Then skill ディレクトリが存在する。
    """
    skill_dir = _lifecycle_skill_dir(skill_name)

    assert skill_dir.is_dir(), f"lifecycle skill が見つかりません: {skill_dir}"
    assert _text_files_under(skill_dir), f"lifecycle skill が空です: {skill_dir}"


@pytest.mark.parametrize("skill_name", _LIFECYCLE_SKILL_NAMES)
@pytest.mark.parametrize("forbidden_fragment", _FORBIDDEN_COMMAND_FRAGMENTS)
def test_lifecycle_skills_do_not_reference_tayk(
    skill_name: str,
    forbidden_fragment: str,
) -> None:
    """Given lifecycle skill と references 配下の全ファイル
    When 未 cutover の次世代 CLI `tayk` への参照を検索する
    Then 実行不能な `bunx tayk <cmd>` 表記は残っていない（Issue #1625）。

    tayk cutover 時にはこのテストを反転し、`uv run yt-*` の残存禁止へ戻すこと。
    """
    skill_dir = _lifecycle_skill_dir(skill_name)

    offenders = _offending_locations(skill_dir, forbidden_fragment)

    assert not offenders, (
        f"{skill_name} に {forbidden_fragment!r} が含まれています。"
        " tayk は未 cutover のため、実行手順は `uv run yt-<cmd>` 形式で書いてください"
        " (Issue #1625):\n  " + "\n  ".join(offenders)
    )
