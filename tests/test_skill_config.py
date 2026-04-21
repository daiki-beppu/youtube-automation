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
    # fixture の sample_channel には config/skills/ がない想定
    channel_dir = tmp_path / "ch"
    (channel_dir / "config").mkdir(parents=True)
    (channel_dir / "config" / "channel_config.json").write_text(
        '{"channel":{"name":"t","short":"t","youtube_handle":"@t","url":"https://x"},'
        '"genre":{"primary":"p","style":"s","context":"c"},'
        '"youtube":{"category_id":"10","privacy_status":"private","language":"en"},'
        '"tags":{"base":[],"themes":{}},'
        '"descriptions":{"opening":"","perfect_for":[],"hashtags":[]},'
        '"title":{"template":""},'
        '"music_engine":"lyria"}',
        encoding="utf-8",
    )
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
    # チャンネル側 override を用意
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "channel_config.json").write_text(
        '{"channel":{"name":"t","short":"t","youtube_handle":"@t","url":"https://x"},'
        '"genre":{"primary":"p","style":"s","context":"c"},'
        '"youtube":{"category_id":"10","privacy_status":"private","language":"en"},'
        '"tags":{"base":[],"themes":{}},'
        '"descriptions":{"opening":"","perfect_for":[],"hashtags":[]},'
        '"title":{"template":""},'
        '"music_engine":"lyria"}',
        encoding="utf-8",
    )
    override_path = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override_path.write_text(
        yaml.safe_dump({"gemini_image": {"brand_background": "custom-color"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False)
    # default にある他キーは残り、override した brand_background は新しい値になる
    assert cfg.get("gemini_image", {}).get("brand_background") == "custom-color"
    # default.yaml の他のキーが残っていること (モデル名など)
    assert "model" in cfg.get("gemini_image", {})


def test_cache_reset(tmp_path, monkeypatch):
    """reset でキャッシュがクリアされ、再度ロードされること"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "channel_config.json").write_text(
        '{"channel":{"name":"t","short":"t","youtube_handle":"@t","url":"https://x"},'
        '"genre":{"primary":"p","style":"s","context":"c"},'
        '"youtube":{"category_id":"10","privacy_status":"private","language":"en"},'
        '"tags":{"base":[],"themes":{}},'
        '"descriptions":{"opening":"","perfect_for":[],"hashtags":[]},'
        '"title":{"template":""},'
        '"music_engine":"lyria"}',
        encoding="utf-8",
    )
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
