import builtins
from collections import UserList
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.suno import prompt_resolution


def _config() -> dict[str, object]:
    return {
        "genre_line": "lo-fi jazz, soft piano",
        "exclude_styles": "harsh noise",
        "full_style_char_limit": 300,
        "mood_descriptors": "warm, focused",
        "style_influence": 45,
        "weirdness": 55,
        "style_variants": {
            "night": {"name": "Night", "genre_line": "late-night jazz"},
        },
        "style_variation": {"enabled": False, "pools": {}},
        "banned_artists": [],
    }


def _patterns() -> dict[str, object]:
    return {
        "title": "Focus Set",
        "mode": "instrumental",
        "patterns": [],
    }


def _resolve_direct(
    *,
    patterns: Mapping[str, object] | None = None,
    config: Mapping[str, object] | None = None,
    override: Mapping[str, object] | None = None,
) -> prompt_resolution.ResolvedPrompts:
    """Resolver core を file I/O なしの mapping 入力で呼ぶ。"""
    raw_override = {} if override is None else dict(override)
    merged_config = {**_config(), **raw_override} if config is None else dict(config)
    return prompt_resolution.resolve(
        _patterns() if patterns is None else patterns,
        merged_config,
        raw_override,
        patterns_path=Path("patterns.yaml"),
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=(),
        verification_collection_path=Path("."),
    )


def test_resolve_explicit_instrumental_mode_overrides_vocal_genre_line():
    resolved = _resolve_direct(
        patterns={**_patterns(), "mode": "instrumental"},
        override={"genre_line": "dream pop vocals"},
    )

    assert not resolved.is_vocal
    assert resolved.genre_line == "dream pop vocals"


def test_resolve_collection_genre_line_overrides_channel_style_and_mode():
    resolved = _resolve_direct(
        patterns={**_patterns(), "mode": None, "genre_line": "collection lo-fi instrumental"},
        override={"genre_line": "channel dream pop vocals"},
    )

    assert resolved.genre_line == "collection lo-fi instrumental"
    assert not resolved.is_vocal


@pytest.mark.parametrize("first_genre", ["first collection soul", "second collection jazz"])
def test_resolve_collection_genre_line_is_isolated_between_calls(first_genre: str):
    first = _resolve_direct(patterns={**_patterns(), "genre_line": first_genre})
    second = _resolve_direct(patterns={**_patterns(), "genre_line": "other collection style"})

    assert first.genre_line == first_genre
    assert second.genre_line == "other collection style"


def test_resolve_collection_genre_line_rejects_non_string_value():
    with pytest.raises(ConfigError, match=r"patterns\.yaml.*genre_line.*string"):
        _resolve_direct(patterns={**_patterns(), "genre_line": ["not", "a", "string"]})


@pytest.mark.parametrize(
    "duration_sec",
    [True, False, "180", 180.0, float("nan"), float("inf"), float("-inf"), 0, -1],
)
def test_resolve_rejects_invalid_duration_sec_override(duration_sec: object):
    with pytest.raises(ConfigError, match=r"duration_sec.*positive integer"):
        _resolve_direct(override={"duration_sec": duration_sec})


def test_resolve_includes_positive_duration_sec_when_explicitly_overridden():
    resolved = _resolve_direct(override={"duration_sec": 180})

    assert resolved.advanced_json_fields["duration_sec"] == 180


def test_resolve_does_not_derive_duration_sec_from_duration_filter():
    resolved = _resolve_direct(override={"duration_filter": {"min_sec": 120, "max_sec": 240}})

    assert "duration_sec" not in resolved.advanced_json_fields


def test_resolve_collection_exclude_styles_overrides_channel_value():
    resolved = _resolve_direct(
        patterns={**_patterns(), "exclude_styles": "collection edm"},
        override={"exclude_styles": "channel metal"},
    )

    assert resolved.exclude_styles == "collection edm"
    assert resolved.advanced_json_fields["exclude_styles"] == "collection edm"


