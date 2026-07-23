"""scripts/video_analyze.py の CLI/解決ロジック ユニットテスト

Issue #103 で追加する CLI `yt-video-analyze` の引数解析と target 解決ロジックを検証する。

検証対象:
1. _extract_video_id_from_url: youtube.com/watch?v= / youtu.be/ / youtube.com/shorts/ + 不正 URL
2. _resolve_url_target: URL から VideoTarget を構築
3. _resolve_own_targets: collections/live/<name>/20-documentation/upload_tracking.json から
   complete_collection.video_id (および videos[]) を解決
4. _resolve_benchmark_targets: ベンチマーク JSON から slug フィルタ + top N 抽出
5. _build_parser: --source 排他、各経路の必須引数

ネットワーク・Gemini API は呼ばない (resolver 層は file system / 既存 loader のみ)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts.video_analyze import (
    _analysis_window_sec_from_config,
    _build_parser,
    _extract_video_id_from_url,
    _resolve_benchmark_targets,
    _resolve_own_targets,
    _resolve_url_target,
    _run_analysis,
    main,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.skill_config import reset as reset_skill_config
from youtube_automation.utils.video_analyzer import VideoAnalyzer, VideoTarget

# ----------------------------------------------------------------------------
# _extract_video_id_from_url
# ----------------------------------------------------------------------------


class TestExtractVideoIdFromUrl:
    def test_youtube_watch_url(self):
        # Given: 標準的な watch?v= URL
        # When/Then
        assert _extract_video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtube_watch_url_with_extra_params(self):
        # Given: 追加パラメータ付き
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123"
        # When/Then
        assert _extract_video_id_from_url(url) == "dQw4w9WgXcQ"

    def test_youtu_be_short_url(self):
        # Given: youtu.be の短縮 URL
        assert _extract_video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_with_query(self):
        # Given: 短縮 URL にクエリ付き
        assert _extract_video_id_from_url("https://youtu.be/dQw4w9WgXcQ?t=10") == "dQw4w9WgXcQ"

    def test_youtu_be_with_trailing_slash(self):
        # Given: 末尾スラッシュ付きの youtu.be (コピー時に付くケース)
        # When/Then: 末尾 / は正規化されて video_id のみが返る
        assert _extract_video_id_from_url("https://youtu.be/dQw4w9WgXcQ/") == "dQw4w9WgXcQ"

    def test_youtube_shorts_url(self):
        # Given: shorts 形式
        assert _extract_video_id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtube_shorts_url_with_trailing_slash(self):
        # Given: 末尾スラッシュ付きの shorts
        assert _extract_video_id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ/") == "dQw4w9WgXcQ"

    def test_invalid_url_raises_validation_error(self):
        # Given: YouTube ではない URL
        with pytest.raises(ValidationError):
            _extract_video_id_from_url("https://example.com/watch?v=abc")

    def test_empty_url_raises_validation_error(self):
        # Given: 空文字
        with pytest.raises(ValidationError):
            _extract_video_id_from_url("")

    def test_watch_without_v_param_raises(self):
        # Given: v パラメータが欠けた watch URL
        with pytest.raises(ValidationError):
            _extract_video_id_from_url("https://www.youtube.com/watch?list=PL123")


# ----------------------------------------------------------------------------
# _resolve_url_target
# ----------------------------------------------------------------------------


class TestResolveUrlTarget:
    def test_returns_video_target_with_extracted_id(self):
        # Given: URL
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        # When
        target = _resolve_url_target(url)

        # Then
        assert isinstance(target, VideoTarget)
        assert target.video_id == "dQw4w9WgXcQ"
        assert target.url == url

    def test_invalid_url_raises(self):
        # Given: 不正 URL
        with pytest.raises(ValidationError):
            _resolve_url_target("not-a-url")


# ----------------------------------------------------------------------------
# _resolve_own_targets
# ----------------------------------------------------------------------------


@pytest.fixture
def channel_dir_with_collection(tmp_path: Path) -> Path:
    """upload_tracking.json を持つ模擬 channel_dir を構築

    - 20260326-rjn-cafe-collection: complete_collection のみ
    - 20260402-rjn-multi-collection: complete_collection + videos[] (1 シリーズ)
    - 20260411-rjn-empty: tracking なし
    """
    live = tmp_path / "collections" / "live"

    cafe = live / "20260326-rjn-cafe-collection" / "20-documentation"
    cafe.mkdir(parents=True)
    (cafe / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "collection_name": "20260326-rjn-cafe-collection",
                "complete_collection": {
                    "video_id": "ABC123",
                    "video_url": "https://www.youtube.com/watch?v=ABC123",
                    "title": "Cafe Complete",
                },
            }
        )
    )

    multi = live / "20260402-rjn-multi-collection" / "20-documentation"
    multi.mkdir(parents=True)
    (multi / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "collection_name": "20260402-rjn-multi-collection",
                "complete_collection": {
                    "video_id": "DEF456",
                    "video_url": "https://www.youtube.com/watch?v=DEF456",
                    "title": "Multi Complete",
                },
                "videos": [
                    {"video_id": "VID001", "title": "Track 1"},
                    {"video_id": "VID002", "title": "Track 2"},
                ],
            }
        )
    )

    empty = live / "20260411-rjn-empty" / "20-documentation"
    empty.mkdir(parents=True)

    return tmp_path


class TestResolveOwnTargets:
    def test_returns_complete_collection_video(self, channel_dir_with_collection):
        # Given: complete_collection のみのコレクション
        targets = _resolve_own_targets(
            channel_dir=channel_dir_with_collection,
            collection_name="20260326-rjn-cafe-collection",
        )

        # Then: 1 件の VideoTarget が返る
        assert len(targets) == 1
        assert targets[0].video_id == "ABC123"
        assert targets[0].url == "https://www.youtube.com/watch?v=ABC123"
        # slug にはコレクション名が入る (own 経路の保存ディレクトリに使う)
        assert targets[0].slug == "20260326-rjn-cafe-collection"

    def test_includes_per_video_entries(self, channel_dir_with_collection):
        # Given: complete_collection + videos[] のコレクション
        targets = _resolve_own_targets(
            channel_dir=channel_dir_with_collection,
            collection_name="20260402-rjn-multi-collection",
        )

        # Then: complete + 各 video が含まれる (合計 3 件)
        ids = {t.video_id for t in targets}
        assert "DEF456" in ids
        assert "VID001" in ids
        assert "VID002" in ids
        assert len(targets) == 3

    def test_missing_tracking_raises(self, channel_dir_with_collection):
        # Given: tracking ファイルがない
        with pytest.raises(ValidationError):
            _resolve_own_targets(
                channel_dir=channel_dir_with_collection,
                collection_name="20260411-rjn-empty",
            )

    def test_unknown_collection_raises(self, channel_dir_with_collection):
        # Given: 存在しないコレクション名
        with pytest.raises(ValidationError):
            _resolve_own_targets(
                channel_dir=channel_dir_with_collection,
                collection_name="does-not-exist",
            )


# ----------------------------------------------------------------------------
# _resolve_benchmark_targets
# ----------------------------------------------------------------------------


class TestResolveBenchmarkTargets:
    def _videos(self) -> list[dict]:
        # 視聴数降順で load_benchmark_videos が返す想定
        return [
            {
                "video_id": "C1",
                "title": "Top Celtic",
                "views": 500000,
                "channel_name": "CelticCh",
                "channel_slug": "celtic-music",
                "published_at": "2026-03-01",
                "thumbnail_url": "https://i.ytimg.com/c1.jpg",
            },
            {
                "video_id": "C2",
                "title": "Mid Celtic",
                "views": 200000,
                "channel_name": "CelticCh",
                "channel_slug": "celtic-music",
                "published_at": "2026-02-15",
                "thumbnail_url": "https://i.ytimg.com/c2.jpg",
            },
            {
                "video_id": "C3",
                "title": "Low Celtic",
                "views": 30000,
                "channel_name": "CelticCh",
                "channel_slug": "celtic-music",
                "published_at": "2026-01-15",
                "thumbnail_url": "https://i.ytimg.com/c3.jpg",
            },
            {
                "video_id": "J1",
                "title": "Jazz Night",
                "views": 1000000,
                "channel_name": "JazzCh",
                "channel_slug": "rain-jazz-night",
                "published_at": "2026-03-01",
                "thumbnail_url": "https://i.ytimg.com/j1.jpg",
            },
        ]

    def test_filters_by_competitor_slug_and_takes_top_n(self, tmp_path):
        # Given: load_benchmark_videos が複数チャンネルの動画を返す
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=self._videos(),
        ):
            # When: celtic-music で top=2
            targets = _resolve_benchmark_targets(
                data_dir=tmp_path,
                competitor_slug="celtic-music",
                top=2,
            )

        # Then: celtic-music の上位 2 件のみ
        assert [t.video_id for t in targets] == ["C1", "C2"]
        assert all(t.slug == "celtic-music" for t in targets)
        assert all(isinstance(t, VideoTarget) for t in targets)
        # URL は watch?v= 形式で組み立てられる
        assert targets[0].url.endswith("v=C1")

    def test_top_larger_than_available_returns_all(self, tmp_path):
        # Given
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=self._videos(),
        ):
            targets = _resolve_benchmark_targets(
                data_dir=tmp_path,
                competitor_slug="celtic-music",
                top=99,
            )

        # Then: 該当 slug の全件 (3) が返る
        assert {t.video_id for t in targets} == {"C1", "C2", "C3"}

    def test_unknown_slug_raises(self, tmp_path):
        # Given: 該当しない slug
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=self._videos(),
        ):
            with pytest.raises(ValidationError):
                _resolve_benchmark_targets(
                    data_dir=tmp_path,
                    competitor_slug="nonexistent",
                    top=5,
                )

    def test_live_video_is_skipped_and_next_vod_promoted(self, tmp_path, caplog):
        # Given: 1 位が live 配信 (duration_iso == "P0D") → スキップして次点 VOD を繰り上げる
        videos = self._videos()
        videos.insert(
            0,
            {
                "video_id": "LIVE1",
                "title": "24/7 Celtic Radio",
                "views": 900000,
                "channel_name": "CelticCh",
                "channel_slug": "celtic-music",
                "published_at": "2026-03-10",
                "duration_iso": "P0D",
                "thumbnail_url": "https://i.ytimg.com/l1.jpg",
            },
        )
        caplog.set_level(logging.INFO, logger="youtube_automation.scripts.video_analyze")
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=videos,
        ):
            targets = _resolve_benchmark_targets(
                data_dir=tmp_path,
                competitor_slug="celtic-music",
                top=2,
            )

        # Then: live は含まれず VOD 上位 2 件が選ばれる
        assert [t.video_id for t in targets] == ["C1", "C2"]
        assert "live 配信 1 本" in caplog.text
        assert "LIVE1" in caplog.text
        assert "Gemini はライブ配信 URL を取り込めないため" in caplog.text

    def test_live_below_selected_top_is_not_logged(self, tmp_path, caplog):
        # Given: top=2 は VOD だけで充足し、3 位以下に live がある
        videos = self._videos()
        videos.append(
            {
                "video_id": "LIVE_AFTER_TOP",
                "title": "24/7 Celtic Radio",
                "views": 1,
                "channel_name": "CelticCh",
                "channel_slug": "celtic-music",
                "published_at": "2026-03-10",
                "duration_iso": "P0D",
                "thumbnail_url": "https://i.ytimg.com/l1.jpg",
            },
        )
        caplog.set_level(logging.INFO, logger="youtube_automation.scripts.video_analyze")
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=videos,
        ):
            targets = _resolve_benchmark_targets(
                data_dir=tmp_path,
                competitor_slug="celtic-music",
                top=2,
            )

        assert [t.video_id for t in targets] == ["C1", "C2"]
        assert "live 配信" not in caplog.text
        assert "LIVE_AFTER_TOP" not in caplog.text

    def test_all_live_slug_raises(self, tmp_path):
        # Given: 該当 slug の動画がすべて live 配信
        videos = [
            {
                "video_id": "LIVE1",
                "title": "24/7 Radio",
                "views": 900000,
                "channel_name": "LiveCh",
                "channel_slug": "live-only",
                "published_at": "2026-03-10",
                "duration_iso": "P0D",
                "thumbnail_url": "https://i.ytimg.com/l1.jpg",
            },
        ]
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=videos,
        ):
            with pytest.raises(ValidationError, match="live 配信のみ"):
                _resolve_benchmark_targets(
                    data_dir=tmp_path,
                    competitor_slug="live-only",
                    top=5,
                )

    def test_top_zero_raises(self, tmp_path):
        # Given: top=0 は意味がない (不整合な値のサイレントスキップ禁止)
        with patch(
            "youtube_automation.scripts.video_analyze.load_benchmark_videos",
            return_value=self._videos(),
        ):
            with pytest.raises(ValidationError):
                _resolve_benchmark_targets(
                    data_dir=tmp_path,
                    competitor_slug="celtic-music",
                    top=0,
                )


# ----------------------------------------------------------------------------
# main: cfg → VideoAnalyzer への analysis_window_sec 受け渡し (#1495)
# ----------------------------------------------------------------------------


class TestMainPassesAnalysisWindow:
    def test_analysis_window_sec_flows_from_cfg_to_analyzer(self, tmp_path):
        # Given: skill-config が窓幅 600 を返す (境界で 1 度だけ解決する既存方針)
        cfg = {
            "model": "gemini-2.5-flash",
            "prompt": "analyze",
            "delay_sec": 0,
            "analysis_window_sec": 600,
        }
        with (
            patch("youtube_automation.scripts.video_analyze.load_skill_config", return_value=cfg),
            patch("youtube_automation.scripts.video_analyze._channel_dir", return_value=tmp_path),
            patch("youtube_automation.scripts.video_analyze.create_global_genai_client", return_value=MagicMock()),
            patch("youtube_automation.scripts.video_analyze.VideoAnalyzer") as analyzer_cls,
            patch("youtube_automation.scripts.video_analyze._run_analysis", return_value=([], [])),
            patch("sys.argv", ["yt-video-analyze", "--url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]),
        ):
            # When: main を実行
            main()

        # Then: cfg の窓幅がそのまま VideoAnalyzer に渡る
        assert analyzer_cls.call_args.kwargs["analysis_window_sec"] == 600


class TestAnalysisWindowSkillConfig:
    def test_default_window_is_900(self, tmp_path):
        # Given: チャンネル側 override なし
        cfg = load_skill_config("video-analyze", use_cache=False, channel_dir=tmp_path)

        # Then: 配布 default の 900 秒
        assert cfg["analysis_window_sec"] == 900

    def test_channel_override_changes_window(self, tmp_path):
        # Given: config/skills/video-analyze.yaml で窓幅を上書き
        skills_dir = tmp_path / "config" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "video-analyze.yaml").write_text("analysis_window_sec: 300\n", encoding="utf-8")

        # When: deep-merge ロード
        cfg = load_skill_config("video-analyze", use_cache=False, channel_dir=tmp_path)

        # Then: override が有効に効く
        assert cfg["analysis_window_sec"] == 300


class TestAnalysisWindowValidation:
    @pytest.mark.parametrize("value", [0, -1, "300", True, False, None])
    def test_rejects_non_positive_or_non_int_window(self, value):
        # Given: skill-config から読み込まれた契約外の窓幅
        cfg = {
            "model": "gemini-2.5-flash",
            "prompt": "analyze",
            "delay_sec": 0,
            "analysis_window_sec": value,
        }

        # When/Then: Gemini API 呼び出し前の境界で fail-fast する
        with pytest.raises(ConfigError, match="analysis_window_sec"):
            _analysis_window_sec_from_config(cfg)

    @pytest.mark.parametrize("yaml_value", ["0", "-1", "'300'", "true", "false", "null"])
    def test_channel_override_invalid_window_is_rejected(self, tmp_path, yaml_value):
        # Given: config/skills/video-analyze.yaml に不正な override
        skills_dir = tmp_path / "config" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "video-analyze.yaml").write_text(
            f"analysis_window_sec: {yaml_value}\n",
            encoding="utf-8",
        )
        cfg = load_skill_config("video-analyze", use_cache=False, channel_dir=tmp_path)

        # When/Then: deep-merge 後の境界検証で拒否される
        with pytest.raises(ConfigError, match="analysis_window_sec"):
            _analysis_window_sec_from_config(cfg)


class TestMainAnalysisWindowFlow:
    def _run_main_with_channel(self, tmp_path, monkeypatch, config_yaml: str) -> MagicMock:
        from youtube_automation.configuration import reset as reset_config

        skills_dir = tmp_path / "config" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "video-analyze.yaml").write_text(config_yaml, encoding="utf-8")

        monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
        reset_config()
        reset_skill_config("video-analyze")

        client = MagicMock()
        response = MagicMock()
        response.text = json.dumps(
            {
                "hook_structure": {"intro_sec": 5, "first_text_at": 2.0},
                "bgm_arc": {"intro": "0-15s", "peak": "1:30", "outro": "4:30-end of clip"},
                "scene_timeline": [{"start": "0:00", "summary": "fade-in cafe"}],
                "thumbnail_alignment": {"signature_present": True},
                "editing_metrics": {"avg_cut_sec": 6.5, "text_per_min": 3},
                "suno_preset": {
                    "genre_line": "lo-fi jazz, soft piano",
                    "exclude_styles": "heavy metal",
                    "rationale": "Soft opening clip.",
                },
            }
        )
        client.models.generate_content.return_value = response

        try:
            with (
                patch("youtube_automation.scripts.video_analyze.create_global_genai_client", return_value=client),
                patch("sys.argv", ["yt-video-analyze", "--url", "https://www.youtube.com/watch?v=ABCDEFGHIJK"]),
            ):
                main()
        finally:
            reset_skill_config("video-analyze")
            reset_config()

        return client

    def test_channel_override_flows_to_gemini_end_offset_and_outputs(self, tmp_path, monkeypatch):
        # Given: チャンネル override で 300 秒に変更
        client = self._run_main_with_channel(
            tmp_path,
            monkeypatch,
            "analysis_window_sec: 300\ndelay_sec: 0\n",
        )

        # Then: 実 main() + 実 VideoAnalyzer 経由で SDK metadata に届く
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert contents[0].video_metadata.end_offset == "300s"

        # And: JSON / Markdown 生成物にも実際の窓幅が残る
        json_path = tmp_path / "data" / "video_analysis" / "url" / "ABCDEFGHIJK.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["analysis_window_sec"] == 300
        assert payload["analysis_scope"]["end_offset_sec"] == 300

        report_path = tmp_path / "reports" / "video_analysis" / "url.md"
        assert "- analysis_window_sec: 300" in report_path.read_text(encoding="utf-8")

    def test_default_window_flows_to_gemini_end_offset(self, tmp_path, monkeypatch):
        # Given: delay だけ override し、analysis_window_sec は配布 default の 900 秒
        client = self._run_main_with_channel(tmp_path, monkeypatch, "delay_sec: 0\n")

        # Then: default の 900 秒が同じ入口から SDK metadata に届く
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert contents[0].video_metadata.end_offset == "900s"


# ----------------------------------------------------------------------------
# _build_parser (argparse contract)
# ----------------------------------------------------------------------------


class TestRunAnalysisCache:
    """#1693: 既存解析 JSON があれば Gemini を呼ばない / --force で再解析"""

    _PAYLOAD: ClassVar[dict] = {"hook_structure": {"intro_sec": 5}}

    def _make_analyzer(self, tmp_path, response_text: str) -> VideoAnalyzer:
        client = MagicMock()
        response = MagicMock()
        response.text = response_text
        client.models.generate_content.return_value = response
        return VideoAnalyzer(
            client=client,
            model="gemini-3.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
            analysis_window_sec=900,
        )

    def _make_target(self) -> VideoTarget:
        return VideoTarget(
            video_id="CACHED000ID",
            slug="rain-jazz-night",
            url="https://www.youtube.com/watch?v=CACHED000ID",
            title="Cached",
        )

    def test_cache_hit_skips_gemini_call(self, tmp_path):
        # Given: 有効な解析 JSON が既存
        analyzer = self._make_analyzer(tmp_path, json.dumps(self._PAYLOAD))
        target = self._make_target()
        analyzer.save_json(target, {"hook_structure": {"intro_sec": 99}, "video_id": target.video_id})
        analyzer.client.models.generate_content.reset_mock()

        # When: force なしで実行
        results, failures = _run_analysis(analyzer=analyzer, targets=[target])

        # Then: Gemini は呼ばれず既存結果が使われる (要件 1)
        assert analyzer.client.models.generate_content.call_count == 0
        assert failures == []
        assert len(results) == 1
        assert results[0]["hook_structure"]["intro_sec"] == 99

    def test_force_reanalyzes_and_overwrites(self, tmp_path):
        # Given: 既存 JSON あり + 新レスポンスを返す Gemini
        analyzer = self._make_analyzer(tmp_path, json.dumps(self._PAYLOAD))
        target = self._make_target()
        analyzer.save_json(target, {"hook_structure": {"intro_sec": 99}, "video_id": target.video_id})

        # When: --force 相当で実行
        results, failures = _run_analysis(analyzer=analyzer, targets=[target], force=True)

        # Then: Gemini が呼ばれ、JSON が上書きされる (要件 2)
        assert analyzer.client.models.generate_content.call_count == 1
        assert failures == []
        assert results[0]["hook_structure"]["intro_sec"] == 5
        saved = json.loads(analyzer.json_path(target).read_text(encoding="utf-8"))
        assert saved["hook_structure"]["intro_sec"] == 5

    def test_broken_cache_triggers_reanalysis(self, tmp_path):
        # Given: 部分書き込みで壊れた既存 JSON
        analyzer = self._make_analyzer(tmp_path, json.dumps(self._PAYLOAD))
        target = self._make_target()
        path = analyzer.json_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"hook_structure": {"intro', encoding="utf-8")

        # When: force なしで実行
        results, failures = _run_analysis(analyzer=analyzer, targets=[target])

        # Then: 破損キャッシュは再利用されず Gemini で再解析される (要件 3)
        assert analyzer.client.models.generate_content.call_count == 1
        assert failures == []
        assert results[0]["hook_structure"]["intro_sec"] == 5
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["hook_structure"]["intro_sec"] == 5

    def test_missing_cache_analyzes_and_saves(self, tmp_path):
        # Given: キャッシュなし
        analyzer = self._make_analyzer(tmp_path, json.dumps(self._PAYLOAD))
        target = self._make_target()

        # When
        _results, failures = _run_analysis(analyzer=analyzer, targets=[target])

        # Then: 通常どおり解析・保存される (キャッシュ導入によるデグレなし)
        assert analyzer.client.models.generate_content.call_count == 1
        assert failures == []
        assert analyzer.json_path(target).exists()


class TestBuildParser:
    def test_benchmark_path_requires_competitor(self):
        # Given: parser
        parser = _build_parser()

        # When/Then: --source benchmark で --competitor 未指定は SystemExit (parser.error)
        with pytest.raises(SystemExit):
            parser.parse_args(["--source", "benchmark", "--top", "5"])

    def test_benchmark_path_parses_with_competitor_and_top(self):
        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--source", "benchmark", "--competitor", "celtic-music", "--top", "3"])

        # Then
        assert args.source == "benchmark"
        assert args.competitor == "celtic-music"
        assert args.top == 3

    def test_removed_channel_flag_names_competitor_replacement(self, capsys):
        parser = _build_parser()

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--source", "benchmark", "--channel", "celtic-music"])

        assert exc_info.value.code == 2
        assert "--channel は --competitor に変わりました" in capsys.readouterr().err

    def test_own_path_requires_collection(self):
        # Given
        parser = _build_parser()

        # When/Then
        with pytest.raises(SystemExit):
            parser.parse_args(["--source", "own"])

    def test_own_path_parses_with_collection(self):
        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--source", "own", "--collection", "20260326-cafe-collection"])

        # Then
        assert args.source == "own"
        assert args.collection == "20260326-cafe-collection"

    def test_url_path_parses(self):
        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])

        # Then
        assert args.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_source_benchmark_rejects_invalid_value(self):
        # Given: argparse choices で制限されている想定
        parser = _build_parser()

        # When/Then: 未知の source 値は SystemExit
        with pytest.raises(SystemExit):
            parser.parse_args(["--source", "garbage"])

    def test_source_and_url_are_mutually_exclusive(self):
        # Given
        parser = _build_parser()

        # When/Then: --source と --url の併用は SystemExit
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--source",
                    "own",
                    "--collection",
                    "x",
                    "--url",
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ]
            )

    def test_force_defaults_to_false(self):
        # Given
        parser = _build_parser()

        # When: --force を付けない
        args = parser.parse_args(["--url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])

        # Then: 既定はキャッシュ再利用 (force=False)
        assert args.force is False

    def test_force_flag_parses(self):
        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--force"])

        # Then
        assert args.force is True

    def test_no_arguments_raises(self):
        # Given: 何も指定しない
        parser = _build_parser()

        # When/Then: 入口経路が決まらないので SystemExit
        with pytest.raises(SystemExit):
            parser.parse_args([])
