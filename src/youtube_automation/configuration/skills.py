"""skill-config ローダー

各スキル (.claude/skills/<skill>/config.default.yaml) のデフォルト値と、
チャンネルリポジトリ側 (config/skills/<skill>.yaml) の上書きをマージして返す。
postmortem は `flop-analysis.yaml` を優先し、旧 `postmortem.yaml` だけが
存在する場合は UserWarning を出して互換読み込みする。

使い方:

    from youtube_automation.configuration.skills import load_skill_config

    cfg = load_skill_config("thumbnail")
    bg = cfg.get("image_generation", {}).get("gemini", {}).get("brand_background")

設計方針:
- 原則スキーマ検証なし。実行経路を切り替える一部の列挙値だけ Fail Fast で検証
- プロセス内キャッシュ (skill 名ごと)。reset() でクリア可
- editable install / wheel 両対応 (importlib.resources)
"""

from __future__ import annotations

import json
import stat
import warnings
from collections.abc import Mapping
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Final

import yaml

from youtube_automation.configuration import channel_dir as configured_channel_dir
from youtube_automation.core.errors import ConfigError

_cache: dict[str, dict[str, Any]] = {}

SKILL_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "analytics",
        "audit.metadata",
        "audit.video",
        "benchmark",
        "collection-ideate",
        "discover-competitors",
        "flop-analysis",
        "loop-video",
        "masterup",
        "music.generate",
        "music.prompt",
        "suno",
        "suno-helper",
        "thumbnail",
    }
)
SKILL_ONLY_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "community-post",
        "live-clean",
        "lyria",
        "music.lyric",
        "metadata-audit",
        "publish",
        "short",
        "suno-lyric",
        "video-analyze",
        "video-description",
        "video-upload",
        "video",
        "videoup",
    }
)

# `postmortem` は `flop-analysis` への既存の読み替え入口であり、配布 config の
# 正規キーではない。正規キー集合へ混ぜると実在ファイルとの双方向契約を壊す。
_LEGACY_SKILL_CONFIG_ALIASES: Final[frozenset[str]] = frozenset({"postmortem"})

# 公開 skill directory の統合後も、下流 override の旧キーと同梱 default の対応を
# 維持する。キー名の移行は migrate-config の責務であり、loader は先行変更しない。
_MOVED_SKILL_CONFIG_DEFAULTS: Final[dict[str, Path]] = {
    "benchmark": Path("channel-research", "config.default.yaml"),
    "collection-ideate": Path("wf-new", "references", "collection-ideate.config.default.yaml"),
    "community-post": Path("publish", "config.default.yaml"),
    "discover-competitors": Path("channel-research", "config.default.yaml"),
    "flop-analysis": Path("analytics", "config.default.yaml"),
    "loop-video": Path("thumbnail", "config.default.yaml"),
    "live-clean": Path("publish", "config.default.yaml"),
    "lyria": Path("music", "config.default.yaml"),
    "masterup": Path("music", "config.default.yaml"),
    "metadata-audit": Path("audit", "config.default.yaml"),
    "suno": Path("music", "config.default.yaml"),
    "suno-helper": Path("music", "config.default.yaml"),
    "suno-lyric": Path("music", "config.default.yaml"),
    "video-upload": Path("publish", "config.default.yaml"),
    "video-description": Path("video", "config.default.yaml"),
    "videoup": Path("video", "config.default.yaml"),
    "video-analyze": Path("audit", "config.default.yaml"),
}

_MOVED_SKILL_CONFIG_SECTIONS: Final[dict[str, tuple[str, ...]]] = {
    "benchmark": ("benchmark",),
    "community-post": ("community",),
    "discover-competitors": ("discover",),
    "flop-analysis": ("flop",),
    "loop-video": ("loop",),
    "live-clean": ("clean",),
    "lyria": ("generate", "lyria"),
    "masterup": ("master",),
    "metadata-audit": ("metadata",),
    "postmortem": ("flop",),
    "suno": ("prompt",),
    "suno-helper": ("generate", "suno"),
    "suno-lyric": ("lyric",),
    "video-upload": ("upload",),
    "video-description": ("describe",),
    "videoup": ("generate",),
    "video-analyze": ("video",),
}

