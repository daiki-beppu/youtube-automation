from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.commands.analytics import postmortem_pending


def _collection(
    channel_root: Path,
    name: str,
    *,
    video_id: str | None = None,
    tracking: bool = True,
    postmortem: bool = False,
) -> Path:
    collection = channel_root / "collections" / "live" / name
    documentation = collection / "20-documentation"
    documentation.mkdir(parents=True)
    if tracking:
        payload = {"schema_version": 3, "complete_collection": {"video_id": video_id}}
        (documentation / "upload_tracking.json").write_text(json.dumps(payload), encoding="utf-8")
    if postmortem:
        (documentation / "postmortem.md").write_text("done\n", encoding="utf-8")
    return collection


def _analytics(channel_root: Path, date: str, *video_ids: str) -> Path:
    path = channel_root / "data" / f"analytics_data_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"video_analytics": {video_id: {} for video_id in video_ids}}),
        encoding="utf-8",
    )
    return path


def _run(channel_root: Path, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(postmortem_pending, "_channel_dir", lambda: channel_root)
    return postmortem_pending.main(argv)


def test_json_uses_latest_analytics_and_classifies_four_fixed_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _collection(tmp_path, "01-pending", video_id="LATEST")
    _collection(tmp_path, "02-old-only", video_id="OLD")
    _collection(tmp_path, "03-no-tracking", tracking=False)
    _collection(tmp_path, "04-no-video", video_id="")
    _collection(tmp_path, "05-complete", video_id="LATEST", postmortem=True)
    _analytics(tmp_path, "20260809", "OLD")
    latest = _analytics(tmp_path, "20260810", "LATEST")

    exit_code = _run(tmp_path, ["--json"], monkeypatch)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": 1,
        "analytics_data_path": latest.relative_to(tmp_path).as_posix(),
        "pending": [
            {
                "collection": "01-pending",
                "video_id": "LATEST",
                "postmortem_path": "collections/live/01-pending/20-documentation/postmortem.md",
            }
        ],
        "unanalyzable": [
            {"collection": "02-old-only", "video_id": "OLD", "reason": "video_not_in_analytics"},
            {"collection": "03-no-tracking", "video_id": None, "reason": "upload_tracking_missing"},
            {"collection": "04-no-video", "video_id": None, "reason": "video_id_missing"},
        ],
    }


def test_missing_analytics_marks_valid_video_candidates_and_keeps_path_null(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _collection(tmp_path, "01-valid", video_id="VIDEO")
    _collection(tmp_path, "02-no-tracking", tracking=False)

    assert _run(tmp_path, ["--json"], monkeypatch) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["analytics_data_path"] is None
    assert payload["pending"] == []
    assert payload["unanalyzable"] == [
        {"collection": "01-valid", "video_id": "VIDEO", "reason": "analytics_data_missing"},
        {"collection": "02-no-tracking", "video_id": None, "reason": "upload_tracking_missing"},
    ]


def test_human_output_is_read_only_and_pending_count_never_changes_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _collection(tmp_path, "pending-collection", video_id="VIDEO")
    _collection(tmp_path, "missing-tracking", tracking=False)
    _analytics(tmp_path, "20260810", "VIDEO")
    before = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    exit_code = _run(tmp_path, [], monkeypatch)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "pending: 1" in output
    assert "pending-collection" in output
    assert "unanalyzable: 1" in output
    assert "missing-tracking" in output
    assert "upload_tracking_missing" in output
    after = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not list(tmp_path.rglob("insights.jsonl"))
    assert not list(tmp_path.rglob("workflow-state.json"))


def test_help_describes_json_output_without_resolving_channel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_channel_resolution() -> Path:
        raise AssertionError("help must be parsed before channel resolution")

    monkeypatch.setattr(postmortem_pending, "_channel_dir", unexpected_channel_resolution)

    with pytest.raises(SystemExit) as raised:
        postmortem_pending.main(["--help"])

    assert raised.value.code == 0
    assert "--json" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "analytics データのルートは object"),
        ({"video_analytics": []}, "video_analytics は object"),
    ],
)
def test_malformed_analytics_shape_is_a_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "data" / "analytics_data_20260810.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _run(tmp_path, ["--json"], monkeypatch) == 1
    assert message in capsys.readouterr().err


def test_malformed_tracking_root_is_a_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = _collection(tmp_path, "malformed", tracking=False)
    tracking = collection / "20-documentation" / "upload_tracking.json"
    tracking.write_text("[]", encoding="utf-8")

    assert _run(tmp_path, ["--json"], monkeypatch) == 1
    assert "upload tracking のルートは object" in capsys.readouterr().err
