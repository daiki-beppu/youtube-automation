"""Pure decisions for `/wf-next` master-audio phase transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

MasterAudioAction = Literal["noop", "adopt", "needs_approval", "wait_for_master"]


@dataclass(frozen=True)
class MasterAudioDecision:
    action: MasterAudioAction
    master_audio: str | None = None
    phase: str | None = None
    reason: str = ""

    @property
    def updates_state(self) -> bool:
        return self.action == "adopt"


def decide_master_audio_transition(
    *,
    raw_master: str | None,
    current_master_audio: str | None,
    final_candidates: Sequence[str],
    skip_manual_mastering: bool,
    approval_gate_audio: bool,
    approved: bool | None = None,
) -> MasterAudioDecision:
    """Return the state transition for `/wf-next` prepared phase step 2-B."""
    if not raw_master or current_master_audio:
        return MasterAudioDecision(action="noop", reason="master-audio step is not pending")

    candidate = next((name for name in final_candidates if name != raw_master), None)
    if candidate:
        return _adopt_or_request_approval(candidate, approval_gate_audio, approved, reason="final candidate")

    if not skip_manual_mastering:
        return MasterAudioDecision(action="wait_for_master", reason="manual mastering is required")

    return _adopt_or_request_approval(raw_master, approval_gate_audio, approved, reason="raw master as final")


def _adopt_or_request_approval(
    filename: str,
    approval_gate_audio: bool,
    approved: bool | None,
    *,
    reason: str,
) -> MasterAudioDecision:
    if approval_gate_audio and approved is not True:
        return MasterAudioDecision(action="needs_approval", reason=reason)
    return MasterAudioDecision(action="adopt", master_audio=filename, phase="mastered", reason=reason)
