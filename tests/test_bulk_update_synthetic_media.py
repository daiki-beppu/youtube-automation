"""yt-bulk-update-synthetic-media (#606) のユニットテスト.

API モックのみで完結（チャンネル fixture 不要）。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts import bulk_update_synthetic_media as mod

# ---------------------------------------------------------------------------
# select_targets
# ---------------------------------------------------------------------------


class TestSelectTargets:
    def test_false_and_unset_are_targets_true_is_skipped(self):
        items = [
            {"video_id": "A", "title": "a", "status": {"privacyStatus": "public", "containsSyntheticMedia": False}},
            {"video_id": "B", "title": "b", "status": {"privacyStatus": "public"}},  # 未設定
            {"video_id": "C", "title": "c", "status": {"privacyStatus": "public", "containsSyntheticMedia": True}},
        ]
        targets, skipped_true, skipped_privacy = mod.select_targets(items, include_private=False)

        assert [t["video_id"] for t in targets] == ["A", "B"]
        assert skipped_true == 1
        assert skipped_privacy == 0

    def test_private_excluded_by_default(self):
        items = [
            {"video_id": "P", "title": "p", "status": {"privacyStatus": "private", "containsSyntheticMedia": False}},
            {"video_id": "U", "title": "u", "status": {"privacyStatus": "unlisted", "containsSyntheticMedia": False}},
        ]
        targets, _, skipped_privacy = mod.select_targets(items, include_private=False)

        assert [t["video_id"] for t in targets] == ["U"]
        assert skipped_privacy == 1

    def test_private_included_with_flag(self):
        items = [
            {"video_id": "P", "title": "p", "status": {"privacyStatus": "private", "containsSyntheticMedia": False}},
        ]
        targets, _, skipped_privacy = mod.select_targets(items, include_private=True)

        assert [t["video_id"] for t in targets] == ["P"]
        assert skipped_privacy == 0


# ---------------------------------------------------------------------------
# build_update_body（read-modify-write の核心）
# ---------------------------------------------------------------------------


class TestBuildUpdateBody:
    def test_preserves_existing_status_and_strips_readonly(self):
        status = {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "publishAt": "2026-01-01T00:00:00Z",
            "license": "youtube",
            "embeddable": True,
            "containsSyntheticMedia": False,
            # read-only キー（送ると 400 の恐れ）
            "uploadStatus": "processed",
            "madeForKids": False,
        }

        body = mod.build_update_body("VID", status)

        assert body["id"] == "VID"
        new_status = body["status"]
        # 既存値が保持される
        assert new_status["privacyStatus"] == "public"
        assert new_status["selfDeclaredMadeForKids"] is False
        assert new_status["publishAt"] == "2026-01-01T00:00:00Z"
        assert new_status["license"] == "youtube"
        assert new_status["embeddable"] is True
        # containsSyntheticMedia は True に差し替え
        assert new_status["containsSyntheticMedia"] is True
        # read-only キーは除去
        assert "uploadStatus" not in new_status
        assert "madeForKids" not in new_status

    def test_does_not_mutate_input_status(self):
        status = {"privacyStatus": "public", "containsSyntheticMedia": False}
        mod.build_update_body("VID", status)
        # 元 dict は不変
        assert status["containsSyntheticMedia"] is False


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _youtube_mock(video_items: list[dict], uploads_items: list[dict] | None = None) -> MagicMock:
    """channels/playlistItems/videos.list/update を備えた YouTube モックを組む."""
    yt = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]
    }
    if uploads_items is None:
        uploads_items = [{"contentDetails": {"videoId": v["id"]}} for v in video_items]
    yt.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": uploads_items,
        # nextPageToken なし → 1 ページで終了
    }
    yt.videos.return_value.list.return_value.execute.return_value = {"items": video_items}
    yt.videos.return_value.update.return_value.execute.return_value = {"id": "ok"}
    return yt


def _video(vid: str, synthetic, privacy: str = "public") -> dict:
    status: dict = {"privacyStatus": privacy}
    if synthetic is not None:
        status["containsSyntheticMedia"] = synthetic
    return {"id": vid, "snippet": {"title": f"title-{vid}"}, "status": status}


class TestMain:
    def test_dry_run_does_not_update(self, monkeypatch):
        yt = _youtube_mock([_video("V1", False), _video("V2", None)])
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-synthetic-media"])
        with (
            patch.object(mod, "get_youtube", return_value=yt),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            mod.main()
        yt.videos.return_value.update.return_value.execute.assert_not_called()
        sleep_mock.assert_not_called()

    def test_apply_updates_each_target(self, monkeypatch):
        yt = _youtube_mock([_video("V1", False), _video("V2", None)])
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-synthetic-media", "--apply"])
        with (
            patch.object(mod, "get_youtube", return_value=yt),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            mod.main()
        assert yt.videos.return_value.update.return_value.execute.call_count == 2
        assert sleep_mock.call_count == 2
        # part="status" で呼ばれる
        _, kwargs = yt.videos.return_value.update.call_args
        assert kwargs["part"] == "status"

    def test_apply_skips_already_true(self, monkeypatch):
        yt = _youtube_mock([_video("V1", True), _video("V2", True)])
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-synthetic-media", "--apply"])
        with (
            patch.object(mod, "get_youtube", return_value=yt),
            patch.object(mod.time, "sleep"),
        ):
            mod.main()  # 例外なく終了（exit しない）
        yt.videos.return_value.update.return_value.execute.assert_not_called()

    def test_empty_uploads_exits_1(self, monkeypatch):
        yt = _youtube_mock([], uploads_items=[])
        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-synthetic-media"])
        with (
            patch.object(mod, "get_youtube", return_value=yt),
            patch.object(mod.time, "sleep"),
        ):
            with pytest.raises(SystemExit) as exc:
                mod.main()
        assert exc.value.code == 1
        yt.videos.return_value.update.return_value.execute.assert_not_called()

    def test_apply_failure_exits_1_and_continues(self, monkeypatch):
        from googleapiclient.errors import HttpError

        yt = _youtube_mock([_video("V1", False), _video("V2", False)])

        resp = MagicMock()
        resp.status = 403
        http_err = HttpError(resp=resp, content=b'{"error": {"errors": [{"reason": "forbidden"}]}}')
        # V1 失敗 / V2 成功 を交互に返す
        yt.videos.return_value.update.return_value.execute.side_effect = [http_err, {"id": "ok"}]

        monkeypatch.setattr(sys, "argv", ["yt-bulk-update-synthetic-media", "--apply"])
        with (
            patch.object(mod, "get_youtube", return_value=yt),
            patch.object(mod.time, "sleep"),
        ):
            with pytest.raises(SystemExit) as exc:
                mod.main()
        # 1 件失敗しても両方 attempt し、最終的に exit 1
        assert exc.value.code == 1
        assert yt.videos.return_value.update.return_value.execute.call_count == 2
