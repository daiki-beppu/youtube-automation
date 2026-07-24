from __future__ import annotations

import base64
import json

import pytest

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.scripts import suno_unattended_request
from youtube_automation.scripts.suno_unattended_request import (
    build_unattended_launch_url,
    build_unattended_request,
    main,
)


def decode_launch_url(url: str) -> dict[str, object]:
    encoded = url.split("#suno-helper-unattended=", 1)[1]
    padding = "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded + padding))


def test_build_request_matches_extension_wire_contract() -> None:
    request = build_unattended_request(
        base_url="http://rjn.localhost:7873/path/?token=ignored",
        collection_id="20260718-rjn-night-drive-collection",
        entry_indices=[0, 2],
        download_format="wav",
        max_entries=2,
        max_concurrent_generations=3,
        max_retries=1,
        request_id="scheduled-test",
    )
    assert request == {
        "version": 1,
        "requestId": "scheduled-test",
        "baseUrl": "http://rjn.localhost:7873/path",
        "collectionId": "20260718-rjn-night-drive-collection",
        "entryIndices": [0, 2],
        "downloadFormat": "wav",
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
        "download_format": "mp3",
        "max_entries": 1,
        "max_concurrent_generations": 1,
        "max_retries": 0,
        "request_id": "request",
    }
    arguments.update(override)
    with pytest.raises(ConfigError, match=message):
        build_unattended_request(**arguments)  # type: ignore[arg-type]


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
    assert request["downloadFormat"] == "mp3"
    assert request["limits"] == {
        "maxEntries": 10,
        "maxConcurrentGenerations": 3,
        "maxRetries": 2,
    }
