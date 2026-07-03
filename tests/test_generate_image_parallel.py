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

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import youtube_automation.scripts.generate_image as generate_image_module
from youtube_automation.scripts.generate_image import (
    build_requests,
    plan_output_paths,
    plan_reference_assignments,
    run_requests_parallel,
)
from youtube_automation.scripts.generate_image import (
    main as generate_image_main,
)
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.composition import resolve_unique_path
from youtube_automation.utils.thumbnail_references import plan_ttp_reference_assignments

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

    def generate(self, request):  # noqa: ANN001 - テスト用フェイク
        with self._lock:
            self.calls.append(request.output_path)
            self.requests.append(request)
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
                "single_step": {"max_attempts": 3, "rotate": True},
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

    monkeypatch.setattr(skill_config_module, "load_skill_config", lambda _name: skill_cfg)


def _benchmark_refs(tmp_path: Path, count: int) -> list[Path]:
    ref_dir = tmp_path / "data" / "thumbnail_compare" / "benchmark" / "jazzgak"
    ref_dir.mkdir(parents=True)
    refs = [ref_dir / f"ref-{idx}.jpg" for idx in range(count)]
    for ref in refs:
        ref.write_bytes(b"fake image")
    return refs


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

    def test_generic_single_step_allows_no_reference_without_ttp_strict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = _FakeProvider()
        argv = [
            "--prompt",
            "prompt",
            "--output",
            str(tmp_path / "short.png"),
            "--max-attempts",
            "1",
            "-y",
        ]

        _patch_generate_image_cli(monkeypatch, argv, provider=provider)

        with pytest.raises(SystemExit) as exc_info:
            generate_image_main()
        assert exc_info.value.code == 0
        assert len(provider.requests) == 1
        assert provider.requests[0].references == []
