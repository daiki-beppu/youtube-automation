"""画像生成プロバイダーの設定 dataclass と skill-config パーサ。

skill-config の `image_generation:` namespace を解析し、
`provider` 値に応じた `GeminiConfig` / `OpenAIConfig` または
codex shell 経路を保持する `ImageGenerationConfig` を構築する。

画像設定は `image_generation:` namespace から読み込む。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Literal

from youtube_automation.core.errors import ConfigError

# プロバイダー識別子。`get_provider` の dispatch キーと一致させる。
ProviderName = Literal["gemini", "openai", "codex"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("gemini", "openai", "codex")
_RETIRED_SUBPROCESS_PROVIDER = "gemini" + "_cli"

# OpenAI が受理するアスペクト比（order.md "期待する動作 1": 16:9 と 9:16 のみ）
OPENAI_SUPPORTED_ASPECT_RATIOS: tuple[str, ...] = ("16:9", "9:16")

# 既定値（skill-config 不在時のフォールバック）
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image"
_DEFAULT_GEMINI_IMAGE_SIZE = "2K"

# OpenAI provider の既定 quality。high は単価が数倍高いため既定にしない
# （provider 切替時の無自覚な高単価課金を防ぐ。high は明示 opt-in のみ、#1697）
_DEFAULT_OPENAI_QUALITY = "medium"
_DEFAULT_CODEX_MAX_PARALLEL = 2
_CODEX_THUMBNAIL_OPT_IN_CLAUSE_KEYS = (
    "variation_clause",
    "style_lock_clause",
    "anatomy_clause",
    "typography_clause",
)


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
    ip_safety_clause: str = ""
    composition_rules: dict[str, object] | None = None
    thumbnail_guidance: str | None = None
    max_parallel: int = _DEFAULT_CODEX_MAX_PARALLEL


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

    `image_generation:` namespace がなければ `ImageGenerationConfig.default()` を返す。
    """
    new_section = skill_cfg.get("image_generation")
    if isinstance(new_section, dict):
        return _build_from_new_namespace(new_section)

    return ImageGenerationConfig.default()


def _build_from_new_namespace(section: dict[str, Any]) -> ImageGenerationConfig:
    provider = section.get("provider", "gemini")
    if _is_retired_subprocess_provider(provider):
        raise _retired_subprocess_provider_error(provider)
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"image_generation.provider={provider!r} は未対応。許容値: {SUPPORTED_PROVIDERS}")

    if provider == "gemini":
        gemini_cfg = _build_gemini(section.get("gemini") or {})
        return ImageGenerationConfig(provider="gemini", gemini=gemini_cfg, openai=None)

    if provider == "openai":
        openai_cfg = _build_openai(section.get("openai") or {})
        return ImageGenerationConfig(provider="openai", gemini=None, openai=openai_cfg)

    gemini_section = section.get("gemini")
    composition_rules = _composition_rules_from_gemini(gemini_section)
    thumbnail_guidance = _codex_thumbnail_guidance_from_gemini(gemini_section)
    ip_safety_clause = _ip_safety_clause_from_gemini(gemini_section)
    codex_cfg = (
        _build_codex(
            section.get("codex"),
            composition_rules=composition_rules,
            thumbnail_guidance=thumbnail_guidance,
            ip_safety_clause=ip_safety_clause,
        )
        if "codex" in section
        else CodexConfig(
            composition_rules=composition_rules,
            thumbnail_guidance=thumbnail_guidance,
            ip_safety_clause=ip_safety_clause,
        )
    )
    return ImageGenerationConfig(provider="codex", gemini=None, openai=None, codex=codex_cfg)


def _build_gemini(d: dict[str, Any]) -> GeminiConfig:
    return GeminiConfig(
        model=d.get("model", _DEFAULT_GEMINI_MODEL),
        image_size=d.get("image_size", _DEFAULT_GEMINI_IMAGE_SIZE),
        variation_guard_enabled=d.get("variation_guard_enabled", True),
    )


def _build_openai(d: dict[str, Any]) -> OpenAIConfig:
    return OpenAIConfig(
        model=d.get("model", "gpt-image-2"),
        quality=d.get("quality", _DEFAULT_OPENAI_QUALITY),
        aspect_ratio=d.get("aspect_ratio", "16:9"),
        thinking=d.get("thinking", "medium"),
        batch=int(d.get("batch", 1)),
    )


def _build_codex(
    d: object,
    *,
    composition_rules: dict[str, object] | None,
    thumbnail_guidance: str | None,
    ip_safety_clause: str,
) -> CodexConfig:
    if not isinstance(d, dict):
        raise ConfigError("image_generation.codex は mapping で指定してください")
    template = d.get("default_prompt_template", "")
    if not isinstance(template, str):
        raise ConfigError("image_generation.codex.default_prompt_template は文字列で指定してください")
    if template:
        template = _validate_codex_prompt_template(template)
    max_parallel = d.get("max_parallel", _DEFAULT_CODEX_MAX_PARALLEL)
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel < 1:
        raise ConfigError("image_generation.codex.max_parallel は 1 以上の整数で指定してください")
    return CodexConfig(
        default_prompt_template=template,
        ip_safety_clause=ip_safety_clause,
        composition_rules=composition_rules,
        thumbnail_guidance=thumbnail_guidance,
        max_parallel=max_parallel,
    )


