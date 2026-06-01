"""imagegen Shared prompt schema bridge (issue #654) のテスト。

本テストは試験導入された ``image_provider.prompt_schema`` の bridge 単体を
検証する。実本番のプロンプト構築フロー (``image_provider.composition`` /
``scripts.generate_image``) は未接続のままであり、既存 thumbnail テスト
(``test_thumbnail_skill_assets.py``) で挙動温存を担保する。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from youtube_automation.utils.image_provider import PromptSchema, prompt_schema


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_default_config() -> dict:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_prompt_schema_has_imagegen_14_fields() -> None:
    schema = PromptSchema()
    expected = (
        "use_case",
        "asset_type",
        "primary_request",
        "input_images",
        "scene",
        "subject",
        "style",
        "composition",
        "lighting",
        "color",
        "materials",
        "text",
        "constraints",
        "avoid",
    )
    for name in expected:
        assert hasattr(schema, name), f"PromptSchema lacks imagegen field: {name}"
    assert len(expected) == 14


def test_render_skips_unset_fields_and_uses_imagegen_labels() -> None:
    schema = PromptSchema(
        use_case="product-mockup (YouTube thumbnail variant)",
        primary_request="A cozy cafe table with steaming coffee",
        input_images=("a.jpg", "b.jpg"),
        style="Hyper-detailed digital matte painting",
    )
    text = prompt_schema.render(schema)
    lines = text.splitlines()

    assert lines[0] == "Use case: product-mockup (YouTube thumbnail variant)"
    assert "Primary request: A cozy cafe table with steaming coffee" in lines
    assert "Input images: a.jpg, b.jpg" in lines
    assert "Style: Hyper-detailed digital matte painting" in lines

    for skipped in (
        "Asset type:",
        "Scene:",
        "Subject:",
        "Composition:",
        "Lighting:",
        "Color:",
        "Materials:",
        "Text:",
        "Constraints:",
        "Avoid:",
    ):
        assert skipped not in text


def test_render_treats_blank_string_and_empty_tuple_as_unset() -> None:
    schema = PromptSchema(
        use_case="   ",
        style="",
        input_images=(),
        primary_request="ok",
    )
    text = prompt_schema.render(schema)
    assert text == "Primary request: ok"


def test_from_skill_config_handles_empty_input() -> None:
    empty = prompt_schema.from_skill_config({})
    # taxonomy 注記 (use_case / asset_type) は config に依らず常に固定値で埋まる
    assert empty.use_case == "product-mockup (YouTube thumbnail variant)"
    assert empty.asset_type == "YouTube thumbnail (1280x720, 16:9, JPEG)"
    # それ以外の 12 項目は未設定
    assert empty.primary_request is None
    assert empty.input_images == ()
    assert empty.constraints is None

    # 非 dict 入力 (None / list / 文字列) でも空 dict と同じ schema を返す
    assert prompt_schema.from_skill_config(None) == empty  # type: ignore[arg-type]
    assert prompt_schema.from_skill_config([]) == empty  # type: ignore[arg-type]


def test_from_skill_config_maps_default_yaml_keys() -> None:
    cfg = _load_default_config()
    schema = prompt_schema.from_skill_config(cfg)

    # imagegen taxonomy 注記は SKILL.md (#650) と整合する固定値
    assert schema.use_case == "product-mockup (YouTube thumbnail variant)"
    assert schema.asset_type == "YouTube thumbnail (1280x720, 16:9, JPEG)"

    # default.yaml は style / brand_background / prompt_prefix を空文字で持つため
    # bridge が空文字を None に正規化していることを確認
    assert schema.style is None
    assert schema.color is None
    assert schema.primary_request is None

    # composition_rules.text_lines が constraints にマップされる
    assert schema.constraints == "タイトルは 2 行以内"


def test_from_skill_config_maps_full_override() -> None:
    override = {
        "image_generation": {
            "gemini": {
                "prompt_prefix": "A jazz bar at night",
                "style": "matte painting",
                "brand_background": "deep navy blue",
                "reference_images": {
                    "default": [
                        "benchmarks/a.jpg",
                        "benchmarks/b.jpg",
                    ],
                },
                "composition_rules": {
                    "environment": "intimate jazz bar interior",
                    "background": "warm amber light",
                    "character_size": "subject occupies ~40% of frame",
                    "character_pose": "seated at bar",
                    "allowed_actions": "sipping cocktail",
                    "ng_actions": "no smoking, no phones",
                    "text_lines": "タイトルは 2 行以内",
                },
                "fixed_character": {
                    "species": "human",
                    "outfit": "wool coat",
                    "expression": "calm",
                },
                "thumbnail_text": {
                    "title_format": "{title_line1} | {title_line2}",
                    "channel_name": "rjn",
                    "copy_position": "right of character",
                    "color": "warm gold",
                    "decoration": "none",
                    "font": {"copy": "classic serif"},
                },
            }
        }
    }
    schema = prompt_schema.from_skill_config(override)

    assert schema.primary_request == "A jazz bar at night"
    assert schema.style == "matte painting"
    assert schema.input_images == ("benchmarks/a.jpg", "benchmarks/b.jpg")
    assert schema.scene == "intimate jazz bar interior. warm amber light"
    assert schema.subject is not None and "human" in schema.subject and "wool coat" in schema.subject
    assert schema.composition is not None and "right of character" in schema.composition
    assert schema.color is not None and "deep navy blue" in schema.color and "warm gold" in schema.color
    assert schema.materials == "none"
    assert schema.text is not None and "rjn" in schema.text and "classic serif" in schema.text
    assert schema.avoid == "no smoking, no phones"
    assert schema.constraints == "タイトルは 2 行以内"


def test_from_skill_config_accepts_string_reference_default() -> None:
    override = {
        "image_generation": {
            "gemini": {
                "reference_images": {"default": "benchmarks/only.jpg"},
            }
        }
    }
    schema = prompt_schema.from_skill_config(override)
    assert schema.input_images == ("benchmarks/only.jpg",)


def test_from_skill_config_round_trip_to_render_does_not_crash() -> None:
    cfg = _load_default_config()
    schema = prompt_schema.from_skill_config(cfg)
    rendered = prompt_schema.render(schema)
    # default.yaml ベースでは use_case / asset_type / constraints のみ出力される
    assert "Use case: product-mockup" in rendered
    assert "Asset type: YouTube thumbnail" in rendered
    assert "Constraints: タイトルは 2 行以内" in rendered
