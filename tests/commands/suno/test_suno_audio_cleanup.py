"""Suno audio cleanup CLI helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from youtube_automation.commands.suno import suno_audio_cleanup as mod
from youtube_automation.commands.suno.suno_audio_cleanup import (
    CleanupConfig,
    apply_cleanup_overrides,
    build_filter,
    cleanup_collection,
    collect_audio_files,
    probe_trimmed_duration,
    process_file,
    resolve_cleanup_config,
    resolve_max_workers,
)
from youtube_automation.core.errors import ConfigError


@pytest.fixture(autouse=True)
def _reuse_input_duration_unless_duration_probe_is_under_test(monkeypatch) -> None:
    monkeypatch.setattr(mod, "probe_trimmed_duration", lambda path, _cfg: mod.probe_duration(path))


def _make_collection(tmp_path: Path, names: list[str]) -> Path:
    collection = tmp_path / "collection"
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
    for name in names:
        (music / name).write_bytes(b"audio")
    return collection


def test_resolve_cleanup_config_defaults_disabled() -> None:
    cfg = resolve_cleanup_config({})
    assert cfg.enabled is False
    assert cfg.target_lufs == -14.0
    assert cfg.backup_originals is True
    assert cfg.trim_silence_trailing is True


def test_resolve_cleanup_config_accepts_overrides() -> None:
    cfg = resolve_cleanup_config(
        {
            "audio": {"bitrate": "256k"},
            "post_processing": {
                "suno_audio_cleanup": {
                    "enabled": True,
                    "max_workers": 4,
                    "loudnorm": {"I": -16, "TP": -2},
                    "eq": {"muddiness_gain_db": -3},
                }
            },
        }
    )
    assert cfg.enabled is True
    assert cfg.bitrate == "256k"
    assert cfg.target_lufs == -16.0
    assert cfg.true_peak == -2.0
    assert cfg.muddiness_gain_db == -3.0


def test_apply_cleanup_overrides_changes_only_explicit_track_values() -> None:
    defaults = CleanupConfig(enabled=True, muddiness_gain_db=-2.0, limiter=True)

    resolved = apply_cleanup_overrides(
        defaults,
        {"eq": {"muddiness_gain_db": -4.0}, "limiter": {"enabled": False}},
    )

    assert resolved.muddiness_gain_db == -4.0
    assert resolved.limiter is False
    assert resolved.harshness_gain_db == defaults.harshness_gain_db
    assert resolved.bitrate == defaults.bitrate


def test_trailing_silence_can_be_disabled_per_track() -> None:
    defaults = CleanupConfig(enabled=True)

    resolved = apply_cleanup_overrides(defaults, {"trim_silence": {"trailing": False}})

    assert resolved.trim_silence is True
    assert resolved.trim_silence_trailing is False


def test_resolve_cleanup_config_rejects_bad_shape() -> None:
    with pytest.raises(ConfigError):
        resolve_cleanup_config({"post_processing": {"suno_audio_cleanup": "yes"}})


@pytest.mark.parametrize("value", [0, -1, 9, 10**100, True, 1.5, "2", None])
def test_resolve_max_workers_rejects_invalid_config_value(value: object) -> None:
    with pytest.raises(ConfigError, match="max_workers"):
        resolve_max_workers(None, {"post_processing": {"suno_audio_cleanup": {"max_workers": value}}})


def test_resolve_max_workers_prefers_cli_value() -> None:
    invalid_lower_precedence = {"post_processing": {"suno_audio_cleanup": {"max_workers": "invalid"}}}
    assert resolve_max_workers(3, invalid_lower_precedence) == 3


def test_resolve_max_workers_uses_config_then_safe_default() -> None:
    configured = {"post_processing": {"suno_audio_cleanup": {"max_workers": 8}}}
    assert resolve_max_workers(None, configured) == 8
    assert resolve_max_workers(None, {}) == 2


@pytest.mark.parametrize("value", [0, 9, 10**100])
def test_parser_rejects_jobs_outside_safe_range_before_execution(value: int) -> None:
    with pytest.raises(SystemExit) as exc_info:
        mod.build_parser().parse_args(["apply", "collection", "--jobs", str(value)])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("value", [0, 9, 10**100, True])
def test_resolve_max_workers_rejects_invalid_programmatic_cli_value(value: object) -> None:
    with pytest.raises(mod.ValidationError, match="jobs"):
        resolve_max_workers(value, {})


@pytest.mark.parametrize(
    ("jobs", "configured", "error_type"),
    [(9, 2, mod.ValidationError), (None, 9, ConfigError)],
)
def test_cleanup_collection_rejects_unsafe_jobs_before_collecting_files(
    tmp_path: Path,
    monkeypatch,
    jobs: int | None,
    configured: int,
    error_type: type[Exception],
) -> None:
    collection = _make_collection(tmp_path, ["00.mp3"])
    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True, "max_workers": configured}}},
    )

    def fail_collect(_collection):
        raise AssertionError("files must not be collected before jobs validation")

    monkeypatch.setattr(mod, "collect_audio_files", fail_collect)

    with pytest.raises(error_type):
        cleanup_collection(collection, apply=True, jobs=jobs)


@pytest.mark.parametrize("value", [1, 8])
def test_parser_accepts_jobs_boundary_values(value: int) -> None:
    args = mod.build_parser().parse_args(["apply", "collection", "--jobs", str(value)])
    assert args.jobs == value


def test_main_passes_jobs_to_cleanup_collection(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(mod, "resolve_collection_dir", lambda value: Path(value))

    def fake_cleanup_collection(collection_dir, *, apply, jobs, force, quiet):
        captured.update(
            collection_dir=collection_dir,
            apply=apply,
            jobs=jobs,
            force=force,
            quiet=quiet,
        )
        return 0

    monkeypatch.setattr(mod, "cleanup_collection", fake_cleanup_collection)

    assert mod.main(["apply", "collection", "--jobs", "3"]) == 0
    assert captured == {
        "collection_dir": Path("collection"),
        "apply": True,
        "jobs": 3,
        "force": False,
        "quiet": False,
    }


def test_build_filter_contains_expected_ffmpeg_steps() -> None:
    filt = build_filter(CleanupConfig(enabled=True), duration_sec=120)
    leading = "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-50dB"
    assert filt.startswith(f"{leading},areverse,{leading},areverse,")
    assert "equalizer=f=350" in filt
    assert "equalizer=f=8000" in filt
    assert "dynaudnorm" in filt
    assert "alimiter=limit=0.95" in filt
    assert "loudnorm=I=-14" in filt
    assert "afade=t=out:st=117:d=3" in filt


def test_build_filter_trailing_opt_out_keeps_leading_trim() -> None:
    filt = build_filter(CleanupConfig(trim_silence_trailing=False))

    assert filt.startswith("silenceremove=start_periods=1:start_duration=0.2:start_threshold=-50dB,")
    assert "areverse" not in filt


def test_build_filter_disabled_trim_has_no_leading_or_trailing_trim() -> None:
    filt = build_filter(CleanupConfig(trim_silence=False))

    assert "silenceremove" not in filt
    assert "areverse" not in filt


def test_probe_trimmed_duration_reads_ffmpeg_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"audio")

    def fake_run(cmd, capture_output, text):
        assert cmd[cmd.index("-af") + 1].count("areverse") == 2
        assert ["-f", "null", "-"] == cmd[cmd.index("-f") : cmd.index("-f") + 3]
        return subprocess.CompletedProcess(cmd, 0, stdout="out_time_us=57000000\nprogress=end\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert probe_trimmed_duration(source, CleanupConfig()) == 57.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_trailing_trim_preserves_mid_track_silence(tmp_path: Path) -> None:
    source = tmp_path / "track.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=5",
            "-filter_complex",
            "[0:a][1:a][2:a][3:a]concat=n=4:v=0:a=1",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    cfg = CleanupConfig(
        backup_originals=False,
        adaptive_eq=False,
        volume_smoothing=False,
        limiter=False,
        loudnorm=False,
        tail_fade_guard=False,
    )

    assert process_file(source, cfg, apply=True, force=False, quiet=True) is True
    output_duration = mod.probe_duration(source)
    assert 6.0 < output_duration < 8.0


def test_collect_audio_files_uses_supported_extensions(tmp_path: Path) -> None:
    collection = _make_collection(tmp_path, ["02-b.wav", "01-a.mp3", "note.txt"])
    files = collect_audio_files(collection)
    assert [p.name for p in files] == ["01-a.mp3", "02-b.wav"]


def test_cleanup_collection_disabled_is_noop(tmp_path: Path, monkeypatch, capsys) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    monkeypatch.setattr(mod, "load_skill_config", lambda _skill: {})
    rc = cleanup_collection(collection, apply=False)
    assert rc == 0
    assert "enabled=false" in capsys.readouterr().out


def test_cleanup_collection_without_adjustments_preserves_default_config(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    observed: list[CleanupConfig] = []
    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )
    monkeypatch.setattr(
        mod,
        "process_file",
        lambda _path, cfg, **_kwargs: observed.append(cfg) or True,
    )

    assert cleanup_collection(collection, apply=True, jobs=1, quiet=True) == 0
    assert observed == [resolve_cleanup_config({"post_processing": {"suno_audio_cleanup": {"enabled": True}}})]


def test_cleanup_collection_applies_override_only_to_matching_filename(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3", "02-b.mp3"])
    paths = mod.CollectionPaths(collection)
    paths.docs_dir.mkdir()
    paths.audio_adjustments_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tracks": {"01-a.mp3": {"eq": {"muddiness_gain_db": -5.0}}},
            }
        ),
        encoding="utf-8",
    )
    observed: dict[str, CleanupConfig] = {}
    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def capture(path, cfg, **_kwargs):
        observed[path.name] = cfg
        return True

    monkeypatch.setattr(mod, "process_file", capture)

    assert cleanup_collection(collection, apply=True, jobs=1, quiet=True) == 0
    assert observed["01-a.mp3"].muddiness_gain_db == -5.0
    assert observed["02-b.mp3"].muddiness_gain_db == -2.0


def test_cleanup_collection_apply_uses_bounded_default_concurrency(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, [f"{index:02d}.mp3" for index in range(4)])
    lock = threading.Lock()
    two_running = threading.Event()
    active = 0
    peak = 0

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        nonlocal active, peak
        assert apply is True
        assert quiet is True
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_running.set()
        assert two_running.wait(timeout=1)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    assert cleanup_collection(collection, apply=True, quiet=True) == 0
    assert peak == 2


def test_cleanup_collection_caps_concurrency_at_explicit_upper_boundary(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, [f"{index:02d}.mp3" for index in range(16)])
    lock = threading.Lock()
    eight_running = threading.Event()
    active = 0
    peak = 0

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 8:
                eight_running.set()
        assert eight_running.wait(timeout=1)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    assert cleanup_collection(collection, apply=True, jobs=8, quiet=True) == 0
    assert peak == 8


def test_cleanup_collection_jobs_one_uses_legacy_main_thread_and_immediate_progress(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    collection = _make_collection(tmp_path, [f"{index:02d}.mp3" for index in range(3)])
    main_thread = threading.current_thread()
    observed_threads: list[threading.Thread] = []

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True, "max_workers": 3}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        observed_threads.append(threading.current_thread())
        assert quiet is False
        if path.name != "00.mp3":
            assert f"cleaned: {int(path.stem) - 1:02d}.mp3" in capsys.readouterr().out
        print(f"cleaned: {path.name}")
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    assert cleanup_collection(collection, apply=True, jobs=1) == 0
    assert observed_threads == [main_thread, main_thread, main_thread]


def test_cleanup_collection_jobs_one_preserves_original_exception_type_and_message(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["00.mp3", "01.mp3"])

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        raise ValueError("legacy exact failure")

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    with pytest.raises(ValueError, match="^legacy exact failure$"):
        cleanup_collection(collection, apply=True, jobs=1)


def test_cleanup_collection_jobs_one_prints_skip_progress_immediately(tmp_path: Path, monkeypatch, capsys) -> None:
    collection = _make_collection(tmp_path, ["00.mp3", "01.mp3"])
    music = collection / "02-Individual-music"
    backup = music / "originals-pre-cleanup"
    backup.mkdir()
    for name in ("00.mp3", "01.mp3"):
        (backup / name).write_bytes(b"original")

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    assert cleanup_collection(collection, apply=True, jobs=1) == 0
    assert capsys.readouterr().out.splitlines() == [
        "skip already cleaned: 00.mp3 (backup exists)",
        "skip already cleaned: 01.mp3 (backup exists)",
        "processed: 2 file(s), changed=0",
    ]


def test_cleanup_collection_stops_submitting_after_failure(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, [f"{index:02d}.mp3" for index in range(5)])
    both_started = threading.Event()
    started: list[str] = []
    lock = threading.Lock()

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        with lock:
            started.append(path.name)
            if len(started) == 2:
                both_started.set()
        assert both_started.wait(timeout=1)
        if path.name == "01.mp3":
            raise RuntimeError("intentional failure")
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    with pytest.raises(RuntimeError, match="01.mp3.*intentional failure"):
        cleanup_collection(collection, apply=True, quiet=True)

    assert started == ["00.mp3", "01.mp3"]


def test_cleanup_collection_cancellation_waits_for_started_work_and_does_not_submit_more(
    tmp_path: Path,
    monkeypatch,
) -> None:
    collection = _make_collection(tmp_path, [f"{index:02d}.mp3" for index in range(4)])
    both_started = threading.Event()
    release_peer = threading.Event()
    started: list[str] = []
    finished: list[str] = []
    lock = threading.Lock()

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        with lock:
            started.append(path.name)
            if len(started) == 2:
                both_started.set()
        assert both_started.wait(timeout=1)
        if path.name == "00.mp3":
            release_peer.set()
            raise KeyboardInterrupt
        assert release_peer.wait(timeout=1)
        finished.append(path.name)
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    with pytest.raises(KeyboardInterrupt):
        cleanup_collection(collection, apply=True, quiet=True)

    assert started == ["00.mp3", "01.mp3"]
    assert finished == ["01.mp3"]


def test_cleanup_collection_reports_results_in_filename_order(tmp_path: Path, monkeypatch, capsys) -> None:
    collection = _make_collection(tmp_path, ["03.mp3", "01.mp3", "02.mp3"])
    all_started = threading.Barrier(3)
    third_finished = threading.Event()
    second_finished = threading.Event()

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True, "max_workers": 3}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        all_started.wait(timeout=1)
        if path.name == "02.mp3":
            assert third_finished.wait(timeout=1)
            second_finished.set()
        elif path.name == "01.mp3":
            assert second_finished.wait(timeout=1)
        else:
            third_finished.set()
        return True

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    assert cleanup_collection(collection, apply=True) == 0
    output = capsys.readouterr().out
    assert output.index("cleaned: 01.mp3") < output.index("cleaned: 02.mp3") < output.index("cleaned: 03.mp3")


def test_cleanup_collection_aggregates_errors_in_filename_order(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["03.mp3", "01.mp3", "02.mp3"])
    all_started = threading.Barrier(3)
    third_finished = threading.Event()
    second_finished = threading.Event()

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True, "max_workers": 3}}},
    )

    def fake_process_file(path, cfg, *, apply, force, quiet):
        all_started.wait(timeout=1)
        if path.name == "02.mp3":
            assert third_finished.wait(timeout=1)
            second_finished.set()
        elif path.name == "01.mp3":
            assert second_finished.wait(timeout=1)
        else:
            third_finished.set()
        raise RuntimeError(f"failed {path.name}")

    monkeypatch.setattr(mod, "process_file", fake_process_file)

    with pytest.raises(RuntimeError) as exc_info:
        cleanup_collection(collection, apply=True, quiet=True)

    message = str(exc_info.value)
    assert message.index("01.mp3") < message.index("02.mp3") < message.index("03.mp3")


def test_cleanup_collection_plan_stays_sequential_without_ffmpeg_encode(tmp_path: Path, monkeypatch, capsys) -> None:
    collection = _make_collection(tmp_path, ["02.mp3", "01.mp3"])
    active = 0
    peak = 0

    monkeypatch.setattr(
        mod,
        "load_skill_config",
        lambda _skill: {"post_processing": {"suno_audio_cleanup": {"enabled": True}}},
    )
    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)

    def fail_encode(*args, **kwargs):
        raise AssertionError("plan must not execute ffmpeg encode")

    monkeypatch.setattr(mod.subprocess, "run", fail_encode)
    real_process_file = mod.process_file

    def observed_process_file(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            return real_process_file(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(mod, "process_file", observed_process_file)

    assert cleanup_collection(collection, apply=False, jobs=2) == 0
    output = capsys.readouterr().out
    assert peak == 1
    assert output.index("01.mp3") < output.index("02.mp3")


def test_process_file_apply_backs_up_original_and_replaces(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"
    assert changed is True
    assert backup.read_bytes() == b"audio"
    assert source.read_bytes() == b"cleaned"


def test_process_file_positions_fade_from_trimmed_duration(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    commands: list[list[str]] = []

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 120)
    monkeypatch.setattr(mod, "probe_trimmed_duration", lambda _path, _cfg: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    audio_filter = commands[0][commands[0].index("-af") + 1]
    assert "afade=t=out:st=57:d=3" in audio_filter
    assert "st=117" not in audio_filter


@pytest.mark.parametrize(
    ("filename", "expected_codec"),
    [("01-a.m4a", "aac"), ("01-a.wav", "pcm_s16le")],
)
def test_process_file_apply_uses_container_matching_codec(
    tmp_path: Path,
    monkeypatch,
    filename: str,
    expected_codec: str,
) -> None:
    collection = _make_collection(tmp_path, [filename])
    source = collection / "02-Individual-music" / filename
    captured_cmd: list[str] = []

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        captured_cmd.extend(cmd)
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert changed is True
    assert source.read_bytes() == b"cleaned"
    assert captured_cmd[captured_cmd.index("-c:a") + 1] == expected_codec


def test_process_file_ffmpeg_failure_preserves_original_and_removes_partial_output(tmp_path: Path, monkeypatch) -> None:
    """REQ-2729-04: ffmpeg 非0終了では元音源を変えず、temp/backup を残さない."""
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    tmp_output = source.parent / ".01-a.cleanup-tmp.mp3"
    backup = source.parent / "originals-pre-cleanup" / source.name

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fail_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"partial-output")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="decode failed")

    monkeypatch.setattr(mod.subprocess, "run", fail_run)

    with pytest.raises(RuntimeError, match=r"(?s)ffmpeg cleanup failed .*rc=1.*decode failed"):
        process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert source.read_bytes() == b"audio"
    assert not tmp_output.exists()
    assert not backup.exists()


def test_process_file_apply_without_backup_preserves_original_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(mod.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        process_file(
            source,
            CleanupConfig(enabled=True, backup_originals=False),
            apply=True,
            force=False,
            quiet=True,
        )

    assert source.read_bytes() == b"audio"
    assert not (source.parent / ".01-a.cleanup-tmp.mp3").exists()


def test_process_file_apply_with_backup_restores_original_when_final_replace_fails(tmp_path: Path, monkeypatch) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    tmp_output = source.parent / ".01-a.cleanup-tmp.mp3"
    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"

    monkeypatch.setattr(mod, "probe_duration", lambda _path: 60)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output, text):
        Path(cmd[-1]).write_bytes(b"cleaned")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    real_replace = mod.os.replace

    def fail_final_replace(src, dst):
        if Path(src) == tmp_output and Path(dst) == source:
            raise OSError("final replace failed")
        real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", fail_final_replace)

    with pytest.raises(OSError, match="final replace failed"):
        process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert source.read_bytes() == b"audio"
    assert not backup.exists()
    assert not tmp_output.exists()


def test_process_file_skips_when_backup_exists(tmp_path: Path) -> None:
    collection = _make_collection(tmp_path, ["01-a.mp3"])
    source = collection / "02-Individual-music" / "01-a.mp3"
    backup = collection / "02-Individual-music" / "originals-pre-cleanup" / "01-a.mp3"
    backup.parent.mkdir()
    backup.write_bytes(b"old")

    changed = process_file(source, CleanupConfig(enabled=True), apply=True, force=False, quiet=True)

    assert changed is False
    assert source.read_bytes() == b"audio"
