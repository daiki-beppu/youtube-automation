"""composition_lock ヘルパーの単体テスト (#489)"""

from __future__ import annotations

from youtube_automation.utils.composition_lock import (
    axes_in_thumbnail_prompt,
    build_self_check_prompt,
    expand_fixed_objects,
    is_composition_locked,
)

# ---------------------------------------------------------------------------
# is_composition_locked
# ---------------------------------------------------------------------------


def test_is_composition_locked_default_true_when_missing():
    """key 自体が無いときはデフォルト True"""
    assert is_composition_locked({}) is True
    assert is_composition_locked(None) is True


def test_is_composition_locked_respects_explicit_false():
    assert is_composition_locked({"composition_lock": False}) is False


def test_is_composition_locked_string_aliases():
    """文字列で "false"/"0"/"off"/"no" は False とみなす"""
    for falsy in ("false", "FALSE", " 0", "off", "no"):
        assert is_composition_locked({"composition_lock": falsy}) is False
    for truthy in ("true", "1", "yes", ""):
        assert is_composition_locked({"composition_lock": truthy}) is True


# ---------------------------------------------------------------------------
# expand_fixed_objects
# ---------------------------------------------------------------------------


def test_expand_fixed_objects_known_keys_use_dictionary():
    out = expand_fixed_objects(["wet_runway", "matte_black_car", "aircraft_mid_distance"])
    # 3 件、全て辞書定型文が含まれる
    assert len(out) == 3
    assert any("wet asphalt airport runway" in phrase for phrase in out)
    assert any("matte-black car" in phrase for phrase in out)
    assert any("mid-distance" in phrase for phrase in out)


def test_expand_fixed_objects_unknown_key_passthrough():
    out = expand_fixed_objects(["foo_bar_baz"])
    assert out == ["foo bar baz"]


def test_expand_fixed_objects_empty_and_none():
    assert expand_fixed_objects(None) == []
    assert expand_fixed_objects([]) == []
    assert expand_fixed_objects("not a list") == []


def test_expand_fixed_objects_ignores_non_strings():
    out = expand_fixed_objects(["wet_runway", 42, None, "", "  "])
    assert out == ["wet asphalt airport runway with reflective puddles"]


# ---------------------------------------------------------------------------
# axes_in_thumbnail_prompt
# ---------------------------------------------------------------------------


def test_axes_in_thumbnail_prompt_detects_drift():
    prompt = "A cinematic photo of a matte-black car parked at a mountain airstrip during blue-hour."
    hits = axes_in_thumbnail_prompt(
        prompt,
        ["mountain airstrip", "urban tunnel exit", "desert airstrip"],
    )
    assert hits == ["mountain airstrip"]


def test_axes_in_thumbnail_prompt_case_insensitive():
    prompt = "Photo at MOUNTAIN AIRSTRIP"
    hits = axes_in_thumbnail_prompt(prompt, ["mountain airstrip"])
    assert hits == ["mountain airstrip"]


def test_axes_in_thumbnail_prompt_skips_too_short_tokens():
    """3 文字未満の値は誤検出が多いためスキップ"""
    prompt = "a photo at xy place"
    hits = axes_in_thumbnail_prompt(prompt, ["xy", "abcd"])
    # "xy" は 2 文字でスキップ、"abcd" は haystack に無い
    assert hits == []


def test_axes_in_thumbnail_prompt_empty_inputs():
    assert axes_in_thumbnail_prompt("", ["anything"]) == []
    assert axes_in_thumbnail_prompt("text", None) == []
    assert axes_in_thumbnail_prompt("text", []) == []


# ---------------------------------------------------------------------------
# build_self_check_prompt
# ---------------------------------------------------------------------------


def test_build_self_check_prompt_includes_fixed_objects_and_guards():
    prompt = build_self_check_prompt(
        fixed_objects=["wet_runway", "matte_black_car"],
        no_logo_guard={"detect_text": True, "detect_logo": True, "detect_watermark": True},
    )
    # 各 fixed object が prompt に登場
    assert "wet asphalt airport runway" in prompt
    assert "matte-black car" in prompt
    # 3 つの guard
    assert "typography" in prompt
    assert "logos" in prompt
    assert "watermarks" in prompt
    # JSON 応答 schema が含まれる
    assert '"checks"' in prompt
    assert '"pass"' in prompt


def test_build_self_check_prompt_respects_disabled_guards():
    prompt = build_self_check_prompt(
        fixed_objects=["wet_runway"],
        no_logo_guard={"detect_text": False, "detect_logo": False, "detect_watermark": False},
    )
    # guard 3 種全部無効でも fixed_objects は出る
    assert "wet asphalt airport runway" in prompt
    # guard 文言は無い
    assert "typography" not in prompt
    assert "watermarks" not in prompt


def test_build_self_check_prompt_with_extra_checks():
    prompt = build_self_check_prompt(
        fixed_objects=None,
        no_logo_guard={},  # detect_* デフォルト True
        extra_checks=["Is the aircraft positioned slightly off-center?"],
    )
    assert "slightly off-center" in prompt


def test_build_self_check_prompt_fallback_when_all_empty():
    """fixed_objects も guards も extra_checks も無い場合は fallback の generic 行が入る"""
    prompt = build_self_check_prompt(
        fixed_objects=None,
        no_logo_guard={"detect_text": False, "detect_logo": False, "detect_watermark": False},
        extra_checks=None,
    )
    assert "Flow365 TTP composition" in prompt
