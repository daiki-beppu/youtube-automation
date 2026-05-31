"""image_provider.config の単体テスト。

skill-config の `image_generation` namespace パース、
旧 `gemini_image` namespace の後方互換読み込み（DeprecationWarning 付き）、
OpenAI provider の `aspect_ratio` バリデーション、
provider 値のバリデーションを検証する。
"""

from __future__ import annotations

import warnings

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.config import (
    SUPPORTED_PROVIDERS,
    GeminiConfig,
    ImageGenerationConfig,
    OpenAIConfig,
    parse_image_generation_config,
    replace_model,
)

# ---------- parse_image_generation_config ----------


class TestParseImageGenerationConfig:
    def test_parses_image_generation_namespace_for_gemini(self):
        # Given: 新 namespace + provider=gemini
        skill_cfg = {
            "image_generation": {
                "provider": "gemini",
                "gemini": {
                    "model": "gemini-3.1-flash-image-preview",
                    "image_size": "2K",
                },
            }
        }

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert isinstance(cfg, ImageGenerationConfig)
        assert cfg.provider == "gemini"
        assert cfg.gemini.model == "gemini-3.1-flash-image-preview"
        assert cfg.gemini.image_size == "2K"

    def test_parses_image_generation_namespace_for_openai(self):
        # Given
        skill_cfg = {
            "image_generation": {
                "provider": "openai",
                "openai": {
                    "model": "gpt-image-2",
                    "quality": "high",
                    "aspect_ratio": "16:9",
                    "thinking": "medium",
                    "batch": 1,
                },
            }
        }

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert cfg.provider == "openai"
        assert cfg.openai.model == "gpt-image-2"
        assert cfg.openai.quality == "high"
        assert cfg.openai.aspect_ratio == "16:9"
        assert cfg.openai.thinking == "medium"
        assert cfg.openai.batch == 1

    def test_parses_image_generation_namespace_for_codex_without_api_sub_config(self):
        """Given image_generation.provider が codex
        When skill-config を parse する
        Then codex は正規 provider として通り、API provider 用 sub-config は作られない。
        """
        # Given
        skill_cfg = {"image_generation": {"provider": "codex"}}

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert cfg.provider == "codex"
        assert cfg.gemini is None
        assert cfg.openai is None

    def test_supported_providers_declares_codex(self):
        """Given provider 設定の許容値
        When SUPPORTED_PROVIDERS を読む
        Then codex / gemini_cli が gemini/openai と同じ provider 値として列挙される。
        """
        assert SUPPORTED_PROVIDERS == ("gemini", "openai", "codex", "gemini_cli")

    def test_parses_image_generation_namespace_for_gemini_cli(self):
        """#474: provider=gemini_cli で GeminiCliConfig が組み立てられる。"""
        # Given
        skill_cfg = {
            "image_generation": {
                "provider": "gemini_cli",
                "gemini_cli": {
                    "model": "gemini-2.5-flash-image-preview",
                    "image_size": "2K",
                    "timeout_seconds": 120,
                },
            }
        }

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert cfg.provider == "gemini_cli"
        assert cfg.gemini_cli is not None
        assert cfg.gemini_cli.model == "gemini-2.5-flash-image-preview"
        assert cfg.gemini_cli.image_size == "2K"
        assert cfg.gemini_cli.timeout_seconds == 120
        # 他 provider の sub-config は埋めない
        assert cfg.gemini is None
        assert cfg.openai is None

    def test_gemini_cli_uses_defaults_when_subconfig_omitted(self):
        """#474: gemini_cli sub-config 省略時は既定値で組み立てる。"""
        # Given
        skill_cfg = {"image_generation": {"provider": "gemini_cli"}}

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert cfg.provider == "gemini_cli"
        assert cfg.gemini_cli.model == "gemini-2.5-flash-image-preview"
        assert cfg.gemini_cli.image_size == "2K"
        assert cfg.gemini_cli.timeout_seconds == 300

    def test_replace_model_overrides_gemini_cli_model(self):
        """#474: replace_model が gemini_cli の active provider 側モデルを差し替える。"""
        # Given
        cfg = parse_image_generation_config({"image_generation": {"provider": "gemini_cli"}})

        # When
        replaced = replace_model(cfg, "gemini-3.0-flash-image-preview")

        # Then
        assert replaced.gemini_cli.model == "gemini-3.0-flash-image-preview"

    def test_legacy_gemini_image_namespace_emits_deprecation_warning(self):
        # Given: 旧 namespace
        skill_cfg = {
            "gemini_image": {
                "model": "gemini-3.1-flash-image-preview",
                "brand_background": "deep navy",
            }
        }

        # When
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = parse_image_generation_config(skill_cfg)

        # Then: gemini provider にフォールバック
        assert cfg.provider == "gemini"
        assert cfg.gemini.model == "gemini-3.1-flash-image-preview"

        # And: DeprecationWarning が発生し新 namespace への移行を促す
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) >= 1, "DeprecationWarning が発生していない"
        msg = str(deprecations[0].message)
        assert "gemini_image" in msg
        assert "image_generation" in msg

    def test_image_generation_takes_precedence_over_legacy_gemini_image(self):
        # Given: 両 namespace が共存（移行期間の状態）
        skill_cfg = {
            "image_generation": {
                "provider": "openai",
                "openai": {
                    "model": "gpt-image-2",
                    "quality": "high",
                    "aspect_ratio": "16:9",
                    "thinking": "medium",
                    "batch": 1,
                },
            },
            "gemini_image": {"model": "gemini-old"},
        }

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then: 新 namespace が勝つ
        assert cfg.provider == "openai"
        assert cfg.openai.model == "gpt-image-2"

    def test_unknown_provider_raises_config_error(self):
        # Given: 未対応 provider 名
        skill_cfg = {
            "image_generation": {
                "provider": "midjourney",
            }
        }

        # When / Then
        with pytest.raises(ConfigError, match="midjourney"):
            parse_image_generation_config(skill_cfg)

    def test_empty_skill_cfg_returns_default_config(self):
        # Given: 空 skill_cfg
        skill_cfg = {}

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then: 既定 provider が解決される（Fail Fast の対象外: 設定不在は許容ケース）
        assert cfg.provider in ("gemini", "openai")
        # And: 対応する provider の dataclass が埋まっている
        if cfg.provider == "gemini":
            assert cfg.gemini is not None
        else:
            assert cfg.openai is not None


