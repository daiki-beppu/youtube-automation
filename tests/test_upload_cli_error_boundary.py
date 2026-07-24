from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.agents._upload_cli_error_boundary import run_upload_cli
from youtube_automation.infrastructure.errors import AutomationError


@pytest.mark.parametrize(
    ("interrupt_message", "expected"),
    [
        ("ユーザーによって中断されました", "\n🛑 ユーザーによって中断されました\n"),
        ("処理が中断されました", "\n🛑 処理が中断されました\n"),
        ("中断されました", "\n🛑 中断されました\n"),
    ],
)
def test_run_upload_cli_preserves_interrupt_contract(capsys, interrupt_message, expected):
    with pytest.raises(SystemExit) as exc_info:
        run_upload_cli(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt),
            failure_message="エラー",
            interrupt_message=interrupt_message,
            interrupt_exit_code=130,
        )

    assert exc_info.value.code == 130
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    "error",
    [ValueError("invalid input"), OSError("unavailable"), AutomationError("domain failure")],
)
def test_run_upload_cli_converts_unexpected_errors_to_cli_contract(capsys, error):
    def operation():
        raise error

    with pytest.raises(SystemExit) as exc_info:
        run_upload_cli(
            operation,
            failure_message="エラー",
            interrupt_message="中断されました",
            interrupt_exit_code=130,
        )

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == f"❌ エラー: {error}\n"


def test_run_upload_cli_does_not_hide_unexpected_exceptions():
    with pytest.raises(RuntimeError, match="programming failure"):
        run_upload_cli(
            lambda: (_ for _ in ()).throw(RuntimeError("programming failure")),
            failure_message="エラー",
            interrupt_message="中断されました",
            interrupt_exit_code=130,
        )


@pytest.mark.parametrize(
    ("module_name", "argv", "patches"),
    [
        (
            "youtube_automation.agents.youtube_auto_uploader",
            ["yt-upload-auto", "--collection", "collection"],
            {"YouTubeAutoUploader": ValueError("auto failure")},
        ),
        (
            "youtube_automation.agents.collection_uploader",
            ["yt-upload-collection"],
            {"CollectionUploader": ValueError("collection failure")},
        ),
        (
            "youtube_automation.agents.short_uploader",
            ["yt-upload-shorts", "collection"],
            {"ShortUploader": ValueError("short failure")},
        ),
    ],
)
def test_each_upload_cli_converts_value_error(capsys, monkeypatch, module_name, argv, patches):
    module = __import__(module_name, fromlist=["main"])
    monkeypatch.setattr("sys.argv", argv)
    patch_values = {}
    if hasattr(module, "load_config"):
        patch_values[f"{module_name}.load_config"] = SimpleNamespace(meta=SimpleNamespace(channel_short="test"))
    if hasattr(module, "create_authenticated_youtube_clients"):
        patch_values[f"{module_name}.create_authenticated_youtube_clients"] = object()

    with ExitStack() as stack:
        for target, value in patch_values.items():
            stack.enter_context(patch(target, return_value=value))
        for name, error in patches.items():
            stack.enter_context(patch(f"{module_name}.{name}", side_effect=error))
        with pytest.raises(SystemExit) as exc_info:
            module.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.startswith("❌ エラー:")


@pytest.mark.parametrize(
    ("module_name", "argv", "patch_target", "expected_code"),
    [
        (
            "youtube_automation.agents.youtube_auto_uploader",
            ["yt-upload-auto"],
            "YouTubeAutoUploader",
            None,
        ),
        (
            "youtube_automation.agents.collection_uploader",
            ["yt-upload-collection"],
            "CollectionUploader",
            None,
        ),
        (
            "youtube_automation.agents.short_uploader",
            ["yt-upload-shorts", "collection"],
            "ShortUploader",
            130,
        ),
    ],
)
def test_each_upload_cli_preserves_interrupt_exit_contract(
    capsys, monkeypatch, module_name, argv, patch_target, expected_code
):
    module = __import__(module_name, fromlist=["main"])
    monkeypatch.setattr("sys.argv", argv)
    patch_values = {}
    if hasattr(module, "load_config"):
        patch_values[f"{module_name}.load_config"] = SimpleNamespace(
            meta=SimpleNamespace(channel_short="test")
        )
    if hasattr(module, "create_authenticated_youtube_clients"):
        patch_values[f"{module_name}.create_authenticated_youtube_clients"] = object()

    with ExitStack() as stack:
        for target, value in patch_values.items():
            stack.enter_context(patch(target, return_value=value))
        stack.enter_context(patch(f"{module_name}.{patch_target}", side_effect=KeyboardInterrupt))
        if expected_code is None:
            module.main()
        else:
            with pytest.raises(SystemExit) as exc_info:
                module.main()
            assert exc_info.value.code == expected_code

    assert "🛑" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ("relative-collection", Path.cwd() / "relative-collection"),
        ("/tmp/absolute-collection", Path("/tmp/absolute-collection")),
    ],
)
def test_shorts_cli_normalizes_collection_to_absolute_path_for_plan(monkeypatch, collection, expected):
    from youtube_automation.agents import short_uploader

    uploader = SimpleNamespace(show_plan=MagicMock())
    monkeypatch.setattr("sys.argv", ["yt-upload-shorts", collection, "--plan"])
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object())
    )

    short_uploader.main()

    uploader.show_plan.assert_called_once_with(expected, short_num=None)


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ("relative-collection", Path.cwd() / "relative-collection"),
        ("/tmp/absolute-collection", Path("/tmp/absolute-collection")),
    ],
)
def test_shorts_cli_normalizes_collection_to_absolute_path_for_upload(
    monkeypatch, capsys, collection, expected
):
    from youtube_automation.agents import short_uploader

    uploader = SimpleNamespace(upload_short=MagicMock(return_value={"action": "short_uploaded"}))
    monkeypatch.setattr("sys.argv", ["yt-upload-shorts", collection])
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object())
    )

    short_uploader.main()

    uploader.upload_short.assert_called_once_with(expected, short_num=None)
    assert capsys.readouterr().out
