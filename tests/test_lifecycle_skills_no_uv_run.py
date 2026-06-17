"""Issue #965: lifecycle skills の dogfood 起動文字列を検証する。

対象 skill は agent/operator がコピーして実行する CLI 例を含むため、Issue #965 の
受入基準どおり legacy uv prefix と旧 bin 名 `bunx yt` の残存を固定する。
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
    "suno-helper",
    "masterup",
    "videoup",
    "video-upload",
    "thumbnail",
    "video-description",
    "analytics-collect",
    "playlist",
    "distrokid-prep",
)

_FORBIDDEN_COMMAND_FRAGMENTS: Final[tuple[str, ...]] = (
    "uv run",
    "bunx yt",
)

_FORBIDDEN_LEGACY_COMMAND_REFERENCES: Final[tuple[tuple[str, str], ...]] = (
    ("suno", "yt-generate-suno"),
    ("suno", "yt-video-analyze"),
    ("suno", "yt-collection-serve"),
    ("wf-new", "yt-analytics"),
    ("wf-new", "yt-collection-serve"),
    ("wf-new", "yt-video-analyze"),
    ("wf-new", "yt-init-collection"),
    ("wf-new", "yt-metadata-audit"),
    ("wf-new", "yt-populate-scene-phrases"),
    ("video-upload", "yt-upload-auto"),
    ("video-upload", "yt-upload-collection"),
)


def _lifecycle_skill_dir(skill_name: str) -> Path:
    return _SKILLS_DIR / skill_name


def _text_files_under(skill_dir: Path) -> list[Path]:
    return sorted(path for path in skill_dir.rglob("*") if path.is_file())


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
    """Given Issue #965 対象 skill 名
    When `.claude/skills/<name>` を参照する
    Then skill ディレクトリが存在する。
    """
    skill_dir = _lifecycle_skill_dir(skill_name)

    assert skill_dir.is_dir(), f"Issue #965 対象 skill が見つかりません: {skill_dir}"
    assert _text_files_under(skill_dir), f"Issue #965 対象 skill が空です: {skill_dir}"


@pytest.mark.parametrize("skill_name", _LIFECYCLE_SKILL_NAMES)
@pytest.mark.parametrize("forbidden_fragment", _FORBIDDEN_COMMAND_FRAGMENTS)
def test_lifecycle_skills_do_not_use_legacy_command_prefixes(
    skill_name: str,
    forbidden_fragment: str,
) -> None:
    """Given Issue #965 対象 lifecycle skill と references 配下の全ファイル
    When legacy command prefix を検索する
    Then `bunx tayk <cmd>` へ置換すべき旧起動文字列は残っていない。
    """
    skill_dir = _lifecycle_skill_dir(skill_name)

    offenders = _offending_locations(skill_dir, forbidden_fragment)

    assert not offenders, (
        f"{skill_name} に {forbidden_fragment!r} が残っています。"
        " `bunx tayk <cmd>` 形式へ置換してください:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    ("skill_name", "legacy_command"),
    _FORBIDDEN_LEGACY_COMMAND_REFERENCES,
)
def test_lifecycle_skills_do_not_keep_rewritten_legacy_command_names(
    skill_name: str,
    legacy_command: str,
) -> None:
    """Given `bunx tayk` へ置換済みの lifecycle skill
    When 旧 entry point 名を検索する
    Then 同じ skill 内で旧名と新名は混在していない。
    """
    skill_dir = _lifecycle_skill_dir(skill_name)

    offenders = _offending_locations(skill_dir, legacy_command)

    assert not offenders, (
        f"{skill_name} に legacy command {legacy_command!r} が残っています。"
        " `bunx tayk <cmd>` 形式へ統一してください:\n  " + "\n  ".join(offenders)
    )
