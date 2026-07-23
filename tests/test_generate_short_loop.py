"""scripts/generate_short_loop.py の smoke テスト

plan 要件 #9 / 14-c / アンチパターン #7 を検証する:
- `_build_parser` が collection positional と `--model` を受ける
- `resolve_paths` (or 等価関数) が `short.png` → `short-loop.mp4` を解決し、`.jpg` フォールバックする
- `load_skill_config("short")` を呼ぶ
- Veo に `aspect_ratio="9:16"` が渡る
- `--model` 引数が伝搬する
- 入力画像欠如時に `SystemExit(1)`

外部 IO（Vertex AI / load_skill_config / load_dotenv 等）は touch しない。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import DEFAULT, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# ---------------------------------------------------------------------------
# 1. _build_parser smoke
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argument_parser(self):
        # Given
        from youtube_automation.scripts.generate_short_loop import _build_parser

        # When
        parser = _build_parser()

        # Then
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_accepts_collection_positional(self):
        """plan 要件 14-c: collection 位置引数を受ける."""
        from youtube_automation.scripts.generate_short_loop import _build_parser

        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["collections/live/foo"])

        # Then
        assert args.collection == "collections/live/foo"

    def test_parser_accepts_model_override(self):
        """plan 要件 14-c: `--model` 引数."""
        from youtube_automation.scripts.generate_short_loop import _build_parser

        # Given
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-lite-generate-preview"])

        # Then
        assert args.model == "veo-3.1-lite-generate-preview"


# ---------------------------------------------------------------------------
# 2. パス解決
# ---------------------------------------------------------------------------


class TestResolvePaths:
    """`resolve_paths` (または `resolve_short_paths`): short.png → short-loop.mp4."""

    def test_short_png_resolved_when_present(self, tmp_path):
        """short.png を見つけて入力に採用する."""
        from youtube_automation.scripts.generate_short_loop import resolve_paths

        # Given: 10-assets/short.png のみ
        col = tmp_path / "20250101-live-foo"
        assets = col / "10-assets"
        assets.mkdir(parents=True)
        png = assets / "short.png"
        png.write_bytes(b"\x00")

        # When
        image_path, output_path = resolve_paths(col)

        # Then
        assert image_path == png
        assert output_path.name == "short-loop.mp4"
        assert output_path.parent == assets

    def test_short_jpg_fallback_when_png_missing(self, tmp_path):
        """short.png が無ければ short.jpg にフォールバック."""
        from youtube_automation.scripts.generate_short_loop import resolve_paths

        # Given: jpg のみ
        col = tmp_path / "20250101-live-bar"
        assets = col / "10-assets"
        assets.mkdir(parents=True)
        jpg = assets / "short.jpg"
        jpg.write_bytes(b"\x00")

        # When
        image_path, _output_path = resolve_paths(col)

        # Then
        assert image_path == jpg

    def test_raises_when_input_image_missing(self, tmp_path):
        from youtube_automation.scripts.generate_short_loop import resolve_paths

        col = tmp_path / "20250101-live-empty"
        (col / "10-assets").mkdir(parents=True)

        with pytest.raises(FileNotFoundError) as excinfo:
            resolve_paths(col)

        message = str(excinfo.value)
        assert str(col / "10-assets" / "short.png") in message
        assert str(col / "10-assets" / "short.jpg") in message


# ---------------------------------------------------------------------------
# 3. main(): Veo に aspect_ratio="9:16" が渡るか
# ---------------------------------------------------------------------------


class TestMain:
    """plan 要件 #9 / アンチパターン #7: Veo 呼出で `aspect_ratio="9:16"` を明示."""

    def test_load_skill_config_called_with_short(self, tmp_path, monkeypatch):
        """plan 要件 14-c: `load_skill_config("short")` を呼ぶ."""
        from youtube_automation.scripts import generate_short_loop as mod

        # Given: 入力画像を準備
        col = tmp_path / "20250101-live-foo"
        assets = col / "10-assets"
        assets.mkdir(parents=True)
        (assets / "short.png").write_bytes(b"\x00")

        monkeypatch.setattr(sys, "argv", ["yt-generate-shorts-loop", str(col), "-y"])

        with patch.multiple(
            "youtube_automation.scripts.generate_short_loop",
            create_veo_genai_client=DEFAULT,
            generate_loop_video=DEFAULT,
            load_skill_config=DEFAULT,
        ) as mocks:
            mocks["load_skill_config"].return_value = {"veo": {"model": "veo-3.1-fast-generate-001"}}
            mocks["generate_loop_video"].return_value = True
            # When
            try:
                mod.main()
            except SystemExit:
                pass

            # Then
            mocks["load_skill_config"].assert_called_with("short")

    def test_main_passes_aspect_ratio_9_16_to_veo(self, tmp_path, monkeypatch):
        """plan アンチパターン #7: Veo 呼出で `aspect_ratio="9:16"` を必ず明示."""
        from youtube_automation.scripts import generate_short_loop as mod

        # Given
        col = tmp_path / "20250101-live-foo"
        assets = col / "10-assets"
        assets.mkdir(parents=True)
        (assets / "short.png").write_bytes(b"\x00")
        monkeypatch.setattr(sys, "argv", ["yt-generate-shorts-loop", str(col), "-y"])

        with patch.multiple(
            "youtube_automation.scripts.generate_short_loop",
            create_veo_genai_client=DEFAULT,
            generate_loop_video=DEFAULT,
            load_skill_config=DEFAULT,
        ) as mocks:
            mocks["load_skill_config"].return_value = {"veo": {"model": "veo-3.1-fast-generate-001"}}
            mocks["generate_loop_video"].return_value = True
            try:
                mod.main()
            except SystemExit:
                pass

            # Then: generate_loop_video の call_args.kwargs["aspect_ratio"] == "9:16"
            call = mocks["generate_loop_video"].call_args
            kwargs = call.kwargs
            assert kwargs.get("aspect_ratio") == "9:16"

    def test_main_propagates_model_override_via_cli(self, tmp_path, monkeypatch):
        """plan 要件 14-c: `--model` 指定が Veo 呼出に伝搬する."""
        from youtube_automation.scripts import generate_short_loop as mod

        # Given
        col = tmp_path / "20250101-live-foo"
        assets = col / "10-assets"
        assets.mkdir(parents=True)
        (assets / "short.png").write_bytes(b"\x00")
        monkeypatch.setattr(
            sys,
            "argv",
            ["yt-generate-shorts-loop", str(col), "--model", "veo-3.1-lite-generate-preview", "-y"],
        )

        with patch.multiple(
            "youtube_automation.scripts.generate_short_loop",
            create_veo_genai_client=DEFAULT,
            generate_loop_video=DEFAULT,
            load_skill_config=DEFAULT,
        ) as mocks:
            mocks["load_skill_config"].return_value = {"veo": {"model": "veo-3.1-fast-generate-001"}}
            mocks["generate_loop_video"].return_value = True
            try:
                mod.main()
            except SystemExit:
                pass

            # Then
            call = mocks["generate_loop_video"].call_args
            # positional or keyword で model が "veo-3.1-lite-generate-preview"
            # generate_loop_video(client, image, output, model, prompt, aspect_ratio=...)
            args = call.args
            kwargs = call.kwargs
            # 4 番目が model 想定
            model_value = args[3] if len(args) >= 4 else kwargs.get("model")
            assert model_value == "veo-3.1-lite-generate-preview"

    def test_main_exits_with_error_when_input_image_missing(self, tmp_path, monkeypatch):
        """plan 要件 14-c: 入力画像欠如で `SystemExit(1)`."""
        from youtube_automation.scripts import generate_short_loop as mod

        # Given: 画像なし
        col = tmp_path / "20250101-live-empty"
        (col / "10-assets").mkdir(parents=True)
        monkeypatch.setattr(sys, "argv", ["yt-generate-shorts-loop", str(col), "-y"])

        with patch.multiple(
            "youtube_automation.scripts.generate_short_loop",
            create_veo_genai_client=DEFAULT,
            generate_loop_video=DEFAULT,
            load_skill_config=DEFAULT,
        ) as mocks:
            mocks["load_skill_config"].return_value = {"veo": {}}

            # When/Then
            with pytest.raises(SystemExit) as excinfo:
                mod.main()
            assert excinfo.value.code == 1
