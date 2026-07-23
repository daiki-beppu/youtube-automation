"""image_provider.config の単体テスト。

skill-config の `image_generation` namespace パース、
OpenAI provider の `aspect_ratio` バリデーション、
provider 値のバリデーションを検証する。
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.config import (
    SUPPORTED_PROVIDERS,
    CodexConfig,
    GeminiConfig,
    ImageGenerationConfig,
    OpenAIConfig,
    build_codex_prompt,
    parse_image_generation_config,
    render_codex_prompt,
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

    def test_openai_quality_defaults_to_medium_when_omitted(self):
        """Given provider=openai で quality 未指定
        When parse する
        Then 既定 quality は medium（high は高単価のため明示 opt-in のみ、#1697）
        """
        skill_cfg = {
            "image_generation": {
                "provider": "openai",
                "openai": {"aspect_ratio": "16:9"},
            }
        }

        cfg = parse_image_generation_config(skill_cfg)

        assert cfg.openai.quality == "medium"

    def test_openai_quality_high_is_honored_when_explicitly_set(self):
        """Given provider=openai で quality=high を明示 override
        When parse する
        Then high が採用される
        """
        skill_cfg = {
            "image_generation": {
                "provider": "openai",
                "openai": {"quality": "high", "aspect_ratio": "16:9"},
            }
        }

        cfg = parse_image_generation_config(skill_cfg)

        assert cfg.openai.quality == "high"

    def test_parses_image_generation_namespace_for_codex_prompt_template(self):
        """Given image_generation.provider が codex
        When skill-config を parse する
        Then codex は正規 provider として通り、prompt template を保持する。
        """
        # Given
        skill_cfg = {
            "image_generation": {
                "provider": "codex",
                "codex": {"default_prompt_template": "Use the title {title}."},
            }
        }

        # When
        cfg = parse_image_generation_config(skill_cfg)

        # Then
        assert cfg.provider == "codex"
        assert cfg.gemini is None
        assert cfg.openai is None
        assert isinstance(cfg.codex, CodexConfig)
        assert cfg.codex.default_prompt_template == "Use the title {title}."

    def test_parses_image_generation_namespace_for_codex_without_subconfig(self):
        """Given image_generation.provider=codex の最小設定
        When skill-config を parse する
        Then 既存互換として provider-only 設定は成功する。
        """
        cfg = parse_image_generation_config({"image_generation": {"provider": "codex"}})

        assert cfg.provider == "codex"
        assert cfg.codex is not None
        assert cfg.codex.default_prompt_template == ""

    @pytest.mark.parametrize(
        "codex_section",
        [
            None,
            "oops",
            ["oops"],
        ],
    )
    def test_codex_provider_rejects_invalid_subconfig_shape(self, codex_section):
        """Given image_generation.provider=codex
        When codex sub-config が mapping ではない
        Then raw AttributeError ではなく ConfigError で fail-fast する。
        """
        with pytest.raises(ConfigError, match="image_generation\\.codex"):
            parse_image_generation_config({"image_generation": {"provider": "codex", "codex": codex_section}})

    @pytest.mark.parametrize(
        "template",
        [
            "No title placeholder.",
            "{title} and {title}",
        ],
    )
    def test_codex_provider_rejects_invalid_prompt_template(self, template):
        """Given image_generation.provider=codex
        When default_prompt_template が空、または `{title}` を exactly once 含まない
        Then ConfigError で fail-fast する。
        """
        with pytest.raises(ConfigError, match="default_prompt_template"):
            parse_image_generation_config(
                {
                    "image_generation": {
                        "provider": "codex",
                        "codex": {"default_prompt_template": template},
                    }
                }
            )

    @pytest.mark.parametrize(
        "template",
        [
            None,
            123,
            ["Use the title {title}."],
        ],
    )
    def test_codex_provider_rejects_non_string_prompt_template(self, template):
        """Given image_generation.provider=codex
        When default_prompt_template が文字列ではない
        Then ConfigError で fail-fast する。
        """
        with pytest.raises(ConfigError, match="default_prompt_template"):
            parse_image_generation_config(
                {
                    "image_generation": {
                        "provider": "codex",
                        "codex": {"default_prompt_template": template},
                    }
                }
            )

    @pytest.mark.parametrize(
        "skill_cfg",
        [
            {"image_generation": {"provider": "codex"}},
            {"image_generation": {"provider": "codex", "codex": {}}},
            {"image_generation": {"provider": "codex", "codex": {"default_prompt_template": ""}}},
        ],
    )
    def test_build_codex_prompt_rejects_missing_prompt_template(self, skill_cfg):
        """Given provider-only Codex config
        When prompt を build する
        Then template 欠落は実行入口で ConfigError にする。
        """
        with pytest.raises(ConfigError, match="default_prompt_template"):
            build_codex_prompt(skill_cfg, "Rain Study")

    def test_render_codex_prompt_replaces_only_title(self):
        """Given Codex prompt template
        When title を渡す
        Then `{title}` だけが差し替わった prompt を返す。
        """
        prompt = render_codex_prompt("Use the title {title}.", "Rain Study")

        assert prompt == "Use the title Rain Study."

    def test_build_codex_prompt_reads_skill_config_shape(self):
        """Given thumbnail skill-config dict
        When Codex prompt helper を呼ぶ
        Then parser 境界検証済み template に title を差し込む。
        """
        prompt = build_codex_prompt(
            {
                "image_generation": {
                    "provider": "codex",
                    "codex": {"default_prompt_template": "Use the title {title}."},
                }
            },
            "Rain Study",
        )

        assert prompt == "Use the title Rain Study."

    def test_build_codex_prompt_injects_gemini_composition_rules_for_codex(self):
        prompt = build_codex_prompt(
            {
                "image_generation": {
                    "provider": "codex",
                    "gemini": {
                        "composition_rules": {
                            "legend_motif": {"required": True, "description": "blues legend"},
                            "allowed_actions": "playing electric guitar",
                        }
                    },
                    "codex": {"default_prompt_template": "Use the title {title}."},
                }
            },
            "Night Groove",
        )

        assert "legend_motif" in prompt
        assert '"required": true' in prompt
        assert "blues legend" in prompt
        assert "playing electric guitar" in prompt
        assert "override the reference subject" in prompt

    @pytest.mark.parametrize("description", [None, "", "   "])
    def test_build_codex_prompt_rejects_required_legend_motif_without_subject_description(self, description):
        skill_cfg = {
            "image_generation": {
                "provider": "codex",
                "gemini": {
                    "composition_rules": {
                        "legend_motif": {"required": True, "description": description},
                    }
                },
                "codex": {"default_prompt_template": "Use the title {title}."},
            }
        }

        with pytest.raises(ConfigError, match="legend_motif.required=true"):
            build_codex_prompt(skill_cfg, "Night Groove")

    def test_gemini_config_does_not_change_when_composition_rules_are_present(self):
        cfg = parse_image_generation_config(
            {
                "image_generation": {
                    "provider": "gemini",
                    "gemini": {
                        "model": "gemini-test",
                        "composition_rules": {"allowed_actions": "reading"},
                    },
                }
            }
        )

        assert cfg.gemini.model == "gemini-test"
        assert not hasattr(cfg.gemini, "composition_rules")

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
                "gemini": {"generation_mode": "single_step"},
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
        assert cfg.gemini_cli.generation_mode == "single_step"
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
