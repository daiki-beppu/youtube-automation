"""skill_config ローダーのユニットテスト"""

from __future__ import annotations

import pytest
import yaml

from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


def test_load_default_only(tmp_path, monkeypatch):
    """デフォルト値のみ (channel override なし) で読み込めること"""
    # skill_config は channel_dir() のみ使用し load_config() を呼ばない
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    # 実スキルの default.yaml を参照せず、_deep_merge のロジックだけを検証
    merged = skill_config._deep_merge(
        {"a": 1, "b": {"x": 1, "y": 2}},
        {"b": {"y": 20, "z": 30}, "c": 4},
    )
    assert merged == {"a": 1, "b": {"x": 1, "y": 20, "z": 30}, "c": 4}


def test_deep_merge_lists_are_replaced():
    """リストは上書きされ、マージはされない"""
    merged = skill_config._deep_merge(
        {"items": [1, 2, 3]},
        {"items": [9]},
    )
    assert merged == {"items": [9]}


def test_missing_default_raises():
    """default.yaml が存在しないスキルは ConfigError"""
    with pytest.raises(ConfigError):
        skill_config.load_skill_config("__nonexistent_skill__")


def test_channel_override_merged(tmp_path, monkeypatch):
    """channel override が default とマージされること"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override_path.write_text(
        yaml.safe_dump({"image_generation": {"gemini": {"brand_background": "custom-color"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False)
    gemini_block = cfg.get("image_generation", {}).get("gemini", {})
    # default にある他キーは残り、override した brand_background は新しい値になる
    assert gemini_block.get("brand_background") == "custom-color"
    # default.yaml の他のキーが残っていること (モデル名など)
    assert "model" in gemini_block


def test_explicit_channel_dir_override_does_not_use_env(tmp_path, monkeypatch):
    """明示 channel_dir 指定時は CHANNEL_DIR ではなく指定先の override を読む."""
    env_channel = tmp_path / "env-ch"
    explicit_channel = tmp_path / "explicit-ch"
    (env_channel / "config" / "skills").mkdir(parents=True)
    (explicit_channel / "config" / "skills").mkdir(parents=True)
    (env_channel / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"marker": "env"}),
        encoding="utf-8",
    )
    (explicit_channel / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"marker": "explicit"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(env_channel))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=explicit_channel)

    assert cfg.get("marker") == "explicit"


def test_cache_reset(tmp_path, monkeypatch):
    """reset でキャッシュがクリアされ、再度ロードされること"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override.write_text(yaml.safe_dump({"marker": "a"}), encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg1 = skill_config.load_skill_config("thumbnail")
    assert cfg1.get("marker") == "a"

    override.write_text(yaml.safe_dump({"marker": "b"}), encoding="utf-8")
    # キャッシュされているので同じ値が返る
    cfg2 = skill_config.load_skill_config("thumbnail")
    assert cfg2.get("marker") == "a"

    # reset 後は再読み込み
    skill_config.reset("thumbnail")
    reset_config()
    cfg3 = skill_config.load_skill_config("thumbnail")
    assert cfg3.get("marker") == "b"


def test_get_collection_ideate_thumbnail_mode_default(tmp_path, monkeypatch):
    """channel override 無しなら配布 default.yaml の parallel を返す"""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    mode = skill_config.get_collection_ideate_thumbnail_mode()
    assert mode == skill_config.THUMBNAIL_MODE_PARALLEL


def test_get_collection_ideate_thumbnail_mode_opt_in_sequential(tmp_path, monkeypatch):
    """channel override で sequential を指定すると sequential を返す"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text(
        yaml.safe_dump({"preview": {"thumbnail_mode": "sequential"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    mode = skill_config.get_collection_ideate_thumbnail_mode()
    assert mode == skill_config.THUMBNAIL_MODE_SEQUENTIAL


def test_get_collection_ideate_thumbnail_mode_invalid_raises(tmp_path, monkeypatch):
    """不正値は ConfigError"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text(
        yaml.safe_dump({"preview": {"thumbnail_mode": "bogus"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="thumbnail_mode"):
        skill_config.get_collection_ideate_thumbnail_mode()


def test_get_collection_ideate_thumbnail_mode_preview_null_is_default(tmp_path, monkeypatch):
    """`preview: null` でも配布 default.yaml がマージ後に preview を補うため parallel を返す"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text("preview:\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    mode = skill_config.get_collection_ideate_thumbnail_mode()
    assert mode == skill_config.THUMBNAIL_MODE_PARALLEL


def test_get_collection_ideate_thumbnail_mode_preview_non_mapping_raises(tmp_path, monkeypatch):
    """`preview` が dict 以外（typo で文字列やリスト）の場合は ConfigError"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text("preview: parallel\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="preview"):
        skill_config.get_collection_ideate_thumbnail_mode()
