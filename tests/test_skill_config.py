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
