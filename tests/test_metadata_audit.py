"""metadata_audit のリモート監査ロジックの回帰テスト.

YouTube Data API v3 公式コード `zh-CN` / `zh-TW` への期待値判定を検証する。
issue #82 の再発防止として、旧コード (`zh-Hans` / `zh-Hant`) を期待値に戻さないことを保証する。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# metadata_audit.py は module-level で channel_dir() を呼ぶため、import 前に
# CHANNEL_DIR を fixture に向ける必要がある（conftest の session-scope fixture は
# collection phase より後に走るため import に間に合わない）。
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
os.environ.setdefault("CHANNEL_DIR", str(_FIXTURE))

import pytest  # noqa: E402

from youtube_automation.scripts.metadata_audit import audit_remote  # noqa: E402

_ZH_ISSUE_TOKEN = "zh codes"  # `metadata_audit.py` のエラー文言 "YT zh codes are ..." に対応


def _yt_response(video_id: str, locs: dict[str, dict]) -> dict:
    """`videos.list()` レスポンスを最小構成で組み立てる."""
    return {
        "items": [
            {
                "id": video_id,
                "snippet": {"title": "test title", "description": "test description"},
                "localizations": locs,
            }
        ]
    }


def _patched_yt(response: dict) -> MagicMock:
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = response
    return yt


class TestAuditRemoteZhCodes:
    """audit_remote の zh-codes 期待値判定."""

    @pytest.mark.parametrize(
        "locs, expected_count, must_contain",
        [
            pytest.param(
                {
                    "zh-CN": {"title": "标题", "description": "desc"},
                    "zh-TW": {"title": "標題", "description": "desc"},
                },
                0,
                [],
                id="canonical_codes_pass",
            ),
            pytest.param(
                {
                    "zh-Hans": {"title": "标题", "description": "desc"},
                    "zh-Hant": {"title": "標題", "description": "desc"},
                },
                1,
                ["zh-CN", "zh-TW"],
                id="legacy_codes_flagged",
            ),
            pytest.param(
                {"zh-CN": {"title": "标题", "description": "desc"}},
                1,
                [],
                id="partial_codes_flagged",
            ),
        ],
    )
    def test_zh_codes(self, locs: dict[str, dict], expected_count: int, must_contain: list[str]) -> None:
        video_id = "VID"
        with patch(
            "youtube_automation.utils.youtube_service.get_youtube",
            return_value=_patched_yt(_yt_response(video_id, locs)),
        ):
            result = audit_remote({video_id: "test-collection"})
        zh_issues = [i for i in result[video_id] if _ZH_ISSUE_TOKEN in i]
        assert len(zh_issues) == expected_count
        for token in must_contain:
            assert token in zh_issues[0]
