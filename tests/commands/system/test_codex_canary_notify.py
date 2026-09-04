from __future__ import annotations

import sys
from argparse import Namespace

import pytest

from youtube_automation import entrypoints
from youtube_automation.commands.system import codex_canary_notify
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind


class RecordingSink:
    def __init__(self, delivered: bool = True) -> None:
        self.delivered = delivered
        self.events: list[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> bool:
        self.events.append(event)
        return self.delivered


@pytest.mark.parametrize(
    ("result", "expected_kind"),
    [
        ("success", NotificationEventKind.CANARY_COMPLETED),
        ("failure", NotificationEventKind.CANARY_FAILED),
        ("cancelled", NotificationEventKind.CANARY_FAILED),
        ("skipped", NotificationEventKind.CANARY_FAILED),
    ],
)
def test_command_maps_github_job_result_to_typed_canary_event(monkeypatch, result, expected_kind) -> None:
    sink = RecordingSink()
    monkeypatch.setattr(codex_canary_notify, "create_discord_notification_sink", lambda: sink)

    assert codex_canary_notify.run(Namespace(result=result, channel="ambient-lab")) == 0
    assert sink.events == [
        NotificationEvent(
            expected_kind,
            "ambient-lab",
            "monthly-codex-canary",
            "codex-action",
        )
    ]


def test_notification_delivery_failure_is_best_effort(monkeypatch, capsys) -> None:
    sink = RecordingSink(delivered=False)
    monkeypatch.setattr(codex_canary_notify, "create_discord_notification_sink", lambda: sink)

    assert codex_canary_notify.run(Namespace(result="failure", channel="ambient-lab")) == 0
    assert "was not delivered" in capsys.readouterr().err


def test_cli_rejects_unknown_job_result_before_notification(monkeypatch) -> None:
    sink = RecordingSink()
    monkeypatch.setattr(codex_canary_notify, "create_discord_notification_sink", lambda: sink)

    with pytest.raises(SystemExit):
        codex_canary_notify.main(["--result", "pending", "--channel", "ambient-lab"])
    assert sink.events == []


def test_console_entrypoint_preserves_notification_channel_option(monkeypatch) -> None:
    sink = RecordingSink()
    monkeypatch.setattr(codex_canary_notify, "create_discord_notification_sink", lambda: sink)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-codex-canary-notify",
            "--result",
            "success",
            "--channel",
            "ambient-lab",
        ],
    )

    assert entrypoints._run("youtube_automation.commands.system.codex_canary_notify") == 0
    assert sink.events[0].channel == "ambient-lab"
