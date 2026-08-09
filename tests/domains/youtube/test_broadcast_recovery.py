from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.youtube.broadcast_recovery import (
    Broadcast,
    RecoveryRequest,
    Stream,
    recover_broadcast,
)


@dataclass
class FakeGateway:
    active: list[Broadcast] = field(default_factory=list)
    upcoming: list[Broadcast] = field(default_factory=list)
    stream_status: str = "active"
    calls: list[tuple] = field(default_factory=list)
    fail_bind_once: bool = False
    fail_transition_once: bool = False

    def list_active_broadcasts(self) -> list[Broadcast]:
        self.calls.append(("list_active",))
        return self.active

    def get_stream(self, stream_id: str) -> Stream:
        self.calls.append(("get_stream", stream_id))
        return Stream(id=stream_id, status=self.stream_status)

    def list_upcoming_broadcasts(self) -> list[Broadcast]:
        self.calls.append(("list_upcoming",))
        return self.upcoming

    def create_broadcast(self, request: RecoveryRequest) -> Broadcast:
        self.calls.append(("create", request.title))
        broadcast = Broadcast(id="created-1", title=request.title, bound_stream_id=None)
        self.upcoming.append(broadcast)
        return broadcast

    def bind_broadcast(self, broadcast_id: str, stream_id: str) -> Broadcast:
        self.calls.append(("bind", broadcast_id, stream_id))
        if self.fail_bind_once:
            self.fail_bind_once = False
            raise RuntimeError("bind failed")
        broadcast = next(item for item in self.upcoming if item.id == broadcast_id)
        self.upcoming.remove(broadcast)
        bound = Broadcast(id=broadcast.id, title=broadcast.title, bound_stream_id=stream_id)
        self.upcoming.append(bound)
        return bound

    def transition_to_live(self, broadcast_id: str) -> Broadcast:
        self.calls.append(("transition", broadcast_id))
        if self.fail_transition_once:
            self.fail_transition_once = False
            raise RuntimeError("transition failed")
        broadcast = next(item for item in self.upcoming if item.id == broadcast_id)
        self.active = [broadcast]
        return broadcast


def request(*, dry_run: bool = False) -> RecoveryRequest:
    return RecoveryRequest(
        stream_id="stream-1",
        title="Channel live",
        scheduled_start_time="2026-08-10T00:00:00Z",
        privacy_status="public",
        dry_run=dry_run,
    )


def test_active_broadcast_is_healthy_without_reading_ingest() -> None:
    gateway = FakeGateway(active=[Broadcast("live-1", "Live", "stream-1")])

    result = recover_broadcast(gateway, request())

    assert result.to_dict() == {
        "status": "healthy",
        "action": "none_active_broadcast",
        "stream_id": "stream-1",
        "broadcast_id": "live-1",
        "dry_run": False,
        "changed": False,
    }
    assert gateway.calls == [("list_active",)]


def test_inactive_ingest_waits_without_listing_or_mutating_broadcasts() -> None:
    gateway = FakeGateway(stream_status="inactive")

    result = recover_broadcast(gateway, request())

    assert result.status == "waiting_ingest"
    assert result.action == "none_ingest_inactive"
    assert gateway.calls == [("list_active",), ("get_stream", "stream-1")]


@pytest.mark.parametrize(
    ("upcoming", "expected_action", "mutation_calls"),
    [
        ([Broadcast("bound-1", "Old title", "stream-1")], "reused_bound_broadcast", ["transition"]),
        ([Broadcast("unbound-1", "Channel live", None)], "bound_existing_broadcast", ["bind", "transition"]),
        ([], "created_broadcast", ["create", "bind", "transition"]),
    ],
)
def test_active_ingest_recovers_with_reuse_precedence(
    upcoming: list[Broadcast], expected_action: str, mutation_calls: list[str]
) -> None:
    gateway = FakeGateway(upcoming=upcoming)

    result = recover_broadcast(gateway, request())

    assert result.status == "recovered"
    assert result.action == expected_action
    assert result.changed is True
    assert [call[0] for call in gateway.calls if call[0] in {"create", "bind", "transition"}] == mutation_calls


def test_dry_run_describes_create_without_mutation() -> None:
    gateway = FakeGateway()

    result = recover_broadcast(gateway, request(dry_run=True))

    assert result.to_dict() == {
        "status": "recovered",
        "action": "would_create_broadcast",
        "stream_id": "stream-1",
        "broadcast_id": None,
        "dry_run": True,
        "changed": False,
    }
    assert not {call[0] for call in gateway.calls} & {"create", "bind", "transition"}


def test_retry_after_transition_failure_reuses_created_and_bound_broadcast() -> None:
    gateway = FakeGateway(fail_transition_once=True)

    with pytest.raises(RuntimeError, match="transition failed"):
        recover_broadcast(gateway, request())
    result = recover_broadcast(gateway, request())

    assert result.action == "reused_bound_broadcast"
    assert [call[0] for call in gateway.calls].count("create") == 1
    assert [call[0] for call in gateway.calls].count("bind") == 1


def test_retry_after_bind_failure_reuses_created_unbound_broadcast() -> None:
    gateway = FakeGateway(fail_bind_once=True)

    with pytest.raises(RuntimeError, match="bind failed"):
        recover_broadcast(gateway, request())
    result = recover_broadcast(gateway, request())

    assert result.action == "bound_existing_broadcast"
    assert [call[0] for call in gateway.calls].count("create") == 1
    assert [call[0] for call in gateway.calls].count("bind") == 2


def test_ambiguous_reusable_broadcasts_fail_loud() -> None:
    gateway = FakeGateway(
        upcoming=[
            Broadcast("one", "One", "stream-1"),
            Broadcast("two", "Two", "stream-1"),
        ]
    )

    with pytest.raises(ValidationError, match="複数"):
        recover_broadcast(gateway, request())
