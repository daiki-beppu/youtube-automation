"""scripts/generate_loop_video.py の CLI 引数パーサのユニットテスト

Issue #129 で `--model` の `choices` 制限を撤廃し、`veo-3.1-lite-generate-preview`
を含む任意のモデル文字列を許容する変更を検証する。

検証対象（plan.md §5 テスト方針）:
1. `_build_parser`: `--model` が任意文字列（preview モデルを含む）を受け付ける
2. `_build_parser`: 旧 2 モデルも引き続き受け付ける（regression）
3. `_build_parser`: `--model` 未指定時は `args.model is None`（main() 側の
   `args.model or veo_config.get("model", DEFAULT_MODEL)` フォールバック解決を維持）
4. `_build_parser`: help 文字列に `veo-3.1-lite-generate-preview` が含まれる

外部 IO（Vertex AI / load_skill_config / load_dotenv 等）は touch しない。
parser のみを切り出してテストする。
"""

from __future__ import annotations

import argparse

from youtube_automation.scripts.generate_loop_video import _build_parser


class TestBuildParser:
    def test_returns_argument_parser(self):
        # Given/When
        parser = _build_parser()

        # Then
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_accepts_lite_preview_model(self):
        # Given: Issue #129 のメインケース。preview モデルを CLI から指定可能。
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-lite-generate-preview"])

        # Then
        assert args.model == "veo-3.1-lite-generate-preview"

    def test_parser_accepts_arbitrary_model_string(self):
        # Given: choices 撤廃の証跡。Veo の preview/GA リリースサイクルに追従するため
        # 未知モデル文字列も argparse 段階では弾かない（API 側でエラーになる前提）。
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "some-future-model-id"])

        # Then
        assert args.model == "some-future-model-id"

    def test_parser_accepts_legacy_fast_model(self):
        # Given: 旧 model（fast）の regression
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-fast-generate-001"])

        # Then
        assert args.model == "veo-3.1-fast-generate-001"

    def test_parser_accepts_legacy_quality_model(self):
        # Given: 旧 model（quality）の regression
        parser = _build_parser()

        # When
        args = parser.parse_args(["--model", "veo-3.1-generate-001"])

        # Then
        assert args.model == "veo-3.1-generate-001"

    def test_parser_model_default_is_none(self):
        # Given: --model 未指定時は None。main() 側の
        # `args.model or veo_config.get("model", DEFAULT_MODEL)` 解決順序を壊さない。
        parser = _build_parser()

        # When
        args = parser.parse_args([])

        # Then
        assert args.model is None

    def test_parser_help_lists_lite_preview_model(self):
        # Given: SKILL.md と config.default.yaml の選択肢列挙と整合する形で
        # CLI help にも preview モデルを例示する。
        parser = _build_parser()

        # When
        help_text = parser.format_help()

        # Then
        assert "veo-3.1-lite-generate-preview" in help_text

    def test_parser_help_lists_legacy_models(self):
        # Given: help 文字列で旧 2 モデルも引き続き例示されている（discoverability 維持）。
        parser = _build_parser()

        # When
        help_text = parser.format_help()

        # Then
        assert "veo-3.1-fast-generate-001" in help_text
        assert "veo-3.1-generate-001" in help_text

    def test_parser_collection_is_optional(self):
        # Given: collection は positional だが nargs="?" で optional（CWD 解決経路を残す）。
        # この既存挙動を model 変更で壊さない regression。
        parser = _build_parser()

        # When
        args = parser.parse_args([])

        # Then
        assert args.collection is None

    def test_parser_collection_accepted_when_provided(self):
        # Given: collection 引数を渡すルート
        parser = _build_parser()

        # When
        args = parser.parse_args(["collections/example", "--model", "veo-3.1-lite-generate-preview"])

        # Then
        assert args.collection == "collections/example"
        assert args.model == "veo-3.1-lite-generate-preview"

    def test_parser_other_flags_still_parse(self):
        # Given: --prompt / --smooth / --crossfade / -y は今回触らない。regression。
        parser = _build_parser()

        # When
        args = parser.parse_args(
            [
                "--prompt",
                "test prompt",
                "--smooth",
                "--crossfade",
                "0.8",
                "-y",
            ]
        )

        # Then
        assert args.prompt == "test prompt"
        assert args.smooth is True
        assert args.crossfade == 0.8
        assert args.yes is True
