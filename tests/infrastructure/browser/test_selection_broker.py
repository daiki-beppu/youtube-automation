from __future__ import annotations

import http.client
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from youtube_automation.core.errors import ReviewError
from youtube_automation.domains.documents.review import ReviewCandidate, SelectionManifest
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _manifest(*, expires: datetime | None = None) -> SelectionManifest:
    return SelectionManifest.create(
        artifact="thumbnail",
        artifact_digest="a" * 64,
        candidates=(ReviewCandidate("candidate-a", "候補 A", "b" * 64),),
        now=NOW,
        lifetime=timedelta(minutes=5),
        expires_at=expires,
    )


def _post(
    broker: SelectionBroker,
    *,
    path: str | None = None,
    origin: str = "null",
    host: str | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    body: bytes | None = None,
) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", broker.port, timeout=2)
    payload = body or urlencode({"candidate_id": "candidate-a", "artifact_digest": "a" * 64}).encode()
    connection.request(
        "POST",
        path or broker.selection_path,
        body=payload,
        headers={
            "Origin": origin,
            "Host": host or broker.host_header,
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        },
    )
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


def test_broker_accepts_one_allowlisted_selection_and_rejects_replay() -> None:
    with SelectionBroker(_manifest(), now=lambda: NOW) as broker:
        assert _post(broker)[0] == 200
        assert broker.wait(timeout=0.1).candidate_id == "candidate-a"
        assert _post(broker)[0] == 409


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"path": "/select/wrong"}, 403),
        ({"origin": "https://evil.example"}, 403),
        ({"host": "evil.example"}, 403),
        ({"content_type": "application/json"}, 415),
        ({"body": b"candidate_id=unknown&artifact_digest=" + b"a" * 64}, 400),
        ({"body": b"candidate_id=candidate-a&artifact_digest=" + b"c" * 64}, 409),
        ({"body": b"x" * 4097}, 413),
    ],
)
def test_broker_rejects_untrusted_request_without_consuming_token(
    overrides: dict[str, str | bytes], status: int
) -> None:
    with SelectionBroker(_manifest(), now=lambda: NOW) as broker:
        assert _post(broker, **overrides)[0] == status
        assert _post(broker)[0] == 200


def test_broker_rejects_expired_manifest() -> None:
    with SelectionBroker(_manifest(expires=NOW), now=lambda: NOW) as broker:
        assert _post(broker)[0] == 410


def test_broker_wakes_all_waiters_and_retains_the_selection() -> None:
    with SelectionBroker(_manifest(), now=lambda: NOW) as broker:
        ready = threading.Barrier(3)

        def await_selection():
            ready.wait(timeout=2)
            return broker.wait(timeout=2)

        with ThreadPoolExecutor(max_workers=2) as executor:
            waiters = [executor.submit(await_selection) for _ in range(2)]
            ready.wait(timeout=2)
            assert _post(broker)[0] == 200
            selections = [waiter.result(timeout=2) for waiter in waiters]

        assert selections[0] is selections[1]
        assert broker.wait(timeout=0) is selections[0]


def test_concurrent_posts_consume_the_token_exactly_once() -> None:
    with SelectionBroker(_manifest(), now=lambda: NOW) as broker:
        ready = threading.Barrier(3)

        def post_together():
            ready.wait(timeout=2)
            return _post(broker)[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            posts = [executor.submit(post_together) for _ in range(2)]
            ready.wait(timeout=2)
            statuses = [post.result(timeout=2) for post in posts]

        assert sorted(statuses) == [200, 409]
        assert broker.wait(timeout=0).candidate_id == "candidate-a"


def test_slow_request_body_does_not_block_selection_timeout(monkeypatch) -> None:
    reading = threading.Event()
    release = threading.Event()
    body = urlencode({"candidate_id": "candidate-a", "artifact_digest": "a" * 64}).encode()
    responses = []

    class SlowBody:
        def read(self, length):
            reading.set()
            release.wait(timeout=2)
            return body[:length]

    with SelectionBroker(_manifest(), now=lambda: NOW) as broker:
        handler = SimpleNamespace(
            path=broker.selection_path,
            headers={
                "Host": broker.host_header,
                "Origin": "null",
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            },
            rfile=SlowBody(),
        )
        monkeypatch.setattr(broker, "_respond", lambda _handler, status, message: responses.append((status, message)))
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(broker._handle, handler)
            assert reading.wait(timeout=2)
            try:
                with pytest.raises(ReviewError, match="timeout"):
                    broker.wait(timeout=0.01)
            finally:
                release.set()
            request.result(timeout=2)

        assert responses[0][0] == 200
        assert broker.wait(timeout=0).candidate_id == "candidate-a"