def _ip_safety_clause_from_gemini(section: object) -> str:
    if not isinstance(section, dict):
        return ""
    single_step = section.get("single_step")
    if not isinstance(single_step, dict) or "ip_safety_clause" not in single_step:
        return ""
    clause = single_step["ip_safety_clause"]
    if not isinstance(clause, str):
        raise ConfigError("image_generation.gemini.single_step.ip_safety_clause は文字列で指定してください")
    return clause.strip()


def _composition_rules_from_gemini(section: object) -> dict[str, object] | None:
    if not isinstance(section, dict) or "composition_rules" not in section:
        return None
    rules = section["composition_rules"]
    if not isinstance(rules, dict):
        raise ConfigError("image_generation.gemini.composition_rules は mapping で指定してください")
    return rules


def _codex_thumbnail_guidance_from_gemini(section: object) -> str | None:
    if not isinstance(section, dict) or "single_step" not in section:
        return None
    single_step = section["single_step"]
    if not isinstance(single_step, dict):
        raise ConfigError("image_generation.gemini.single_step は mapping で指定してください")

    configured: list[tuple[str, str]] = []
    for key in _CODEX_THUMBNAIL_OPT_IN_CLAUSE_KEYS:
        value = single_step.get(key, "")
        if not isinstance(value, str):
            raise ConfigError(f"image_generation.gemini.single_step.{key} は文字列で指定してください")
        if normalized := value.strip():
            configured.append((key, normalized))

    if len(configured) > 1:
        keys = ", ".join(key for key, _ in configured)
        raise ConfigError(f"Codex thumbnail の opt-in clause は 1 つだけ指定してください: {keys}")
    if not configured:
        return None
    key, guidance = configured[0]
    return _render_thumbnail_typography_clause(section) if key == "typography_clause" else guidance


def _required_mapping(value: object, key: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{key} は object で指定してください")
    return value


def _required_non_empty_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} は空でない文字列で指定してください")
    return value


def _render_thumbnail_typography_clause(gemini: object) -> str:
    gemini = _required_mapping(gemini, "image_generation.gemini")
    single_step = _required_mapping(gemini.get("single_step"), "image_generation.gemini.single_step")
    thumbnail_text = _required_mapping(gemini.get("thumbnail_text"), "image_generation.gemini.thumbnail_text")
    font = _required_mapping(thumbnail_text.get("font"), "image_generation.gemini.thumbnail_text.font")
    typography_clause = _required_non_empty_string(
        single_step.get("typography_clause"),
        "image_generation.gemini.single_step.typography_clause",
    )
    font_description = _required_non_empty_string(
        font.get("copy"),
        "image_generation.gemini.thumbnail_text.font.copy",
    )
    if "{font_description}" not in typography_clause:
        raise ConfigError(
            "image_generation.gemini.single_step.typography_clause は {font_description} を含めてください"
        )
    return typography_clause.replace("{font_description}", font_description).strip()


def expand_thumbnail_prompt_clauses(prompt: str, skill_cfg: dict) -> str:
    """thumbnail skill-config の prompt clause placeholder を展開する。"""
    typography_placeholder = "${typography_clause}"
    text_strip_placeholder = "${text_strip_clause}"
    if typography_placeholder not in prompt and text_strip_placeholder not in prompt:
        return prompt
    image_generation = _required_mapping(skill_cfg.get("image_generation"), "image_generation")
    gemini = _required_mapping(image_generation.get("gemini"), "image_generation.gemini")
    if typography_placeholder in prompt:
        rendered_clause = _render_thumbnail_typography_clause(gemini)
        prompt = prompt.replace(typography_placeholder, rendered_clause)
    if text_strip_placeholder in prompt:
        single_step = _required_mapping(gemini.get("single_step"), "image_generation.gemini.single_step")
        text_strip_clause = _required_non_empty_string(
            single_step.get("text_strip_clause"),
            "image_generation.gemini.single_step.text_strip_clause",
        ).strip()
        prompt = prompt.replace(text_strip_placeholder, text_strip_clause)
    return prompt


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


def _render_codex_thumbnail_guidance(guidance: str | None) -> str:
    if guidance is None:
        return ""
    return f"\n\nAdditional thumbnail guidance:\n{guidance}"


def _append_codex_ip_safety_clause(prompt: str, clause: str) -> str:
    if not clause or clause in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{clause}"


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
    prompt = _append_codex_ip_safety_clause(prompt, cfg.codex.ip_safety_clause)
    return (
        prompt
        + _render_codex_thumbnail_guidance(cfg.codex.thumbnail_guidance)
        + _render_codex_composition_rules(cfg.codex.composition_rules)
    )


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
    raise ConfigError(f"未対応の provider={cfg.provider!r}")


def _is_retired_subprocess_provider(provider: object) -> bool:
    return provider == _RETIRED_SUBPROCESS_PROVIDER


def _retired_subprocess_provider_error(provider: object) -> ConfigError:
    return ConfigError(
        f"image_generation.provider: {provider} は廃止されました。provider: gemini（Vertex AI）を使用してください"
    )
