"""``generate_image`` の attempt ループ並列化に関するテスト（Issue #584）。

並列化の不変条件を担保する:

- 生成枚数が変わらない（``--max-attempts N`` で N 件）
- 出力ファイルの -vN 採番が逐次実行と一致する（``plan_output_paths``）
- 参照画像のローテーション割り当てが逐次実行と一致する（``plan_reference_assignments``）
- ``--max-attempts 1``（単発）の経路が従来どおり 1 件
- 失敗（``ConfigError``）は future の例外として回収され、他結果を握りつぶさない

API 呼び出しはフェイク provider で mock 化する。
"""

from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import youtube_automation.scripts.generate_image as generate_image_module
from youtube_automation.scripts.generate_image import (
    apply_ab_test_pattern,
    build_requests,
    expand_thumbnail_prompt_clauses,
    plan_output_paths,
    plan_reference_assignments,
    resolve_ab_test_patterns,
    run_requests_parallel,
)
from youtube_automation.scripts.generate_image import (
    main as generate_image_main,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.composition import resolve_unique_path
from youtube_automation.utils.thumbnail_references import (
    plan_ttp_reference_assignments,
    record_ttp_reference_assignments,
    resolve_dedup_recent_collections,
)

# ---- フェイク provider ------------------------------------------------------


class _FakeResult:
    def __init__(self, *, success: bool, saved_path: Path | None) -> None:
        self.success = success
        self.saved_path = saved_path


class _FakeProvider:
    """provider.generate を記録するフェイク。記録は lock 下で安全に追記する。"""

    def __init__(self, *, fail_on: set[Path] | None = None) -> None:
        self._fail_on = fail_on or set()
        self._lock = threading.Lock()
        self.calls: list[Path] = []
        self.requests: list = []

    def generate(self, request):
        with self._lock:
            self.calls.append(request.output_path)
            self.requests.append(request)
        if request.output_path in self._fail_on:
            raise ConfigError(f"forced failure: {request.output_path}")
        return _FakeResult(success=True, saved_path=request.output_path)


# ---- plan_output_paths -----------------------------------------------------


class TestExpandThumbnailPromptClauses:
    def test_replaces_typography_clause_with_configured_font_description(self) -> None:
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "single_step": {
                        "typography_clause": "Render title in a consistent {font_description} typeface.",
                    },
                    "thumbnail_text": {"font": {"copy": "classic serif"}},
                }
            }
        }

        prompt = expand_thumbnail_prompt_clauses("Text-included thumbnail prompt. ${typography_clause}", skill_cfg)

        assert prompt == "Text-included thumbnail prompt. Render title in a consistent classic serif typeface."

    def test_leaves_prompt_without_placeholder_unchanged(self) -> None:
        assert expand_thumbnail_prompt_clauses("No typography placeholder.", {}) == "No typography placeholder."

    @pytest.mark.parametrize(
        "skill_cfg, message",
        [
            ({"image_generation": []}, "image_generation"),
            ({"image_generation": {"gemini": []}}, "image_generation.gemini"),
            ({"image_generation": {"gemini": {"single_step": []}}}, "single_step"),
            ({"image_generation": {"gemini": {"single_step": {}, "thumbnail_text": []}}}, "thumbnail_text"),
            (
                {"image_generation": {"gemini": {"single_step": {}, "thumbnail_text": {"font": []}}}},
                "thumbnail_text.font",
            ),
            (
                {
                    "image_generation": {
                        "gemini": {
                            "single_step": {"typography_clause": 123},
                            "thumbnail_text": {"font": {"copy": "classic serif"}},
                        }
                    }
                },
                "typography_clause",
            ),
            (
                {
                    "image_generation": {
                        "gemini": {
                            "single_step": {"typography_clause": "Use {font_description}."},
                            "thumbnail_text": {"font": {"copy": ""}},
                        }
                    }
                },
                "font.copy",
            ),
            (
                {
                    "image_generation": {
                        "gemini": {
                            "single_step": {"typography_clause": "Use consistent lettering."},
                            "thumbnail_text": {"font": {"copy": "classic serif"}},
                        }
                    }
                },
                "font_description",
            ),
        ],
    )
    def test_rejects_malformed_typography_config(self, skill_cfg: dict, message: str) -> None:
        with pytest.raises(ConfigError, match=message):
            expand_thumbnail_prompt_clauses("Text-included thumbnail prompt. ${typography_clause}", skill_cfg)