def test_resolve_collection_empty_exclude_styles_is_explicit():
    resolved = _resolve_direct(
        patterns={**_patterns(), "exclude_styles": ""},
        override={"exclude_styles": "channel metal"},
    )

    assert resolved.exclude_styles == ""
    assert resolved.advanced_json_fields == {"exclude_styles": ""}


@pytest.mark.parametrize("exclude_styles", [None, [], {}])
def test_resolve_collection_exclude_styles_rejects_non_string(exclude_styles: object):
    with pytest.raises(ConfigError, match=r"patterns\.yaml.*exclude_styles.*string"):
        _resolve_direct(patterns={**_patterns(), "exclude_styles": exclude_styles})


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"style_influence": 85}, {"style_influence": 85}),
        ({"weirdness": 30}, {"weirdness": 30}),
        ({"exclude_styles": "hyperpop, edm"}, {"exclude_styles": "hyperpop, edm"}),
        (
            {"style_influence": 85, "weirdness": 30, "exclude_styles": "hyperpop, edm"},
            {"style_influence": 85, "weirdness": 30, "exclude_styles": "hyperpop, edm"},
        ),
        ({"style_influence": 0, "weirdness": 0}, {"style_influence": 0, "weirdness": 0}),
        ({"vocal_gender": "male"}, {"vocal_gender": "male"}),
        ({"vocal_gender": ""}, {}),
        ({}, {}),
    ],
)
def test_resolve_gates_advanced_fields_on_explicit_override(override: dict[str, object], expected: dict[str, object]):
    assert _resolve_direct(override=override).advanced_json_fields == expected


def test_resolve_collection_vocal_gender_overrides_channel_value():
    resolved = _resolve_direct(
        patterns={**_patterns(), "vocal_gender": "female"},
        override={"vocal_gender": "male"},
    )

    assert resolved.advanced_json_fields["vocal_gender"] == "female"


def test_resolve_collection_empty_vocal_gender_removes_channel_value():
    resolved = _resolve_direct(
        patterns={**_patterns(), "vocal_gender": ""},
        override={"vocal_gender": "male"},
    )

    assert "vocal_gender" not in resolved.advanced_json_fields


@pytest.mark.parametrize("vocal_gender", [None, "other"])
def test_resolve_collection_vocal_gender_rejects_values_outside_contract(vocal_gender: object):
    with pytest.raises(ConfigError, match=r"patterns\.yaml.*vocal_gender.*male.*female.*neutral.*auto"):
        _resolve_direct(patterns={**_patterns(), "vocal_gender": vocal_gender})


def test_resolve_collection_style_variant_overrides_same_named_channel_variant():
    resolved = _resolve_direct(
        patterns={
            **_patterns(),
            "style_variants": {"ambient": {"name": "Collection Soul", "genre_line": "collection acoustic soul"}},
        },
        override={"style_variants": {"ambient": {"name": "Channel Ambient", "genre_line": "channel ambient pad"}}},
    )

    assert prompt_resolution.resolve_style_variant(resolved, "ambient") == {
        "name": "Collection Soul",
        "genre_line": "collection acoustic soul",
    }


def test_resolve_explicit_empty_style_variants_does_not_inherit_channel_keys():
    resolved = _resolve_direct(
        patterns={**_patterns(), "style_variants": {}},
        override={"style_variants": {"ambient": {"name": "Channel Ambient", "genre_line": "channel ambient pad"}}},
    )

    with pytest.raises(ConfigError, match="未定義の style variant"):
        prompt_resolution.resolve_style_variant(resolved, "ambient")


@pytest.mark.parametrize(
    ("style_variants", "error_pattern"),
    [
        (None, r"style_variants.*mapping"),
        ([], r"style_variants.*mapping"),
        ({"ambient": []}, r"style_variants\.ambient.*mapping"),
        ({"ambient": {"name": "Ambient"}}, r"style_variants\.ambient\.genre_line.*string"),
        ({"ambient": {"genre_line": "ambient pad"}}, r"style_variants\.ambient\.name.*string"),
    ],
)
def test_resolve_collection_style_variants_reject_invalid_shapes(style_variants: object, error_pattern: str):
    with pytest.raises(ConfigError, match=error_pattern):
        _resolve_direct(patterns={**_patterns(), "style_variants": style_variants})


