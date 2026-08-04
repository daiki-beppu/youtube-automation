"""HTTP error から domain error へ変換する payload 境界テスト。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from youtube_automation.infrastructure.errors import YouTubeAPIError


def _http_error(*, content: object, status: object = 403) -> SimpleNamespace:
    return SimpleNamespace(resp=SimpleNamespace(status=status), content=content)


def test_from_http_error_decodes_bytes_and_extracts_nested_reason() -> None:
    error = _http_error(
        status="429",
        content=json.dumps(
            {
                "error": {
                    "errors": [
                        {"message": "ignored"},
                        {"reason": "quotaExceeded"},
                    ]
                }
            }
        ).encode(),
    )

    converted = YouTubeAPIError.from_http_error(error, "upload failed")

    assert converted.status_code == 429
    assert converted.reason == "quotaExceeded"
    assert str(converted).startswith("upload failed:")


def test_from_http_error_extracts_direct_error_reason() -> None:
    error = _http_error(content='{"error": {"reason": "forbidden"}}')

    converted = YouTubeAPIError.from_http_error(error, "request failed")

    assert converted.status_code == 403
    assert converted.reason == "forbidden"


@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        "[]",
        '{"error": "not-an-object"}',
        '{"error": {"errors": [{"reason": 123}], "reason": 456}}',
    ],
    ids=["invalid-json", "non-object-root", "non-object-error", "non-string-reasons"],
)
def test_from_http_error_returns_no_reason_for_unsupported_payload_shapes(content: object) -> None:
    converted = YouTubeAPIError.from_http_error(_http_error(content=content), "request failed")

    assert converted.status_code == 403
    assert converted.reason is None


def test_from_http_error_allows_missing_status() -> None:
    error = SimpleNamespace(content=b'{"error": {"reason": "backendError"}}')

    converted = YouTubeAPIError.from_http_error(error, "request failed")

    assert converted.status_code is None
    assert converted.reason == "backendError"