# 名前空間移行後も、明示 migration 前の下流 override を同じ実行経路で読む。
_NAMESPACED_LEGACY_OVERRIDE_OWNERS: Final[dict[str, str]] = {
    "music.prompt": "suno",
    "music.lyric": "suno-lyric",
    "audit.metadata": "metadata-audit",
    "video.generate": "videoup",
    "audit.video": "video-analyze",
}

_THUMBNAIL_TEXT_RENDER_MODES = frozenset({"ai_burn_in", "deterministic"})
_ACKNOWLEDGED_UNKNOWN_KEYS = "acknowledged_unknown_keys"

# #1702: 基底 config から縮小済みのキー。channel override は引き続き deep-merge で
# 有効（挙動は壊さない）だが、後続リリースでの物理削除に先立ち DeprecationWarning で
# 移行を促す。移行先は diff_prompt_template / thumbnail_text.text_overlay_prompt の本文。
_DEPRECATED_OVERRIDE_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "thumbnail": (
        ("image_generation", "gemini", "composition_rules", "environment"),
        ("image_generation", "gemini", "composition_rules", "character_size"),
        ("image_generation", "gemini", "composition_rules", "character_pose"),
        ("image_generation", "gemini", "composition_rules", "allowed_actions"),
        ("image_generation", "gemini", "composition_rules", "ng_actions"),
        ("image_generation", "gemini", "composition_rules", "background"),
        ("image_generation", "gemini", "composition_rules", "channel_branding"),
        ("image_generation", "gemini", "thumbnail_text", "channel_name_style"),
        ("image_generation", "gemini", "thumbnail_text", "title_format"),
        ("image_generation", "gemini", "thumbnail_text", "title_prefix"),
        ("image_generation", "gemini", "thumbnail_text", "copy_position"),
        ("image_generation", "gemini", "thumbnail_text", "color"),
        ("image_generation", "gemini", "thumbnail_text", "decoration"),
    ),
}

# config.default.yaml との merge ではなく、load_channel_override() や skill 同梱
# script から直接参照する正規のトップレベルキー。defaults に値を置くと「明示設定の
# 有無」を区別できなくなるため、未知キー検査だけで skill ごとに宣言する。
_KNOWN_OVERRIDE_ONLY_KEYS: dict[str, frozenset[str]] = {
    "suno": frozenset({"tracklist_strategy", "vocal_gender"}),
    "videoup": frozenset({"effect", "shrink"}),
}


def _collect_deprecated_override_keys(
    skill: str, override: dict[str, object], *, codex_provider: bool = False
) -> list[str]:
    """override に含まれる deprecated キーを dotted path のリストで返す。"""
    found: list[str] = []
    for key_path in _DEPRECATED_OVERRIDE_KEYS.get(skill, ()):
        node: object = override
        for key in key_path:
            if not isinstance(node, dict) or key not in node:
                break
            node = node[key]
        else:
            dotted_path = ".".join(key_path)
            if not (codex_provider and dotted_path.startswith("image_generation.gemini.composition_rules.")):
                found.append(dotted_path)
    return found


def _warn_deprecated_override_keys(
    skill: str,
    override: dict[str, object],
    override_path: Path,
    merged: dict[str, object],
) -> None:
    image_generation = merged.get("image_generation")
    codex_provider = isinstance(image_generation, dict) and image_generation.get("provider") == "codex"
    deprecated_keys = _collect_deprecated_override_keys(skill, override, codex_provider=codex_provider)
    if not deprecated_keys:
        return
    migration_target = (
        "image_generation.codex.default_prompt_template または single_step の opt-in clause"
        if codex_provider
        else "diff_prompt_template / thumbnail_text.text_overlay_prompt の本文"
    )
    warnings.warn(
        f"skill-config {override_path} の deprecated キーを検出しました: "
        f"{', '.join(deprecated_keys)}。これらは基底 config から縮小済みで、"
        "後続リリースで削除予定です（現時点では従来どおり deep-merge されます）。"
        f"意図は {migration_target} へ移行してください (#1702)。",
        DeprecationWarning,
        stacklevel=3,
    )


