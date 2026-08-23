from __future__ import annotations

import pytest

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.human_tasks import (
    CollectionTaskState,
    build_human_task_report,
    render_human_tasks_summary,
)
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.infrastructure.notifications import discord
from youtube_automation.infrastructure.notifications.discord import DiscordNotificationSink
from youtube_automation.infrastructure.youtube.notification import NotificationError


def _event(kind: NotificationEventKind) -> NotificationEvent:
    return NotificationEvent(
        kind=kind,
        channel="ambient-lab",
        collection="night-rain",
        stage="media-handoff",
    )


@pytest.mark.parametrize(
    ("kind", "classification"),
    [
        (NotificationEventKind.HANDOFF_COMPLETED, "NORMAL"),
        (NotificationEventKind.NON_FAST_FORWARD_STOPPED, "ABNORMAL"),
    ],
)
def test_send_resolves_discord_secret_and_posts_classified_event(
    kind: NotificationEventKind,
    classification: str,
) -> None:
    resolved_names: list[str] = []
    posted: list[tuple[str, str | None]] = []

    def resolve_secret(name: str) -> str:
        resolved_names.append(name)
        return "https://discord.com/api/webhooks/id/token"

    def post_webhook(*, content: str, webhook_url: str | None) -> None:
        posted.append((content, webhook_url))

    sink = DiscordNotificationSink(
        secret_resolver=resolve_secret,
        webhook_sender=post_webhook,
    )

    delivered = sink.notify(_event(kind))

    assert delivered is True
    assert resolved_names == ["DISCORD_WEBHOOK_URL"]
    assert len(posted) == 1
    content, webhook_url = posted[0]
    assert webhook_url == "https://discord.com/api/webhooks/id/token"
    assert f"[{classification}]" in content
    assert f"event: {kind.value}" in content
    assert "channel: ambient-lab" in content
    assert "collection: night-rain" in content
    assert "stage: media-handoff" in content


@pytest.mark.parametrize(
    "failure",
    [
        ConfigError("secret unavailable"),
        NotificationError("webhook POST failed: secret-bearing-detail"),
    ],
)
def test_send_is_best_effort_and_redacts_known_delivery_failures(
    failure: ConfigError | NotificationError,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_secret(_: str) -> str:
        if isinstance(failure, ConfigError):
            raise failure
        return "https://discord.com/api/webhooks/id/token"

    def fail_webhook(*, content: str, webhook_url: str | None) -> None:
        del content, webhook_url
        if isinstance(failure, NotificationError):
            raise failure

    sink = DiscordNotificationSink(
        secret_resolver=fail_secret,
        webhook_sender=fail_webhook,
    )

    delivered = sink.notify(_event(NotificationEventKind.CANARY_FAILED))

    assert delivered is False
    stderr = capsys.readouterr().err
    assert "Discord notification was not delivered" in stderr
    assert "event=canary_failed" in stderr
    assert "secret unavailable" not in stderr
    assert "secret-bearing-detail" not in stderr


def test_send_does_not_hide_unexpected_programming_errors() -> None:
    def explode(*, content: str, webhook_url: str | None) -> None:
        del content, webhook_url
        raise RuntimeError("bug")

    sink = DiscordNotificationSink(
        secret_resolver=lambda _: "https://discord.com/api/webhooks/id/token",
        webhook_sender=explode,
    )

    with pytest.raises(RuntimeError, match="bug"):
        sink.notify(_event(NotificationEventKind.HANDOFF_COMPLETED))


def test_send_human_tasks_posts_deterministic_action_summary() -> None:
    posted: list[str] = []
    sink = DiscordNotificationSink(
        secret_resolver=lambda _: "https://discord.com/api/webhooks/id/token",
        webhook_sender=lambda *, content, webhook_url: posted.append(content),
    )
    report = build_human_task_report(
        "soulful-grooves",
        (CollectionTaskState("volume-one", "complete", None),),
        distrokid_enabled=True,
    )

    assert (
        sink.notify(
            NotificationEvent(
                NotificationEventKind.HUMAN_TASKS_PENDING,
                report.channel,
                report.tasks[0].collection,
                "human-tasks",
                render_human_tasks_summary(report),
            )
        )
        is True
    )
    assert len(posted) == 1
    assert posted[0].startswith("[ACTION] ")
    assert "pending: 1" in posted[0]
    assert "- distrokid_submission: volume-one (phase=complete)" in posted[0]
    assert posted[0].count("channel: soulful-grooves") == 1
    assert posted[0].count("[ACTION]") == 1


def test_factory_wires_canonical_secret_and_webhook_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved: list[str] = []
    posted: list[str] = []

    def resolve_secret(name: str) -> str:
        resolved.append(name)
        return "https://discord.com/api/webhooks/id/token"

    def post_webhook(*, content: str, webhook_url: str | None) -> None:
        del webhook_url
        posted.append(content)

    monkeypatch.setattr(discord, "get_secret", resolve_secret)
    monkeypatch.setattr(discord, "notify", post_webhook)

    delivered = discord.create_discord_notification_sink().notify(_event(NotificationEventKind.PUBLISH_COMPLETED))

    assert delivered is True
    assert resolved == ["DISCORD_WEBHOOK_URL"]
    assert len(posted) == 1
