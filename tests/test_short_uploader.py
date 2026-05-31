"""ShortUploader のユニットテスト

テスト対象: `youtube_automation.agents.short_uploader.ShortUploader`

plan §171 / test-design.md §44-50 §86 §117-122 §146-147 を満たすケース構成。
委譲設計（`YouTubeAutoUploader` を所有）を検証し、継承禁止の規約を回帰させる。

主要シナリオ:
- `_calculate_short_publish_at`: CC publish_at + 1day + config.shorts.publish_time の計算と TZ 適用
- `_check_upload_interval`: config.shorts.min_hours_between_shorts_per_collection の境界
- `_find_short_video`: `shorts/short-NN-*.mp4` 優先・`short.mp4` fallback・両方無で FileNotFoundError
- `upload_short`: 委譲先 `YouTubeAutoUploader.upload_video` の呼出・結果分岐
- `_update_workflow_state`: `post_upload.shorts: list[dict]` で upsert by short_num
- `__init__`: `config.shorts.enabled=false` で UploadError
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _setup_collection(
    tmp_path: Path,
    *,
    has_publish_at: bool = True,
    has_short_thumbnail: str | None = None,
    short_num: int | None = None,
    publish_at: str | None = None,
    has_tracking: bool = True,
) -> Path:
    """テスト用のコレクションディレクトリを組み立てる.

    Args:
        has_publish_at: tracking に complete_collection.publish_at を入れるか
        has_short_thumbnail: "jpg" / "png" / None
        short_num: NN 指定時に 01-master/shorts/short-NN-foo.mp4 を作る
        publish_at: 明示的な publish_at（指定無ければ「未来日」）
        has_tracking: upload_tracking.json を作るか
    """
    col = tmp_path / "collections" / "live" / "20250101-live-foo-collection"
    col.mkdir(parents=True)
    # workflow-state.json
    (col / "workflow-state.json").write_text(
        json.dumps({"theme": "battle", "collection_name": "Foo Collection"}),
        encoding="utf-8",
    )
    # upload_tracking.json
    if has_tracking:
        cc: dict = {
            "video_id": "CC_VIDEO_ID",
            "video_url": "https://youtu.be/CC_VIDEO_ID",
            "status": "completed",
            "upload_time": "2025-01-01T10:00:00+09:00",
        }
        if has_publish_at:
            cc["publish_at"] = publish_at or "2099-01-01T10:00:00+09:00"
        (col / "20-documentation").mkdir(parents=True)
        (col / "20-documentation" / "upload_tracking.json").write_text(
            json.dumps({"complete_collection": cc}),
            encoding="utf-8",
        )
    # 動画ファイル
    master = col / "01-master"
    master.mkdir()
    if short_num is not None:
        shorts_dir = master / "shorts"
        shorts_dir.mkdir()
        # 複数マッチで sorted() 検証用に 2 ファイル置く
        (shorts_dir / f"short-{short_num:02d}-alpha.mp4").write_bytes(b"\x00")
    else:
        (master / "short.mp4").write_bytes(b"\x00")
    # サムネ
    if has_short_thumbnail in ("jpg", "png"):
        assets = col / "10-assets"
        assets.mkdir()
        (assets / f"short-thumbnail.{has_short_thumbnail}").write_bytes(b"\x00")
    return col


@contextmanager
def _make_short_uploader(
    *,
    schedule_config: dict | None = None,
):
    """ShortUploader を YouTubeAutoUploader モック付きで生成する contextmanager.

    `with` ブロック内では `YouTubeAutoUploader` のパッチが有効。
    将来 `upload_short` 等が `YouTubeAutoUploader(...)` を再生成する設計に変わっても、
    パッチがブロック全体で生きているため沈黙のままパスする脆さがない（testing-review #3 解消）。

    Usage:
        with _make_short_uploader() as (uploader, mock_inner):
            mock_inner.upload_video.return_value = "V"
            ...
    """
    from youtube_automation.agents import short_uploader as su_mod

    with patch.object(su_mod, "YouTubeAutoUploader") as mock_cls:
        mock_uploader = MagicMock()
        mock_cls.return_value = mock_uploader
        uploader = su_mod.ShortUploader()
        # schedule_config を差し替え（デフォルトは {}）
        uploader.schedule_config = schedule_config or {}
        yield uploader, mock_uploader


def _freeze_short_uploader_now(monkeypatch, frozen: datetime) -> None:
    """short_uploader モジュール内の datetime.now を固定する."""
    from youtube_automation.agents import short_uploader as su_mod

    class _Fake(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(su_mod, "datetime", _Fake)


# ---------------------------------------------------------------------------
# 1. TestInit
# ---------------------------------------------------------------------------


class TestInit:
    """plan 要件 6.6 + アンチパターン #2: ShortUploader は YouTubeAutoUploader を継承せず委譲."""

    def test_short_uploader_does_not_inherit_youtube_auto_uploader(self):
        """継承禁止 — `issubclass` で YouTubeAutoUploader を継承していないことを確認."""
        # Given: 両クラスを import
        from youtube_automation.agents.short_uploader import ShortUploader
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        # When: クラス階層関係を取得
        is_subclass = issubclass(ShortUploader, YouTubeAutoUploader)

        # Then: クラス階層に YouTubeAutoUploader が含まれない
        assert is_subclass is False

    def test_short_uploader_owns_youtube_auto_uploader_instance(self):
        """plan 要件 6.6: `self.uploader = YouTubeAutoUploader(...)` 委譲構造を保証."""
        # Given/When
        with _make_short_uploader() as (uploader, mock_inner):
            # Then: `uploader.uploader` 属性が YouTubeAutoUploader モックを指す
            assert uploader.uploader is mock_inner

    def test_init_raises_when_shorts_disabled(self, tmp_path, monkeypatch):
        """`config.shorts.enabled=False` の channel では `__init__` が `UploadError` を投げる."""
        import shutil

        from youtube_automation.agents.short_uploader import ShortUploader
        from youtube_automation.utils.config import reset
        from youtube_automation.utils.exceptions import UploadError

        # Given: sample_channel をコピーして shorts.enabled=false に書き換える
        src = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
        dst = tmp_path / "channel"
        shutil.copytree(src, dst)
        (dst / "config" / "channel" / "shorts.json").write_text('{"shorts": {"enabled": false}}', encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(dst))
        reset()

        # When / Then
        with pytest.raises(UploadError, match="shorts.enabled"):
            ShortUploader()


