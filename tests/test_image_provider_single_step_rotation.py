"""``image_provider.composition`` の single_step ローテーション/プリフライト テスト。

Issue #356 で追加された以下を網羅する:

- ``select_reference``: rotate=True で attempt 毎に切替、rotate=False / 1 件で先頭固定、空リストで ValueError
- ``validate_single_step_references``: single_step モード + reference 未設定 → ConfigError
- ``normalize_reference_default``: str / list / None / 空文字列 / 混合の正規化
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.domains.thumbnail.references import (
    canonicalize_benchmark_reference,
    format_reference_assignment,
    infer_benchmark_channel,
    normalize_reference_default,
    plan_ttp_reference_assignments,
    resolve_configured_benchmark_references,
)
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.image_provider.composition import select_reference, validate_single_step_references

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

    def test_infers_channel_from_benchmark_filename_hyphen_videoid_suffix(self) -> None:
        assert infer_benchmark_channel(Path("/data/thumbnail_compare/benchmark/jazzgak-abc123.jpg")) == "jazzgak"

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


class TestStrictBenchmarkReferenceBoundaries:
    def test_configured_relative_reference_resolves_canonically(self, tmp_path: Path) -> None:
        reference = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "channel" / "a.jpg"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"image")

        result = resolve_configured_benchmark_references(
            tmp_path,
            "data/thumbnail_compare/benchmark/channel/a.jpg",
        )

        assert result.references == [reference.resolve()]
        assert result.placeholders == []
        assert result.invalid_reasons == []

    def test_configured_placeholder_and_escaped_paths_are_not_accepted(self, tmp_path: Path) -> None:
        result = resolve_configured_benchmark_references(
            tmp_path,
            ["{{REFERENCE}}", "../outside.jpg", str(tmp_path / "absolute.jpg")],
        )

        assert result.references == []
        assert result.placeholders == ["{{REFERENCE}}"]
        assert any("channel_dir 外" in reason for reason in result.invalid_reasons)
        assert any("絶対パス" in reason for reason in result.invalid_reasons)

    def test_canonicalization_rejects_missing_and_outside_paths(self, tmp_path: Path) -> None:
        benchmark = tmp_path / "benchmark"
        benchmark.mkdir()
        outside = tmp_path / "outside.jpg"
        outside.write_bytes(b"outside")

        with pytest.raises(ConfigError, match="見つかりません"):
            canonicalize_benchmark_reference(benchmark / "missing.jpg", benchmark)
        with pytest.raises(ConfigError, match="benchmark サムネイルに限定"):
            canonicalize_benchmark_reference(outside, benchmark)

    def test_recent_history_is_avoided_before_older_and_unused_references(self, tmp_path: Path) -> None:
        benchmark = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "channel"
        benchmark.mkdir(parents=True)
        recent, old, unused = [benchmark / name for name in ("recent.jpg", "old.jpg", "unused.jpg")]
        for path in (recent, old, unused):
            path.write_bytes(path.name.encode())
        older_log = tmp_path / "collections" / "live" / "20260101-old" / "20-documentation" / "thumbnail-prompts.md"
        recent_log = tmp_path / "collections" / "live" / "20260102-new" / "20-documentation" / "thumbnail-prompts.md"
        for log, ref in ((older_log, old), (recent_log, recent)):
            log.parent.mkdir(parents=True)
            log.write_text(
                "## Reference Assignments\n"
                "| attempt | output | reference_image | benchmark_channel |\n"
                "|---:|---|---|---|\n"
                f"| 1 | x | `{ref.relative_to(tmp_path)}` | channel |\n",
                encoding="utf-8",
            )

        selected = plan_ttp_reference_assignments(
            [recent, old, unused],
            2,
            True,
            benchmark_root=benchmark.parent,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        )

        assert selected == [unused.resolve(), old.resolve()]

    def test_all_used_references_fall_back_deterministically(self, tmp_path: Path) -> None:
        benchmark = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "channel"
        benchmark.mkdir(parents=True)
        refs = [benchmark / "a.jpg", benchmark / "b.jpg"]
        for ref in refs:
            ref.write_bytes(b"image")
        log = tmp_path / "collections" / "live" / "20260101-one" / "20-documentation" / "thumbnail-prompts.md"
        log.parent.mkdir(parents=True)
        log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            + "".join(
                f"| {index} | x | `{ref.relative_to(tmp_path)}` | channel |\n" for index, ref in enumerate(refs, 1)
            ),
            encoding="utf-8",
        )

        selected = plan_ttp_reference_assignments(
            refs,
            2,
            True,
            benchmark_root=benchmark.parent,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        )

        assert selected == [ref.resolve() for ref in refs]

    def test_unreadable_history_is_reported_as_config_error(self, tmp_path: Path, monkeypatch) -> None:
        benchmark = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "channel"
        benchmark.mkdir(parents=True)
        ref = benchmark / "a.jpg"
        ref.write_bytes(b"image")
        log = tmp_path / "collections" / "live" / "20260101-one" / "20-documentation" / "thumbnail-prompts.md"
        log.parent.mkdir(parents=True)
        log.write_text("## Reference Assignments\n", encoding="utf-8")
        original = Path.read_text

        def fail_history(path: Path, *args, **kwargs):
            if path == log:
                raise OSError("denied")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_history)
        with pytest.raises(ConfigError, match="履歴を読み取れません"):
            plan_ttp_reference_assignments(
                [ref],
                1,
                True,
                benchmark_root=benchmark.parent,
                channel_dir=tmp_path,
                dedup_recent_collections=1,
            )