class TestAbTestPatterns:
    def test_disabled_or_missing_preserves_single_thumbnail_flow(self) -> None:
        assert resolve_ab_test_patterns({}) == []
        assert resolve_ab_test_patterns({"ab_test": {"enabled": False, "patterns": []}}) == []
        assert apply_ab_test_pattern("base prompt", [], None) == "base prompt"

    def test_resolves_three_patterns_and_appends_selected_variation(self) -> None:
        patterns = resolve_ab_test_patterns(
            {
                "ab_test": {
                    "enabled": True,
                    "patterns": [
                        {"name": "a", "variation": "Use a close-up composition."},
                        {"name": "b", "variation": "Use a cool blue palette."},
                        {"name": "copy", "variation": "Use a shorter title copy."},
                    ],
                }
            }
        )

        assert [pattern["name"] for pattern in patterns] == ["a", "b", "copy"]
        assert apply_ab_test_pattern("base prompt\n", patterns, "b") == "base prompt\nUse a cool blue palette."

    @pytest.mark.parametrize(
        "ab_test, message",
        [
            ({"enabled": True, "patterns": []}, "1 件以上"),
            (
                {
                    "enabled": True,
                    "patterns": [
                        {"name": "a", "variation": "A"},
                        {"name": "b", "variation": "B"},
                        {"name": "c", "variation": "C"},
                        {"name": "d", "variation": "D"},
                    ],
                },
                "3 件以内",
            ),
            ({"enabled": True, "patterns": [{"name": "../a", "variation": "A"}]}, "英小文字"),
            ({"enabled": True, "patterns": [{"name": "a", "variation": ""}]}, "variation"),
            (
                {
                    "enabled": True,
                    "patterns": [
                        {"name": "a", "variation": "A"},
                        {"name": "a", "variation": "B"},
                    ],
                },
                "重複",
            ),
        ],
    )
    def test_rejects_invalid_enabled_config(self, ab_test: dict, message: str) -> None:
        with pytest.raises(ConfigError, match=message):
            resolve_ab_test_patterns({"ab_test": ab_test})

    def test_rejects_unknown_or_disabled_pattern_selection(self) -> None:
        with pytest.raises(ConfigError, match="enabled=true"):
            apply_ab_test_pattern("base", [], "a")

        patterns = [{"name": "a", "variation": "A"}]
        with pytest.raises(ConfigError, match="有効値: a"):
            apply_ab_test_pattern("base", patterns, "b")


class TestPlanOutputPaths:
    def test_single_attempt_returns_first_only(self, tmp_path: Path) -> None:
        first = tmp_path / "main.png"
        assert plan_output_paths(first, 1) == [first]

    def test_zero_count_returns_empty(self, tmp_path: Path) -> None:
        assert plan_output_paths(tmp_path / "main.png", 0) == []

    def test_three_attempts_clean_dir(self, tmp_path: Path) -> None:
        first = tmp_path / "main.png"
        assert plan_output_paths(first, 3) == [
            first,
            tmp_path / "main-v2.png",
            tmp_path / "main-v3.png",
        ]

    def test_first_path_with_version_suffix(self, tmp_path: Path) -> None:
        first = tmp_path / "main-v3.png"
        assert plan_output_paths(first, 3) == [
            first,
            tmp_path / "main-v4.png",
            tmp_path / "main-v5.png",
        ]

    def test_skips_preexisting_disk_files(self, tmp_path: Path) -> None:
        first = tmp_path / "main.png"
        # main-v2.png が既に disk 上に存在する場合はスキップする
        (tmp_path / "main-v2.png").write_bytes(b"x")
        assert plan_output_paths(first, 3) == [
            first,
            tmp_path / "main-v3.png",
            tmp_path / "main-v4.png",
        ]

    @pytest.mark.parametrize("count", [1, 2, 3, 5, 8])
    def test_matches_serial_resolve_unique_path_chain(self, tmp_path: Path, count: int) -> None:
        """逐次実行（resolve_unique_path を直列チェーン + ファイル生成）と完全一致する。"""
        first = tmp_path / "main.png"

        # 逐次実行の再現: 各 attempt で生成したファイルを disk に作り、
        # 次の attempt は resolve_unique_path(current) で採番する。
        serial: list[Path] = []
        current = first
        for attempt in range(count):
            if attempt > 0:
                current = resolve_unique_path(current)
            current.write_bytes(b"x")  # provider.generate がファイルを生成した想定
            serial.append(current)

        # plan は disk を汚さない計画なので、別ディレクトリで実行して比較する
        clean = tmp_path / "clean"
        clean.mkdir()
        planned = plan_output_paths(clean / "main.png", count)

        assert [p.name for p in planned] == [p.name for p in serial]


