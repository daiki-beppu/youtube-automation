from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.infrastructure.media import fal_video_task_store as store


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    image = tmp_path / "main.png"
    image.write_bytes(b"original-image")
    return tmp_path / "loop.mp4", image


def _save(output: Path, image: Path, root: Path) -> Path:
    return store.save(
        output,
        image,
        request_id="request-1",
        response_url="https://queue.fal.run/result",
        status_url="https://queue.fal.run/status",
        cancel_url="https://queue.fal.run/cancel",
        submitted_at="2026-09-04T00:00:00Z",
        model="minimax/h3-max-turbo/image-to-video",
        prompt="slow clouds",
        duration_seconds=5,
        resolution="768P",
        prompt_expansion_mode="balanced",
        channel_root=root,
    )


def test_round_trip(paths: tuple[Path, Path], tmp_path: Path) -> None:
    output, image = paths
    saved = _save(output, image, tmp_path)

    assert saved.parent == tmp_path / "tmp" / "fal-video-tasks"
    assert store.load(output, channel_root=tmp_path) == json.loads(saved.read_text())


def test_load_rejects_symlink(paths: tuple[Path, Path], tmp_path: Path) -> None:
    output, _ = paths
    path = store.state_path(output, channel_root=tmp_path)
    path.parent.mkdir(parents=True)
    target = tmp_path / "target.json"
    target.write_text("{}")
    path.symlink_to(target)

    assert store.load(output, channel_root=tmp_path) is None
    assert not path.exists()
    assert target.exists()


@pytest.mark.parametrize("content", ["not-json", "[]"])
def test_load_discards_broken_state(paths: tuple[Path, Path], tmp_path: Path, content: str) -> None:
    output, _ = paths
    path = store.state_path(output, channel_root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(content)

    assert store.load(output, channel_root=tmp_path) is None
    assert not path.exists()


def test_load_discards_output_path_mismatch(paths: tuple[Path, Path], tmp_path: Path) -> None:
    output, image = paths
    path = _save(output, image, tmp_path)
    data = json.loads(path.read_text())
    data["output_path"] = str(tmp_path / "other.mp4")
    path.write_text(json.dumps(data))

    assert store.load(output, channel_root=tmp_path) is None
    assert not path.exists()


@pytest.mark.parametrize("missing", ["response_url", "status_url", "cancel_url"])
def test_load_discards_state_missing_queue_url(paths: tuple[Path, Path], tmp_path: Path, missing: str) -> None:
    output, image = paths
    path = _save(output, image, tmp_path)
    data = json.loads(path.read_text())
    del data[missing]
    path.write_text(json.dumps(data))

    assert store.load(output, channel_root=tmp_path) is None
    assert not path.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("input_image_sha256", "different"),
        ("prompt_sha256", "different"),
        ("model", "other/model"),
        ("duration_seconds", 10),
        ("resolution", "480P"),
        ("prompt_expansion_mode", "quality"),
    ],
)
def test_matches_returns_false_for_each_input_difference(
    paths: tuple[Path, Path], tmp_path: Path, key: str, value: object
) -> None:
    output, image = paths
    _save(output, image, tmp_path)
    state = store.load(output, channel_root=tmp_path)
    assert state is not None
    state[key] = value

    assert not store.matches(
        state,
        image,
        model="minimax/h3-max-turbo/image-to-video",
        prompt="slow clouds",
        duration_seconds=5,
        resolution="768P",
        prompt_expansion_mode="balanced",
    )


def test_clear_removes_state(paths: tuple[Path, Path], tmp_path: Path) -> None:
    output, image = paths
    path = _save(output, image, tmp_path)

    store.clear(output, channel_root=tmp_path)

    assert not path.exists()