def _find_nested_key_paths(defaults: dict[str, object], target_key: str) -> list[str]:
    paths: list[str] = []

    def visit(node: dict[str, object], prefix: tuple[str, ...]) -> None:
        for key, value in node.items():
            path = (*prefix, key)
            if prefix and key == target_key:
                paths.append(".".join(path))
            if isinstance(value, dict):
                visit(value, path)

    visit(defaults, ())
    return paths


def _warn_unknown_top_level_override_keys(
    skill: str,
    override: dict[str, object],
    defaults: dict[str, object],
    override_path: Path,
    acknowledged: set[str],
) -> None:
    known_keys = defaults.keys() | _KNOWN_OVERRIDE_ONLY_KEYS.get(skill, frozenset())
    unknown_keys = sorted(override.keys() - known_keys - acknowledged)
    if not unknown_keys:
        return
    suggestions = [
        f"'{unknown_key}' → {', '.join(repr(path) for path in nested_paths)}"
        for unknown_key in unknown_keys
        if (nested_paths := _find_nested_key_paths(defaults, unknown_key))
    ]
    suggestion_message = f" 配置先候補: {'; '.join(suggestions)}。" if suggestions else ""
    warnings.warn(
        f"skill-config {override_path} の未知のトップレベルキーを検出しました: "
        f"{', '.join(unknown_keys)}。キー名または階層を確認してください。"
        f"{suggestion_message}"
        "値は互換性のためマージされますが、コードからは参照されない可能性があります。"
        "SKILL.md 経由で AI が読む設計であれば意図どおりです。",
        UserWarning,
        stacklevel=3,
    )


def _split_acknowledged_unknown_keys(
    override: dict[str, object], override_path: Path
) -> tuple[dict[str, object], set[str]]:
    raw = override.get(_ACKNOWLEDGED_UNKNOWN_KEYS, [])
    if not isinstance(raw, list) or any(not isinstance(key, str) or not key for key in raw):
        raise ConfigError(
            f"skill-config {override_path} の acknowledged_unknown_keys は空でない string の array で指定してください"
        )
    cleaned = {key: value for key, value in override.items() if key != _ACKNOWLEDGED_UNKNOWN_KEYS}
    return cleaned, set(raw)


def skill_config_default_relative_path(skill: str) -> Path:
    """Return one config key's canonical path below the distributed skills root."""
    return _MOVED_SKILL_CONFIG_DEFAULTS.get(skill, Path(skill, "config.default.yaml"))


def _default_path(skill: str) -> Path:
    """パッケージ同梱の default.yaml を解決する。

    wheel インストール時は youtube_automation/_skills/<skill>/config.default.yaml、
    editable install 時はソースツリーの .claude/skills/<skill>/config.default.yaml。
    """
    default_skill = "flop-analysis" if skill == "postmortem" else skill
    relative_path = skill_config_default_relative_path(default_skill)
    try:
        resource = files("youtube_automation").joinpath("_skills", *relative_path.parts)
        with as_file(resource) as p:
            path = Path(p)
            if path.exists():
                return path
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    src_fallback = Path(__file__).resolve().parents[3] / ".claude" / "skills" / relative_path
    if src_fallback.exists():
        return src_fallback

    raise ConfigError(
        f"スキル '{skill}' の config.default.yaml が見つかりません "
        "(wheel が壊れているか editable install のソースツリーから実行してください)"
    )


def _channel_override_path(skill: str, target_channel_dir: Path | None = None, suffix: str = "yaml") -> Path:
    """チャンネルリポジトリ側の上書き config パスを返す (存在チェックは呼び出し側)。"""
    root = target_channel_dir if target_channel_dir is not None else configured_channel_dir()
    return root / "config" / "skills" / f"{skill}.{suffix}"


def _channel_override_candidates(skill: str, target_channel_dir: Path | None = None) -> list[Path]:
    """チャンネル側 override 候補を返す。

    JSON 優先は masterup の TS generate-master 互換に限定する。全 skill の
    JSON override 契約は docs / skill 側の読み替えも必要なため別 issue で扱う。
    """
    if skill == "masterup":
        return [
            _channel_override_path(skill, target_channel_dir, "json"),
            _channel_override_path(skill, target_channel_dir, "yaml"),
        ]
    if skill == "postmortem":
        return [
            _channel_override_path("flop-analysis", target_channel_dir, "yaml"),
            _channel_override_path(skill, target_channel_dir, "yaml"),
        ]
    return [_channel_override_path(skill, target_channel_dir, "yaml")]


