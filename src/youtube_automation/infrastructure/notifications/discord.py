"""Best-effort Discord delivery for typed pipeline events."""

from __future__ import annotations

import sys
from typing import Protocol

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.notifications import NotificationEvent, category_for
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.secrets import get_secret
from youtube_automation.infrastructure.youtube.notification import NotificationError, notify

_WEBHOOK_SECRET_NAME = "DISCORD_WEBHOOK_URL"


class SecretResolver(Protocol):
    def __call__(self, name: str) -> str: ...


class WebhookSender(Protocol):
    def __call__(self, *, content: str, webhook_url: str | None) -> None: ...


class DiscordNotificationSink:
    """Deliver classified events without making notification a pipeline gate."""

    def __init__(
        self,
        *,
        secret_resolver: SecretResolver,
        webhook_sender: WebhookSender,
    ) -> None:
        self._secret_resolver = secret_resolver
        self._webhook_sender = webhook_sender

    def notify(self, event: NotificationEvent) -> bool:
        event = NotificationEvent(
            event.kind, event.channel, event.collection, event.stage, redact_sensitive_data(event.detail)
        )
        return self._send_content(
            _render_event(event),
            failure_context=(
                f"event={event.kind.value}, channel={event.channel}, collection={event.collection}, stage={event.stage}"
            ),
        )

    def _send_content(self, content: str, *, failure_context: str) -> bool:
        try:
            webhook_url = self._secret_resolver(_WEBHOOK_SECRET_NAME)
            self._webhook_sender(
                content=content,
                webhook_url=webhook_url,
            )
        except (ConfigError, NotificationError):
            print(
                f"Discord notification was not delivered ({failure_context})",
                file=sys.stderr,
            )
            return False
        return True


def create_discord_notification_sink() -> DiscordNotificationSink:
    """Compose the Discord adapter with canonical secret and HTTP owners."""

    return DiscordNotificationSink(secret_resolver=get_secret, webhook_sender=notify)


def _render_event(event: NotificationEvent) -> str:
    category = category_for(event.kind).value.upper()
    return "\n".join(
        (
            f"[{category}] YouTube automation pipeline event",
            f"event: {event.kind.value}",
            f"channel: {event.channel}",
            f"collection: {event.collection}",
            f"stage: {event.stage}",
            *((f"detail: {event.detail}",) if event.detail else ()),
        )
    )
