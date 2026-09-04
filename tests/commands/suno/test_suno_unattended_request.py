from __future__ import annotations

import base64
import io
import json
from urllib.error import URLError

import pytest

from youtube_automation.commands.suno import suno_unattended_request
from youtube_automation.commands.suno.suno_unattended_request import (
    build_unattended_launch_url,
    build_unattended_request,
    main,
    register_unattended_request,
)
from youtube_automation.core.errors import ConfigError


def decode_launch_url(url: str) -> dict[str, object]:
    encoded = url.split("#suno-helper-unattended=", 1)[1]
    padding = "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded + padding))


def test_build_request_matches_extension_wire_contract() -> None:
    request = build_unattended_request(
        base_url="http://rjn.localhost:7873/path/?token=ignored",
        collection_id="20260718-rjn-night-drive-collection",
        entry_indices=[0, 2],
        max_entries=2,
        max_concurrent_generations=3,
        max_retries=1,
        skip_download=True,
        request_id="scheduled-test",
    )
    assert request == {
        "version": 1,
        "requestId": "scheduled-test",
        "baseUrl": "http://rjn.localhost:7873/path",
        "collectionId": "20260718-rjn-night-drive-collection",
        "entryIndices": [0, 2],
        "skipDownload": True,
        "limits": {
            "maxEntries": 2,
            "maxConcurrentGenerations": 3,
            "maxRetries": 1,
        },
    }
    assert decode_launch_url(
        build_unattended_launch_url(
            base_url=str(request["baseUrl"]),
            nonce="abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890",
        )
    ) == {
        "version": 1,
        "baseUrl": "http://rjn.localhost:7873/path",
        "nonce": "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890",
    }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"base_url": "https://example.com"}, "loopback"),
        ({"entry_indices": [1, 1]}, "重複"),
        ({"max_entries": 0}, "1..100"),
        ({"max_concurrent_generations": 11}, "1..10"),
        ({"max_retries": 6}, "0..5"),
    ],
)
def test_rejects_unsafe_or_unbounded_requests(override: dict[str, object], message: str) -> None:
    arguments: dict[str, object] = {
        "base_url": "http://localhost:7873",
        "collection_id": "collection",
        "entry_indices": [0],
        "max_entries": 1,
        "max_concurrent_generations": 1,
        "max_retries": 0,
        "skip_download": False,
        "request_id": "request",
    }
    arguments.update(override)
    with pytest.raises(ConfigError, match=message):
        build_unattended_request(**arguments)  # type: ignore[arg-type]


def test_register_unattended_request_posts_json_and_returns_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-2729-05: localhost 登録の HTTP method/body/timeout と成功 response を固定する."""
    captured: dict[str, object] = {}
    expected_nonce = "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890"

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return io.BytesIO(json.dumps({"nonce": expected_nonce}).encode())

    monkeypatch.setattr(suno_unattended_request, "urlopen", fake_urlopen)
    request_payload = {"version": 1, "collectionId": "collection"}

    nonce = register_unattended_request("http://localhost:7873/path/", request_payload)

    request = captured["request"]
    assert request.full_url == "http://localhost:7873/path/unattended/requests"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == request_payload
    assert captured["timeout"] == 10
    assert nonce == expected_nonce


def test_register_unattended_request_wraps_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-2729-06: localhost 通信失敗は ConfigError として原因付きで公開する."""

    def fail_urlopen(_request, timeout):
        assert timeout == 10
        raise URLError("connection refused")

    monkeypatch.setattr(suno_unattended_request, "urlopen", fail_urlopen)

    with pytest.raises(ConfigError, match="登録できません.*connection refused"):
        register_unattended_request("http://localhost:7873", {"version": 1})


@pytest.mark.parametrize("payload", [[], {}, {"nonce": ""}, {"nonce": 123}])
def test_register_unattended_request_rejects_invalid_nonce_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    """REQ-2729-07: response shape/nonce が不正なら成功扱いしない."""
    monkeypatch.setattr(
        suno_unattended_request,
        "urlopen",
        lambda _request, timeout: io.BytesIO(json.dumps(payload).encode()) if timeout == 10 else None,
    )

    with pytest.raises(ConfigError, match="有効な unattended nonce"):
        register_unattended_request("http://localhost:7873", {"version": 1})


def test_cli_uses_skill_config_defaults(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        suno_unattended_request,
        "register_unattended_request",
        lambda _base_url, request: captured.append(request) or "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890",
    )
    assert (
        main(
            [
                "--base-url",
                "http://localhost:7873",
                "--collection-id",
                "collection",
                "--request-id",
                "scheduled-test",
            ]
        )
        == 0
    )
    envelope = decode_launch_url(capsys.readouterr().out.strip())
    assert envelope["nonce"] == "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890"
    request = captured[0]
    assert "downloadFormat" not in request
    assert request["skipDownload"] is False
    assert request["limits"] == {
        "maxEntries": 10,
        "maxConcurrentGenerations": 3,
        "maxRetries": 2,
    }


def test_cli_skip_download_sets_wire_contract(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        suno_unattended_request,
        "register_unattended_request",
        lambda _base_url, request: captured.append(request) or "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890",
    )

    assert (
        main(
            [
                "--base-url",
                "http://localhost:7873",
                "--collection-id",
                "collection",
                "--request-id",
                "scheduled-test",
                "--skip-download",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert captured[0]["skipDownload"] is True