# ---------- OpenAIConfig aspect_ratio バリデーション ----------


class TestOpenAIConfigAspectRatioValidation:
    @pytest.mark.parametrize("ratio", ["16:9", "9:16"])
    def test_accepts_supported_aspect_ratios(self, ratio: str):
        # Given / When
        cfg = OpenAIConfig(
            model="gpt-image-2",
            quality="high",
            aspect_ratio=ratio,
            thinking="medium",
            batch=1,
        )

        # Then
        assert cfg.aspect_ratio == ratio

    @pytest.mark.parametrize("ratio", ["1:1", "4:3", "3:4", "21:9", "16x9", "16:9 ", ""])
    def test_rejects_unsupported_aspect_ratios(self, ratio: str):
        # When / Then
        with pytest.raises(ConfigError, match="aspect_ratio"):
            OpenAIConfig(
                model="gpt-image-2",
                quality="high",
                aspect_ratio=ratio,
                thinking="medium",
                batch=1,
            )

    def test_parse_propagates_unsupported_aspect_ratio_error(self):
        # Given
        skill_cfg = {
            "image_generation": {
                "provider": "openai",
                "openai": {
                    "model": "gpt-image-2",
                    "quality": "high",
                    "aspect_ratio": "1:1",
                    "thinking": "medium",
                    "batch": 1,
                },
            }
        }

        # When / Then
        with pytest.raises(ConfigError, match="aspect_ratio"):
            parse_image_generation_config(skill_cfg)


# ---------- GeminiConfig はアスペクト比制限なし（branding/icon.png 用途） ----------


class TestGeminiConfigDoesNotRestrictAspectRatio:
    """Gemini provider は branding/icon.png (1:1) 等の任意比率を受け付ける必要がある。

    `OpenAIConfig` のような `__post_init__` バリデーションを `GeminiConfig` に
    入れてしまうと既存 CLI (`yt-generate-image --aspect-ratio 1:1`) を壊す。
    """

    def test_gemini_config_construction_does_not_take_aspect_ratio_field(self):
        # Given: GeminiConfig の必須キーだけを渡す
        # When
        cfg = GeminiConfig(
            model="gemini-3.1-flash-image-preview",
            image_size="2K",
        )

        # Then: aspect_ratio は config レベルでは保持しない（Request 側で渡す）
        assert cfg.model == "gemini-3.1-flash-image-preview"
        assert cfg.image_size == "2K"
        assert not hasattr(cfg, "aspect_ratio") or getattr(cfg, "aspect_ratio", None) is None


# ---------- ImageGenerationConfig.default() ----------


class TestImageGenerationConfigDefault:
    def test_default_returns_a_valid_config(self):
        # When
        cfg = ImageGenerationConfig.default()

        # Then: provider が解決され、その provider の dataclass が埋まっている
        assert cfg.provider in ("gemini", "openai")
        if cfg.provider == "gemini":
            assert cfg.gemini is not None
            assert cfg.gemini.model
        else:
            assert cfg.openai is not None
            assert cfg.openai.model
