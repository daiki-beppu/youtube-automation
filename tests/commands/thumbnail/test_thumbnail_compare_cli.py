from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from youtube_automation.commands.thumbnail import compare_thumbnails as mod
from youtube_automation.core.errors import DocumentRenderError


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


def _write_thumbnail(tmp_path: Path, stage: str, collection: str, content: bytes = b"image") -> Path:
    thumbnail = tmp_path / "collections" / stage / collection / "10-assets" / "thumbnail.jpg"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(content)
    return thumbnail


def test_collect_channel_thumbnails_preserves_live_discovery(tmp_path: Path):
    comparer = _comparer(tmp_path)
    live = _write_thumbnail(tmp_path, "live", "20260101-x-rain-collection")

    assert comparer._collect_channel_thumbnails() == [live]


def test_collect_channel_thumbnails_includes_only_planning_final_thumbnail(tmp_path: Path):
    comparer = _comparer(tmp_path)
    planning = _write_thumbnail(tmp_path, "planning", "20260202-x-snow-collection")
    assets = planning.parent
    for excluded in ("thumbnail-v1.jpg", "planning-preview.png", "main.png", "main.jpg"):
        (assets / excluded).write_bytes(b"excluded")

    assert comparer._collect_channel_thumbnails() == [planning]


def test_collect_channel_thumbnails_orders_live_before_planning(tmp_path: Path):
    comparer = _comparer(tmp_path)
    planning = _write_thumbnail(tmp_path, "planning", "20260202-x-snow-collection")
    live = _write_thumbnail(tmp_path, "live", "20260101-x-rain-collection")

    assert comparer._collect_channel_thumbnails() == [live, planning]


def test_collect_channel_thumbnails_deduplicates_same_resolved_file(tmp_path: Path):
    comparer = _comparer(tmp_path)
    live = _write_thumbnail(tmp_path, "live", "20260101-x-rain-collection")
    planning = tmp_path / "collections" / "planning" / "20260101-x-rain-collection" / "10-assets" / "thumbnail.jpg"
    planning.parent.mkdir(parents=True)
    planning.symlink_to(live)

    assert comparer._collect_channel_thumbnails() == [live]