# ---- plan_reference_assignments --------------------------------------------


class TestPlanReferenceAssignments:
    def test_no_references_returns_none_list(self) -> None:
        assert plan_reference_assignments([], 3, rotate=True) == [None, None, None]

    def test_rotate_cycles(self) -> None:
        refs = [Path("/a.jpg"), Path("/b.jpg")]
        assert plan_reference_assignments(refs, 4, rotate=True) == [
            Path("/a.jpg"),
            Path("/b.jpg"),
            Path("/a.jpg"),
            Path("/b.jpg"),
        ]

    def test_no_rotate_pins_first(self) -> None:
        refs = [Path("/a.jpg"), Path("/b.jpg")]
        assert plan_reference_assignments(refs, 3, rotate=False) == [
            Path("/a.jpg"),
            Path("/a.jpg"),
            Path("/a.jpg"),
        ]

    def test_strict_requires_references(self) -> None:
        with pytest.raises(ConfigError, match="参照画像が必須"):
            plan_ttp_reference_assignments([], 3, rotate=True)

    def test_strict_assigns_unique_reference_per_attempt_without_reuse(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/b.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/c.jpg"),
        ]
        assert plan_ttp_reference_assignments(refs, 3, rotate=True) == refs

    def test_strict_rejects_reference_shortage(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/b.jpg"),
        ]
        with pytest.raises(ConfigError, match="候補数分のユニークな参照画像"):
            plan_ttp_reference_assignments(refs, 3, rotate=True)

    def test_strict_rejects_duplicate_reference_paths(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/b.jpg"),
        ]
        with pytest.raises(ConfigError, match="同一参照画像を再利用"):
            plan_ttp_reference_assignments(refs, 3, rotate=True)

    def test_strict_ignores_unused_duplicate_reference_paths(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/b.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/c.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
        ]
        assert plan_ttp_reference_assignments(refs, 3, rotate=True) == refs[:3]

    def test_strict_rejects_no_rotate_for_multiple_attempts(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/b.jpg"),
            Path("/data/thumbnail_compare/benchmark/jazzgak/c.jpg"),
        ]
        with pytest.raises(ConfigError, match="--no-rotate"):
            plan_ttp_reference_assignments(refs, 3, rotate=False)

    def test_strict_reference_index_style_single_attempt_allows_one_reference(self) -> None:
        refs = [Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg")]
        assert plan_ttp_reference_assignments(refs, 1, rotate=False) == refs

    def test_no_rotate_single_attempt_pins_first_reference_despite_history(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        _write_reference_assignments(
            tmp_path,
            "planning/20260712-recent",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg"],
        )

        assert plan_ttp_reference_assignments(
            refs,
            1,
            rotate=False,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        ) == [refs[0]]

    def test_excludes_references_used_by_recent_collections(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 4)
        prompt_log = (
            tmp_path / "collections" / "planning" / "20260712-recent" / "20-documentation" / "thumbnail-prompts.md"
        )
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg` | jazzgak |\n"
            "| 2 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg` | jazzgak |\n",
            encoding="utf-8",
        )

        assert (
            plan_ttp_reference_assignments(refs, 2, rotate=True, channel_dir=tmp_path, dedup_recent_collections=1)
            == refs[2:]
        )

    def test_excludes_references_from_every_assignment_section_in_one_log(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        prompt_log = (
            tmp_path / "collections" / "planning" / "20260712-recent" / "20-documentation" / "thumbnail-prompts.md"
        )
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | thumbnail | `data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg` | jazzgak |\n"
            "\n## Prompt Details\nold content\n\n"
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | collection-ideate preview | `data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg` | jazzgak |\n",
            encoding="utf-8",
        )

        assert plan_ttp_reference_assignments(
            refs,
            1,
            rotate=True,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        ) == [refs[2]]

    def test_recent_collection_window_is_ordered_by_collection_across_states(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        _write_reference_assignments(
            tmp_path,
            "planning/20260101-old",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg"],
        )
        _write_reference_assignments(
            tmp_path,
            "live/20260712-new",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg"],
        )

        assert plan_ttp_reference_assignments(
            refs,
            2,
            rotate=True,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        ) == [refs[2], refs[0]]

    def test_zero_dedup_window_disables_history_exclusion(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        _write_reference_assignments(
            tmp_path,
            "planning/20260712-recent",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg"],
        )

        assert (
            plan_ttp_reference_assignments(
                refs,
                2,
                rotate=True,
                channel_dir=tmp_path,
                dedup_recent_collections=0,
            )
            == refs
        )

    def test_missing_dedup_window_uses_default_of_five(self) -> None:
        assert resolve_dedup_recent_collections(None) == 5

    @pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
    def test_invalid_dedup_window_is_rejected(self, value: object) -> None:
        with pytest.raises(ConfigError, match="0 以上の整数"):
            resolve_dedup_recent_collections(value)

    def test_falls_back_to_position_order_after_entire_pool_was_used(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        prompt_log = tmp_path / "collections" / "live" / "20260712-recent" / "20-documentation" / "thumbnail-prompts.md"
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg` | jazzgak |\n"
            "| 2 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg` | jazzgak |\n",
            encoding="utf-8",
        )

        assert (
            plan_ttp_reference_assignments(refs, 2, rotate=True, channel_dir=tmp_path, dedup_recent_collections=1)
            == refs
        )

    def test_prefers_never_used_references_before_reusing_outside_recent_window(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 10)
        for index in range(6):
            _write_reference_assignments(
                tmp_path,
                f"live/202607{index + 1:02d}-collection",
                [f"data/thumbnail_compare/benchmark/jazzgak/ref-{index}.jpg"],
            )

        assert plan_ttp_reference_assignments(
            refs,
            1,
            rotate=True,
            channel_dir=tmp_path,
            dedup_recent_collections=5,
        ) == [refs[6]]

    def test_fills_partial_dedup_shortage_in_position_order(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        prompt_log = (
            tmp_path / "collections" / "planning" / "20260712-recent" / "20-documentation" / "thumbnail-prompts.md"
        )
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg` | jazzgak |\n"
            "| 2 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg` | jazzgak |\n",
            encoding="utf-8",
        )

        assert plan_ttp_reference_assignments(
            refs,
            2,
            rotate=True,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        ) == [refs[2], refs[0]]

    def test_ignores_legacy_collection_without_reference_assignments(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        legacy_log = (
            tmp_path / "collections" / "planning" / "20260712-legacy" / "20-documentation" / "thumbnail-prompts.md"
        )
        legacy_log.parent.mkdir(parents=True)
        legacy_log.write_text("# old prompt format\n", encoding="utf-8")

        assert (
            plan_ttp_reference_assignments(refs, 2, rotate=True, channel_dir=tmp_path, dedup_recent_collections=1)
            == refs
        )

    def test_legacy_collection_counts_toward_recent_window(self, tmp_path: Path) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        _write_reference_assignments(
            tmp_path,
            "live/20260711-older",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg"],
        )
        legacy_collection = tmp_path / "collections" / "planning" / "20260712-latest-legacy"
        legacy_collection.mkdir(parents=True)

        assert plan_ttp_reference_assignments(
            refs,
            2,
            rotate=True,
            channel_dir=tmp_path,
            dedup_recent_collections=1,
        ) == [refs[1], refs[0]]

    def test_rejects_reference_history_that_cannot_be_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        prompt_log = _write_reference_assignments(
            tmp_path,
            "planning/20260712-unreadable",
            ["data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg"],
        )
        original_read_text = Path.read_text

        def fail_for_prompt_log(path: Path, *args: object, **kwargs: object) -> str:
            if path == prompt_log:
                raise PermissionError("history denied")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_for_prompt_log)

        with pytest.raises(ConfigError, match=f"{re.escape(str(prompt_log))}.*history denied"):
            plan_ttp_reference_assignments(
                refs,
                2,
                rotate=True,
                channel_dir=tmp_path,
                dedup_recent_collections=1,
            )

    def test_strict_rejects_mixed_known_benchmark_channels(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak-a.jpg"),
            Path("/data/thumbnail_compare/benchmark/lofi-b.jpg"),
        ]
        with pytest.raises(ConfigError, match="benchmark_channel=unknown"):
            plan_ttp_reference_assignments(refs, 2, rotate=True)

    def test_strict_rejects_unknown_benchmark_channel_paths(self) -> None:
        refs = [Path("/refs/a.jpg"), Path("/refs/b.jpg")]
        with pytest.raises(ConfigError, match="benchmark_channel=unknown"):
            plan_ttp_reference_assignments(refs, 2, rotate=True)

    def test_strict_rejects_known_unknown_mixed_channels(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/refs/b.jpg"),
        ]
        with pytest.raises(ConfigError, match="benchmark_channel=unknown"):
            plan_ttp_reference_assignments(refs, 2, rotate=True)

    def test_strict_rejects_mixed_benchmark_subdirectory_channels(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak/a.jpg"),
            Path("/data/thumbnail_compare/benchmark/lofi/b.jpg"),
        ]
        with pytest.raises(ConfigError, match="同じベンチマークチャンネル"):
            plan_ttp_reference_assignments(refs, 2, rotate=True)

    def test_strict_canonicalizes_and_rejects_parent_escape(self, tmp_path: Path) -> None:
        benchmark_root = tmp_path / "data" / "thumbnail_compare" / "benchmark"
        channel_dir = benchmark_root / "jazzgak"
        channel_dir.mkdir(parents=True)
        outside = tmp_path / "data" / "thumbnail_compare" / "outside.jpg"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"outside")
        valid = channel_dir / "a.jpg"
        valid.write_bytes(b"valid")

        escaped = channel_dir / ".." / ".." / "outside.jpg"
        with pytest.raises(ConfigError, match="benchmark サムネイルに限定"):
            plan_ttp_reference_assignments([valid, escaped], 2, rotate=True, benchmark_root=benchmark_root)

    def test_strict_canonicalizes_and_rejects_symlink_escape(self, tmp_path: Path) -> None:
        benchmark_root = tmp_path / "data" / "thumbnail_compare" / "benchmark"
        channel_dir = benchmark_root / "jazzgak"
        channel_dir.mkdir(parents=True)
        outside = tmp_path / "secret.jpg"
        outside.write_bytes(b"secret")
        valid = channel_dir / "a.jpg"
        valid.write_bytes(b"valid")
        escaped = channel_dir / "linked.jpg"
        escaped.symlink_to(outside)

        with pytest.raises(ConfigError, match="benchmark サムネイルに限定"):
            plan_ttp_reference_assignments([valid, escaped], 2, rotate=True, benchmark_root=benchmark_root)


# ---- build_requests --------------------------------------------------------


class TestBuildRequests:
    def test_count_and_paths_and_refs(self, tmp_path: Path) -> None:
        paths = [tmp_path / "main.png", tmp_path / "main-v2.png"]
        refs: list[Path | None] = [Path("/a.jpg"), Path("/b.jpg")]
        requests = build_requests(
            "prompt text",
            paths,
            refs,
            aspect_ratio="16:9",
            image_size="2K",
        )
        assert len(requests) == 2
        assert [r.output_path for r in requests] == paths
        assert requests[0].references == [Path("/a.jpg")]
        assert requests[1].references == [Path("/b.jpg")]
        assert all(r.prompt == "prompt text" for r in requests)

    def test_none_reference_yields_empty_references(self, tmp_path: Path) -> None:
        requests = build_requests(
            "p",
            [tmp_path / "main.png"],
            [None],
            aspect_ratio="16:9",
            image_size="2K",
        )
        assert requests[0].references == []


# ---- run_requests_parallel -------------------------------------------------


class TestRunRequestsParallel:
    def test_single_request_runs_once(self, tmp_path: Path) -> None:
        provider = _FakeProvider()
        requests = build_requests("p", [tmp_path / "main.png"], [None], aspect_ratio="16:9", image_size="2K")
        results, errors = run_requests_parallel(provider, requests, max_workers=3, aspect_ratio="16:9")
        assert errors == []
        assert len(results) == 1
        assert results[0].success is True
        assert provider.calls == [tmp_path / "main.png"]

    def test_all_requests_executed_results_ordered(self, tmp_path: Path) -> None:
        paths = plan_output_paths(tmp_path / "main.png", 5)
        provider = _FakeProvider()
        requests = build_requests("p", paths, [None] * 5, aspect_ratio="16:9", image_size="2K")
        results, errors = run_requests_parallel(provider, requests, max_workers=3, aspect_ratio="16:9")
        assert errors == []
        assert len(results) == 5
        # results は attempt 順に整列し、各 result.saved_path が対応パスを指す
        assert [r.saved_path for r in results] == paths
        # 全リクエストが実行された（順不同なので集合で比較）
        assert set(provider.calls) == set(paths)

    def test_config_error_is_collected_not_swallowed(self, tmp_path: Path) -> None:
        paths = plan_output_paths(tmp_path / "main.png", 3)
        # 2 番目（index 1）の attempt だけ失敗させる
        provider = _FakeProvider(fail_on={paths[1]})
        requests = build_requests("p", paths, [None] * 3, aspect_ratio="16:9", image_size="2K")
        results, errors = run_requests_parallel(provider, requests, max_workers=3, aspect_ratio="16:9")
        # 失敗は (index, ConfigError) として回収される
        assert len(errors) == 1
        assert errors[0][0] == 1
        assert isinstance(errors[0][1], ConfigError)
        # 他の attempt の結果は握りつぶされず保持される
        assert results[0] is not None and results[0].success
        assert results[1] is None
        assert results[2] is not None and results[2].success

    def test_empty_requests(self) -> None:
        provider = _FakeProvider()
        results, errors = run_requests_parallel(provider, [], max_workers=3, aspect_ratio="16:9")
        assert results == []
        assert errors == []


# ---- CLI integration -------------------------------------------------------


def _patch_generate_image_cli(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    provider: _FakeProvider,
    channel_root: Path | None = None,
    skill_cfg_override: dict | None = None,
) -> None:
    cfg = SimpleNamespace(
        provider="gemini",
        gemini=SimpleNamespace(model="gemini-test"),
        openai=None,
    )
    skill_cfg = {
        "image_generation": {
            "gemini": {
                "generation_mode": "single_step",
                "single_step": {
                    "max_attempts": 3,
                    "rotate": True,
                    "typography_clause": "Render title in a consistent {font_description} typeface.",
                },
                "thumbnail_text": {"font": {"copy": "classic serif"}},
                "reference_images": {
                    "default": [
                        "data/thumbnail_compare/benchmark/jazzgak/a.jpg",
                        "data/thumbnail_compare/benchmark/jazzgak/b.jpg",
                        "data/thumbnail_compare/benchmark/jazzgak/c.jpg",
                    ]
                },
            }
        }
    }

    monkeypatch.setattr(sys, "argv", ["yt-generate-image", *argv])
    monkeypatch.setattr(generate_image_module, "load_image_generation_config", lambda: cfg)
    monkeypatch.setattr(generate_image_module, "get_provider", lambda _cfg: provider)
    if channel_root is not None:
        monkeypatch.setattr(generate_image_module, "_channel_root", lambda: channel_root)

    import youtube_automation.utils.skill_config as skill_config_module

    monkeypatch.setattr(skill_config_module, "load_skill_config", lambda _name: skill_cfg_override or skill_cfg)


def _benchmark_refs(tmp_path: Path, count: int) -> list[Path]:
    ref_dir = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "jazzgak"
    ref_dir.mkdir(parents=True)
    refs = [ref_dir / f"ref-{idx}.jpg" for idx in range(count)]
    for ref in refs:
        ref.write_bytes(b"fake image")
    return refs


def test_generate_image_cli_applies_ab_pattern_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"fake image")
    skill_cfg = {
        "ab_test": {
            "enabled": True,
            "patterns": [
                {"name": "a", "variation": "Use a close-up composition."},
                {"name": "b", "variation": "Use a cool blue palette."},
            ],
        },
        "image_generation": {
            "gemini": {
                "generation_mode": "single_step",
                "single_step": {"max_attempts": 1, "rotate": True},
            }
        },
    }
    _patch_generate_image_cli(
        monkeypatch,
        [
            "--prompt",
            "base prompt",
            "--output",
            str(tmp_path / "thumbnail-b-v1.jpg"),
            "--reference",
            str(reference),
            "--ab-pattern",
            "b",
            "-y",
        ],
        provider=provider,
        channel_root=tmp_path,
        skill_cfg_override=skill_cfg,
    )

    with pytest.raises(SystemExit) as exc_info:
        generate_image_main()

    assert exc_info.value.code == 0
    assert len(provider.requests) == 1
    assert provider.requests[0].prompt == "base prompt\nUse a cool blue palette."


def test_generate_image_cli_rejects_invalid_ab_config_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    skill_cfg = {
        "ab_test": {"enabled": True, "patterns": []},
        "image_generation": {"gemini": {"generation_mode": "two_phase"}},
    }
    _patch_generate_image_cli(
        monkeypatch,
        ["--prompt", "base prompt", "--output", str(tmp_path / "thumbnail.jpg"), "-y"],
        provider=provider,
        channel_root=tmp_path,
        skill_cfg_override=skill_cfg,
    )

    with pytest.raises(SystemExit) as exc_info:
        generate_image_main()

    assert exc_info.value.code == 1
    assert provider.calls == []


def _write_reference_assignments(tmp_path: Path, collection: str, references: list[str]) -> Path:
    prompt_log = tmp_path / "collections" / collection / "20-documentation" / "thumbnail-prompts.md"
    prompt_log.parent.mkdir(parents=True)
    rows = "".join(f"| {index} | output | `{reference}` | jazzgak |\n" for index, reference in enumerate(references, 1))
    prompt_log.write_text(
        "## Reference Assignments\n"
        "| attempt | output | reference_image | benchmark_channel |\n"
        "|---:|---|---|---|\n"
        f"{rows}",
        encoding="utf-8",
    )
    return prompt_log


def test_record_ttp_reference_assignments_wraps_persistence_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_log = tmp_path / "collections" / "planning" / "collection" / "20-documentation" / "thumbnail-prompts.md"

    def fail_write(_self: Path, *_args: object, **_kwargs: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(ConfigError, match=rf"参照画像履歴を保存できません: {re.escape(str(prompt_log))}: disk full"):
        record_ttp_reference_assignments(prompt_log, [tmp_path / "reference.jpg"], tmp_path)


class TestGenerateImageCLIReferenceContract:
    def test_single_step_cli_assigns_one_unique_reference_per_attempt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        provider = _FakeProvider()
        output = tmp_path / "thumbnail-v1.jpg"
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(output),
            "--max-attempts",
            "3",
            "--max-workers",
            "1",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, channel_root=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0

        assert len(provider.requests) == 3
        assert [request.references for request in provider.requests] == [[ref] for ref in refs]
        assert [request.output_path.name for request in provider.requests] == [
            "thumbnail-v1.jpg",
            "thumbnail-v2.jpg",
            "thumbnail-v3.jpg",
        ]
        captured = capsys.readouterr()
        assert "benchmark_channel=jazzgak" in captured.out

    def test_cli_applies_configured_recent_collection_deduplication(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 4)
        prompt_log = (
            tmp_path / "collections" / "planning" / "20260712-recent" / "20-documentation" / "thumbnail-prompts.md"
        )
        prompt_log.parent.mkdir(parents=True)
        prompt_log.write_text(
            "## Reference Assignments\n"
            "| attempt | output | reference_image | benchmark_channel |\n"
            "|---:|---|---|---|\n"
            "| 1 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-0.jpg` | jazzgak |\n"
            "| 2 | output | `data/thumbnail_compare/benchmark/jazzgak/ref-1.jpg` | jazzgak |\n",
            encoding="utf-8",
        )
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--max-attempts",
            "2",
            "--max-workers",
            "1",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])
        skill_cfg = {"image_generation": {"gemini": {"reference_images": {"dedup_recent_collections": 1}}}}
        _patch_generate_image_cli(
            monkeypatch,
            argv,
            provider=provider,
            channel_root=tmp_path,
            skill_cfg_override=skill_cfg,
        )

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()

        assert exc_info.value.code == 0
        assert [request.references for request in provider.requests] == [[refs[2]], [refs[3]]]

    def test_cli_expands_typography_clause_before_provider_request(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ref = tmp_path / "ref.jpg"
        ref.write_bytes(b"fake image")
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "Text-included thumbnail prompt. ${typography_clause}",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--reference",
            str(ref),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0

        assert len(provider.requests) == 1
        assert (
            provider.requests[0].prompt
            == "Text-included thumbnail prompt. Render title in a consistent classic serif typeface."
        )

    @pytest.mark.parametrize(
        "skill_cfg, message",
        [
            (
                {"image_generation": {"gemini": {"single_step": [], "thumbnail_text": {"font": {"copy": "serif"}}}}},
                "single_step",
            ),
            (
                {
                    "image_generation": {
                        "gemini": {
                            "single_step": {"typography_clause": []},
                            "thumbnail_text": {"font": {"copy": "serif"}},
                        }
                    }
                },
                "typography_clause",
            ),
            (
                {
                    "image_generation": {
                        "gemini": {
                            "single_step": {"typography_clause": "Use {font_description}."},
                            "thumbnail_text": {"font": {"copy": []}},
                        }
                    }
                },
                "font.copy",
            ),
        ],
    )
    def test_cli_reports_malformed_typography_config_as_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        skill_cfg: dict,
        message: str,
    ) -> None:
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "Text-included thumbnail prompt. ${typography_clause}",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, skill_cfg_override=skill_cfg)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()

        assert exc_info.value.code == 1
        assert provider.requests == []
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out
        assert message in captured.out

    def test_single_step_cli_rejects_reference_shortage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--max-attempts",
            "3",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, channel_root=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 1
        assert provider.requests == []

    def test_single_step_cli_rejects_no_rotate_for_multiple_attempts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--max-attempts",
            "3",
            "--no-rotate",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, channel_root=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 1
        assert provider.requests == []

    def test_reference_index_forces_single_request_with_selected_reference(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 3)
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--max-attempts",
            "3",
            "--reference-index",
            "1",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, channel_root=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0

        assert len(provider.requests) == 1
        assert provider.requests[0].references == [refs[1]]

    def test_reference_index_out_of_range_exits_before_request(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refs = _benchmark_refs(tmp_path, 2)
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "thumbnail-v1.jpg"),
            "--reference-index",
            "2",
            "--ttp-strict-references",
            "-y",
        ]
        for ref in refs:
            argv.extend(["--reference", str(ref)])

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, channel_root=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 1
        assert provider.requests == []

    def test_ttp_strict_rejects_missing_cli_references_before_existing_output_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        provider = _FakeProvider()
        output = tmp_path / "thumbnail-v1.jpg"
        output.write_bytes(b"existing")
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(output),
            "--ttp-strict-references",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 1
        assert provider.requests == []
        captured = capsys.readouterr()
        assert "reference_images.default" in captured.out
        assert "--reference" in captured.out
        assert "上書きしますか" not in captured.out

    def test_generic_single_step_rejects_no_reference_without_ttp_strict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        provider = _FakeProvider()
        output = tmp_path / "short.png"
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(output),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 1
        assert provider.requests == []
        assert not output.exists()
        captured = capsys.readouterr()
        assert "single_step モードでは --reference の指定が必須" in captured.out
        assert "モード:" not in captured.out

    def test_single_step_cli_allows_reference_without_ttp_strict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ref = tmp_path / "ref.jpg"
        ref.write_bytes(b"fake image")
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "short.png"),
            "--reference",
            str(ref),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0
        assert len(provider.requests) == 1
        assert provider.requests[0].references == [ref]

    def test_two_phase_cli_allows_no_reference(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = _FakeProvider()
        skill_cfg = {
            "image_generation": {
                "gemini": {
                    "generation_mode": "two_phase",
                    "single_step": {"max_attempts": 1, "rotate": True},
                }
            }
        }
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "short.png"),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider, skill_cfg_override=skill_cfg)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0
        assert len(provider.requests) == 1
        assert provider.requests[0].references == []
