"""pyproject.toml の Shorts 関連 console_scripts entry point の存在検証

plan 要件 #11 / 14（テスト追加）に対応する。
editable install されていない環境でも `pyproject.toml` を直接パースして検証する
ことで、CI / sandbox 環境のリグレッションを最低限担保する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _load_scripts_table() -> dict:
    """`[project.scripts]` テーブルを dict として返す."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    with open(_PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    return data.get("project", {}).get("scripts", {})


@pytest.fixture(scope="module")
def scripts() -> dict:
    return _load_scripts_table()


# ---------------------------------------------------------------------------
# 3 件の entry point 検証
# ---------------------------------------------------------------------------


def test_yt_upload_shorts_entry_registered(scripts):
    """plan 要件 #11: `yt-upload-shorts` が `short_uploader:main` を指す."""
    # When
    target = scripts.get("yt-upload-shorts")

    # Then
    assert target == "youtube_automation.agents.short_uploader:main", f"yt-upload-shorts が期待値と異なる: {target!r}"


def test_yt_generate_shorts_loop_entry_registered(scripts):
    """plan 要件 #11: `yt-generate-shorts-loop` が `generate_short_loop:main` を指す."""
    # When
    target = scripts.get("yt-generate-shorts-loop")

    # Then
    assert target == "youtube_automation.scripts.generate_short_loop:main", (
        f"yt-generate-shorts-loop が期待値と異なる: {target!r}"
    )


def test_yt_shorts_bulk_update_loc_entry_registered(scripts):
    """plan 要件 #11: `yt-shorts-bulk-update-loc` が `bulk_update_short_localizations:main` を指す."""
    # When
    target = scripts.get("yt-shorts-bulk-update-loc")

    # Then
    assert target == "youtube_automation.scripts.bulk_update_short_localizations:main", (
        f"yt-shorts-bulk-update-loc が期待値と異なる: {target!r}"
    )


def test_legacy_singular_yt_upload_short_not_registered(scripts):
    """plan アンチパターン #4: 旧 `yt-upload-short`（単数形）の alias は提供しない（fail-loud）."""
    # Then
    assert "yt-upload-short" not in scripts, (
        "旧 `yt-upload-short` (singular) は提供しないこと。fail-loud で運営者に通知する"
    )
