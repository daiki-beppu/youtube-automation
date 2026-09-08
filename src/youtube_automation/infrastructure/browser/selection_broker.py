"""Single-use loopback HTTP broker for product-neutral review selection."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from youtube_automation.core.errors import ReviewError, ReviewSelectionError
from youtube_automation.domains.documents.review import SelectionManifest

_MAX_BODY_BYTES = 4096


@dataclass(frozen=True)
class BrokerSelection:
    candidate_id: str
    artifact_digest: str


class _BrokerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, owner: "SelectionBroker") -> None:
        super().__init__(("127.0.0.1", 0), _SelectionHandler)
        self.owner = owner
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="review-selection-broker", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


class _SelectionHandler(BaseHTTPRequestHandler):
    server: _BrokerServer

    def do_POST(self) -> None:
        self.server.owner._handle(self)

    def do_GET(self) -> None:
        self.send_error(405)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _parse_selection_form(raw: bytes) -> tuple[str, str]:
    """Decode the two single-valued fields accepted by the selection protocol."""
    try:
        fields = parse_qs(raw.decode("ascii"), strict_parsing=True)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("invalid form body") from error
    if set(fields) != {"candidate_id", "artifact_digest"} or any(len(values) != 1 for values in fields.values()):
        raise ValueError("invalid form fields")
    return fields["candidate_id"][0], fields["artifact_digest"][0]


class SelectionBroker:
    """Bind only loopback and accept one validated candidate selection."""

    def __init__(self, manifest: SelectionManifest, *, now: Callable[[], datetime] | None = None) -> None:
        self.manifest = manifest
        self._now = now or (lambda: datetime.now(UTC))
        self._selection: BrokerSelection | None = None
        self._condition = threading.Condition()
        self._server = _BrokerServer(self)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def host_header(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def selection_path(self) -> str:
        return f"/select/{self.manifest.token}"

    @property
    def endpoint(self) -> str:
        return f"http://{self.host_header}{self.selection_path}"

    def __enter__(self) -> "SelectionBroker":
        self._server.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._server.close()

    def wait(self, *, timeout: float) -> BrokerSelection:
        with self._condition:
            if not self._condition.wait_for(lambda: self._selection is not None, timeout=timeout):
                raise ReviewError("Web選択がtimeoutしました。再実行するか --transport terminal を明示してください")
            assert self._selection is not None
            return self._selection

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        if handler.path != self.selection_path:
            self._respond(handler, 403, "invalid token")
            return
        if handler.headers.get("Host") != self.host_header or handler.headers.get("Origin") != "null":
            self._respond(handler, 403, "untrusted origin")
            return
        if handler.headers.get("Content-Type") != "application/x-www-form-urlencoded":
            self._respond(handler, 415, "unsupported content type")
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            self._respond(handler, 400, "invalid content length")
            return
        if length < 1 or length > _MAX_BODY_BYTES:
            self._respond(handler, 413 if length > _MAX_BODY_BYTES else 400, "invalid body size")
            return
        with self._condition:
            consumed = self._selection is not None
        if consumed:
            self._respond(handler, 409, "token already consumed")
            return
        # Network I/O must not hold the condition used by timed selection waiters.
        raw = handler.rfile.read(length)
        try:
            candidate_id, artifact_digest = _parse_selection_form(raw)
        except ValueError as error:
            self._respond(handler, 400, str(error))
            return
        status, message = self._accept_selection(candidate_id, artifact_digest)
        self._respond(handler, status, message)

    def _accept_selection(self, candidate_id: str, artifact_digest: str) -> tuple[int, str]:
        """Validate and publish one selection atomically, waking every waiter."""
        with self._condition:
            if self._selection is not None:
                return 409, "token already consumed"
            try:
                candidate = self.manifest.validate_selection(
                    token=self.manifest.token,
                    candidate_id=candidate_id,
                    artifact_digest=artifact_digest,
                    now=self._now(),
                )
            except ReviewSelectionError as exc:
                message = str(exc)
                status = 410 if "期限" in message else 409 if "digest" in message else 400
                return status, "selection rejected"
            self._selection = BrokerSelection(candidate_id=candidate.id, artifact_digest=artifact_digest)
            self._condition.notify_all()
            return 200, "selection accepted; you may close this tab"

    @staticmethod
    def _respond(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        body = message.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)


__all__ = ["BrokerSelection", "SelectionBroker"]
