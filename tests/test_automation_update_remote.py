from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.commands.system import automation_update_remote
from youtube_automation.infrastructure.errors import ConfigError


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_github_api_get_builds_expected_request_and_token_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("GH_TOKEN", "fallback-secret")
    captured: dict[str, object] = {}

    def fake_open(request, *, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return _Response(json.dumps({"sha": "abc"}).encode())

    with patch.object(automation_update_remote.urllib.request, "urlopen", side_effect=fake_open):
        result = automation_update_remote._github_api_get("repos/owner/repo/commits/main")

    assert result == {"sha": "abc"}
    assert captured == {
        "url": "https://api.github.com/repos/owner/repo/commits/main",
        "headers": {
            "accept": "application/vnd.github+json",
            "user-agent": "yt-automation-update",
            "authorization": "Bearer github-secret",
        },
        "timeout": 30,
    }


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("offline"),
        TimeoutError("slow"),
    ],
)
def test_github_api_get_wraps_transport_failures(failure: BaseException) -> None:
    with patch.object(automation_update_remote.urllib.request, "urlopen", side_effect=failure):
        with pytest.raises(ConfigError, match=r"https://api\.github\.com/repos/owner/repo") as exc_info:
            automation_update_remote._github_api_get("repos/owner/repo")

    assert exc_info.value.__cause__ is failure


def test_github_api_get_wraps_invalid_json() -> None:
    with patch.object(
        automation_update_remote.urllib.request,
        "urlopen",
        return_value=_Response(b"{broken"),
    ):
        with pytest.raises(ConfigError, match="GitHub API") as exc_info:
            automation_update_remote._github_api_get("repos/owner/repo")

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("package = {}\n", None),
        ('[[package]]\nname = "other"\n', None),
        ('[[package]]\nname = "youtube-channels-automation"\nsource = "registry"\n', None),
    ],
)
def test_locked_git_sha_handles_valid_non_matching_shapes(tmp_path: Path, body: str, expected: str | None) -> None:
    (tmp_path / "uv.lock").write_text(body, encoding="utf-8")

    assert automation_update_remote._locked_git_sha(tmp_path) == expected


def test_locked_git_sha_rejects_malformed_toml(tmp_path: Path) -> None:
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text("[[package]\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="uv.lock を読み込めません") as exc_info:
        automation_update_remote._locked_git_sha(tmp_path)

    assert exc_info.value.__cause__ is not None
