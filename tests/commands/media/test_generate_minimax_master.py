"""``yt-generate-minimax-master`` の契約テスト。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from youtube_automation.commands.media import generate_minimax_master
from youtube_automation.core.errors import ConfigError, GeneratorError, ValidationError


@pytest.fixture(autouse=True)
def _isolate_channel_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    return collection


def _configs(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(skill: str, **_kwargs: object) -> dict[str, object]:
        if skill == "music.generate":
            return {
                "minimax": {
                    "model": "music-3.0",
                    "duration_padding_min": 0,
                    "request_timeout_sec": 360,
                }
            }
        if skill == "masterup":
            return {"audio": {"crossfade_duration": 2.5, "bitrate": "256k"}}
        raise AssertionError(f"unexpected skill config: {skill}")

    monkeypatch.setattr(generate_minimax_master, "load_skill_config", load)


def _response(audio: bytes = b"MINIMAX_MP3") -> dict[str, object]:
    return {
        "data": {"audio": audio.hex(), "status": 2},
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "trace_id": "trace-1",
    }


def _lyrics(path: Path, lyrics: str = "[Intro]\n夜が明ける\n\n[Verse 1]\n静かな朝\n\n[Chorus]\n歩き出そう") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{"name": "夜明け — Dawn", "lyrics": lyrics}], ensure_ascii=False),
        encoding="utf-8",
    )


def test_extract_audio_accepts_official_completed_hex_response() -> None:
    assert generate_minimax_master._extract_audio(_response(b"audio")) == b"audio"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"base_resp": {"status_code": 0}, "data": []},
        {"base_resp": {"status_code": 0}, "data": {"status": 1, "audio": "00"}},
        {"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": "not-hex"}},
        {"base_resp": {"status_code": 1004}, "data": {"status": 2, "audio": "00"}},
    ],
)
def test_extract_audio_rejects_invalid_or_failed_response(body: dict[str, object]) -> None:
    with pytest.raises(GeneratorError):
        generate_minimax_master._extract_audio(body)


def test_segment_count_uses_five_minute_generation_boundary() -> None:
    assert generate_minimax_master._resolve_segment_count(60, 0) == 12
    assert generate_minimax_master._resolve_segment_count(61, 0) == 13


@pytest.mark.parametrize("target,padding", [(0, 0), (-1, 0), (60, -1)])
def test_segment_count_rejects_invalid_duration(target: float, padding: float) -> None:
    with pytest.raises(ValidationError):
        generate_minimax_master._resolve_segment_count(target, padding)


def test_run_generates_segments_logs_each_song_and_combines_existing_master_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    _configs(monkeypatch)
    request_json = Mock(return_value=_response())
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)
    log_generation = Mock()
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "log_generation", log_generation)
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "print_last_report", Mock())
    master = collection / "01-master" / "master.mp3"
    generate_master = Mock(return_value=master)
    monkeypatch.setattr(generate_minimax_master.generate_master, "generate_master", generate_master)

    result = generate_minimax_master.main(
        [
            "--prompt",
            "ambient piano, rain",
            "--name",
            "rain",
            "--target-duration",
            "9",
            "--collection",
            str(collection),
        ]
    )

    assert result == 0
    assert request_json.call_count == 2
    for call in request_json.call_args_list:
        assert call.args == (
            "/v1/music_generation",
            {
                "model": "music-3.0",
                "prompt": "ambient piano, rain",
                "is_instrumental": True,
                "output_format": "hex",
                "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
            },
        )
        assert call.kwargs == {"timeout": 360.0}
    music_dir = collection / "02-Individual-music"
    assert (music_dir / "01_rain.mp3").read_bytes() == b"MINIMAX_MP3"
    assert (music_dir / "02_rain.mp3").read_bytes() == b"MINIMAX_MP3"
    assert log_generation.call_count == 2
    for call in log_generation.call_args_list:
        assert call.args == ("audio",)
        assert call.kwargs["model"] == "music-3.0"
        assert call.kwargs["quantity"] == 1
        assert call.kwargs["unit"] == "song"
    generate_master.assert_called_once_with(collection, 2.5, "256k")


def test_vocal_run_sends_verified_lyrics_once_and_writes_master_without_segment_combination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    lyrics_path = collection / "20-documentation/suno-lyrics.json"
    lyrics = "[Intro]\n夜が明ける\n\n[Verse 1]\n静かな朝\n\n[Chorus]\n歩き出そう"
    _lyrics(lyrics_path, lyrics)
    _configs(monkeypatch)
    request_json = Mock(return_value=_response(b"VOCAL_MP3"))
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)
    log_generation = Mock()
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "log_generation", log_generation)
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "print_last_report", Mock())
    combine = Mock(side_effect=AssertionError("vocal generation must not combine segments"))
    monkeypatch.setattr(generate_minimax_master.generate_master, "generate_master", combine)

    result = generate_minimax_master.main(
        [
            "--prompt",
            "Japanese indie folk, hopeful dawn",
            "--lyrics",
            "20-documentation/suno-lyrics.json",
            "--name",
            "dawn",
            "--collection",
            str(collection),
        ]
    )

    assert result == 0
    request_json.assert_called_once_with(
        "/v1/music_generation",
        {
            "model": "music-3.0",
            "prompt": "Japanese indie folk, hopeful dawn",
            "lyrics": lyrics,
            "is_instrumental": False,
            "output_format": "hex",
            "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        },
        timeout=360.0,
    )
    assert (collection / "01-master/master.mp3").read_bytes() == b"VOCAL_MP3"
    assert list((collection / "02-Individual-music").iterdir()) == []
    combine.assert_not_called()
    log_generation.assert_called_once()
    assert log_generation.call_args.args == ("audio",)
    assert log_generation.call_args.kwargs["quantity"] == 1
    assert log_generation.call_args.kwargs["unit"] == "song"
    assert log_generation.call_args.kwargs["metadata"]["mode"] == "vocal"


@pytest.mark.parametrize(
    "fixture",
    [
        "missing",
        "multiple",
        "empty",
        "too_long",
    ],
)
def test_vocal_input_failure_stops_before_paid_api_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: str,
) -> None:
    collection = _collection(tmp_path)
    lyrics_path = collection / "20-documentation/suno-lyrics.json"
    if fixture == "multiple":
        lyrics_path.parent.mkdir(parents=True)
        lyrics_path.write_text(
            json.dumps(
                [
                    {"name": "one", "lyrics": "[Verse]\none"},
                    {"name": "two", "lyrics": "[Verse]\ntwo"},
                ]
            ),
            encoding="utf-8",
        )
    elif fixture == "empty":
        _lyrics(lyrics_path, "")
    elif fixture == "too_long":
        _lyrics(lyrics_path, "[Verse]\n" + "a" * 3493)
    _configs(monkeypatch)
    request_json = Mock(side_effect=AssertionError("invalid lyrics must not spend credits"))
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)

    result = generate_minimax_master.main(
        [
            "--prompt",
            "vocal song",
            "--lyrics",
            "20-documentation/suno-lyrics.json",
            "--name",
            "song",
            "--collection",
            str(collection),
        ]
    )

    assert result != 0
    request_json.assert_not_called()
    assert not (collection / "01-master/master.mp3").exists()


def test_vocal_resume_skips_api_and_duplicate_cost_when_master_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    _lyrics(collection / "20-documentation/suno-lyrics.json")
    master = collection / "01-master/master.mp3"
    master.write_bytes(b"existing-vocal")
    _configs(monkeypatch)
    request_json = Mock(side_effect=AssertionError("completed vocal must not regenerate"))
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)
    log_generation = Mock()
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "log_generation", log_generation)
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "print_last_report", Mock())

    assert (
        generate_minimax_master.main(
            [
                "--prompt",
                "vocal song",
                "--lyrics",
                "20-documentation/suno-lyrics.json",
                "--name",
                "song",
                "--collection",
                str(collection),
            ]
        )
        == 0
    )

    assert master.read_bytes() == b"existing-vocal"
    request_json.assert_not_called()
    log_generation.assert_not_called()


def test_vocal_api_failure_keeps_master_absent_and_does_not_log_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    _lyrics(collection / "20-documentation/suno-lyrics.json")
    _configs(monkeypatch)
    request_json = Mock(side_effect=GeneratorError("safe upstream failure"))
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)
    log_generation = Mock()
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "log_generation", log_generation)

    result = generate_minimax_master.main(
        [
            "--prompt",
            "vocal song",
            "--lyrics",
            "20-documentation/suno-lyrics.json",
            "--name",
            "song",
            "--max-retries",
            "0",
            "--collection",
            str(collection),
        ]
    )

    assert result != 0
    request_json.assert_called_once()
    log_generation.assert_not_called()
    assert not (collection / "01-master/master.mp3").exists()


def test_vocal_prompt_limit_is_checked_before_paid_api_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    _lyrics(collection / "20-documentation/suno-lyrics.json")
    _configs(monkeypatch)
    request_json = Mock(side_effect=AssertionError("oversized prompt must not spend credits"))
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)

    result = generate_minimax_master.main(
        [
            "--prompt",
            "p" * 2001,
            "--lyrics",
            "20-documentation/suno-lyrics.json",
            "--name",
            "song",
            "--collection",
            str(collection),
        ]
    )

    assert result != 0
    request_json.assert_not_called()
    assert not (collection / "01-master/master.mp3").exists()


def test_resume_skips_existing_segment_without_api_or_duplicate_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _collection(tmp_path)
    existing = collection / "02-Individual-music" / "01_resume.mp3"
    existing.write_bytes(b"existing")
    _configs(monkeypatch)
    request_json = Mock(return_value=_response())
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", request_json)
    log_generation = Mock()
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "log_generation", log_generation)
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(
        generate_minimax_master.generate_master,
        "generate_master",
        Mock(return_value=collection / "01-master/master.mp3"),
    )

    assert (
        generate_minimax_master.main(
            [
                "--prompt",
                "ambient",
                "--name",
                "resume",
                "--target-duration",
                "9",
                "--collection",
                str(collection),
            ]
        )
        == 0
    )

    assert existing.read_bytes() == b"existing"
    request_json.assert_called_once()
    log_generation.assert_called_once()


def test_paid_audio_is_recovered_when_segment_write_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segment = tmp_path / "segment.mp3"
    monkeypatch.setattr(generate_minimax_master, "_write_audio_file", Mock(side_effect=KeyboardInterrupt))
    recovered = tmp_path / "tmp/minimax-recovered/recovered.mp3"
    persist = Mock(return_value=recovered)
    monkeypatch.setattr(generate_minimax_master, "persist_recovered_audio", persist)

    with pytest.raises(KeyboardInterrupt):
        generate_minimax_master._persist_segment(b"paid-audio", segment)

    persist.assert_called_once_with(b"paid-audio")


def test_recovery_path_is_content_addressed_beneath_channel_tmp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_minimax_master, "channel_dir", lambda: tmp_path)

    first = generate_minimax_master.persist_recovered_audio(b"same-audio")
    second = generate_minimax_master.persist_recovered_audio(b"same-audio")

    assert first == second
    assert first.parent == tmp_path / "tmp/minimax-recovered"
    assert first.read_bytes() == b"same-audio"


def test_help_uses_canonical_harness_before_runtime_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = Mock(side_effect=AssertionError("runtime must not resolve"))
    monkeypatch.setattr(generate_minimax_master, "load_skill_config", forbidden)
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", forbidden)

    with pytest.raises(SystemExit, match="0"):
        generate_minimax_master.main(["--help"])

    forbidden.assert_not_called()


def test_cost_log_is_persisted_as_song_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _collection(tmp_path)
    _configs(monkeypatch)
    monkeypatch.setattr(generate_minimax_master.minimax_client, "request_json", Mock(return_value=_response()))
    monkeypatch.setattr(generate_minimax_master.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(
        generate_minimax_master.generate_master,
        "generate_master",
        Mock(return_value=collection / "01-master/master.mp3"),
    )

    assert (
        generate_minimax_master.main(
            [
                "--prompt",
                "ambient",
                "--name",
                "cost",
                "--target-duration",
                "4",
                "--collection",
                str(collection),
            ]
        )
        == 0
    )

    costs = json.loads((tmp_path / "data/audio_costs.json").read_text(encoding="utf-8"))
    assert len(costs) == 1
    assert costs[0]["unit"] == "song"


def test_target_duration_falls_back_to_channel_audio_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_minimax_master,
        "load_config",
        Mock(return_value=SimpleNamespace(audio=SimpleNamespace(target_duration_min=90))),
    )

    assert generate_minimax_master._resolve_target_duration(None) == 90.0


def test_minimax_config_rejects_non_object_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate_minimax_master, "load_skill_config", Mock(return_value={"minimax": []}))

    with pytest.raises(ConfigError, match="music.generate.minimax"):
        generate_minimax_master._minimax_config()
