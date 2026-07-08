"""image_provider の統合テスト。

データフロー横断（skill-config YAML → loader → parse → factory → provider）が
末端まで `provider` 値を正しく伝搬することを検証する。

このテストは以下のモジュール境界を結合して動作確認する:
- youtube_automation.utils.skill_config (YAML loader)
- youtube_automation.utils.image_provider.config (parse)
- youtube_automation.utils.image_provider (factory)
- youtube_automation.utils.image_provider.gemini / openai (provider impl)
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
import yaml

from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider import (
    get_provider,
    load_image_generation_config,
)
from youtube_automation.utils.image_provider.composition import resolve_composition_source
from youtube_automation.utils.image_provider.gemini import GeminiImageProvider
from youtube_automation.utils.image_provider.openai import OpenAIImageProvider


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


def _write_thumbnail_override(channel_dir: Path, payload: dict) -> None:
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / "thumbnail.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestProviderSwitchEndToEnd:
    def test_openai_provider_selected_from_yaml(self, tmp_path: Path, monkeypatch):
        """Given skill-config YAML が `image_generation.provider: openai` を宣言
        When load_image_generation_config → get_provider を順に呼ぶ
        Then OpenAIImageProvider が返り、設定値（model/quality/aspect_ratio）が末端まで届く。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(
            channel_dir,
            {
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
            },
        )

        # When
        cfg = load_image_generation_config()
        provider = get_provider(cfg)

        # Then
        assert cfg.provider == "openai"
        assert isinstance(provider, OpenAIImageProvider)
        assert cfg.openai.model == "gpt-image-2"
        assert cfg.openai.aspect_ratio == "16:9"
        assert cfg.openai.quality == "high"

    def test_gemini_provider_selected_from_yaml(self, tmp_path: Path, monkeypatch):
        """Given skill-config YAML が `image_generation.provider: gemini` を宣言
        When ロード → ファクトリ
        Then GeminiImageProvider が返り、model が末端まで届く。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(
            channel_dir,
            {
                "image_generation": {
                    "provider": "gemini",
                    "gemini": {
                        "model": "gemini-3.1-flash-image-preview",
                        "image_size": "2K",
                    },
                }
            },
        )

        # When
        cfg = load_image_generation_config()
        provider = get_provider(cfg)

        # Then
        assert cfg.provider == "gemini"
        assert isinstance(provider, GeminiImageProvider)
        assert cfg.gemini.model == "gemini-3.1-flash-image-preview"

    def test_codex_provider_selected_from_yaml_and_rejected_by_api_factory(self, tmp_path: Path, monkeypatch):
        """Given skill-config YAML が `image_generation.provider: codex` を宣言
        When load_image_generation_config → get_provider を順に呼ぶ
        Then config 層では codex が伝搬し、API provider factory は codex-image.sh 経路へ誘導する。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(channel_dir, {"image_generation": {"provider": "codex"}})

        # When
        cfg = load_image_generation_config()

        # Then
        assert cfg.provider == "codex"
        assert cfg.gemini is None
        assert cfg.openai is None
        assert cfg.codex is not None
        assert cfg.codex.default_prompt_template.count("{title}") == 1
        for required in (
            "TTP this reference thumbnail into a stronger original textless background",
            "winning layout",
            "Remove all text",
            "Do not add any title text yet",
        ):
            assert required in cfg.codex.default_prompt_template
        with pytest.raises(ConfigError, match="codex-image\\.sh"):
            get_provider(cfg)

    def test_legacy_gemini_image_yaml_still_loads_with_warning(self, tmp_path: Path, monkeypatch):
        """Given 旧 namespace (`gemini_image:`) のみを持つ channel override yaml
        When load_image_generation_config を呼ぶ
        Then DeprecationWarning とともに gemini provider 設定が解決され、
            override 値（default と異なるモデル名）が末端まで到達する。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        # default.yaml の model="gemini-3.1-flash-image-preview" と区別できる値で
        # override が末端まで効いていることを保証する
        legacy_model = "gemini-old-experimental"
        _write_thumbnail_override(
            channel_dir,
            {
                "gemini_image": {
                    "model": legacy_model,
                    "brand_background": "deep navy",
                }
            },
        )

        # When
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = load_image_generation_config()

        # Then
        assert cfg.provider == "gemini"
        assert cfg.gemini.model == legacy_model, "override が default で上書きされ末端まで届いていない"
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) >= 1, "後方互換時に DeprecationWarning が発生していない"


class TestResolveCompositionSource:
    """``composition_source`` 解決の後方互換 (legacy `gemini_image:` のみ override)。

    default.yaml が `image_generation.gemini.*` を宣言しているため、merge 後の
    `image_generation.gemini` は常に non-empty となる。merged dict ベースで
    legacy フォールバックを判定すると、ユーザーが旧 namespace で書いた
    `gemini_image.composition_prefix` 等が黙って捨てられる。
    `resolve_composition_source` は override 単体を見て legacy 値を返す。
    """

    def test_legacy_gemini_image_only_override_returned_as_source(self, tmp_path: Path, monkeypatch):
        """Given user override が `gemini_image:` のみで `image_generation:` を持たない
        When resolve_composition_source を呼ぶ
        Then user の `composition_prefix` / `brand_background` が含まれた legacy dict が返る。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(
            channel_dir,
            {
                "gemini_image": {
                    "brand_background": "deep navy",
                    "composition_prefix": "Cinematic, dramatic lighting,",
                    "composition_keywords": ["cinematic", "dramatic"],
                }
            },
        )

        # When
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            skill_cfg = skill_config.load_skill_config("thumbnail", use_cache=False)
        source = resolve_composition_source(skill_cfg, "gemini")

        # Then
        assert source.get("brand_background") == "deep navy", "legacy `gemini_image.brand_background` が默殺されている"
        assert source.get("composition_prefix") == "Cinematic, dramatic lighting,", (
            "legacy `composition_prefix` が default の `image_generation.gemini.*` で上書きされている"
        )
        assert source.get("composition_keywords") == ["cinematic", "dramatic"]

    def test_new_namespace_override_returned_when_set(self, tmp_path: Path, monkeypatch):
        """Given user override が `image_generation:` を持つ
        When resolve_composition_source を呼ぶ
        Then merged 後の `image_generation.<provider>` dict が返る。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(
            channel_dir,
            {
                "image_generation": {
                    "provider": "gemini",
                    "gemini": {"brand_background": "warm amber"},
                }
            },
        )

        # When
        skill_cfg = skill_config.load_skill_config("thumbnail", use_cache=False)
        source = resolve_composition_source(skill_cfg, "gemini")

        # Then
        assert source.get("brand_background") == "warm amber"

    def test_openai_provider_does_not_consult_legacy_namespace(self, tmp_path: Path, monkeypatch):
        """Given user override が legacy `gemini_image:` のみ
        When provider="openai" で resolve_composition_source を呼ぶ
        Then merged `image_generation.openai` が返り、legacy section は混入しない。
        """
        # Given
        channel_dir = tmp_path / "ch"
        channel_dir.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
        _write_thumbnail_override(
            channel_dir,
            {"gemini_image": {"brand_background": "should-not-leak"}},
        )

        # When
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            skill_cfg = skill_config.load_skill_config("thumbnail", use_cache=False)
        source = resolve_composition_source(skill_cfg, "openai")

        # Then
        assert "brand_background" not in source or source.get("brand_background") != "should-not-leak"
        # default.yaml の openai section が返ることを確認
        assert source.get("model") == "gpt-image-2"