# ---------------------------------------------------------------------------
# 2. TestCalculateShortPublishAt (plan 要件 6.2 / 14-a)
# ---------------------------------------------------------------------------


class TestCalculateShortPublishAt:
    """`_calculate_short_publish_at`: CC publish_at + 1day + short_publish_time."""

    def _freeze_now(self, monkeypatch, frozen: datetime):
        _freeze_short_uploader_now(monkeypatch, frozen)

    def test_normal_path_cc_publish_plus_one_day_plus_short_publish_time(self, tmp_path, monkeypatch):
        """plan 要件 6.2: CC publish_at の翌日 + short_publish_time."""
        # Given: now=2099-01-01 09:00, CC publish_at=2099-01-02 10:00, short_publish_time=08:00
        col = _setup_collection(tmp_path, publish_at="2099-01-02T10:00:00+09:00")
        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, _):
            # config.workflow.post_upload.short_publish_time = "08:00" は default
            self._freeze_now(monkeypatch, datetime(2099, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            publish_at = uploader._calculate_short_publish_at(col)

        # Then: CC の翌日 (2099-01-03) 08:00 JST
        assert publish_at is not None
        dt = datetime.fromisoformat(publish_at)
        assert dt.year == 2099 and dt.month == 1 and dt.day == 3
        assert dt.hour == 8 and dt.minute == 0

    def test_past_publish_date_returns_none(self, tmp_path, monkeypatch):
        """plan 要件 6.2: 算出結果が現在より過去なら None（即時公開扱い）."""
        # Given: now=2099-01-10, CC publish_at=2099-01-01（既に翌日も過去）
        col = _setup_collection(tmp_path, publish_at="2099-01-01T10:00:00+09:00")
        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, _):
            self._freeze_now(monkeypatch, datetime(2099, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            publish_at = uploader._calculate_short_publish_at(col)

        # Then: 過去のため None
        assert publish_at is None

    def test_publish_at_missing_falls_back_to_upload_time(self, tmp_path, monkeypatch):
        """plan 要件 6.2: CC.publish_at 未設定なら upload_time を基準にする."""
        # Given: publish_at なし、upload_time=2099-01-02T10:00:00+09:00
        col = _setup_collection(tmp_path, has_publish_at=False)
        # upload_time を未来に書き換え
        tracking_path = col / "20-documentation" / "upload_tracking.json"
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
        tracking["complete_collection"]["upload_time"] = "2099-01-02T10:00:00+09:00"
        tracking_path.write_text(json.dumps(tracking), encoding="utf-8")

        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, _):
            self._freeze_now(monkeypatch, datetime(2099, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            publish_at = uploader._calculate_short_publish_at(col)

        # Then: upload_time の翌日 08:00 JST
        assert publish_at is not None
        dt = datetime.fromisoformat(publish_at)
        assert dt.day == 3 and dt.hour == 8

    def test_naive_datetime_gets_timezone_applied(self, tmp_path, monkeypatch):
        """plan 要件 6.2: tracking の datetime が TZ naive なら schedule_config の TZ を適用."""
        # Given: upload_time が naive
        col = _setup_collection(tmp_path, has_publish_at=False)
        tracking_path = col / "20-documentation" / "upload_tracking.json"
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
        tracking["complete_collection"]["upload_time"] = "2099-01-02T10:00:00"
        tracking_path.write_text(json.dumps(tracking), encoding="utf-8")

        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, _):
            self._freeze_now(monkeypatch, datetime(2099, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            publish_at = uploader._calculate_short_publish_at(col)

        # Then: 翌日 08:00 JST（TZ が JST で組み立てられる）
        assert publish_at is not None
        dt = datetime.fromisoformat(publish_at)
        assert dt.tzinfo is not None
        # offset が +09:00 (Asia/Tokyo)
        assert dt.utcoffset() == timedelta(hours=9)

    def test_returns_none_when_tracking_missing(self, tmp_path):
        """tracking 自体が無いと publish_at は None 扱い."""
        # Given: tracking 無し
        col = _setup_collection(tmp_path, has_tracking=False)
        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, _):
            # When
            publish_at = uploader._calculate_short_publish_at(col)

        # Then
        assert publish_at is None


# ---------------------------------------------------------------------------
# 3. TestCheckUploadInterval (plan 要件 6.1 / 14-a)
# ---------------------------------------------------------------------------


class TestCheckUploadInterval:
    """`_check_upload_interval`: 24h 制約と境界."""

    def _freeze_now(self, monkeypatch, frozen: datetime):
        _freeze_short_uploader_now(monkeypatch, frozen)

    def test_no_previous_upload_returns_true(self, tmp_path, monkeypatch):
        """前回投稿なし → 投稿可."""
        # Given: live/ 配下に short upload 記録なし
        with _make_short_uploader(
            schedule_config={"shorts": {"min_hours_between_shorts": 24}, "schedule": {"timezone": "Asia/Tokyo"}}
        ) as (uploader, _):
            uploader.channel_dir = tmp_path  # live/ 配下が存在しない
            self._freeze_now(monkeypatch, datetime(2099, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            ok, _msg = uploader._check_upload_interval()

        # Then
        assert ok is True

    def test_under_24h_returns_false(self, tmp_path, monkeypatch):
        """前回投稿から 24h 未満 → 投稿不可."""
        # Given: live/ 配下に直近の short upload を記録（new schema list 形式）
        live = tmp_path / "collections" / "live" / "20250101-live-prev"
        live.mkdir(parents=True)
        (live / "workflow-state.json").write_text(
            json.dumps(
                {
                    "post_upload": {
                        "shorts": [
                            {
                                "short_num": None,
                                "video_id": "SHORT_PREV",
                                "uploaded_at": "2099-01-10T08:00:00+09:00",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        with _make_short_uploader(
            schedule_config={"shorts": {"min_hours_between_shorts": 24}, "schedule": {"timezone": "Asia/Tokyo"}}
        ) as (uploader, _):
            uploader.channel_dir = tmp_path
            self._freeze_now(monkeypatch, datetime(2099, 1, 10, 20, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            ok, _msg = uploader._check_upload_interval()

        # Then: 12h しか経過していないので False
        assert ok is False

    def test_over_24h_returns_true(self, tmp_path, monkeypatch):
        """前回投稿から 24h 超 → 投稿可."""
        # Given: 25h 前の short upload
        live = tmp_path / "collections" / "live" / "20250101-live-prev"
        live.mkdir(parents=True)
        (live / "workflow-state.json").write_text(
            json.dumps(
                {
                    "post_upload": {
                        "shorts": [
                            {
                                "short_num": 1,
                                "video_id": "SHORT_PREV",
                                "uploaded_at": "2099-01-09T08:00:00+09:00",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        with _make_short_uploader(
            schedule_config={"shorts": {"min_hours_between_shorts": 24}, "schedule": {"timezone": "Asia/Tokyo"}}
        ) as (uploader, _):
            uploader.channel_dir = tmp_path
            self._freeze_now(monkeypatch, datetime(2099, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            ok, _msg = uploader._check_upload_interval()

        # Then
        assert ok is True

    def test_default_24h_used_when_schedule_config_missing(self, tmp_path, monkeypatch):
        """schedule_config に shorts.min_hours_between_shorts が無ければ default 24h."""
        # Given: 23h 前の short upload, schedule_config 空
        live = tmp_path / "collections" / "live" / "20250101-live-prev"
        live.mkdir(parents=True)
        (live / "workflow-state.json").write_text(
            json.dumps(
                {
                    "post_upload": {
                        "shorts": [
                            {
                                "short_num": None,
                                "video_id": "X",
                                "uploaded_at": "2099-01-09T10:00:00+09:00",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        with _make_short_uploader(schedule_config={}) as (uploader, _):
            uploader.channel_dir = tmp_path
            self._freeze_now(monkeypatch, datetime(2099, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

            # When
            ok, _msg = uploader._check_upload_interval()

        # Then: default 24h で 23h は不足 → False
        assert ok is False


# ---------------------------------------------------------------------------
# 4. TestFindShortVideo (plan 要件 6.3 / 14-a §171)
# ---------------------------------------------------------------------------


class TestFindShortVideo:
    """`_find_short_video`: 探索順と FileNotFoundError raise."""

    def test_prefers_numbered_short_when_short_num_provided(self, tmp_path):
        """plan 要件 6.3: `short-NN-*.mp4` 優先."""
        # Given: short-01-alpha.mp4 と short.mp4 を両方置く
        col = _setup_collection(tmp_path, short_num=1)
        (col / "01-master" / "short.mp4").write_bytes(b"\x00")
        with _make_short_uploader() as (uploader, _):
            # When
            path = uploader._find_short_video(col, short_num=1)

        # Then: shorts/short-01-*.mp4 が選ばれる
        assert path.parent.name == "shorts"
        assert path.name.startswith("short-01")

    def test_falls_back_to_short_mp4_when_short_num_none(self, tmp_path):
        """plan 要件 6.3: short_num=None なら NN glob skip し short.mp4 を返す."""
        # Given: shorts/ ディレクトリは存在せず short.mp4 のみ
        col = _setup_collection(tmp_path)  # short_num=None → short.mp4 のみ

        with _make_short_uploader() as (uploader, _):
            # When
            path = uploader._find_short_video(col, short_num=None)

        # Then
        assert path.name == "short.mp4"

    def test_sorted_first_among_multiple_numbered_matches(self, tmp_path):
        """補足設計判断 §155: glob 複数マッチは sorted() 先頭を採用."""
        # Given: short-01-alpha.mp4 と short-01-beta.mp4
        col = _setup_collection(tmp_path, short_num=1)
        (col / "01-master" / "shorts" / "short-01-beta.mp4").write_bytes(b"\x00")
        with _make_short_uploader() as (uploader, _):
            # When
            path = uploader._find_short_video(col, short_num=1)

        # Then: lexicographic で先頭の "alpha" が選ばれる
        assert path.name == "short-01-alpha.mp4"

    def test_short_num_none_skips_numbered_glob_even_if_present(self, tmp_path):
        """plan 要件 6.3: short_num=None なら NN glob を完全に skip."""
        # Given: shorts/short-01-foo.mp4 と short.mp4 両方
        col = _setup_collection(tmp_path, short_num=1)
        (col / "01-master" / "short.mp4").write_bytes(b"\x00")
        with _make_short_uploader() as (uploader, _):
            # When
            path = uploader._find_short_video(col, short_num=None)

        # Then: short.mp4 が選ばれる（shorts/ は無視）
        assert path.name == "short.mp4"

    def test_raises_file_not_found_when_neither_exists(self, tmp_path):
        """plan §171 厳密準拠: 両方無で FileNotFoundError を raise."""
        # Given: 動画ファイルなし
        col = tmp_path / "collections" / "live" / "empty"
        (col / "01-master").mkdir(parents=True)
        with _make_short_uploader() as (uploader, _):
            # When/Then
            with pytest.raises(FileNotFoundError, match="short"):
                uploader._find_short_video(col, short_num=1)


# ---------------------------------------------------------------------------
# 5. TestUploadShort (plan 要件 6.4-6.6)
# ---------------------------------------------------------------------------
# Note: 旧 TestGenerateLocalizations は dead code（`ShortUploader._generate_localizations`）
# 検証のためのテストだったため、メソッド削除と合わせて撤去した（AI-NEW-short-uploader-L214）。
# Shorts fallback description ロジックは
# `test_metadata_generator_shorts.py::test_localization_description_template_missing_uses_fallback`
# が module-level helper `build_short_localizations` 経路で同等カバーする。


class TestUploadShort:
    """`upload_short` の orchestration: 成功/失敗/interval block/サムネ探索/FileNotFoundError 握り潰し."""

    def _patch_interval_ok(self, uploader):
        """interval check を ok=True に固定."""
        uploader._check_upload_interval = lambda: (True, "ok")

    def test_success_returns_short_uploaded(self, tmp_path):
        """成功時 action == 'short_uploaded'."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = "VIDEO_NEW"

            # When
            result = uploader.upload_short(col)

        # Then
        assert result["action"] == "short_uploaded"
        assert result["details"]["video_id"] == "VIDEO_NEW"

    def test_publish_at_future_passed_into_metadata(self, tmp_path, monkeypatch):
        """publish_at が未来日なら metadata に反映される."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader(schedule_config={"schedule": {"timezone": "Asia/Tokyo"}}) as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            # _calculate_short_publish_at を未来日に差し替え
            uploader._calculate_short_publish_at = lambda _col: "2099-01-03T08:00:00+09:00"
            mock_inner.upload_video.return_value = "VIDEO_X"

            # When
            uploader.upload_short(col)

            # Then: upload_video の第 2 引数 metadata に publish_at が乗っている
            call = mock_inner.upload_video.call_args
        metadata = call.args[1] if len(call.args) >= 2 else call.kwargs.get("metadata")
        assert metadata.get("publish_at") == "2099-01-03T08:00:00+09:00"

    def test_thumbnail_jpg_preferred(self, tmp_path):
        """plan 要件 6.5: 10-assets/short-thumbnail.jpg を優先."""
        # Given
        col = _setup_collection(tmp_path, has_short_thumbnail="jpg")
        # png も追加
        (col / "10-assets" / "short-thumbnail.png").write_bytes(b"\x00")
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = "V"

            # When
            uploader.upload_short(col)

            # Then: thumbnail に .jpg が渡る
            call = mock_inner.upload_video.call_args
        thumb = call.args[2] if len(call.args) >= 3 else call.kwargs.get("thumbnail_path")
        assert thumb.endswith("short-thumbnail.jpg")

    def test_thumbnail_png_fallback(self, tmp_path):
        """plan 要件 6.5: jpg が無ければ png にフォールバック."""
        # Given
        col = _setup_collection(tmp_path, has_short_thumbnail="png")
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = "V"

            # When
            uploader.upload_short(col)

            # Then
            call = mock_inner.upload_video.call_args
        thumb = call.args[2] if len(call.args) >= 3 else call.kwargs.get("thumbnail_path")
        assert thumb.endswith("short-thumbnail.png")

    def test_thumbnail_none_when_both_missing(self, tmp_path):
        """plan 要件 6.5: 両方無時 thumbnail=None で upload 続行（致命的にしない）."""
        # Given: サムネ無し
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = "V"

            # When
            result = uploader.upload_short(col)

            # Then: upload は実行され、thumbnail は None
            call = mock_inner.upload_video.call_args
        thumb = call.args[2] if len(call.args) >= 3 else call.kwargs.get("thumbnail_path")
        assert thumb is None
        assert result["action"] == "short_uploaded"

    def test_interval_block_returns_short_upload_blocked(self, tmp_path):
        """plan 要件 6.1: 24h 未満なら 'short_upload_blocked' を返す."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            # interval check fails
            uploader._check_upload_interval = lambda: (False, "wait 12h")

            # When
            result = uploader.upload_short(col)

            # Then
            assert result["action"] == "short_upload_blocked"
            # upload_video は呼ばれない
            mock_inner.upload_video.assert_not_called()

    def test_description_contains_cc_video_url(self, tmp_path):
        """description に CC URL が含まれる（generate_shorts_metadata 経由）."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = "V"

            # When
            uploader.upload_short(col)

            # Then: upload_video.metadata.description に CC URL が含まれる
            call = mock_inner.upload_video.call_args
        metadata = call.args[1] if len(call.args) >= 2 else call.kwargs.get("metadata")
        assert "https://youtu.be/CC_VIDEO_ID" in metadata["description"]

    def test_find_short_video_file_not_found_caught_and_short_upload_failed(self, tmp_path):
        """plan §171 / test-design L121-122: `_find_short_video` の FileNotFoundError は
        `upload_short` 内で握り潰され `short_upload_failed` を返す（再 raise しない）."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            # _find_short_video が raise
            with patch.object(
                uploader,
                "_find_short_video",
                side_effect=FileNotFoundError("shorts/short-01-*.mp4 や short.mp4 が無い"),
            ):
                # When
                result = uploader.upload_short(col)

            # Then
            assert result["action"] == "short_upload_failed"
            mock_inner.upload_video.assert_not_called()

    def test_tracking_missing_returns_short_upload_failed(self, tmp_path):
        """tracking 無時 'short_upload_failed' を返す."""
        # Given: tracking 無し
        col = _setup_collection(tmp_path, has_tracking=False)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)

            # When
            result = uploader.upload_short(col)

            # Then
            assert result["action"] == "short_upload_failed"
            mock_inner.upload_video.assert_not_called()

    def test_upload_video_returns_none_yields_short_upload_failed(self, tmp_path):
        """委譲先 upload_video が None を返したら 'short_upload_failed'."""
        # Given
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, mock_inner):
            self._patch_interval_ok(uploader)
            mock_inner.upload_video.return_value = None

            # When
            result = uploader.upload_short(col)

        # Then
        assert result["action"] == "short_upload_failed"


# ---------------------------------------------------------------------------
# 7. TestUpdateWorkflowState (plan アンチパターン #10 / test-design TDR-002)
# ---------------------------------------------------------------------------


class TestUpdateWorkflowState:
    """`_update_workflow_state` のスキーマ: `post_upload.shorts: list[dict]` で `short_num` をキーに upsert.

    `bulk_update_short_localizations.collect_short_videos` と同スキーマで対称検証する。
    """

    def test_initial_write_creates_list_entry(self, tmp_path):
        """初回書き込みで `post_upload.shorts = [{...}]` の list を作る."""
        # Given: workflow-state.json が空
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, _):
            # When
            uploader._update_workflow_state(
                col,
                short_num=1,
                video_id="V1",
                publish_at="2099-01-03T08:00:00+09:00",
            )

        # Then
        ws = json.loads((col / "workflow-state.json").read_text(encoding="utf-8"))
        shorts = ws["post_upload"]["shorts"]
        assert isinstance(shorts, list)
        assert len(shorts) == 1
        assert shorts[0]["short_num"] == 1
        assert shorts[0]["video_id"] == "V1"

    def test_uploaded_at_is_schedule_timezone_aware(self, tmp_path):
        """uploaded_at は schedule timezone 付き ISO 8601 で書かれる."""
        col = _setup_collection(tmp_path)
        with _make_short_uploader(schedule_config={"schedule": {"timezone": "UTC"}}) as (uploader, _):
            uploader._update_workflow_state(col, short_num=1, video_id="V1", publish_at=None)

        ws = json.loads((col / "workflow-state.json").read_text(encoding="utf-8"))
        uploaded_at = ws["post_upload"]["shorts"][0]["uploaded_at"]
        dt = datetime.fromisoformat(uploaded_at)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)

    def test_same_short_num_replaces_existing_entry(self, tmp_path):
        """同じ `short_num` を再 upsert したら既存 entry が置換される."""
        # Given: 既に short_num=1 で V1 を書いた状態
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, _):
            uploader._update_workflow_state(col, short_num=1, video_id="V1", publish_at=None)

            # When: 同じ short_num=1 を別 video_id で再 upsert
            uploader._update_workflow_state(col, short_num=1, video_id="V1_NEW", publish_at=None)

        # Then: list の長さは 1 のままで V1_NEW に置換
        ws = json.loads((col / "workflow-state.json").read_text(encoding="utf-8"))
        shorts = ws["post_upload"]["shorts"]
        assert len(shorts) == 1
        assert shorts[0]["video_id"] == "V1_NEW"

    def test_different_short_num_appends(self, tmp_path):
        """異なる `short_num` は append される."""
        # Given: short_num=1 を書く
        col = _setup_collection(tmp_path)
        with _make_short_uploader() as (uploader, _):
            uploader._update_workflow_state(col, short_num=1, video_id="V1", publish_at=None)

            # When: short_num=2 を書く
            uploader._update_workflow_state(col, short_num=2, video_id="V2", publish_at=None)

        # Then: list の長さは 2
        ws = json.loads((col / "workflow-state.json").read_text(encoding="utf-8"))
        shorts = ws["post_upload"]["shorts"]
        assert len(shorts) == 2
        nums = {s["short_num"] for s in shorts}
        assert nums == {1, 2}

    def test_skips_when_workflow_state_missing(self, tmp_path):
        """workflow-state.json が無ければ warning を出して skip（致命的にしない）."""
        # Given: workflow-state.json なし
        col = tmp_path / "collections" / "live" / "ws-missing"
        col.mkdir(parents=True)
        with _make_short_uploader() as (uploader, _):
            # When: 例外を投げず処理が終わる
            uploader._update_workflow_state(col, short_num=1, video_id="V1", publish_at=None)

        # Then: ファイルは作成されない
        assert not (col / "workflow-state.json").exists()
