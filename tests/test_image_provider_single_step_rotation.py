"""``image_provider.composition`` の single_step ローテーション/プリフライト テスト。

Issue #356 で追加された以下を網羅する:

- ``select_reference``: rotate=True で attempt 毎に切替、rotate=False / 1 件で先頭固定、空リストで ValueError
- ``validate_single_step_references``: single_step モード + reference 未設定 → ConfigError
- ``normalize_reference_default``: str / list / None / 空文字列 / 混合の正規化
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.composition import (
    format_reference_assignment,
    infer_benchmark_channel,
    normalize_reference_default,
    select_reference,
    validate_single_step_references,
)

# ---- select_reference ------------------------------------------------------


class TestSelectReference:
    def test_rotate_true_cycles_attempts(self) -> None:
        refs = [Path("/a.jpg"), Path("/b.jpg"), Path("/c.jpg")]
        assert select_reference(refs, attempt=0, rotate=True) == Path("/a.jpg")
        assert select_reference(refs, attempt=1, rotate=True) == Path("/b.jpg")
        assert select_reference(refs, attempt=2, rotate=True) == Path("/c.jpg")
        assert select_reference(refs, attempt=3, rotate=True) == Path("/a.jpg")

    def test_rotate_false_pins_to_first(self) -> None:
        refs = [Path("/a.jpg"), Path("/b.jpg"), Path("/c.jpg")]
        for attempt in (0, 1, 2, 5):
            assert select_reference(refs, attempt=attempt, rotate=False) == Path("/a.jpg")

    def test_single_item_list_pins_regardless_of_rotate(self) -> None:
        refs = [Path("/only.jpg")]
        for rotate in (True, False):
            for attempt in (0, 1, 5):
                assert select_reference(refs, attempt=attempt, rotate=rotate) == Path("/only.jpg")

    def test_empty_list_raises(self) -> None:
        with pytest.raises(ValueError):
            select_reference([], attempt=0, rotate=True)


# ---- benchmark channel trace ----------------------------------------------


class TestBenchmarkChannelTrace:
    def test_infers_channel_from_benchmark_subdirectory(self) -> None:
        assert infer_benchmark_channel(Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg")) == "jazzgak"

    def test_does_not_infer_channel_from_ambiguous_hyphen_filename_prefix(self) -> None:
        assert infer_benchmark_channel(Path("/data/thumbnail_compare/benchmark/jazzgak-abc123.jpg")) == "unknown"

    def test_infers_channel_from_benchmark_filename_views_suffix(self) -> None:
        path = Path("/data/thumbnail_compare/benchmark/jazzgak_120k_abc123xyz.jpg")
        assert infer_benchmark_channel(path) == "jazzgak"

    def test_infers_hyphenated_channel_from_benchmark_filename_videoid_suffix(self) -> None:
        assert infer_benchmark_channel(Path("/data/thumbnail_compare/benchmark/jazz-gak_abc123xyz.jpg")) == "jazz-gak"

    def test_unknown_when_path_does_not_follow_benchmark_convention(self) -> None:
        assert infer_benchmark_channel(Path("/refs/a.jpg")) == "unknown"

    def test_format_reference_assignment_includes_channel_for_logs(self) -> None:
        formatted = format_reference_assignment(Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"))
        assert "jazzgak" in formatted
        assert "benchmark_channel=" in formatted


# ---- validate_single_step_references --------------------------------------


class TestValidateSingleStepReferences:
    def test_non_single_step_mode_passes(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "two_phase",
                    "reference_images": {"default": None},
                },
            },
        }
        # 例外を投げないこと
        validate_single_step_references(skill_cfg)

    def test_missing_image_generation_passes(self) -> None:
        validate_single_step_references({})

    def test_missing_gemini_passes(self) -> None:
        validate_single_step_references({"image_generation": {}})

    def test_single_step_with_string_default_passes(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": "branding/ref.png"},
                },
            },
        }
        validate_single_step_references(skill_cfg)

    def test_single_step_with_list_default_passes(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": ["a.jpg", "b.jpg"]},
                },
            },
        }
        validate_single_step_references(skill_cfg)

    def test_single_step_without_reference_images_raises(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {"generation_mode": "single_step"},
            },
        }
        with pytest.raises(ConfigError, match="single_step モードには"):
            validate_single_step_references(skill_cfg)

    def test_single_step_with_none_default_raises(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": None},
                },
            },
        }
        with pytest.raises(ConfigError):
            validate_single_step_references(skill_cfg)

    def test_single_step_with_empty_string_default_raises(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": "   "},
                },
            },
        }
        with pytest.raises(ConfigError):
            validate_single_step_references(skill_cfg)

    def test_single_step_with_empty_list_default_raises(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "single_step",
                    "reference_images": {"default": []},
                },
            },
        }
        with pytest.raises(ConfigError):
            validate_single_step_references(skill_cfg)


# ---- normalize_reference_default ------------------------------------------


class TestNormalizeReferenceDefault:
    def test_none_returns_empty(self) -> None:
        assert normalize_reference_default(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_reference_default("") == []
        assert normalize_reference_default("   ") == []

    def test_string_returns_single_element_list(self) -> None:
        assert normalize_reference_default("branding/ref.png") == ["branding/ref.png"]

    def test_string_strips_whitespace(self) -> None:
        assert normalize_reference_default("  branding/ref.png  ") == ["branding/ref.png"]

    def test_list_returns_as_is(self) -> None:
        assert normalize_reference_default(["a.jpg", "b.jpg"]) == ["a.jpg", "b.jpg"]

    def test_list_filters_empty_strings(self) -> None:
        assert normalize_reference_default(["a.jpg", "", "  ", "b.jpg"]) == ["a.jpg", "b.jpg"]

    def test_empty_list_returns_empty(self) -> None:
        assert normalize_reference_default([]) == []
