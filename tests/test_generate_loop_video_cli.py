"""scripts/generate_loop_video.py の CLI 引数パーサと resolve_prompt のユニットテスト。

Issue #129: `--model` の任意文字列対応。
Issue #358: `--motion-targets` / `--static-targets` の構造化プロンプト対応と
            `resolve_prompt` の優先順位制御。

外部 IO（Vertex AI / load_skill_config / load_dotenv 等）は touch しない。
parser と resolve_prompt（純関数）のみを切り出してテストする。
"""

from __future__ import annotations

import argparse

from youtube_automation.scripts.generate_loop_video import _build_parser, resolve_prompt
from youtube_automation.utils.veo_generator import DEFAULT_PROMPT


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

    def test_parser_accepts_motion_and_static_targets(self):
        # Issue #358: 構造化プロンプト用 CLI 引数
        parser = _build_parser()

        args = parser.parse_args(
            [
                "--motion-targets",
                "leaves,steam",
                "--static-targets",
                "character,two animals (count remains 2)",
            ]
        )

        assert args.motion_targets == "leaves,steam"
        assert args.static_targets == "character,two animals (count remains 2)"

    def test_parser_motion_static_default_none(self):
        # 未指定時は None
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.motion_targets is None
        assert args.static_targets is None


# ---------- resolve_prompt (Issue #358) ----------


_TEMPLATE = (
    "Static composition. The scene is a living painting: {static_clause} remain exactly as in the source image. "
    "The only motion is {motion_clause} — subtle. {base_rules} Loop seamlessly."
)
_BASE_RULES = "Preserve the original lighting."


def _args(prompt=None, motion=None, static=None) -> argparse.Namespace:
    return argparse.Namespace(prompt=prompt, motion_targets=motion, static_targets=static)


class TestResolvePrompt:
    def test_prompt_overrides_everything(self):
        # 優先順位 1: --prompt は最強
        veo_config = {
            "motion_targets": ["leaves"],
            "static_targets": ["character"],
            "prompt_template": _TEMPLATE,
            "base_rules": _BASE_RULES,
            "default_prompt": "default value",
        }
        args = _args(prompt="custom full prompt", motion="x,y", static="z")

        result = resolve_prompt(args, veo_config)

        assert result == "custom full prompt"

    def test_cli_structured_overrides_skill_config_structured(self):
        # 優先順位 2: CLI structured が skill-config の structured / default_prompt より優先
        veo_config = {
            "motion_targets": ["from-config-motion"],
            "static_targets": ["from-config-static"],
            "prompt_template": _TEMPLATE,
            "base_rules": _BASE_RULES,
            "default_prompt": "should not be used",
        }
        args = _args(motion="from-cli-motion", static="from-cli-static")

        result = resolve_prompt(args, veo_config)

        assert "from-cli-motion" in result
        assert "from-cli-static" in result
        assert "from-config-motion" not in result
        assert "should not be used" not in result

    def test_cli_motion_only_with_empty_static_uses_fallback(self):
        # CLI で motion のみ指定 → static は "the rest of the scene" にフォールバック
        veo_config = {
            "prompt_template": _TEMPLATE,
            "base_rules": "",
            "default_prompt": "should not be used",
        }
        args = _args(motion="leaves")

        result = resolve_prompt(args, veo_config)

        assert "leaves" in result
        assert "the rest of the scene" in result

    def test_skill_config_structured_used_when_cli_unspecified(self):
        # 優先順位 3: CLI 未指定で skill-config の structured が非空
        veo_config = {
            "motion_targets": ["config-motion"],
            "static_targets": ["config-static"],
            "prompt_template": _TEMPLATE,
            "base_rules": "",
            "default_prompt": "should not be used",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert "config-motion" in result
        assert "config-static" in result
        assert "should not be used" not in result

    def test_default_prompt_used_when_structured_empty(self):
        # 優先順位 4: structured 系すべて空 → default_prompt
        veo_config = {
            "motion_targets": [],
            "static_targets": [],
            "prompt_template": _TEMPLATE,
            "default_prompt": "channel default prompt",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == "channel default prompt"

    def test_hardcoded_default_used_when_no_config(self):
        # 優先順位 5: skill-config が完全に空
        veo_config: dict = {}
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == DEFAULT_PROMPT

    def test_structured_skipped_when_template_missing(self):
        # prompt_template が無い場合は structured 構築をスキップして default_prompt
        veo_config = {
            "motion_targets": ["leaves"],
            "static_targets": ["character"],
            "default_prompt": "fallback default",
        }
        args = _args()

        result = resolve_prompt(args, veo_config)

        assert result == "fallback default"

    def test_cli_static_only_falls_through_to_skill_config(self, capsys):
        # CLI で static のみ指定 → CLI structured 試行 → motion 空で ValueError →
        # skill-config の motion_targets が非空ならそちらを採用するが、
        # static は CLI 側を優先したいケースは現仕様では非サポート（warning 後 fallback）
        veo_config = {
            "motion_targets": [],
            "static_targets": [],
            "prompt_template": _TEMPLATE,
            "default_prompt": "channel default",
        }
        args = _args(static="character")

        result = resolve_prompt(args, veo_config)

        # CLI motion 空 → structured 構築失敗 → default_prompt
        assert result == "channel default"
        captured = capsys.readouterr()
        assert "CLI structured prompt 構築失敗" in captured.out

    def test_prompt_with_structured_warns(self, capsys):
        # --prompt 指定 + --motion-targets 指定 → warning 出して --prompt 優先
        veo_config = {"prompt_template": _TEMPLATE}
        args = _args(prompt="full", motion="leaves", static="character")

        result = resolve_prompt(args, veo_config)

        assert result == "full"
        captured = capsys.readouterr()
        assert "--prompt が指定されたため" in captured.out
