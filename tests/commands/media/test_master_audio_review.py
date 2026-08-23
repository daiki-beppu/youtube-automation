from __future__ import annotations

from unittest.mock import Mock

from youtube_automation.application.master_audio_review import MasterAudioReviewResult
from youtube_automation.commands.media import master_audio_review


def test_cli_passes_explicit_review_contract_to_application(tmp_path, monkeypatch) -> None:
    execute = Mock(return_value=MasterAudioReviewResult(status="selected", candidate_id="worktree:final.wav"))
    monkeypatch.setattr(master_audio_review, "review_and_finalize_master_audio", execute)

    assert (
        master_audio_review.main(
            [
                "--collection",
                str(tmp_path),
                "--skip-manual-mastering",
                "false",
                "--skip-audio-approval",
                "false",
                "--transport",
                "terminal",
                "--candidate-id",
                "worktree:final.wav",
            ]
        )
        == 0
    )

    assert execute.call_args.kwargs == {
        "skip_manual_mastering": False,
        "skip_audio_approval": False,
        "transport": "terminal",
        "candidate_id": "worktree:final.wav",
        "main_repo_root": None,
    }


def test_terminal_required_returns_exit_code_two(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        master_audio_review,
        "review_and_finalize_master_audio",
        Mock(return_value=MasterAudioReviewResult(status="terminal_required", candidates=("worktree:final.wav",))),
    )

    assert (
        master_audio_review.main(
            [
                "--collection",
                str(tmp_path),
                "--skip-manual-mastering",
                "false",
                "--skip-audio-approval",
                "false",
                "--transport",
                "terminal",
            ]
        )
        == 2
    )
