"""Media subprocess boundary の画像圧縮結果契約テスト。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.infrastructure import process


def _set_output_path(monkeypatch: pytest.MonkeyPatch, output: Path) -> None:
    monkeypatch.setattr(
        process.tempfile,
        "NamedTemporaryFile",
        lambda **_kwargs: SimpleNamespace(name=str(output)),
    )


def test_compress_image_tries_qualities_in_order_until_candidate_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "compressed.jpg"
    _set_output_path(monkeypatch, output)
    qualities: list[int] = []

    def fake_run(command, **_kwargs):
        quality = int(command[command.index("-qscale:v") + 1])
        qualities.append(quality)
        output.write_bytes(b"x" * (101 if quality == 2 else 100))

    monkeypatch.setattr(process.subprocess, "run", fake_run)

    result = process.compress_image(source, [2, 5, 9], max_bytes=100)

    assert result == output
    assert output.stat().st_size == 100
    assert qualities == [2, 5]


def test_compress_image_returns_first_candidate_below_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "compressed.jpg"
    _set_output_path(monkeypatch, output)
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        output.write_bytes(b"small")

    monkeypatch.setattr(process.subprocess, "run", fake_run)

    assert process.compress_image(source, [3, 7], max_bytes=100) == output
    assert len(calls) == 1
    assert calls[0] == [
        "ffmpeg",
        "-y",
        "-i",
        str(source.resolve()),
        "-qscale:v",
        "3",
        str(output),
    ]


def test_compress_image_removes_oversized_temp_and_returns_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "compressed.jpg"
    _set_output_path(monkeypatch, output)
    qualities: list[int] = []

    def fake_run(command, **_kwargs):
        qualities.append(int(command[command.index("-qscale:v") + 1]))
        output.write_bytes(b"oversized")

    monkeypatch.setattr(process.subprocess, "run", fake_run)

    result = process.compress_image(source, [2, 4, 6], max_bytes=3)

    assert result == source
    assert source.read_bytes() == b"source"
    assert qualities == [2, 4, 6]
    assert not output.exists()
