from __future__ import annotations

import json

from youtube_automation.commands.youtube import stream_broadcast_recover
from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.youtube.broadcast_recovery import Broadcast


class HealthyGateway:
    def list_active_broadcasts(self):
        return [Broadcast("broadcast-1", "Live", "stream-1")]


class ErrorGateway:
    def list_active_broadcasts(self):
        raise YouTubeAPIError("access_token=ya29.supersecret")


def test_cli_emits_structured_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(stream_broadcast_recover, "_create_gateway", lambda force_reauth: HealthyGateway())

    exit_code = stream_broadcast_recover.main(["--stream-id", "stream-1", "--title", "Channel live", "--dry-run"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "healthy",
        "action": "none_active_broadcast",
        "stream_id": "stream-1",
        "broadcast_id": "broadcast-1",
        "dry_run": True,
        "changed": False,
    }


def test_cli_emits_redacted_structured_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(stream_broadcast_recover, "_create_gateway", lambda force_reauth: ErrorGateway())

    exit_code = stream_broadcast_recover.main(["--stream-id", "stream-1", "--title", "Live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "supersecret" not in captured.err
    assert json.loads(captured.err) == {
        "status": "error",
        "error": "access_token=<redacted-token>",
    }