def _override_candidate_exists(path: Path, *, strict_regular_file: bool) -> bool:
    if not strict_regular_file:
        return path.exists()
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ConfigError(f"skill-config 読み込み失敗: {path}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ConfigError(f"skill-config は regular file である必要があります: {path}")
    return True


def _resolve_channel_override(skill: str, target_channel_dir: Path | None = None) -> Path | None:
    candidates = _channel_override_candidates(skill, target_channel_dir)
    selected = next(
        (path for path in candidates if _override_candidate_exists(path, strict_regular_file=skill == "masterup")),
        None,
    )
    if skill == "postmortem" and selected == candidates[1]:
        warnings.warn(
            f"旧 skill-config {selected} を読み込みます。{candidates[0]} へリネームしてください。",
            UserWarning,
            stacklevel=3,
        )
    return selected


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """dict を再帰的にマージする (override 優先)。

    リスト・スカラは override で置き換え。dict は再帰マージ。
    """
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"skill-config 読み込み失敗: {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"skill-config の root は dict である必要があります: {path}")
    return data


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"skill-config 読み込み失敗: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"skill-config の root は dict である必要があります: {path}")
    return data


def _load_override(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return _load_json(path)
    return _load_yaml(path)


def _validate_thumbnail_text_render(config: Mapping[str, object]) -> None:
    text_render = config.get("text_render")
    if not isinstance(text_render, dict):
        raise ConfigError("thumbnail.text_render.mode は ai_burn_in / deterministic のいずれかで指定してください")
    mode = text_render.get("mode")
    if mode not in _THUMBNAIL_TEXT_RENDER_MODES:
        raise ConfigError(
            f"thumbnail.text_render.mode は ai_burn_in / deterministic のいずれかで指定してください: {mode!r}"
        )


def _validate_skill_config(skill: str, config: Mapping[str, object]) -> None:
    if skill == "thumbnail":
        _validate_thumbnail_text_render(config)


def _split_skill_config_key(skill: str) -> tuple[str, str | None]:
    owner, separator, section = skill.partition(".")
    if not separator:
        return owner, None
    if not owner or not section:
        raise ConfigError(f"skill-config 名前空間キーが不正です: {skill}")
    return owner, section


def _select_moved_default_section(owner: str, defaults: dict[str, object]) -> dict[str, object]:
    section_path = _MOVED_SKILL_CONFIG_SECTIONS.get(owner)
    if section_path is None:
        return defaults
    selected: object = defaults
    for section in section_path:
        if not isinstance(selected, dict):
            break
        selected = selected.get(section)
    if not isinstance(selected, dict):
        dotted = ".".join(section_path)
        raise ConfigError(f"skill-config {owner} は同梱 default の mapping 節 {dotted!r} として存在する必要があります")
    return dict(selected)


def load_skill_config(
    skill: str,
    *,
    use_cache: bool = True,
    channel_dir: Path | None = None,
) -> dict[str, Any]:
    """skill-config を読み込んで返す (default + channel override のマージ結果)。

    Args:
        skill: スキル名 (例: "thumbnail", "suno")
        use_cache: プロセス内キャッシュを使うか (テスト時は False 推奨)
        channel_dir: 明示したチャンネルリポジトリから override を読む。
            省略時は CHANNEL_DIR / カレントディレクトリ設定を使う。

    Returns:
        マージ済み設定 dict

    Raises:
        ConfigError: default.yaml が見つからない、YAML パース失敗など
    """
    if skill not in SKILL_CONFIG_KEYS | SKILL_ONLY_CONFIG_KEYS | _LEGACY_SKILL_CONFIG_ALIASES:
        raise ConfigError(f"未登録の skill-config キーです: {skill}")

    use_shared_cache = use_cache and channel_dir is None
    if use_shared_cache and skill in _cache:
        return _cache[skill]

    owner, section = _split_skill_config_key(skill)
    defaults = _load_yaml(_default_path(owner))
    defaults = _select_moved_default_section(owner, defaults)

    override_path = _resolve_channel_override(owner, channel_dir)
    legacy_override_owner: str | None = None
    if override_path is None and (legacy_owner := _NAMESPACED_LEGACY_OVERRIDE_OWNERS.get(skill)) is not None:
        override_path = _resolve_channel_override(legacy_owner, channel_dir)
        legacy_override_owner = legacy_owner if override_path is not None else None
    if override_path is not None:
        override, acknowledged = _split_acknowledged_unknown_keys(_load_override(override_path), override_path)
        if legacy_override_owner is not None and section is not None:
            override = {section: override}
        merged = _deep_merge(defaults, override)
        warning_owner = legacy_override_owner or owner
        warning_override = override[section] if legacy_override_owner is not None and section is not None else override
        warning_defaults = defaults[section] if legacy_override_owner is not None and section is not None else defaults
        _warn_deprecated_override_keys(warning_owner, warning_override, override_path, merged)
        _warn_unknown_top_level_override_keys(
            warning_owner, warning_override, warning_defaults, override_path, acknowledged
        )
    else:
        merged = defaults

    if section is not None:
        selected = merged.get(section)
        if not isinstance(selected, dict):
            raise ConfigError(f"skill-config {skill} は mapping の節として存在する必要があります")
        merged = dict(selected)

    _validate_skill_config(owner if section is None else skill, merged)

    if use_shared_cache:
        _cache[skill] = merged
    return merged


def load_channel_override(skill: str) -> dict[str, Any]:
    """チャンネル側 override 単体を返す (default とのマージは行わない)。

    skill-config の旧 namespace 移行など、ユーザーが明示的に設定したキーだけを
    検出したいケースで使う。override ファイルが無ければ空 dict。
    """
    owner, section = _split_skill_config_key(skill)
    path = _resolve_channel_override(owner)
    legacy_override = False
    if path is None and (legacy_owner := _NAMESPACED_LEGACY_OVERRIDE_OWNERS.get(skill)) is not None:
        path = _resolve_channel_override(legacy_owner)
        legacy_override = path is not None
    if path is None:
        return {}
    override, _ = _split_acknowledged_unknown_keys(_load_override(path), path)
    if legacy_override:
        return override
    if section is not None:
        selected = override.get(section)
        if selected is None:
            return {}
        if not isinstance(selected, dict):
            raise ConfigError(f"skill-config {skill} の channel override は mapping の節である必要があります")
        return dict(selected)
    return override


THUMBNAIL_MODE_PARALLEL = "parallel"
"""デフォルト: テキスト candidate_count 案 → 確認 → candidate_count 枚を一括生成 → 比較選択。"""

THUMBNAIL_MODE_SEQUENTIAL = "sequential"
"""コスト 1/candidate_count opt-in: テキスト candidate_count 案 → 選択 → 選ばれた 1 案だけサムネ生成。"""

_VALID_THUMBNAIL_MODES = frozenset({THUMBNAIL_MODE_SEQUENTIAL, THUMBNAIL_MODE_PARALLEL})


def get_collection_ideate_thumbnail_mode() -> str:
    """collection-ideate skill の thumbnail_mode を返す。

    skill-config の `preview.thumbnail_mode` を参照。配布 default は
    THUMBNAIL_MODE_PARALLEL。default.yaml も override も無い場合は
    THUMBNAIL_MODE_PARALLEL にフォールバック。不正な shape/値は ConfigError。
    """
    cfg = load_skill_config("collection-ideate")
    preview = cfg.get("preview")
    if preview is None:
        preview = {}
    if not isinstance(preview, dict):
        raise ConfigError(f"collection-ideate.preview は mapping である必要があります: {preview!r}")
    mode = preview.get("thumbnail_mode", THUMBNAIL_MODE_PARALLEL)
    if mode not in _VALID_THUMBNAIL_MODES:
        raise ConfigError(
            "collection-ideate.preview.thumbnail_mode は "
            f"{sorted(_VALID_THUMBNAIL_MODES)} のいずれかである必要があります: {mode!r}"
        )
    return mode


def reset(skill: str | None = None) -> None:
    """キャッシュをクリアする (テスト用)。

    Args:
        skill: 指定時はそのスキルのみクリア、省略時は全クリア
    """
    if skill is None:
        _cache.clear()
    else:
        _cache.pop(skill, None)
