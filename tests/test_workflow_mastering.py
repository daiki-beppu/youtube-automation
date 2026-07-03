from __future__ import annotations

from youtube_automation.utils.workflow_mastering import decide_master_audio_transition


def test_raw_final_adopts_raw_master_when_no_final_candidate() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=[],
        skip_manual_mastering=True,
        approval_gate_audio=False,
    )

    assert decision.updates_state is True
    assert decision.action == "adopt"
    assert decision.master_audio == "master-rain.wav"
    assert decision.phase == "mastered"


def test_raw_final_disabled_waits_without_state_update() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=[],
        skip_manual_mastering=False,
        approval_gate_audio=False,
    )

    assert decision.updates_state is False
    assert decision.action == "wait_for_master"
    assert decision.master_audio is None
    assert decision.phase is None


def test_raw_final_audio_gate_waits_for_approval_without_state_update() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=[],
        skip_manual_mastering=True,
        approval_gate_audio=True,
        approved=None,
    )

    assert decision.updates_state is False
    assert decision.action == "needs_approval"
    assert decision.master_audio is None
    assert decision.phase is None


def test_raw_final_audio_gate_rejection_keeps_state_unchanged() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=[],
        skip_manual_mastering=True,
        approval_gate_audio=True,
        approved=False,
    )

    assert decision.updates_state is False
    assert decision.action == "needs_approval"


def test_raw_final_audio_gate_approval_adopts_raw_master() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=[],
        skip_manual_mastering=True,
        approval_gate_audio=True,
        approved=True,
    )

    assert decision.updates_state is True
    assert decision.action == "adopt"
    assert decision.master_audio == "master-rain.wav"
    assert decision.phase == "mastered"


def test_existing_final_candidate_keeps_priority_over_raw_final() -> None:
    decision = decide_master_audio_transition(
        raw_master="master-rain.wav",
        current_master_audio=None,
        final_candidates=["master-rain.wav", "master.wav"],
        skip_manual_mastering=True,
        approval_gate_audio=False,
    )

    assert decision.updates_state is True
    assert decision.master_audio == "master.wav"
    assert decision.phase == "mastered"
