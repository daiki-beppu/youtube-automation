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

from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import yaml

from youtube_automation.utils.config import channel_dir
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


def _channel_override_path(skill: str) -> Path:
    """チャンネルリポジトリ側の上書き config パスを返す (存在チェックは呼び出し側)。"""
    return channel_dir() / "config" / "skills" / f"{skill}.yaml"


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
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"skill-config の root は dict である必要があります: {path}")
    return data


def load_skill_config(skill: str, *, use_cache: bool = True) -> dict[str, Any]:
    """skill-config を読み込んで返す (default + channel override のマージ結果)。

    Args:
        skill: スキル名 (例: "thumbnail", "suno")
        use_cache: プロセス内キャッシュを使うか (テスト時は False 推奨)

    Returns:
        マージ済み設定 dict

    Raises:
        ConfigError: default.yaml が見つからない、YAML パース失敗など
    """
    if use_cache and skill in _cache:
        return _cache[skill]

    defaults = _load_yaml(_default_path(skill))

    override_path = _channel_override_path(skill)
    if override_path.exists():
        override = _load_yaml(override_path)
        merged = _deep_merge(defaults, override)
    else:
        merged = defaults

    if use_cache:
        _cache[skill] = merged
    return merged


def load_channel_override(skill: str) -> dict[str, Any]:
    """チャンネル側 override 単体を返す (default とのマージは行わない)。

    skill-config の旧 namespace 移行など、ユーザーが明示的に設定したキーだけを
    検出したいケースで使う。override ファイルが無ければ空 dict。
    """
    path = _channel_override_path(skill)
    if not path.exists():
        return {}
    return _load_yaml(path)


def reset(skill: str | None = None) -> None:
    """キャッシュをクリアする (テスト用)。

    Args:
        skill: 指定時はそのスキルのみクリア、省略時は全クリア
    """
    if skill is None:
        _cache.clear()
    else:
        _cache.pop(skill, None)