@pytest.mark.parametrize(
    ("style_variation", "error_pattern"),
    [
        (None, r"suno\.style_variation は mapping"),
        ([], r"suno\.style_variation は mapping"),
        ({"enabled": "yes"}, r"enabled は bool"),
        ({"enabled": True, "pools": None}, r"pools は mapping"),
        ({"enabled": True, "pools": []}, r"pools は mapping"),
        ({"enabled": True, "pools": {"": ["warm texture"]}}, r"axis 名"),
        ({"enabled": True, "pools": {1: ["warm texture"]}}, r"axis 名"),
        ({"enabled": True, "pools": {"texture": "warm texture"}}, r"texture は list\[str\]"),
        ({"enabled": True, "pools": {"texture": [3]}}, r"descriptor は非空文字列"),
        ({"enabled": True, "pools": {"texture": [""]}}, r"descriptor は非空文字列"),
        ({"enabled": True, "pools": {"texture": ["thundering warmth"]}}, r"禁止形容詞"),
        ({"enabled": True, "pools": {"texture": ["rain texture"]}}, r"雨音・環境音 NG ワード"),
        ({"enabled": True, "pools": {"texture": ["piano"]}}, r"裸楽器名"),
        ({"enabled": True, "pools": {"texture": ["Drake texture"]}}, r"アーティスト名"),
    ],
)
def test_resolve_style_variation_rejects_invalid_config_shapes(style_variation: object, error_pattern: str):
    with pytest.raises(ConfigError, match=error_pattern):
        _resolve_direct(
            config={**_config(), "style_variation": style_variation, "banned_artists": ["Drake"]},
            override={"style_variation": style_variation},
        )


def test_resolve_style_variant_rejects_unknown_explicit_key():
    resolved = _resolve_direct(
        patterns={**_patterns(), "style_variants": {"ambient": {"name": "Ambient", "genre_line": "ambient pad"}}}
    )

    with pytest.raises(ConfigError, match="未定義の style variant"):
        prompt_resolution.resolve_style_variant(resolved, "typo_variant")


