"""skill-config ローダー

各スキル (.claude/skills/<skill>/config.default.yaml) のデフォルト値と、
チャンネルリポジトリ側 (config/skills/<skill>.yaml) の上書きをマージして返す。

使い方:

    from youtube_automation.utils.skill_config import load_skill_config

    cfg = load_skill_config("thumbnail")
    bg = cfg.get("gemini_image", {}).get("brand_background")

設計方針:
- スキーマ検証なし。YAML のコメントで説明、コード側は .get() でゆるく適応
- プロセス内キャッシュ (skill 名ごと)。reset() でクリア可
- editable install / wheel 両対応 (importlib.resources)
"""

from __future__ import annotations

import json
import stat
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import yaml

from youtube_automation.utils.config import channel_dir as configured_channel_dir
from youtube_automation.utils.exceptions import ConfigError

_cache: dict[str, dict[str, Any]] = {}


def _default_path(skill: str) -> Path:
    """パッケージ同梱の default.yaml を解決する。

    wheel インストール時は youtube_automation/_skills/<skill>/config.default.yaml、
    editable install 時はソースツリーの .claude/skills/<skill>/config.default.yaml。
    """
    try:
        resource = files("youtube_automation").joinpath("_skills", skill, "config.default.yaml")
        with as_file(resource) as p:
            path = Path(p)
            if path.exists():
                return path
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    src_fallback = Path(__file__).resolve().parents[3] / ".claude" / "skills" / skill / "config.default.yaml"
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
    use_shared_cache = use_cache and channel_dir is None
    if use_shared_cache and skill in _cache:
        return _cache[skill]

    defaults = _load_yaml(_default_path(skill))

    override_path = next(
        (
            path
            for path in _channel_override_candidates(skill, channel_dir)
            if _override_candidate_exists(path, strict_regular_file=skill == "masterup")
        ),
        None,
    )
    if override_path is not None:
        override = _load_override(override_path)
        merged = _deep_merge(defaults, override)
    else:
        merged = defaults

    if use_shared_cache:
        _cache[skill] = merged
    return merged


def load_channel_override(skill: str) -> dict[str, Any]:
    """チャンネル側 override 単体を返す (default とのマージは行わない)。

    skill-config の旧 namespace 移行など、ユーザーが明示的に設定したキーだけを
    検出したいケースで使う。override ファイルが無ければ空 dict。
    """
    path = next(
        (
            candidate
            for candidate in _channel_override_candidates(skill)
            if _override_candidate_exists(candidate, strict_regular_file=skill == "masterup")
        ),
        None,
    )
    if path is None:
        return {}
    return _load_override(path)


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
