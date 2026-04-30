"""utils/video_analyzer.py のユニットテスト

Issue #103 で追加する VideoAnalyzer / VideoAnalysisReport / VideoTarget の
振る舞いを検証する。Gemini Client は全テストでモックする (ネットワーク非依存)。

検証対象:
1. VideoTarget dataclass: 必須フィールドが保持される
2. VideoAnalyzer.analyze_url: Gemini レスポンスを JSON にパースし、メタデータを併せて返す
   - 正常系 (素の JSON)
   - コードフェンス付き JSON ( ```json ... ``` ) のフェンス除去
   - JSON パース失敗時に ValidationError を送出 (エラー握りつぶし禁止)
   - delay_sec が time.sleep に渡される (API レート対策)
3. VideoAnalyzer.save_json: data/video_analysis/<slug>/<video_id>.json に書き出す
4. VideoAnalysisReport.render: 必要セクションを含む Markdown を生成する
5. VideoAnalysisReport.write: reports/video_analysis/<slug>.md に書き出す
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.video_analyzer import (
    VideoAnalysisReport,
    VideoAnalyzer,
    VideoTarget,
)


def _make_target(**overrides) -> VideoTarget:
    """テスト用 VideoTarget の最小ファクトリ"""
    base = {
        "video_id": "ABCDEFGHIJK",
        "slug": "rain-jazz-night",
        "url": "https://www.youtube.com/watch?v=ABCDEFGHIJK",
        "title": "Sample Title",
    }
    base.update(overrides)
    return VideoTarget(**base)


def _make_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


def _make_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value = _make_response(response_text)
    return client


_VALID_PAYLOAD = {
    "hook_structure": {"intro_sec": 5, "first_text_at": 2.0},
    "bgm_arc": {"intro": "0-15s", "peak": "1:30", "outro": "9:30-end"},
    "scene_timeline": [{"start": "0:00", "summary": "fade-in cafe"}],
    "thumbnail_alignment": {"signature_present": True},
    "editing_metrics": {"avg_cut_sec": 6.5, "text_per_min": 3},
}


class TestVideoTarget:
    def test_holds_required_fields(self):
        # Given: 必要な属性
        target = VideoTarget(
            video_id="vid_001",
            slug="celtic-music",
            url="https://www.youtube.com/watch?v=vid_001",
            title="Celtic Forest",
        )

        # Then: 各属性にアクセスできる
        assert target.video_id == "vid_001"
        assert target.slug == "celtic-music"
        assert target.url == "https://www.youtube.com/watch?v=vid_001"
        assert target.title == "Celtic Forest"


class TestVideoAnalyzerAnalyzeUrl:
    def test_parses_plain_json_response(self, tmp_path):
        # Given: 素の JSON を返す Gemini Client
        client = _make_client(json.dumps(_VALID_PAYLOAD))
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
        )
        target = _make_target()

        # When: analyze_url を呼ぶ
        result = analyzer.analyze_url(target)

        # Then: パース結果のドメインキーが含まれ、メタも併走している
        assert result["hook_structure"]["intro_sec"] == 5
        assert result["bgm_arc"]["peak"] == "1:30"
        assert result["scene_timeline"][0]["summary"] == "fade-in cafe"
        assert result["thumbnail_alignment"]["signature_present"] is True
        assert result["editing_metrics"]["avg_cut_sec"] == 6.5

        # メタデータが上書きされていない (target の値が反映)
        assert result["video_id"] == target.video_id
        assert result["slug"] == target.slug
        assert result["url"] == target.url
        assert result["title"] == target.title
        assert result["model"] == "gemini-2.5-flash"
        # analyzed_at は ISO 文字列で保存される
        assert isinstance(result["analyzed_at"], str) and result["analyzed_at"]

        # Gemini Client が 1 回だけ呼ばれている
        assert client.models.generate_content.call_count == 1

    def test_strips_code_fence_wrapped_json(self, tmp_path):
        # Given: ```json ... ``` で囲まれたレスポンス
        fenced = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
        client = _make_client(fenced)
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
        )

        # When: analyze_url を呼ぶ
        result = analyzer.analyze_url(_make_target())

        # Then: フェンスが除去されてパースできる
        assert result["hook_structure"]["intro_sec"] == 5

    def test_strips_bare_code_fence(self, tmp_path):
        # Given: ``` ... ``` (json タグなし)
        fenced = "```\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
        client = _make_client(fenced)
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
        )

        # When/Then: タグ無しでもパースできる
        result = analyzer.analyze_url(_make_target())
        assert result["bgm_arc"]["intro"] == "0-15s"

    def test_raises_validation_error_on_invalid_json(self, tmp_path):
        # Given: JSON にならないレスポンス
        client = _make_client("this is not json at all")
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
        )

        # When/Then: 握りつぶさず ValidationError を投げる
        with pytest.raises(ValidationError):
            analyzer.analyze_url(_make_target())

    def test_uses_target_url_in_request(self, tmp_path):
        # Given: 解析対象 URL
        client = _make_client(json.dumps(_VALID_PAYLOAD))
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze the video",
            delay_sec=0,
            data_dir=tmp_path,
        )
        target = _make_target(url="https://youtu.be/SHORTID0001")

        # When: analyze_url
        analyzer.analyze_url(target)

        # Then: generate_content の呼び出し引数に URL とプロンプトが含まれる
        call = client.models.generate_content.call_args
        rendered = repr(call)
        assert "https://youtu.be/SHORTID0001" in rendered
        assert "analyze the video" in rendered

    def test_sleeps_delay_sec_between_calls(self, tmp_path):
        # Given: delay_sec を指定
        client = _make_client(json.dumps(_VALID_PAYLOAD))
        analyzer = VideoAnalyzer(
            client=client,
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=7,
            data_dir=tmp_path,
        )

        # When: analyze_url を呼ぶ
        with patch("youtube_automation.utils.video_analyzer.time.sleep") as mock_sleep:
            analyzer.analyze_url(_make_target())

        # Then: sleep が delay_sec で呼ばれる (API レート対策)
        mock_sleep.assert_called_once_with(7)


class TestVideoAnalyzerSaveJson:
    def test_writes_to_slug_subdirectory(self, tmp_path):
        # Given: data_dir に紐づく analyzer
        analyzer = VideoAnalyzer(
            client=MagicMock(),
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=tmp_path,
        )
        target = _make_target(video_id="VID42", slug="celtic-forest")
        payload = {"video_id": "VID42", **_VALID_PAYLOAD}

        # When: save_json
        out_path = analyzer.save_json(target, payload)

        # Then: data/video_analysis/<slug>/<video_id>.json に書かれる
        expected = tmp_path / "video_analysis" / "celtic-forest" / "VID42.json"
        assert out_path == expected
        assert expected.exists()

        loaded = json.loads(expected.read_text(encoding="utf-8"))
        assert loaded["video_id"] == "VID42"
        assert loaded["hook_structure"]["intro_sec"] == 5

    def test_creates_intermediate_directories(self, tmp_path):
        # Given: 存在しないディレクトリ階層
        nested = tmp_path / "does" / "not" / "exist"
        analyzer = VideoAnalyzer(
            client=MagicMock(),
            model="gemini-2.5-flash",
            prompt="analyze",
            delay_sec=0,
            data_dir=nested,
        )
        target = _make_target(video_id="V1", slug="ambient")

        # When: save_json
        out_path = analyzer.save_json(target, {"video_id": "V1"})

        # Then: 中間ディレクトリが自動作成され、ファイルが書かれる
        assert out_path.exists()
        assert out_path.parent.is_dir()


class TestVideoAnalysisReport:
    def _sample_results(self) -> list[dict]:
        return [
            {
                "video_id": "VID01",
                "slug": "celtic-music",
                "url": "https://www.youtube.com/watch?v=VID01",
                "title": "Celtic Forest",
                "analyzed_at": "2026-04-29T10:00:00",
                "model": "gemini-2.5-flash",
                **_VALID_PAYLOAD,
            },
            {
                "video_id": "VID02",
                "slug": "celtic-music",
                "url": "https://www.youtube.com/watch?v=VID02",
                "title": "Celtic Lake",
                "analyzed_at": "2026-04-29T10:01:00",
                "model": "gemini-2.5-flash",
                "hook_structure": {"intro_sec": 8},
                "bgm_arc": {"intro": "0-10s"},
                "scene_timeline": [],
                "thumbnail_alignment": {"signature_present": False},
                "editing_metrics": {"avg_cut_sec": 4.2},
            },
        ]

    def test_render_includes_required_sections(self):
        # Given: 解析結果
        results = self._sample_results()

        # When: render を呼ぶ
        md = VideoAnalysisReport.render(slug="celtic-music", results=results, failures=[])

        # Then: 必要セクションが Markdown に含まれる
        assert "celtic-music" in md
        assert "VID01" in md
        assert "VID02" in md
        assert "Celtic Forest" in md
        assert "Celtic Lake" in md
        # 主要キー名は人間向けレポートにラベルとして登場するはず
        assert "hook_structure" in md or "Hook" in md.title() or "フック" in md
        assert "bgm_arc" in md or "BGM" in md
        assert "scene_timeline" in md or "シーン" in md or "Scene" in md
        assert "thumbnail_alignment" in md or "サムネ" in md or "Thumbnail" in md
        assert "editing_metrics" in md or "編集" in md or "Editing" in md

    def test_render_reports_failure_count(self):
        # Given: 一部失敗あり
        failures = [
            {"video_id": "BAD1", "url": "https://youtu.be/BAD1", "error": "JSON parse failed"},
        ]
        results = self._sample_results()

        # When: render
        md = VideoAnalysisReport.render(slug="celtic-music", results=results, failures=failures)

        # Then: 失敗が明示される (エラー握りつぶし禁止)
        assert "BAD1" in md
        # 失敗件数を示す手がかりがある
        assert ("失敗" in md) or ("failed" in md.lower())

    def test_render_handles_empty_results(self):
        # Given: 結果なし、失敗のみ
        failures = [{"video_id": "X1", "url": "u", "error": "boom"}]

        # When: render
        md = VideoAnalysisReport.render(slug="celtic-music", results=[], failures=failures)

        # Then: 空でも Markdown を生成できる
        assert isinstance(md, str)
        assert "X1" in md

    def test_write_creates_report_file(self, tmp_path):
        # Given: reports_dir + Markdown
        content = "# sample report\n"

        # When: write
        out_path = VideoAnalysisReport.write(
            reports_dir=tmp_path,
            slug="rain-jazz-night",
            content=content,
        )

        # Then: reports/video_analysis/<slug>.md に書かれる
        expected = tmp_path / "video_analysis" / "rain-jazz-night.md"
        assert out_path == expected
        assert expected.read_text(encoding="utf-8") == content

    def test_write_creates_intermediate_dirs(self, tmp_path):
        # Given: 存在しないネスト
        deep = tmp_path / "x" / "y"

        # When: write
        out_path = VideoAnalysisReport.write(
            reports_dir=deep,
            slug="ambient",
            content="hi",
        )

        # Then: 中間ディレクトリが作成される
        assert out_path.exists()
        assert (deep / "video_analysis").is_dir()