def test_live_and_planning_output_names_do_not_collide_or_overwrite(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    live = _write_thumbnail(tmp_path, "live", "20260101-x-rain-collection", b"live")
    _write_thumbnail(tmp_path, "planning", "20260101-x-rain-collection", b"planning")
    planning_output = comparer.channel_thumb_dir / "mine_planning_20260101-x-rain-collection.jpg"
    planning_output.parent.mkdir(parents=True)
    planning_output.write_bytes(b"existing")
    monkeypatch.setattr(mod, "ensure_benchmark_fresh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])
    resized = []
    comparer._resize_thumbnail = lambda source, _output: resized.append(source) or True

    comparer.collect_and_compare(no_open=True)

    live_output = comparer.channel_thumb_dir / "mine_rain.jpg"
    assert live_output.resolve() == live.resolve()
    assert planning_output.read_bytes() == b"existing"
    assert resized == [live_output, planning_output]


def test_download_thumbnail_writes_requested_destination(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    calls = []

    def open_url(url, *, timeout):
        calls.append((url, timeout))
        return BytesIO(b"image")

    monkeypatch.setattr(mod.urllib.request, "urlopen", open_url)

    assert comparer._download_thumbnail("https://example.test/thumb.jpg", destination) is True
    assert destination.read_bytes() == b"image"
    assert calls == [("https://example.test/thumb.jpg", mod.DOWNLOAD_TIMEOUT_SECONDS)]


def test_download_failure_returns_false_and_leaves_no_artifact(tmp_path: Path, monkeypatch):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    assert comparer._download_thumbnail("https://example.test/thumb.jpg", destination) is False
    assert not destination.exists()


def test_download_timeout_is_bounded_and_reports_target(tmp_path: Path, monkeypatch, caplog):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    calls = []

    class SlowResponse:
        def __init__(self):
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            self.read_count += 1
            if self.read_count == 1:
                return b"partial"
            raise TimeoutError("timed out")

    def timeout(url, *, timeout):
        calls.append((url, timeout))
        return SlowResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", timeout)

    assert comparer._download_thumbnail("https://example.test/slow.jpg", destination) is False
    assert calls == [("https://example.test/slow.jpg", mod.DOWNLOAD_TIMEOUT_SECONDS)]
    assert not destination.exists()
    assert not (tmp_path / ".download.jpg.part").exists()
    assert "https://example.test/slow.jpg" in caplog.text
    assert "タイムアウト" in caplog.text


def test_download_slow_drip_stops_at_wall_clock_deadline(tmp_path: Path, monkeypatch, caplog):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    ticks = iter((0.0, 5.0, 10.0, 16.0))

    class SlowDripResponse:
        read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read1(self, _size):
            self.read_count += 1
            return b"still downloading"

    response = SlowDripResponse()
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *_args, **_kwargs: response)

    assert comparer._download_thumbnail("https://example.test/drip.jpg", destination) is False
    assert response.read_count == 1
    assert not destination.exists()
    assert not (tmp_path / ".download.jpg.part").exists()
    assert "https://example.test/drip.jpg" in caplog.text
    assert "タイムアウト" in caplog.text


def test_download_url_error_wrapped_timeout_uses_timeout_diagnostic(tmp_path: Path, monkeypatch, caplog):
    comparer = _comparer(tmp_path)
    destination = tmp_path / "download.jpg"
    monkeypatch.setattr(
        mod.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(TimeoutError("socket timed out"))),
    )

    assert comparer._download_thumbnail("https://example.test/wrapped.jpg", destination) is False
    assert "ダウンロードタイムアウト" in caplog.text
    assert "ダウンロード失敗" not in caplog.text


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


def test_resize_timeout_is_bounded_and_removes_partial_output(tmp_path: Path, monkeypatch, caplog):
    comparer = _comparer(tmp_path)
    source = tmp_path / "source.jpg"
    output = tmp_path / "small.jpg"
    source.write_bytes(b"source")
    calls = []

    def timeout(command, **kwargs):
        calls.append((command, kwargs))
        output.write_bytes(b"partial")
        raise mod.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(mod.subprocess, "run", timeout)

    assert comparer._resize_thumbnail(source, output) is False
    assert calls[0][1]["timeout"] == mod.FFMPEG_TIMEOUT_SECONDS
    assert not output.exists()
    assert source.name in caplog.text
    assert "タイムアウト" in caplog.text


def test_collect_reports_refresh_progress_before_refresh_starts(tmp_path: Path, monkeypatch, capsys):
    comparer = _comparer(tmp_path)

    def refresh(*_args, **_kwargs):
        assert "ベンチマーク鮮度確認" in capsys.readouterr().out

    monkeypatch.setattr(mod, "ensure_benchmark_fresh", refresh)
    monkeypatch.setattr(mod, "load_benchmark_videos", lambda *_args, **_kwargs: [])
    comparer._collect_channel_thumbnails = lambda: []

    comparer.collect_and_compare(no_open=True)


def test_collect_continues_with_json_when_benchmark_report_pair_is_stale(tmp_path: Path, monkeypatch, caplog):
    comparer = _comparer(tmp_path)
    loaded = []
    monkeypatch.setattr(
        mod,
        "ensure_benchmark_fresh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DocumentRenderError("structured document JSON と HTML が対応していません")
        ),
    )
    monkeypatch.setattr(
        mod,
        "load_benchmark_videos",
        lambda *_args, **_kwargs: loaded.append(True) or [],
    )
    comparer._collect_channel_thumbnails = lambda: []

    comparer.collect_and_compare(no_open=True)

    assert loaded == [True]
    assert "stale HTML は使用せず" in caplog.text
    assert "uv run yt-document-render --fix --all ." in caplog.text


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
