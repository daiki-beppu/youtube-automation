"""skill_config ローダーのユニットテスト"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
import yaml

from youtube_automation.configuration import reset as reset_config
from youtube_automation.configuration import skills as skill_config
from youtube_automation.core.errors import ConfigError

EXPECTED_PYTHON_SKILL_CONFIG_KEYS = frozenset(
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
EXPECTED_SKILL_ONLY_CONFIG_KEYS = frozenset(
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


def test_skill_config_keys_classify_python_and_skill_only_consumers() -> None:
    assert skill_config.SKILL_CONFIG_KEYS == EXPECTED_PYTHON_SKILL_CONFIG_KEYS
    assert skill_config.SKILL_ONLY_CONFIG_KEYS == EXPECTED_SKILL_ONLY_CONFIG_KEYS


def test_unregistered_skill_config_key_raises_config_error_before_path_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        skill_config,
        "_default_path",
        lambda _skill: pytest.fail("未登録キーで default path を解決してはいけません"),
    )

    with pytest.raises(ConfigError, match="未登録の skill-config キー"):
        skill_config.load_skill_config("unregistered", use_cache=False)


def test_load_namespaced_skill_config_returns_only_requested_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_path = tmp_path / "music.default.yaml"
    default_path.write_text("prompt:\n  model: v5\nmaster:\n  target_lufs: -14\n", encoding="utf-8")
    channel_dir = tmp_path / "channel"
    overrides = channel_dir / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "music.yaml").write_text("prompt:\n  model: custom\n", encoding="utf-8")
    monkeypatch.setattr(
        skill_config,
        "SKILL_CONFIG_KEYS",
        skill_config.SKILL_CONFIG_KEYS | {"music.prompt"},
    )
    monkeypatch.setattr(skill_config, "_default_path", lambda owner: default_path if owner == "music" else None)

    loaded = skill_config.load_skill_config("music.prompt", use_cache=False, channel_dir=channel_dir)

    assert loaded == {"model": "custom"}


def test_load_namespaced_skill_config_uses_legacy_owner_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_path = tmp_path / "music.default.yaml"
    default_path.write_text("prompt:\n  model: v5\n", encoding="utf-8")
    channel_dir = tmp_path / "channel"
    overrides = channel_dir / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "suno.yaml").write_text("model: legacy-custom\n", encoding="utf-8")
    monkeypatch.setattr(skill_config, "_default_path", lambda owner: default_path if owner == "music" else None)

    loaded = skill_config.load_skill_config("music.prompt", use_cache=False, channel_dir=channel_dir)

    assert loaded == {"model": "legacy-custom"}


@pytest.mark.parametrize(
    ("legacy_key", "target_skill", "section"),
    [
        (source, migration.target_skill, migration.section)
        for source, migration in skill_config.SKILL_CONFIG_MIGRATIONS.items()
    ],
)
def test_legacy_skill_config_uses_migrated_override_when_legacy_file_is_absent(
    tmp_path: Path,
    legacy_key: str,
    target_skill: str,
    section: str | None,
) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    migrated_override = {"migration_test_marker": legacy_key}
    section_path = skill_config._MOVED_SKILL_CONFIG_SECTIONS.get(legacy_key, ())
    nested_override: dict[str, object] = migrated_override
    for path_part in reversed(section_path):
        nested_override = {path_part: nested_override}
    target_override = {**nested_override, "acknowledged_unknown_keys": ["migration_test_marker"]}
    (overrides / f"{target_skill}.yaml").write_text(yaml.safe_dump(target_override), encoding="utf-8")

    loaded = skill_config.load_skill_config(legacy_key, use_cache=False, channel_dir=tmp_path)

    assert loaded["migration_test_marker"] == legacy_key


def test_legacy_skill_config_narrows_migrated_override_through_full_section_path(tmp_path: Path) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "music.yaml").write_text(
        "generate:\n  provider: sibling\n  lyria:\n    model: lyria-002\n",
        encoding="utf-8",
    )

    loaded = skill_config.load_skill_config("lyria", use_cache=False, channel_dir=tmp_path)

    assert loaded["model"] == "lyria-002"
    assert "provider" not in loaded


def test_legacy_and_namespaced_keys_resolve_the_same_migrated_override(tmp_path: Path) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "thumbnail.yaml").write_text(
        "loop:\n  skip_preview_approval: true\n",
        encoding="utf-8",
    )

    legacy = skill_config.load_skill_config("loop-video", use_cache=False, channel_dir=tmp_path)
    namespaced = skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=tmp_path)["loop"]

    assert legacy == namespaced


def test_legacy_skill_config_file_keeps_priority_over_migrated_override(tmp_path: Path) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "loop-video.yaml").write_text("skip_preview_approval: true\n", encoding="utf-8")
    (overrides / "thumbnail.yaml").write_text("loop:\n  skip_preview_approval: false\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("loop-video", use_cache=False, channel_dir=tmp_path)

    assert loaded["skip_preview_approval"] is True


def test_legacy_skill_config_uses_defaults_when_migrated_override_section_is_absent(tmp_path: Path) -> None:
    expected = skill_config.load_skill_config(
        "loop-video",
        use_cache=False,
        channel_dir=tmp_path / "without-overrides",
    )
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "thumbnail.yaml").write_text(
        "image_generation:\n  provider: gemini\n",
        encoding="utf-8",
    )

    loaded = skill_config.load_skill_config("loop-video", use_cache=False, channel_dir=tmp_path)

    assert loaded == expected


def test_legacy_skill_config_rejects_non_mapping_migrated_override_section(tmp_path: Path) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "thumbnail.yaml").write_text("loop: null\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="移行先 'loop' は mapping"):
        skill_config.load_skill_config("loop-video", use_cache=False, channel_dir=tmp_path)


def test_load_namespaced_skill_config_rejects_missing_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default_path = tmp_path / "music.default.yaml"
    default_path.write_text("master:\n  target_lufs: -14\n", encoding="utf-8")
    channel_dir = tmp_path / "channel"
    channel_dir.mkdir()
    monkeypatch.setattr(
        skill_config,
        "SKILL_CONFIG_KEYS",
        skill_config.SKILL_CONFIG_KEYS | {"music.prompt"},
    )
    monkeypatch.setattr(skill_config, "_default_path", lambda owner: default_path if owner == "music" else None)

    with pytest.raises(ConfigError, match=r"music\.prompt.*mapping の節"):
        skill_config.load_skill_config("music.prompt", use_cache=False, channel_dir=channel_dir)


def test_load_namespaced_channel_override_returns_requested_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "music.yaml").write_text(
        "prompt:\n  model: custom\nmaster:\n  target_lufs: -14\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    assert skill_config.load_channel_override("music.prompt") == {"model": "custom"}


def test_load_namespaced_channel_override_uses_legacy_owner_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "suno.yaml").write_text("model: legacy-custom\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    assert skill_config.load_channel_override("music.prompt") == {"model": "legacy-custom"}


def test_moved_channel_research_modes_keep_legacy_loader_and_override_keys(tmp_path: Path) -> None:
    overrides = tmp_path / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "benchmark.yaml").write_text("freshness_days: 7\n", encoding="utf-8")
    (overrides / "discover-competitors.yaml").write_text("search:\n  top: 12\n", encoding="utf-8")

    benchmark = skill_config.load_skill_config("benchmark", use_cache=False, channel_dir=tmp_path)
    discover = skill_config.load_skill_config("discover-competitors", use_cache=False, channel_dir=tmp_path)

    assert benchmark["freshness_days"] == 7
    assert "benchmark" not in benchmark and "discover" not in benchmark
    assert discover["search"]["top"] == 12
    assert "benchmark" not in discover and "discover" not in discover


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


def test_unknown_top_level_override_key_warns_but_still_merges(tmp_path, monkeypatch):
    """#2520: 未知のトップレベルキーを silent に無視させない。"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override_path.write_text(
        yaml.safe_dump({"auto_select": {"enabled": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(UserWarning, match=r"thumbnail\.yaml.*auto_select") as caught:
        cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg["auto_select"] == {"enabled": True}
    message = str(caught[0].message)
    assert "コードからは参照されない可能性があります" in message
    assert "SKILL.md 経由で AI が読む設計であれば意図どおりです" in message
    assert "利用側に参照されない可能性があります" not in message
    # 警告の発生位置は loader 内部ではなく呼び出し元コードを指す
    assert caught[0].filename == __file__


def test_acknowledged_unknown_keys_suppress_only_named_warning(tmp_path, monkeypatch):
    channel_dir = tmp_path / "ch"
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "suno.yaml").write_text(
        yaml.safe_dump(
            {
                "acknowledged_unknown_keys": ["tracks_per_pattern"],
                "tracks_per_pattern": 1,
                "duration_policy": "legacy",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(UserWarning, match=r"suno\.yaml.*duration_policy") as caught:
        cfg = skill_config.load_skill_config("suno", use_cache=False)

    assert "tracks_per_pattern" not in str(caught[0].message)
    assert cfg["tracks_per_pattern"] == 1
    assert "acknowledged_unknown_keys" not in cfg
    assert "acknowledged_unknown_keys" not in skill_config.load_channel_override("suno")


@pytest.mark.parametrize("value", ["tracks_per_pattern", [""], [1], {"tracks_per_pattern": True}])
def test_acknowledged_unknown_keys_must_be_non_empty_string_list(tmp_path, monkeypatch, value):
    channel_dir = tmp_path / "ch"
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "suno.yaml").write_text(
        yaml.safe_dump({"acknowledged_unknown_keys": value, "tracks_per_pattern": 1}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="acknowledged_unknown_keys は空でない string の array"):
        skill_config.load_skill_config("suno", use_cache=False)


@pytest.mark.parametrize(
    ("skill", "override"),
    [
        ("suno", {"vocal_gender": "female", "tracklist_strategy": "ttp"}),
        ("videoup", {"effect": {"type": "particles"}, "shrink": {"enabled": True}}),
    ],
)
def test_known_override_only_top_level_keys_do_not_warn(tmp_path, monkeypatch, skill, override):
    """#3795: default 外でも正規の直接参照キーは未知キー扱いしない。"""
    channel_dir = tmp_path / "ch"
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / f"{skill}.yaml").write_text(yaml.safe_dump(override), encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = skill_config.load_skill_config(skill, use_cache=False)

    assert not [warning for warning in caught if "未知のトップレベルキー" in str(warning.message)]
    assert all(cfg[key] == value for key, value in override.items())


def test_known_override_only_keys_do_not_hide_genuinely_unknown_key(tmp_path, monkeypatch):
    """#3795: allowlist と同居する未知キーには従来どおり警告する。"""
    channel_dir = tmp_path / "ch"
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "suno.yaml").write_text(
        yaml.safe_dump({"vocal_gender": "female", "tracks_per_pattern": 3}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(UserWarning, match=r"suno\.yaml.*tracks_per_pattern") as caught:
        skill_config.load_skill_config("suno", use_cache=False)

    assert "vocal_gender" not in str(caught[0].message)


def test_misplaced_top_level_override_key_warns_with_nested_path(tmp_path, monkeypatch):
    """#2558: nested schema と同名の誤配置には正しい dotted path を示す。"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override_path.write_text(
        yaml.safe_dump({"auto_selection": {"enabled": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(
        UserWarning,
        match=r"thumbnail\.yaml.*auto_selection.*image_generation\.auto_selection",
    ):
        cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg["auto_selection"] == {"enabled": True}


def test_thumbnail_deprecated_override_keys_warn_but_still_merge(tmp_path, monkeypatch):
    """#1702: 縮小済みキーの override は壊さず deep-merge しつつ DeprecationWarning を出す。"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump(
            {
                "image_generation": {
                    "gemini": {
                        "composition_rules": {"environment": "cozy tavern", "text_lines": "1 行"},
                        "thumbnail_text": {"copy_position": "left of character"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(DeprecationWarning) as records:
        cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    message = str(records[0].message)
    assert "image_generation.gemini.composition_rules.environment" in message
    assert "image_generation.gemini.thumbnail_text.copy_position" in message
    assert "#1702" in message
    # 警告の発生位置は loader 内部ではなく呼び出し元コードを指す
    assert records[0].filename == __file__
    # override は従来どおり有効（後方互換 no-op を維持）
    gemini = cfg["image_generation"]["gemini"]
    assert gemini["composition_rules"]["environment"] == "cozy tavern"
    assert gemini["composition_rules"]["text_lines"] == "1 行"
    assert gemini["thumbnail_text"]["copy_position"] == "left of character"


def test_thumbnail_codex_composition_rules_are_not_deprecated(tmp_path, monkeypatch):
    channel_dir = tmp_path / "ch"
    override_dir = channel_dir / "config" / "skills"
    override_dir.mkdir(parents=True)
    (override_dir / "thumbnail.yaml").write_text(
        yaml.safe_dump(
            {
                "image_generation": {
                    "provider": "codex",
                    "gemini": {
                        "composition_rules": {
                            "environment": "bright studio",
                            "background": "light gray",
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert not [warning for warning in caught if issubclass(warning.category, DeprecationWarning)]
    assert cfg["image_generation"]["gemini"]["composition_rules"]["background"] == "light gray"


def test_thumbnail_override_without_deprecated_keys_does_not_warn(tmp_path, monkeypatch):
    """#1702: 縮小後の実効キーだけの override では DeprecationWarning を出さない。"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump(
            {
                "image_generation": {
                    "gemini": {
                        "composition_rules": {"text_lines": "1 行"},
                        "thumbnail_text": {"channel_name": "Focus", "text_overlay_prompt": "Add {title_line1}."},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg["image_generation"]["gemini"]["thumbnail_text"]["channel_name"] == "Focus"


def test_load_skill_config_postmortem_prefers_flop_analysis_override(tmp_path, monkeypatch):
    """postmortem は新名 flop-analysis override を default にマージする。"""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "flop-analysis.yaml").write_text(
        yaml.safe_dump({"thresholds": {"min_impressions": 321}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        cfg = skill_config.load_skill_config("postmortem", use_cache=False)

    assert cfg["thresholds"]["min_impressions"] == 321
    assert "ctr_low" in cfg["hypothesis_ratios"]
    assert not warning_records


def test_load_skill_config_postmortem_uses_flop_analysis_default_directory(tmp_path, monkeypatch):
    """directory rename 後も既存 loader key が新 directory の default を読む。"""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("postmortem", use_cache=False)

    assert cfg["thresholds"]["ratio_vs_median"] == {"strong": 0.5, "moderate": 0.7, "mild": 0.9}
    assert cfg["hypothesis_ratios"]["ctr_low"] == 0.7


def test_load_skill_config_postmortem_warns_for_legacy_override(tmp_path, monkeypatch):
    """旧名だけなら読み込み、旧名と移行先を含む UserWarning を出す。"""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    legacy_path = skills_dir / "postmortem.yaml"
    replacement_path = skills_dir / "flop-analysis.yaml"
    legacy_path.write_text(
        yaml.safe_dump({"thresholds": {"min_impressions": 654}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.warns(UserWarning) as warning_records:
        cfg = skill_config.load_skill_config("postmortem", use_cache=False)

    assert cfg["thresholds"]["min_impressions"] == 654
    assert str(legacy_path) in str(warning_records[0].message)
    assert str(replacement_path) in str(warning_records[0].message)
    assert warning_records[0].filename == __file__


def test_load_skill_config_postmortem_does_not_read_legacy_when_both_exist(tmp_path, monkeypatch):
    """新旧併存時は新名を採用し、不正な旧名も読まず警告しない。"""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "flop-analysis.yaml").write_text(
        yaml.safe_dump({"thresholds": {"min_impressions": 777}}),
        encoding="utf-8",
    )
    (skills_dir / "postmortem.yaml").write_text("[broken", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        cfg = skill_config.load_skill_config("postmortem", use_cache=False)

    assert cfg["thresholds"]["min_impressions"] == 777
    assert not warning_records


def test_load_channel_override_postmortem_uses_same_legacy_fallback(tmp_path, monkeypatch):
    """override 単体 API も新名優先と旧名 fallback 警告を適用する。"""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    legacy_path = skills_dir / "postmortem.yaml"
    replacement_path = skills_dir / "flop-analysis.yaml"
    legacy_path.write_text(yaml.safe_dump({"legacy_only": True}), encoding="utf-8")
    replacement_path.write_text(yaml.safe_dump({"new_only": True}), encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        cfg = skill_config.load_channel_override("postmortem")

    assert cfg == {"new_only": True}
    assert not warning_records

    replacement_path.unlink()
    with pytest.warns(UserWarning) as warning_records:
        cfg = skill_config.load_channel_override("postmortem")

    assert cfg == {"legacy_only": True}
    assert str(legacy_path) in str(warning_records[0].message)
    assert str(replacement_path) in str(warning_records[0].message)


def test_load_skill_config_postmortem_invalid_new_override_does_not_fallback(tmp_path, monkeypatch):
    """不正な新名が選ばれたら有効な旧名へ逃げず ConfigError にする。"""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    replacement_path = skills_dir / "flop-analysis.yaml"
    replacement_path.write_text("[broken", encoding="utf-8")
    (skills_dir / "postmortem.yaml").write_text(
        yaml.safe_dump({"thresholds": {"min_impressions": 999}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        with pytest.raises(ConfigError, match=str(replacement_path)):
            skill_config.load_skill_config("postmortem", use_cache=False)

    assert not warning_records


def test_thumbnail_dedup_window_can_be_overridden(tmp_path, monkeypatch):
    """thumbnail の default 値と channel override が実行設定へマージされること。"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"image_generation": {"gemini": {"reference_images": {"dedup_recent_collections": 2}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg["image_generation"]["gemini"]["reference_images"]["dedup_recent_collections"] == 2


def test_load_skill_config_masterup_json_override_wins_over_yaml(tmp_path, monkeypatch):
    """masterup は JSON override が YAML override より優先されること."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    (channel_dir / "config" / "skills" / "masterup.json").write_text(
        json.dumps({"audio": {"bitrate": "256k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("masterup", use_cache=False)

    assert cfg.get("audio", {}).get("bitrate") == "256k"


def test_load_skill_config_masterup_enables_suno_cleanup_by_default(tmp_path, monkeypatch):
    """masterup の同梱既定で Suno 個別音源 cleanup が有効になること."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("masterup", use_cache=False)

    assert cfg["post_processing"]["suno_audio_cleanup"]["enabled"] is True
    assert cfg["post_processing"]["suno_audio_cleanup"]["max_workers"] == 2
    assert cfg["post_processing"]["suno_audio_cleanup"]["loudnorm"]["I"] == -14


def test_load_skill_config_masterup_allows_suno_cleanup_opt_out(tmp_path, monkeypatch):
    """channel JSON override で Suno 個別音源 cleanup を無効化できること."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.json").write_text(
        json.dumps({"post_processing": {"suno_audio_cleanup": {"enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("masterup", use_cache=False)

    assert cfg["post_processing"]["suno_audio_cleanup"]["enabled"] is False
    assert cfg["post_processing"]["suno_audio_cleanup"]["loudnorm"]["I"] == -14


def test_load_skill_config_non_masterup_json_is_ignored(tmp_path, monkeypatch):
    """masterup 以外は既存 YAML override 契約のままにする."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"image_generation": {"gemini": {"brand_background": "yaml"}}}),
        encoding="utf-8",
    )
    (channel_dir / "config" / "skills" / "thumbnail.json").write_text(
        json.dumps({"image_generation": {"gemini": {"brand_background": "json"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg.get("image_generation", {}).get("gemini", {}).get("brand_background") == "yaml"


def test_load_skill_config_falls_back_to_yaml_when_json_absent(tmp_path, monkeypatch):
    """JSON が無い場合は既存 YAML override を読むこと."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"archive": {"marker": "yaml"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False)

    assert cfg.get("archive", {}).get("marker") == "yaml"


def test_load_skill_config_masterup_json_root_must_be_mapping(tmp_path, monkeypatch):
    """masterup JSON override の root が dict 以外なら YAML fallback せず ConfigError."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "masterup.json").write_text("[]\n", encoding="utf-8")
    (channel_dir / "config" / "skills" / "masterup.yaml").write_text(
        yaml.safe_dump({"marker": "yaml"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="root は dict"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_broken_json_raises_without_yaml_fallback(tmp_path, monkeypatch):
    """壊れた masterup JSON override がある場合は YAML fallback せず ConfigError."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "masterup.json").write_text("{", encoding="utf-8")
    (channel_dir / "config" / "skills" / "masterup.yaml").write_text(
        yaml.safe_dump({"marker": "yaml"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="skill-config 読み込み失敗"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_broken_json_symlink_raises_without_yaml_fallback(tmp_path, monkeypatch):
    """broken masterup.json symlink がある場合は YAML fallback せず ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.json").symlink_to(channel_dir / "missing-masterup.json")
    (skills_dir / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="regular file"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_json_directory_raises_without_yaml_fallback(tmp_path, monkeypatch):
    """masterup.json が directory の場合は YAML fallback せず ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.json").mkdir()
    (skills_dir / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="regular file"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_json_lstat_error_raises_without_yaml_fallback(tmp_path, monkeypatch):
    """masterup.json の stat 失敗時は YAML fallback せず ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.json").write_text("{}", encoding="utf-8")
    (skills_dir / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path.name == "masterup.json":
            raise PermissionError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    with pytest.raises(ConfigError, match="skill-config 読み込み失敗"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_yaml_directory_raises_when_json_absent(tmp_path, monkeypatch):
    """masterup.yaml が directory の場合は ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.yaml").mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="regular file"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_broken_yaml_symlink_raises_when_json_absent(tmp_path, monkeypatch):
    """broken masterup.yaml symlink の場合は ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.yaml").symlink_to(channel_dir / "missing-masterup.yaml")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="regular file"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_skill_config_masterup_yaml_lstat_error_raises_when_json_absent(tmp_path, monkeypatch):
    """masterup.yaml の stat 失敗時は ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.yaml").write_text("audio:\n  bitrate: 128k\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path.name == "masterup.yaml":
            raise PermissionError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    with pytest.raises(ConfigError, match="skill-config 読み込み失敗"):
        skill_config.load_skill_config("masterup", use_cache=False)


def test_load_channel_override_masterup_json_wins_over_yaml(tmp_path, monkeypatch):
    """load_channel_override() でも masterup JSON override が YAML より優先されること."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    (channel_dir / "config" / "skills" / "masterup.json").write_text(
        json.dumps({"audio": {"bitrate": "256k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_channel_override("masterup")

    assert cfg == {"audio": {"bitrate": "256k"}}


def test_load_channel_override_masterup_broken_json_raises_without_yaml_fallback(tmp_path, monkeypatch):
    """load_channel_override() でも壊れた masterup JSON は YAML fallback しない."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.json").write_text("{", encoding="utf-8")
    (skills_dir / "masterup.yaml").write_text(
        yaml.safe_dump({"audio": {"bitrate": "128k"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="skill-config 読み込み失敗"):
        skill_config.load_channel_override("masterup")


def test_load_channel_override_masterup_yaml_directory_raises_when_json_absent(tmp_path, monkeypatch):
    """load_channel_override() でも masterup.yaml directory は ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.yaml").mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="regular file"):
        skill_config.load_channel_override("masterup")


def test_load_channel_override_masterup_yaml_lstat_error_raises_when_json_absent(tmp_path, monkeypatch):
    """load_channel_override() でも masterup.yaml stat 失敗は ConfigError."""
    channel_dir = tmp_path / "ch"
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "masterup.yaml").write_text("audio:\n  bitrate: 128k\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path.name == "masterup.yaml":
            raise PermissionError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    with pytest.raises(ConfigError, match="skill-config 読み込み失敗"):
        skill_config.load_channel_override("masterup")


def test_load_channel_override_falls_back_to_yaml_when_json_absent(tmp_path, monkeypatch):
    """load_channel_override() でも JSON 不在時は YAML fallback すること."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"marker": "yaml"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_channel_override("thumbnail")

    assert cfg == {"marker": "yaml"}


def test_collection_ideate_freshness_days_default_comes_from_skill_config(tmp_path):
    """collection-ideate の絶対鮮度 default は実 loader で読める."""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()

    cfg = skill_config.load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)

    assert cfg.get("freshness_days") == 7


def test_thumbnail_owns_loop_video_defaults(tmp_path):
    """#3832: thumbnail の loop 節がループ生成 default の正本になる。"""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()

    cfg = skill_config.load_skill_config("thumbnail", use_cache=False, channel_dir=channel_dir)

    assert cfg["loop"]["enabled"] is True
    assert cfg["loop"]["veo"]["duration_seconds"] == 8


@pytest.mark.parametrize(
    ("skill", "path"),
    [
        ("collection-ideate", ("preview", "skip_cost_confirm")),
        ("lyria", ("skip_generation_approval",)),
        ("loop-video", ("skip_billing_approval",)),
        ("loop-video", ("skip_preview_approval",)),
    ],
)
def test_unattended_approval_skip_defaults_are_opt_in(tmp_path, skill, path):
    """#2418: 既存チャンネルは全停止点を従来どおり維持する."""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()

    value = skill_config.load_skill_config(skill, use_cache=False, channel_dir=channel_dir)
    for key in path:
        value = value[key]

    assert value is False


def test_collection_ideate_skip_cost_confirm_channel_override(tmp_path):
    """#2422: nested override は他の preview default を保持して deep-merge される."""
    channel_dir = tmp_path / "ch"
    overrides = channel_dir / "config" / "skills"
    overrides.mkdir(parents=True)
    (overrides / "collection-ideate.yaml").write_text(
        yaml.safe_dump({"preview": {"skip_cost_confirm": True}}),
        encoding="utf-8",
    )

    preview = skill_config.load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)["preview"]

    assert preview["skip_cost_confirm"] is True
    assert preview["candidate_count"] == 3


def test_collection_ideate_freshness_days_channel_override(tmp_path):
    """channel override の freshness_days が default より優先される."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text(yaml.safe_dump({"freshness_days": 14}), encoding="utf-8")

    cfg = skill_config.load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)

    assert cfg.get("freshness_days") == 14


def test_collection_ideate_config_has_no_stale_action_contract(tmp_path):
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()

    cfg = skill_config.load_skill_config("collection-ideate", use_cache=False, channel_dir=channel_dir)

    assert "freshness" not in cfg


def test_analytics_report_theme_colors_default_comes_from_skill_config(tmp_path):
    """analytics の HTML テーマ色 default は実 loader で読める."""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()

    cfg = skill_config.load_skill_config("analytics", use_cache=False, channel_dir=channel_dir)

    assert cfg.get("theme", {}).get("colors") == {
        "background": "#0f1419",
        "card_background": "#1a2332",
        "accent": "#c8a96e",
        "text": "#e8e6e3",
        "chart_palette": ["#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7", "#dfe6e9"],
        "success": "#00b894",
        "warning": "#fdcb6e",
        "danger": "#e17055",
    }


def test_analytics_report_theme_colors_channel_override(tmp_path):
    """analytics の HTML テーマ色は channel override で差し替えられる."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "analytics.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "theme": {
                    "colors": {
                        "accent": "#123456",
                        "chart_palette": ["#111111", "#222222"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = skill_config.load_skill_config("analytics", use_cache=False, channel_dir=channel_dir)

    colors = cfg.get("theme", {}).get("colors")
    assert colors.get("accent") == "#123456"
    assert colors.get("chart_palette") == ["#111111", "#222222"]
    assert colors.get("background") == "#0f1419"
    assert cfg.get("html", {}).get("kpi_cards") == ["total_views", "total_watch_time", "subscribers", "ctr"]


def test_explicit_channel_dir_override_does_not_use_env(tmp_path, monkeypatch):
    """明示 channel_dir 指定時は CHANNEL_DIR ではなく指定先の override を読む."""
    env_channel = tmp_path / "env-ch"
    explicit_channel = tmp_path / "explicit-ch"
    (env_channel / "config" / "skills").mkdir(parents=True)
    (explicit_channel / "config" / "skills").mkdir(parents=True)
    (env_channel / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"archive": {"marker": "env"}}),
        encoding="utf-8",
    )
    (explicit_channel / "config" / "skills" / "thumbnail.yaml").write_text(
        yaml.safe_dump({"archive": {"marker": "explicit"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(env_channel))

    env_cfg = skill_config.load_skill_config("thumbnail")
    cfg = skill_config.load_skill_config("thumbnail", channel_dir=explicit_channel)

    assert env_cfg.get("archive", {}).get("marker") == "env"
    assert cfg.get("archive", {}).get("marker") == "explicit"
    assert skill_config.load_skill_config("thumbnail").get("archive", {}).get("marker") == "env"


def test_channel_override_root_must_be_mapping(tmp_path, monkeypatch):
    """override の root が dict 以外なら ConfigError にする."""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    (channel_dir / "config" / "skills" / "thumbnail.yaml").write_text("[]\n", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    with pytest.raises(ConfigError, match="root は dict"):
        skill_config.load_skill_config("thumbnail", use_cache=False)


def test_cache_reset(tmp_path, monkeypatch):
    """reset でキャッシュがクリアされ、再度ロードされること"""
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "thumbnail.yaml"
    override.write_text(yaml.safe_dump({"archive": {"marker": "a"}}), encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg1 = skill_config.load_skill_config("thumbnail")
    assert cfg1.get("archive", {}).get("marker") == "a"

    override.write_text(yaml.safe_dump({"archive": {"marker": "b"}}), encoding="utf-8")
    # キャッシュされているので同じ値が返る
    cfg2 = skill_config.load_skill_config("thumbnail")
    assert cfg2.get("archive", {}).get("marker") == "a"

    # reset 後は再読み込み
    skill_config.reset("thumbnail")
    reset_config()
    cfg3 = skill_config.load_skill_config("thumbnail")
    assert cfg3.get("archive", {}).get("marker") == "b"


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
