"""画像生成プロバイダーの設定 dataclass と skill-config パーサ。

skill-config の `image_generation:` namespace を解析し、
`provider` 値に応じた `GeminiConfig` / `OpenAIConfig` または
codex shell 経路を保持する `ImageGenerationConfig` を構築する。

旧 `gemini_image:` namespace は ``DeprecationWarning`` 付きで読み込み継続する
（後方互換性。新 namespace と共存時は新 namespace を優先）。
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, replace
from typing import Any, Literal

from youtube_automation.utils.exceptions import ConfigError

# プロバイダー識別子。`get_provider` の dispatch キーと一致させる。
ProviderName = Literal["gemini", "openai", "codex", "gemini_cli"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("gemini", "openai", "codex", "gemini_cli")

# OpenAI が受理するアスペクト比（order.md "期待する動作 1": 16:9 と 9:16 のみ）
OPENAI_SUPPORTED_ASPECT_RATIOS: tuple[str, ...] = ("16:9", "9:16")

# 既定値（skill-config 不在時のフォールバック）
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image-preview"
_DEFAULT_GEMINI_IMAGE_SIZE = "2K"

# gemini_cli provider 既定値（サブスク認証の gemini CLI 経由 / nano-banana）
_DEFAULT_GEMINI_CLI_MODEL = "gemini-2.5-flash-image-preview"
_DEFAULT_GEMINI_CLI_IMAGE_SIZE = "2K"
_DEFAULT_GEMINI_CLI_TIMEOUT = 300

# OpenAI provider の既定 quality。high は単価が数倍高いため既定にしない
# （provider 切替時の無自覚な高単価課金を防ぐ。high は明示 opt-in のみ、#1697）
_DEFAULT_OPENAI_QUALITY = "medium"


@dataclass(frozen=True)
class GeminiConfig:
    """Gemini 画像生成プロバイダーの設定。

    Note:
        ``aspect_ratio`` フィールドは持たない。Gemini は branding/icon.png 用途で
        1:1 等の任意比率を受け付ける必要があるため、aspect_ratio は
        ``ImageGenerationRequest`` 経由で都度渡す。
    """

    model: str
    image_size: str = _DEFAULT_GEMINI_IMAGE_SIZE
    variation_guard_enabled: bool = True


@dataclass(frozen=True)
class GeminiCliConfig:
    """gemini CLI 経由（サブスク認証）画像生成プロバイダーの設定。

    ADC 課金の ``GeminiConfig`` と異なり、Google AI Pro/Ultra サブスクで認証された
    ``gemini`` CLI（``@google/gemini-cli``）を subprocess で叩く。GCP 従量課金を
    発生させずに枚数の多いサムネ生成のコストを抑える用途 (#474)。

    Note:
        ``GeminiConfig`` 同様に ``aspect_ratio`` フィールドは持たない。比率は
        ``ImageGenerationRequest`` 経由で都度渡し、branding/icon.png 用途の 1:1 等も許容する。

    Attributes:
        model: gemini CLI に ``-m`` で渡すモデル ID
        image_size: 解像度ヒント（プロンプトに埋め込む）
        timeout_seconds: subprocess 1 回あたりのタイムアウト秒
        generation_mode: thumbnail の生成モード。``single_step`` の場合は参照画像を必須化する
    """

    model: str = _DEFAULT_GEMINI_CLI_MODEL
    image_size: str = _DEFAULT_GEMINI_CLI_IMAGE_SIZE
    timeout_seconds: int = _DEFAULT_GEMINI_CLI_TIMEOUT
    generation_mode: str | None = None


@dataclass(frozen=True)
class OpenAIConfig:
    """OpenAI 画像生成プロバイダー（gpt-image-2 系）の設定。

    ``__post_init__`` で ``aspect_ratio`` を ``OPENAI_SUPPORTED_ASPECT_RATIOS`` に
    制限する（Fail Fast）。
    """

    model: str
    quality: str
    aspect_ratio: str
    thinking: str
    batch: int

    def __post_init__(self) -> None:
        if self.aspect_ratio not in OPENAI_SUPPORTED_ASPECT_RATIOS:
            raise ConfigError(
                f"OpenAI image_generation.openai.aspect_ratio={self.aspect_ratio!r} は未対応。"
                f"許容値: {OPENAI_SUPPORTED_ASPECT_RATIOS}"
            )


@dataclass(frozen=True)
class CodexConfig:
    """Codex shell 経路で使う prompt 設定。"""

    default_prompt_template: str = ""
    composition_rules: dict[str, object] | None = None


@dataclass(frozen=True)
class ImageGenerationConfig:
    """provider 切り替え可能な画像生成設定の親 dataclass。

    ``provider`` の値に対応する側のみが非 None（例: provider="gemini" なら
    ``gemini`` のみ）。``codex`` は shell 経路なので API provider ではないが、
    prompt template などの実行契約は ``codex`` に保持する。
    """

    provider: ProviderName
    gemini: GeminiConfig | None = None
    openai: OpenAIConfig | None = None
    codex: CodexConfig | None = None
    gemini_cli: GeminiCliConfig | None = None

    @classmethod
    def default(cls) -> "ImageGenerationConfig":
        """skill-config 不在時のフォールバック既定値。"""
        return cls(
            provider="gemini",
            gemini=GeminiConfig(model=_DEFAULT_GEMINI_MODEL, image_size=_DEFAULT_GEMINI_IMAGE_SIZE),
            openai=None,
        )


def parse_image_generation_config(skill_cfg: dict[str, Any]) -> ImageGenerationConfig:
    """skill-config（dict）から `ImageGenerationConfig` を組み立てる。

    優先順位:
    1. `image_generation:` namespace があればそちらを使う
    2. `gemini_image:` namespace のみあれば後方互換でロード
    3. どちらも無ければ `ImageGenerationConfig.default()` を返す

    `gemini_image:` namespace が（共存・単独どちらの場合でも）skill_cfg に存在すれば
    ``DeprecationWarning`` を発行する。
    """
    legacy_section = skill_cfg.get("gemini_image")
    if isinstance(legacy_section, dict):
        warnings.warn(
            "skill-config の `gemini_image:` namespace は非推奨です。"
            "`image_generation.provider: gemini` + `image_generation.gemini.*` に移行してください。",
            DeprecationWarning,
            stacklevel=2,
        )

    new_section = skill_cfg.get("image_generation")
    if isinstance(new_section, dict):
        return _build_from_new_namespace(new_section)

    if isinstance(legacy_section, dict):
        return _build_from_legacy_gemini(legacy_section)

    return ImageGenerationConfig.default()


def _build_from_new_namespace(section: dict[str, Any]) -> ImageGenerationConfig:
    provider = section.get("provider", "gemini")
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"image_generation.provider={provider!r} は未対応。許容値: {SUPPORTED_PROVIDERS}")

    if provider == "gemini":
        gemini_cfg = _build_gemini(section.get("gemini") or {})
        return ImageGenerationConfig(provider="gemini", gemini=gemini_cfg, openai=None)

    if provider == "openai":
        openai_cfg = _build_openai(section.get("openai") or {})
        return ImageGenerationConfig(provider="openai", gemini=None, openai=openai_cfg)

    if provider == "gemini_cli":
        gemini_section = section.get("gemini")
        generation_mode = gemini_section.get("generation_mode") if isinstance(gemini_section, dict) else None
        gemini_cli_cfg = _build_gemini_cli(section.get("gemini_cli") or {}, generation_mode=generation_mode)
        return ImageGenerationConfig(provider="gemini_cli", gemini_cli=gemini_cli_cfg)

    gemini_section = section.get("gemini")
    composition_rules = _composition_rules_from_gemini(gemini_section)
    codex_cfg = (
        _build_codex(section.get("codex"), composition_rules=composition_rules)
        if "codex" in section
        else CodexConfig(composition_rules=composition_rules)
    )
    return ImageGenerationConfig(provider="codex", gemini=None, openai=None, codex=codex_cfg)


def _build_from_legacy_gemini(legacy: dict[str, Any]) -> ImageGenerationConfig:
    """旧 `gemini_image:` 直下の dict から GeminiConfig を組み立てる。"""
    return ImageGenerationConfig(
        provider="gemini",
        gemini=_build_gemini(legacy),
        openai=None,
    )


def _build_gemini(d: dict[str, Any]) -> GeminiConfig:
    return GeminiConfig(
        model=d.get("model", _DEFAULT_GEMINI_MODEL),
        image_size=d.get("image_size", _DEFAULT_GEMINI_IMAGE_SIZE),
        variation_guard_enabled=d.get("variation_guard_enabled", True),
    )


def _build_gemini_cli(d: dict[str, object], *, generation_mode: str | None = None) -> GeminiCliConfig:
    return GeminiCliConfig(
        model=d.get("model", _DEFAULT_GEMINI_CLI_MODEL),
        image_size=d.get("image_size", _DEFAULT_GEMINI_CLI_IMAGE_SIZE),
        timeout_seconds=int(d.get("timeout_seconds", _DEFAULT_GEMINI_CLI_TIMEOUT)),
        generation_mode=generation_mode,
    )


def _build_openai(d: dict[str, Any]) -> OpenAIConfig:
    return OpenAIConfig(
        model=d.get("model", "gpt-image-2"),
        quality=d.get("quality", _DEFAULT_OPENAI_QUALITY),
        aspect_ratio=d.get("aspect_ratio", "16:9"),
        thinking=d.get("thinking", "medium"),
        batch=int(d.get("batch", 1)),
    )


def _build_codex(d: object, *, composition_rules: dict[str, object] | None) -> CodexConfig:
    if not isinstance(d, dict):
        raise ConfigError("image_generation.codex は mapping で指定してください")
    template = d.get("default_prompt_template", "")
    if not isinstance(template, str):
        raise ConfigError("image_generation.codex.default_prompt_template は文字列で指定してください")
    if template:
        template = _validate_codex_prompt_template(template)
    return CodexConfig(default_prompt_template=template, composition_rules=composition_rules)


def _composition_rules_from_gemini(section: object) -> dict[str, object] | None:
    if not isinstance(section, dict) or "composition_rules" not in section:
        return None
    rules = section["composition_rules"]
    if not isinstance(rules, dict):
        raise ConfigError("image_generation.gemini.composition_rules は mapping で指定してください")
    return rules


def _validate_codex_prompt_template(template: Any) -> str:
    if not isinstance(template, str) or not template.strip():
        raise ConfigError("image_generation.codex.default_prompt_template は空でない文字列で指定してください")
    if template.count("{title}") != 1:
        raise ConfigError("image_generation.codex.default_prompt_template は {title} をちょうど 1 回含めてください")
    return template


def render_codex_prompt(template: str, title: str) -> str:
    """Codex thumbnail prompt template の `{title}` を差し替える。"""
    if not isinstance(title, str) or not title.strip():
        raise ConfigError("Codex thumbnail prompt の title は空でない文字列で指定してください")
    return _validate_codex_prompt_template(template).replace("{title}", title)


def _render_codex_composition_rules(rules: dict[str, object] | None) -> str:
    if not rules:
        return ""
    rendered = json.dumps(rules, ensure_ascii=False, sort_keys=True)
    return f"\n\nComposition rules (must follow; these override the reference subject):\n{rendered}"


def _validate_required_legend_motif(rules: dict[str, object] | None) -> None:
    if not rules:
        return
    legend_motif = rules.get("legend_motif")
    if not isinstance(legend_motif, dict) or legend_motif.get("required") is not True:
        return
    description = legend_motif.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ConfigError(
            "image_generation.gemini.composition_rules.legend_motif.required=true の場合、"
            "被写体を指定する空でない description が必要です"
        )


def build_codex_prompt(skill_cfg: dict[str, Any], title: str) -> str:
    """thumbnail skill-config から Codex 用 prompt を生成する。"""
    cfg = parse_image_generation_config(skill_cfg)
    if cfg.provider != "codex" or cfg.codex is None:
        raise ConfigError("image_generation.provider=codex の設定で実行してください")
    _validate_required_legend_motif(cfg.codex.composition_rules)
    prompt = render_codex_prompt(cfg.codex.default_prompt_template, title)
    return prompt + _render_codex_composition_rules(cfg.codex.composition_rules)


def replace_model(cfg: ImageGenerationConfig, model: str) -> ImageGenerationConfig:
    """``ImageGenerationConfig`` の active provider 側のモデル ID を差し替えた複製を返す。

    CLI の ``--model`` 引数で skill-config のモデル値を上書きする用途。
    active provider 側の sub-config が None なら ``ConfigError``。
    """
    if cfg.provider == "gemini":
        if cfg.gemini is None:
            raise ConfigError("provider=gemini だが gemini 設定が見つかりません")
        return replace(cfg, gemini=replace(cfg.gemini, model=model))
    if cfg.provider == "openai":
        if cfg.openai is None:
            raise ConfigError("provider=openai だが openai 設定が見つかりません")
        return replace(cfg, openai=replace(cfg.openai, model=model))
    if cfg.provider == "gemini_cli":
        if cfg.gemini_cli is None:
            raise ConfigError("provider=gemini_cli だが gemini_cli 設定が見つかりません")
        return replace(cfg, gemini_cli=replace(cfg.gemini_cli, model=model))
    raise ConfigError(f"未対応の provider={cfg.provider!r}")
