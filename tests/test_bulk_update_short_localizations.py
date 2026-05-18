"""scripts/bulk_update_short_localizations.py のユニットテスト

plan 要件 #10 / 14-d / アンチパターン #8 を検証する:
- `collect_short_videos`: live/*/workflow-state.json の `post_upload.shorts: list` から video_id 収集
- tracking 欠如時 skip
- `build_short_localizations`（共通 helper）経由の各言語生成 / theme 反映
- short_title_template 欠如時の言語 skip
- dry-run 時に execute() されない
- 通常実行で `videos().update().execute()` が動画数分呼ばれる
- 成功 1 回ごとに `time.sleep(0.5)`
- 対象 0 件で `SystemExit(1)`
- `generate_shorts_metadata` と `bulk_update` 出力の parity（theme 反映）
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.utils.config import load_config, reset
from youtube_automation.utils.metadata_generator import build_short_localizations

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _setup_channel(tmp_path: Path, *, with_short_template: bool = True) -> Path:
    """sample_channel をコピーし localizations を差し替えたチャンネル dir を返す."""
    src = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
    dst = tmp_path / "channel"
    shutil.copytree(src, dst)
    loc_data = {
        "supported_languages": ["ja", "en"],
        "default_language": "ja",
        "languages": {
            "ja": {
                "title_template": "{scene_phrase}",
                "description": {"tagline": "JP tagline"},
            },
            "en": {
                "title_template": "{scene_phrase}",
                "description": {"tagline": "EN tagline"},
            },
        },
    }
    if with_short_template:
        loc_data["languages"]["ja"]["short_title_template"] = "{theme} | {channel_name} #Shorts"
        loc_data["languages"]["ja"]["short_description_template"] = (
            "{collection_name} | {channel_name}\n♫ → {cc_video_url}\n{tagline}"
        )
        loc_data["languages"]["en"]["short_title_template"] = "{theme} ✦ {channel_name} #Shorts"
        loc_data["languages"]["en"]["short_description_template"] = (
            "{collection_name} | {channel_name}\n♫ → {cc_video_url}\n{tagline}"
        )
    (dst / "config" / "localizations.json").write_text(json.dumps(loc_data, ensure_ascii=False), encoding="utf-8")
    yt_path = dst / "config" / "channel" / "youtube.json"
    yt = json.loads(yt_path.read_text(encoding="utf-8"))
    yt.setdefault("content_model", {})["languages"] = list(loc_data["supported_languages"])
    yt_path.write_text(json.dumps(yt, ensure_ascii=False), encoding="utf-8")
    return dst


def _make_collection_with_shorts(ch: Path, name: str, *, shorts: list[dict], cc_video_url: str = "https://youtu.be/CC"):
    """live/<name>/ コレクションを作る (post_upload.shorts list 形式)."""
    col = ch / "collections" / "live" / name
    col.mkdir(parents=True)
    (col / "workflow-state.json").write_text(
        json.dumps(
            {
                "collection_name": name.replace("-", " ").title(),
                "theme": "battle",
                "post_upload": {"shorts": shorts},
            }
        ),
        encoding="utf-8",
    )
    (col / "20-documentation").mkdir(parents=True)
    (col / "20-documentation" / "upload_tracking.json").write_text(
        json.dumps({"complete_collection": {"video_url": cc_video_url}}),
        encoding="utf-8",
    )
    return col


# ---------------------------------------------------------------------------
# 1. collect_short_videos
# ---------------------------------------------------------------------------


class TestCollectShortVideos:
    """live/*/workflow-state.json から video_id を収集（list 形式スキーマ）."""

    def test_collects_from_post_upload_shorts_list(self, tmp_path, monkeypatch):
        """plan 要件 14-d: `post_upload.shorts: list` から video_id を集める."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_shorts(
            ch,
            "20250101-live-foo",
            shorts=[
                {"short_num": 1, "video_id": "V_FOO_1", "uploaded_at": "2025-01-01T08:00:00+09:00"},
            ],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        videos = mod.collect_short_videos()

        # Then
        ids = [v["video_id"] for v in videos]
        assert "V_FOO_1" in ids

    def test_skips_collections_without_tracking(self, tmp_path, monkeypatch):
        """tracking 欠如時はそのコレクションを skip."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given: tracking なしのコレクションを 1 つ作る
        ch = _setup_channel(tmp_path)
        col = ch / "collections" / "live" / "20250101-live-no-tracking"
        col.mkdir(parents=True)
        (col / "workflow-state.json").write_text(
            json.dumps({"post_upload": {"shorts": [{"short_num": 1, "video_id": "V_NOTRACK"}]}}),
            encoding="utf-8",
        )
        # tracking ファイル無し
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        videos = mod.collect_short_videos()

        # Then: 収集されない
        ids = [v["video_id"] for v in videos]
        assert "V_NOTRACK" not in ids

    def test_skips_entries_without_video_id(self, tmp_path, monkeypatch):
        """`shorts` list 内に video_id 欠落 entry があれば skip."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        ch = _setup_channel(tmp_path)
        _make_collection_with_shorts(
            ch,
            "20250101-live-foo",
            shorts=[
                {"short_num": 1},  # video_id 欠落
                {"short_num": 2, "video_id": "V_OK"},
            ],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()

        # When
        videos = mod.collect_short_videos()
        ids = [v["video_id"] for v in videos]

        # Then
        assert "V_OK" in ids
        assert None not in ids
        assert len(videos) == 1


# ---------------------------------------------------------------------------
# 2. build_short_localizations 経由の検証
# ---------------------------------------------------------------------------
# bulk_update は `metadata_generator.build_short_localizations` を直接呼ぶようになったため、
# テストも module helper を直接検証する（AI-NEW-shorts-localizations-DRY 対応で 3 経路統一）。


class TestBuildShortLocalizations:
    """short_title_template の有無で言語が含まれる/skip される."""

    def test_includes_languages_with_short_title_template(self, tmp_path, monkeypatch):
        # Given: ja / en の両方に short_title_template あり
        ch = _setup_channel(tmp_path, with_short_template=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        config = load_config()

        # When
        locs = build_short_localizations(
            config,
            collection_name="Foo Collection",
            theme="battle",
            cc_video_url="https://youtu.be/CC",
        )

        # Then
        assert "ja" in locs
        assert "en" in locs

    def test_skips_languages_without_short_title_template(self, tmp_path, monkeypatch):
        # Given: short_title_template 全言語欠如
        ch = _setup_channel(tmp_path, with_short_template=False)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        config = load_config()

        # When
        locs = build_short_localizations(
            config,
            collection_name="Foo",
            theme="battle",
            cc_video_url="https://youtu.be/CC",
        )

        # Then
        assert locs == {}

    def test_theme_is_substituted_into_title_template(self, tmp_path, monkeypatch):
        """AI-NEW-bulk-update-loc-L161 回帰: theme が title template に反映される.

        旧 bulk_update は `theme=""` ハードコードで初回 upload のタイトル
        （`generate_shorts_metadata` 由来）を破壊していた。共通 helper 経由で
        `theme` 必須化することで、bulk_update 経路でも初回と同じタイトルが出ることを保証する.
        """
        # Given
        ch = _setup_channel(tmp_path, with_short_template=True)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        config = load_config()

        # When
        locs = build_short_localizations(
            config,
            collection_name="Foo Collection",
            theme="battle",
            cc_video_url="https://youtu.be/CC",
        )

        # Then: title に theme が埋め込まれている
        # ja: "{theme} | {channel_name} #Shorts"
        assert locs["ja"]["title"].startswith("battle | ")
        # en: "{theme} ✦ {channel_name} #Shorts"
        assert locs["en"]["title"].startswith("battle ✦ ")


# ---------------------------------------------------------------------------
# 3. main: dry-run / 実行 / sleep / 0 件
# ---------------------------------------------------------------------------


class TestMain:
    """plan 要件 14-d: dry-run / execute / time.sleep(0.5) / 0 件で SystemExit(1)."""

    def _build_youtube_mock(self) -> MagicMock:
        yt = MagicMock()
        yt.videos.return_value.update.return_value.execute.return_value = {"id": "ok"}
        return yt

    def test_main_dry_run_does_not_call_execute(self, tmp_path, monkeypatch):
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given
        ch = _setup_channel(tmp_path)
        _make_collection_with_shorts(
            ch,
            "20250101-live-foo",
            shorts=[{"short_num": 1, "video_id": "V1"}],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-shorts-bulk-update-loc", "--dry-run"])
        yt_mock = self._build_youtube_mock()

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            # When
            try:
                mod.main()
            except SystemExit as e:
                assert e.code in (None, 0)

            # Then: execute は呼ばれない、sleep もしない
            yt_mock.videos.return_value.update.return_value.execute.assert_not_called()
            sleep_mock.assert_not_called()

    def test_main_apply_calls_execute_per_video(self, tmp_path, monkeypatch):
        """plan 要件 14-d: 通常実行で videos().update().execute() が動画数分呼ばれる."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given: 2 本の short
        ch = _setup_channel(tmp_path)
        _make_collection_with_shorts(
            ch,
            "20250101-live-foo",
            shorts=[
                {"short_num": 1, "video_id": "V1"},
                {"short_num": 2, "video_id": "V2"},
            ],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-shorts-bulk-update-loc"])
        yt_mock = self._build_youtube_mock()

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep"),
        ):
            # When
            try:
                mod.main()
            except SystemExit as e:
                assert e.code in (None, 0)

            # Then
            assert yt_mock.videos.return_value.update.return_value.execute.call_count == 2

    def test_main_apply_sleeps_0_5_per_video(self, tmp_path, monkeypatch):
        """plan アンチパターン #8: 成功 1 回ごとに time.sleep(0.5)."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given: 2 本の short
        ch = _setup_channel(tmp_path)
        _make_collection_with_shorts(
            ch,
            "20250101-live-foo",
            shorts=[
                {"short_num": 1, "video_id": "V1"},
                {"short_num": 2, "video_id": "V2"},
            ],
        )
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-shorts-bulk-update-loc"])
        yt_mock = self._build_youtube_mock()

        with (
            patch.object(mod, "get_youtube", return_value=yt_mock),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            try:
                mod.main()
            except SystemExit as e:
                assert e.code in (None, 0)

            # Then: sleep が 2 回、すべて 0.5 で呼ばれる
            assert sleep_mock.call_count == 2
            for c in sleep_mock.call_args_list:
                assert c == call(0.5)

    def test_main_exits_when_no_target_videos(self, tmp_path, monkeypatch):
        """plan 要件 14-d: 対象 0 件で SystemExit(1)."""
        from youtube_automation.scripts import bulk_update_short_localizations as mod

        # Given: live/ ディレクトリ自体が無い
        ch = _setup_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        reset()
        monkeypatch.setattr(sys, "argv", ["yt-shorts-bulk-update-loc"])

        with patch.object(mod, "get_youtube") as yt_mock:
            # When/Then
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 1
            # API は触らない
            yt_mock.assert_not_called()
