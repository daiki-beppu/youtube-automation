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

import threading
from pathlib import Path

import pytest

from youtube_automation.scripts.generate_image import (
    build_requests,
    plan_output_paths,
    plan_reference_assignments,
    run_requests_parallel,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.composition import resolve_unique_path

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

    def generate(self, request):  # noqa: ANN001 - テスト用フェイク
        with self._lock:
            self.calls.append(request.output_path)
        if request.output_path in self._fail_on:
            raise ConfigError(f"forced failure: {request.output_path}")
        return _FakeResult(success=True, saved_path=request.output_path)


# ---- plan_output_paths -----------------------------------------------------


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
            plan_reference_assignments([], 3, rotate=True, require_unique=True)

    def test_strict_assigns_unique_reference_per_attempt_without_reuse(self) -> None:
        refs = [Path("/bench-a.jpg"), Path("/bench-b.jpg"), Path("/bench-c.jpg")]
        assert plan_reference_assignments(refs, 3, rotate=True, require_unique=True) == refs

    def test_strict_rejects_reference_shortage(self) -> None:
        refs = [Path("/bench-a.jpg"), Path("/bench-b.jpg")]
        with pytest.raises(ConfigError, match="候補数分のユニークな参照画像"):
            plan_reference_assignments(refs, 3, rotate=True, require_unique=True)

    def test_strict_rejects_duplicate_reference_paths(self) -> None:
        refs = [Path("/bench-a.jpg"), Path("/bench-a.jpg"), Path("/bench-b.jpg")]
        with pytest.raises(ConfigError, match="同一参照画像を再利用"):
            plan_reference_assignments(refs, 3, rotate=True, require_unique=True)

    def test_strict_ignores_unused_duplicate_reference_paths(self) -> None:
        refs = [Path("/bench-a.jpg"), Path("/bench-b.jpg"), Path("/bench-c.jpg"), Path("/bench-a.jpg")]
        assert plan_reference_assignments(refs, 3, rotate=True, require_unique=True) == refs[:3]

    def test_strict_rejects_no_rotate_for_multiple_attempts(self) -> None:
        refs = [Path("/bench-a.jpg"), Path("/bench-b.jpg"), Path("/bench-c.jpg")]
        with pytest.raises(ConfigError, match="--no-rotate"):
            plan_reference_assignments(refs, 3, rotate=False, require_unique=True)

    def test_strict_reference_index_style_single_attempt_allows_one_reference(self) -> None:
        refs = [Path("/bench-a.jpg")]
        assert plan_reference_assignments(refs, 1, rotate=False, require_unique=True) == refs

    def test_strict_rejects_mixed_known_benchmark_channels(self) -> None:
        refs = [
            Path("/data/thumbnail_compare/benchmark/jazzgak-a.jpg"),
            Path("/data/thumbnail_compare/benchmark/lofi-b.jpg"),
        ]
        with pytest.raises(ConfigError, match="同じベンチマークチャンネル"):
            plan_reference_assignments(refs, 2, rotate=True, require_unique=True)

    def test_strict_allows_unknown_benchmark_channel_paths_for_compatibility(self) -> None:
        refs = [Path("/refs/a.jpg"), Path("/refs/b.jpg")]
        assert plan_reference_assignments(refs, 2, rotate=True, require_unique=True) == refs


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
