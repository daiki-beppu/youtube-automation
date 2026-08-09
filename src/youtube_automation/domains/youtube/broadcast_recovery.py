"""Provider-neutral decision flow for recovering a YouTube live broadcast."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from youtube_automation.core.errors import ValidationError

RecoveryStatus = Literal["healthy", "waiting_ingest", "recovered", "error"]


@dataclass(frozen=True)
class Broadcast:
    id: str
    title: str
    bound_stream_id: str | None


@dataclass(frozen=True)
class Stream:
    id: str
    status: str


@dataclass(frozen=True)
class RecoveryRequest:
    stream_id: str
    title: str
    scheduled_start_time: str
    privacy_status: str
    dry_run: bool = False


@dataclass(frozen=True)
class RecoveryResult:
    status: RecoveryStatus
    action: str
    stream_id: str
    broadcast_id: str | None
    dry_run: bool
    changed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BroadcastRecoveryGateway(Protocol):
    def list_active_broadcasts(self) -> list[Broadcast]: ...

    def get_stream(self, stream_id: str) -> Stream: ...

    def list_upcoming_broadcasts(self) -> list[Broadcast]: ...

    def create_broadcast(self, request: RecoveryRequest) -> Broadcast: ...

    def bind_broadcast(self, broadcast_id: str, stream_id: str) -> Broadcast: ...

    def transition_to_live(self, broadcast_id: str) -> Broadcast: ...


def _one_or_none(candidates: list[Broadcast], description: str) -> Broadcast | None:
    if len(candidates) > 1:
        ids = ", ".join(item.id for item in candidates)
        raise ValidationError(f"再利用可能な {description} が複数あります: {ids}")
    return candidates[0] if candidates else None


def recover_broadcast(
    gateway: BroadcastRecoveryGateway,
    request: RecoveryRequest,
) -> RecoveryResult:
    """Recover a missing active broadcast without multiplying upcoming events."""
    active = gateway.list_active_broadcasts()
    if active:
        return RecoveryResult(
            status="healthy",
            action="none_active_broadcast",
            stream_id=request.stream_id,
            broadcast_id=active[0].id,
            dry_run=request.dry_run,
            changed=False,
        )

    stream = gateway.get_stream(request.stream_id)
    if stream.status != "active":
        return RecoveryResult(
            status="waiting_ingest",
            action="none_ingest_inactive",
            stream_id=request.stream_id,
            broadcast_id=None,
            dry_run=request.dry_run,
            changed=False,
        )

    upcoming = gateway.list_upcoming_broadcasts()
    bound = _one_or_none(
        [item for item in upcoming if item.bound_stream_id == request.stream_id],
        "bound broadcast",
    )
    unbound = None
    if bound is None:
        unbound = _one_or_none(
            [item for item in upcoming if item.bound_stream_id is None and item.title == request.title],
            "unbound broadcast",
        )

    if request.dry_run:
        if bound is not None:
            action, broadcast_id = "would_reuse_bound_broadcast", bound.id
        elif unbound is not None:
            action, broadcast_id = "would_bind_existing_broadcast", unbound.id
        else:
            action, broadcast_id = "would_create_broadcast", None
        return RecoveryResult(
            status="recovered",
            action=action,
            stream_id=request.stream_id,
            broadcast_id=broadcast_id,
            dry_run=True,
            changed=False,
        )

    if bound is not None:
        candidate = bound
        action = "reused_bound_broadcast"
    elif unbound is not None:
        candidate = gateway.bind_broadcast(unbound.id, request.stream_id)
        action = "bound_existing_broadcast"
    else:
        created = gateway.create_broadcast(request)
        candidate = gateway.bind_broadcast(created.id, request.stream_id)
        action = "created_broadcast"

    live = gateway.transition_to_live(candidate.id)
    return RecoveryResult(
        status="recovered",
        action=action,
        stream_id=request.stream_id,
        broadcast_id=live.id,
        dry_run=False,
        changed=True,
    )