def test_resolve_from_path_matches_mapping_core(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns = _patterns()
    patterns_path.write_text(yaml.safe_dump(patterns), encoding="utf-8")
    config = _config()
    override = {"style_influence": 0, "vocal_gender": "male"}
    monkeypatch.setattr(prompt_resolution, "load_skill_config", lambda _name: config)
    monkeypatch.setattr(prompt_resolution, "load_channel_override", lambda _name: override)

    from_path = prompt_resolution.resolve_from_path(patterns_path)
    from_mapping = prompt_resolution.resolve(
        patterns,
        config,
        override,
        patterns_path=patterns_path,
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=(),
        verification_collection_path=patterns_path.parent,
    )

    assert from_path == from_mapping
    assert from_path.base_style == "lo-fi jazz, soft piano, warm, focused"
    assert from_path.genre_line == "lo-fi jazz, soft piano"
    assert from_path.banned_artists == ()
    assert not from_path.auto_lyrics_structure
    assert from_path.duration_filter == {"min_sec": 60, "max_sec": 300}
    assert from_path.advanced_json_fields == {"style_influence": 0, "vocal_gender": "male"}


def test_resolve_from_path_validates_collection_before_missing_vocal_workflow(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "collection" / "20-documentation" / "suno-patterns.yaml"
    patterns_path.parent.mkdir(parents=True)
    patterns_path.write_text(
        yaml.safe_dump({**_patterns(), "mode": "vocal", "exclude_styles": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_resolution, "load_skill_config", lambda _name: _config())
    monkeypatch.setattr(prompt_resolution, "load_channel_override", lambda _name: {})

    with pytest.raises(ConfigError, match=r"suno-patterns\.yaml: exclude_styles must be a string"):
        prompt_resolution.resolve_from_path(patterns_path)


def test_resolve_from_path_does_not_probe_stale_outputs_for_valid_input(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(yaml.safe_dump(_patterns()), encoding="utf-8")
    monkeypatch.setattr(prompt_resolution, "load_skill_config", lambda _name: _config())
    monkeypatch.setattr(prompt_resolution, "load_channel_override", lambda _name: {})
    original_exists = Path.exists

    def reject_stale_probe(path: Path) -> bool:
        if path.name in {"suno-prompts.md", "suno-prompts.json"}:
            raise OSError("stale output probe must be demand-driven")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", reject_stale_probe)

    resolved = prompt_resolution.resolve_from_path(patterns_path)

    assert not resolved.is_vocal


def test_resolve_from_path_probes_stale_outputs_only_for_undefined_channel_variant(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "20-documentation" / "suno-patterns.yaml"
    patterns_path.parent.mkdir(parents=True)
    patterns_path.write_text(yaml.safe_dump(_patterns()), encoding="utf-8")
    (patterns_path.parent / "suno-prompts.md").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(prompt_resolution, "load_skill_config", lambda _name: _config())
    monkeypatch.setattr(prompt_resolution, "load_channel_override", lambda _name: {})
    original_exists = Path.exists
    probed_names: list[str] = []

    def record_stale_probe(path: Path) -> bool:
        if path.name in {"suno-prompts.md", "suno-prompts.json"}:
            probed_names.append(path.name)
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", record_stale_probe)

    resolved = prompt_resolution.resolve_from_path(patterns_path)
    assert probed_names == []

    with pytest.raises(ConfigError, match="suno-prompts.md"):
        prompt_resolution.resolve_style_variant(resolved, "missing")

    assert probed_names == ["suno-prompts.md", "suno-prompts.json"]


def test_resolve_applies_collection_fields_without_mutating_override(tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns = {
        **_patterns(),
        "genre_line": "collection jazz",
        "exclude_styles": "collection noise",
        "vocal_gender": "",
        "style_variants": {},
    }
    override = {"exclude_styles": "channel noise", "vocal_gender": "female"}

    resolved = prompt_resolution.resolve(
        patterns,
        _config(),
        override,
        patterns_path=patterns_path,
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=(),
        verification_collection_path=patterns_path.parent,
    )

    assert resolved.genre_line == "collection jazz"
    assert resolved.exclude_styles == "collection noise"
    assert resolved.advanced_json_fields == {"exclude_styles": "collection noise"}
    assert resolved.style_variants == {}
    assert not resolved.uses_channel_style_variants
    assert override == {"exclude_styles": "channel noise", "vocal_gender": "female"}


def test_resolve_style_variant_reports_loader_supplied_stale_outputs_for_channel_fallback(tmp_path: Path):
    patterns_path = tmp_path / "20-documentation" / "suno-patterns.yaml"
    resolved = prompt_resolution.resolve(
        _patterns(),
        _config(),
        {},
        patterns_path=patterns_path,
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=("suno-prompts.md",),
        verification_collection_path=tmp_path,
    )

    with pytest.raises(ConfigError) as exc_info:
        prompt_resolution.resolve_style_variant(resolved, "missing")

    message = str(exc_info.value)
    assert str(patterns_path) in message
    assert "channel fallback drift" in message
    assert "既存成果物 (suno-prompts.md) は更新されず stale のまま" in message
    assert f"uv run yt-suno-verify {tmp_path}" in message


def test_mapping_core_and_variant_resolution_do_not_touch_filesystem_or_loaders(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "20-documentation" / "suno-patterns.yaml"
    original_open = builtins.open
    original_path_methods = {name: getattr(Path, name) for name in ("resolve", "exists", "is_file", "read_text")}

    def deny_loader(*_args, **_kwargs):
        raise AssertionError("mapping core must not call configuration or lyrics loaders")

    def deny_target_open(file, *args, **kwargs):
        if str(file).startswith(str(tmp_path)):
            raise AssertionError("mapping core must not open files")
        return original_open(file, *args, **kwargs)

    def deny_target_path_method(name):
        original = original_path_methods[name]

        def guarded(path, *args, **kwargs):
            if str(path).startswith(str(tmp_path)):
                raise AssertionError(f"mapping core must not call Path.{name}")
            return original(path, *args, **kwargs)

        return guarded

    monkeypatch.setattr(builtins, "open", deny_target_open)
    monkeypatch.setattr(prompt_resolution, "load_skill_config", deny_loader)
    monkeypatch.setattr(prompt_resolution, "load_channel_override", deny_loader)
    monkeypatch.setattr(prompt_resolution, "load_suno_lyrics_by_name", deny_loader)
    for name in original_path_methods:
        monkeypatch.setattr(Path, name, deny_target_path_method(name))

    resolved = prompt_resolution.resolve(
        _patterns(),
        _config(),
        {},
        patterns_path=patterns_path,
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=("suno-prompts.json",),
        verification_collection_path=tmp_path,
    )

    with pytest.raises(ConfigError, match="suno-prompts.json"):
        prompt_resolution.resolve_style_variant(resolved, "missing")


def test_resolve_snapshots_and_freezes_caller_owned_nested_values(tmp_path: Path):
    patterns = {
        **_patterns(),
        "patterns": [
            {
                "name_jp": "集中",
                "name_en": "Focus",
                "scenes": ["soft piano"],
                "metadata": {"tags": ["original"]},
            }
        ],
    }
    config = _config()
    override = {"style_influence": {"levels": [45]}}
    lyrics = {"集中 — Focus": "original lyrics"}
    resolved = prompt_resolution.resolve(
        patterns,
        config,
        override,
        patterns_path=tmp_path / "patterns.yaml",
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=lyrics,
        existing_output_names=(),
        verification_collection_path=tmp_path,
    )

    patterns["patterns"][0]["scenes"].append("mutated scene")
    patterns["patterns"][0]["metadata"]["tags"].append("mutated tag")
    config["style_variants"]["night"]["genre_line"] = "mutated style"
    override["style_influence"]["levels"].append(99)
    lyrics["集中 — Focus"] = "mutated lyrics"

    assert resolved.patterns[0]["scenes"] == ("soft piano",)
    assert resolved.patterns[0]["metadata"]["tags"] == ("original",)
    assert resolved.style_variants["night"]["genre_line"] == "late-night jazz"
    assert resolved.advanced_json_fields["style_influence"] == {"levels": (45,)}
    assert resolved.external_lyrics["集中 — Focus"] == "original lyrics"
    with pytest.raises(TypeError):
        resolved.advanced_json_fields["new"] = "forbidden"
    with pytest.raises(TypeError):
        resolved.style_variants["night"]["genre_line"] = "forbidden"


def test_resolve_snapshots_bytearray_and_non_list_mutable_sequences(tmp_path: Path):
    byte_values = bytearray(b"\x01\x02")
    sequence_values = UserList([{"payload": bytearray(b"\x03\x04")}])
    override = {
        "style_influence": byte_values,
        "weirdness": sequence_values,
    }

    resolved = prompt_resolution.resolve(
        _patterns(),
        _config(),
        override,
        patterns_path=tmp_path / "patterns.yaml",
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=None,
        existing_output_names=(),
        verification_collection_path=tmp_path,
    )
    byte_values.append(3)
    sequence_values[0]["payload"].append(5)
    sequence_values.append({"payload": bytearray(b"\x06")})

    assert resolved.advanced_json_fields["style_influence"] == b"\x01\x02"
    assert resolved.advanced_json_fields["weirdness"] == ({"payload": b"\x03\x04"},)


class _FalseyLyrics(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str]):
        self._values = dict(values)

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __bool__(self) -> bool:
        return False


def test_resolve_preserves_nonempty_falsey_lyrics_mapping(tmp_path: Path):
    lyrics = _FalseyLyrics({"Focus": "kept lyrics"})

    resolved = prompt_resolution.resolve(
        {**_patterns(), "mode": "vocal"},
        _config(),
        {},
        patterns_path=tmp_path / "patterns.yaml",
        workflow_state_path=None,
        workflow_track_count=None,
        lyrics=lyrics,
        existing_output_names=(),
        verification_collection_path=tmp_path,
    )

    assert resolved.has_external_lyrics
    assert resolved.external_lyrics == {"Focus": "kept lyrics"}
