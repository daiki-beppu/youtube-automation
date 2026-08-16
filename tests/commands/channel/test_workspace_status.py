"""``yt-workspace-status`` CLI の契約テスト。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation import entrypoints
from youtube_automation.commands.channel import workspace_status


def _make_channel(workspace: Path, slug: str, *, token: bool = False) -> Path:
    channel = workspace / "channels" / slug
    (channel / "config" / "channel").mkdir(parents=True)
    if token:
        auth = channel / "auth"
        auth.mkdir()
        (auth / "token.readonly.json").write_text("{}\n", encoding="utf-8")
    return channel


def _config(channel_id: str, channel_name: str) -> SimpleNamespace:
    return SimpleNamespace(meta=SimpleNamespace(channel_id=channel_id, channel_name=channel_name))


def _youtube_response(*items: tuple[str, str, str, str, str]) -> dict[str, object]:
    return {
        "items": [
            {
                "id": channel_id,
                "snippet": {"title": title},
                "statistics": {
                    "subscriberCount": subscribers,
                    "viewCount": views,
                    "videoCount": videos,
                },
            }
            for channel_id, title, subscribers, views, videos in items
        ]
    }


def _configure_api(monkeypatch: pytest.MonkeyPatch, response: dict[str, object]):
    request = Mock()
    request.execute.return_value = response
    channels = Mock()
    channels.list.return_value = request
    youtube = Mock()
    youtube.channels.return_value = channels
    clients = SimpleNamespace(youtube_readonly=youtube)
    factory = Mock(return_value=clients)
    monkeypatch.setattr(workspace_status, "create_readonly_youtube_clients", factory)
    return factory, channels, request


def test_table_collects_all_channels_with_one_channels_list_request_in_slug_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = _make_channel(tmp_path, "alpha", token=True)
    zeta = _make_channel(tmp_path, "zeta")
    configs = {
        alpha: _config("UC_ALPHA", "Alpha local"),
        zeta: _config("UC_ZETA", "Zeta local"),
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda path: configs[path])
    select_channel = Mock()
    monkeypatch.setattr(workspace_status, "select_channel", select_channel)
    quota = Mock()
    monkeypatch.setattr(workspace_status.cost_tracker, "log_quota", quota)
    factory, channels, request = _configure_api(
        monkeypatch,
        _youtube_response(
            ("UC_ZETA", "Zeta API", "2000", "30000", "40"),
            ("UC_ALPHA", "Alpha API", "1000", "20000", "30"),
        ),
    )

    assert workspace_status.main([]) == workspace_status.EXIT_OK

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.index("alpha") < captured.out.index("zeta")
    assert "Alpha API" in captured.out
    assert "1,000" in captured.out
    assert "20,000" in captured.out
    assert "30" in captured.out
    channels.list.assert_called_once_with(part="snippet,statistics", id="UC_ALPHA,UC_ZETA")
    request.execute.assert_called_once_with()
    quota.assert_called_once_with("youtube-data-api", "channels.list", 1)
    select_channel.assert_called_once_with("alpha")
    factory.assert_called_once_with()


def test_json_output_is_machine_readable_and_keeps_slug_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = _make_channel(tmp_path, "alpha", token=True)
    beta = _make_channel(tmp_path, "beta")
    configs = {
        alpha: _config("UC_ALPHA", "Alpha local"),
        beta: _config("UC_BETA", "Beta local"),
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda path: configs[path])
    monkeypatch.setattr(workspace_status, "select_channel", Mock())
    monkeypatch.setattr(workspace_status.cost_tracker, "log_quota", Mock())
    _configure_api(
        monkeypatch,
        _youtube_response(
            ("UC_BETA", "Beta API", "2", "20", "200"),
            ("UC_ALPHA", "Alpha API", "1", "10", "100"),
        ),
    )

    assert workspace_status.main(["--json"]) == workspace_status.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "slug": "alpha",
            "channel_id": "UC_ALPHA",
            "channel_name": "Alpha API",
            "subscriber_count": 1,
            "total_views": 10,
            "video_count": 100,
        },
        {
            "slug": "beta",
            "channel_id": "UC_BETA",
            "channel_name": "Beta API",
            "subscriber_count": 2,
            "total_views": 20,
            "video_count": 200,
        },
    ]


def test_missing_channel_id_is_warned_and_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = _make_channel(tmp_path, "alpha", token=True)
    missing = _make_channel(tmp_path, "missing")
    configs = {
        alpha: _config("UC_ALPHA", "Alpha local"),
        missing: _config("", "Missing"),
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda path: configs[path])
    monkeypatch.setattr(workspace_status, "select_channel", Mock())
    monkeypatch.setattr(workspace_status.cost_tracker, "log_quota", Mock())
    _, channels, _ = _configure_api(
        monkeypatch,
        _youtube_response(("UC_ALPHA", "Alpha API", "1", "10", "2")),
    )

    assert workspace_status.main([]) == workspace_status.EXIT_OK

    captured = capsys.readouterr()
    assert "missing" in captured.err
    assert "channel_id" in captured.err
    assert "missing" not in captured.out
    channels.list.assert_called_once_with(part="snippet,statistics", id="UC_ALPHA")


def test_all_missing_channel_ids_returns_nonzero_without_auth_or_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_channel(tmp_path, "alpha", token=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda _path: _config("", "Alpha"))
    select_channel = Mock()
    create_clients = Mock()
    monkeypatch.setattr(workspace_status, "select_channel", select_channel)
    monkeypatch.setattr(workspace_status, "create_readonly_youtube_clients", create_clients)

    assert workspace_status.main([]) == workspace_status.EXIT_NO_CHANNEL_IDS

    captured = capsys.readouterr()
    assert "alpha" in captured.err
    assert "channel_id" in captured.err
    select_channel.assert_not_called()
    create_clients.assert_not_called()


def test_first_readonly_token_in_slug_order_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = _make_channel(tmp_path, "alpha", token=True)
    beta = _make_channel(tmp_path, "beta", token=True)
    configs = {alpha: _config("UC_ALPHA", "Alpha"), beta: _config("UC_BETA", "Beta")}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda path: configs[path])
    selected = Mock()
    monkeypatch.setattr(workspace_status, "select_channel", selected)
    monkeypatch.setattr(workspace_status.cost_tracker, "log_quota", Mock())
    _configure_api(
        monkeypatch,
        _youtube_response(
            ("UC_ALPHA", "Alpha", "1", "2", "3"),
            ("UC_BETA", "Beta", "4", "5", "6"),
        ),
    )

    assert workspace_status.main([]) == workspace_status.EXIT_OK
    selected.assert_called_once_with("alpha")


def test_channel_override_selects_requested_token_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = _make_channel(tmp_path, "alpha", token=True)
    beta = _make_channel(tmp_path, "beta", token=True)
    configs = {alpha: _config("UC_ALPHA", "Alpha"), beta: _config("UC_BETA", "Beta")}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda path: configs[path])
    selected = Mock()
    monkeypatch.setattr(workspace_status, "select_channel", selected)
    monkeypatch.setattr(workspace_status.cost_tracker, "log_quota", Mock())
    _configure_api(
        monkeypatch,
        _youtube_response(
            ("UC_ALPHA", "Alpha", "1", "2", "3"),
            ("UC_BETA", "Beta", "4", "5", "6"),
        ),
    )

    assert workspace_status.main(["--channel", "beta"]) == workspace_status.EXIT_OK
    selected.assert_called_once_with("beta")


def test_missing_readonly_token_is_actionable_and_does_not_create_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    channel = _make_channel(tmp_path, "alpha")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace_status, "load_config_from_path", lambda _path: _config("UC_ALPHA", "Alpha"))
    create_clients = Mock()
    monkeypatch.setattr(workspace_status, "create_readonly_youtube_clients", create_clients)

    assert workspace_status.main([]) == workspace_status.EXIT_AUTH_REQUIRED

    captured = capsys.readouterr()
    assert "yt-oauth --readonly" in captured.err
    assert channel.name in captured.err
    create_clients.assert_not_called()


def test_workspace_exit_codes_match_yt_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert workspace_status.main([]) == workspace_status.EXIT_OUTSIDE_WORKSPACE
    assert "workspace が見つかりません" in capsys.readouterr().err

    (tmp_path / "channels").mkdir()
    assert workspace_status.main([]) == workspace_status.EXIT_EMPTY_WORKSPACE
    assert "channel がありません" in capsys.readouterr().err


def test_unreadable_workspace_returns_shared_unreadable_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        workspace_status,
        "find_workspace_root",
        Mock(side_effect=PermissionError("permission denied")),
    )

    assert workspace_status.main([]) == workspace_status.EXIT_UNREADABLE
    assert "読み取れません" in capsys.readouterr().err


def test_help_returns_before_workspace_auth_and_api_resolution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forbidden = Mock(side_effect=AssertionError("help must not resolve runtime dependencies"))
    monkeypatch.setattr(workspace_status, "find_workspace_root", forbidden)
    monkeypatch.setattr(workspace_status, "select_channel", forbidden)
    monkeypatch.setattr(workspace_status, "create_readonly_youtube_clients", forbidden)

    with pytest.raises(SystemExit, match="0"):
        workspace_status.main(["--help"])

    output = capsys.readouterr().out
    assert "usage: yt-workspace-status" in output
    assert "--channel" in output
    assert "--json" in output
    forbidden.assert_not_called()


def test_entrypoint_is_registered_and_keeps_credential_channel_argument() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        scripts = tomllib.load(file)["project"]["scripts"]

    assert scripts["yt-workspace-status"] == "youtube_automation.entrypoints:yt_workspace_status"
    assert callable(entrypoints.yt_workspace_status)
    assert "youtube_automation.commands.channel.workspace_status" in entrypoints._CHANNEL_OPTION_CONFLICTS
