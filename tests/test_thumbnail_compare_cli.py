from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.commands.thumbnail import compare_thumbnails as mod


def _comparer(tmp_path: Path) -> mod.ThumbnailComparer:
    comparer = object.__new__(mod.ThumbnailComparer)
    comparer.config = SimpleNamespace(meta=SimpleNamespace(channel_short="mine"))
    comparer.channel_dir = tmp_path
    comparer.data_dir = tmp_path / "data"
    comparer.min_views = 100
    comparer.competitor_slug = None
    comparer.channel_slug = "mine"
    comparer.compare_dir = comparer.data_dir / "thumbnail_compare"
    comparer.benchmark_dir = comparer.compare_dir / "benchmark"
    comparer.channel_thumb_dir = comparer.compare_dir / "mine"
    comparer.small_dir = comparer.compare_dir / "small"
    return comparer


def test_download_thumbnail_writes_requested_destination(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    calls = []

    def retrieve(url, output):
        calls.append((url, output))
        Path(output).write_bytes(b"image")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", retrieve)

    assert comparer._download_thumbnail("https://example.test/thumb.jpg", destination) is True
    assert destination.read_bytes() == b"image"
    assert calls == [("https://example.test/thumb.jpg", str(destination))]


def test_download_failure_returns_false_and_leaves_no_artifact(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    monkeypatch.setattr(
        mod.urllib.request,
        "urlretrieve",
        lambda *_args: (_ for _ in ()).throw(OSError("offline")),
    )

    assert comparer._download_thumbnail("https://example.test/thumb.jpg", destination) is False
    assert not destination.exists()


def test_resize_invokes_ffmpeg_with_fixed_mobile_dimensions(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    source = tmp_path / "source.jpg"
    output = tmp_path / "small.jpg"
    source.write_bytes(b"source")
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    assert comparer._resize_thumbnail(source, output) is True
    command, kwargs = calls[0]
    assert f"scale={mod.SMALL_WIDTH}:{mod.SMALL_HEIGHT}" in command
    assert command[-1] == str(output.resolve())
    assert kwargs["check"] is True


@pytest.mark.parametrize("error", [FileNotFoundError("ffmpeg"), mod.subprocess.CalledProcessError(1, ["ffmpeg"])])
def test_resize_failures_return_false(tmp_path: Path, monkeypatch, error):
    comparer = _comparer(tmp_path)
    monkeypatch.setattr(mod.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    assert comparer._resize_thumbnail(tmp_path / "source.jpg", tmp_path / "small.jpg") is False


def test_collect_continues_after_download_and_resize_failures_and_opens_small_dir(tmp_path: Path, monkeypatch, capsys):
    comparer = _comparer(tmp_path)
    thumb = tmp_path / "collections" / "live" / "20260101-x-rain-collection" / "10-assets" / "thumbnail.jpg"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"mine")
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mod,
        "load_benchmark_videos",
        lambda *_args, **_kwargs: [
            {
                "views": 10_000,
                "channel_slug": "other",
                "video_id": "bad",
                "thumbnail_url": "https://bad",
                "title": "bad",
            },
            {
                "views": 20_000,
                "channel_slug": "other",
                "video_id": "good",
                "thumbnail_url": "https://good",
                "title": "good",
            },
        ],
    )
    comparer._collect_channel_thumbnails = lambda: [thumb]
    comparer._download_thumbnail = lambda url, output: url.endswith("good")
    comparer._resize_thumbnail = lambda source, output: "mine_" in source.name
    opened = []
    monkeypatch.setattr(mod.subprocess, "run", lambda command, **_kwargs: opened.append(command))

    comparer.collect_and_compare(small_only=True)

    assert len(opened) == 1
    assert opened[0] == ["open", str(comparer.small_dir.resolve())]
    assert "ベンチマーク 1枚" in capsys.readouterr().out
    assert (comparer.channel_thumb_dir / "mine_rain.jpg").exists()


def test_collect_no_open_never_launches_platform_opener(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])
    comparer._collect_channel_thumbnails = lambda: []
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    comparer.collect_and_compare(no_open=True)

    assert calls == []
