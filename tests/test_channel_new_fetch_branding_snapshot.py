import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".claude/skills/channel-new/references/fetch_branding_snapshot.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_branding_snapshot", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeRequest:
    def __init__(self, result: object):
        self.result = result

    def execute(self) -> dict:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeChannels:
    def __init__(self, responses: dict[str, object], calls: list[dict[str, str]]):
        self.responses = responses
        self.calls = calls

    def list(self, *, part: str, id: str) -> FakeRequest:  # noqa: A002
        self.calls.append({"part": part, "id": id})
        return FakeRequest(self.responses[id])


class FakeYouTube:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[dict[str, str]] = []

    def channels(self) -> FakeChannels:
        return FakeChannels(self.responses, self.calls)


def _patch_youtube_handler(monkeypatch: pytest.MonkeyPatch, module, youtube: FakeYouTube) -> None:
    monkeypatch.setattr(
        module,
        "YouTubeOAuthHandler",
        lambda: SimpleNamespace(get_youtube_service=lambda: youtube),
    )


def test_fetch_branding_snapshot_writes_untrusted_json_for_multiple_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    youtube = FakeYouTube(
        {
            "UC_A": {"items": [{"id": "UC_A", "snippet": {"description": "A"}}]},
            "UC_B": {"items": [{"id": "UC_B", "brandingSettings": {"channel": {"keywords": "b"}}}]},
        }
    )
    _patch_youtube_handler(monkeypatch, module, youtube)

    output = tmp_path / "nested" / "competitor-branding-snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_branding_snapshot.py",
            "--channel-id",
            "UC_A",
            "--channel-id",
            "UC_B",
            "--output",
            str(output),
        ],
    )

    module.main()

    assert youtube.calls == [
        {"part": "snippet,brandingSettings,localizations", "id": "UC_A"},
        {"part": "snippet,brandingSettings,localizations", "id": "UC_B"},
    ]
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "untrusted_data": True,
        "source": "youtube.channels.list(part=snippet,brandingSettings,localizations)",
        "items": [
            {"id": "UC_A", "snippet": {"description": "A"}},
            {"id": "UC_B", "brandingSettings": {"channel": {"keywords": "b"}}},
        ],
    }


def test_fetch_branding_snapshot_empty_items_fails_without_writing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    youtube = FakeYouTube({"UC_MISSING": {"items": []}})
    _patch_youtube_handler(monkeypatch, module, youtube)
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_branding_snapshot.py",
            "--channel-id",
            "UC_MISSING",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(ValidationError, match="Expected exactly one YouTube channel"):
        module.main()

    assert not output.exists()


def test_fetch_branding_snapshot_id_mismatch_fails_without_writing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    youtube = FakeYouTube({"UC_EXPECTED": {"items": [{"id": "UC_OTHER"}]}})
    _patch_youtube_handler(monkeypatch, module, youtube)
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_branding_snapshot.py",
            "--channel-id",
            "UC_EXPECTED",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(ValidationError, match="id mismatch"):
        module.main()

    assert not output.exists()


def test_fetch_branding_snapshot_api_exception_fails_without_writing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    youtube = FakeYouTube({"UC_A": YouTubeAPIError("quota")})
    _patch_youtube_handler(monkeypatch, module, youtube)
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_branding_snapshot.py",
            "--channel-id",
            "UC_A",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(YouTubeAPIError, match="quota"):
        module.main()

    assert not output.exists()


def test_fetch_branding_snapshot_partial_failure_does_not_write_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    youtube = FakeYouTube(
        {
            "UC_A": {"items": [{"id": "UC_A"}]},
            "UC_MISSING": {"items": []},
        }
    )
    _patch_youtube_handler(monkeypatch, module, youtube)
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_branding_snapshot.py",
            "--channel-id",
            "UC_A",
            "--channel-id",
            "UC_MISSING",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(ValidationError):
        module.main()

    assert not output.exists()
