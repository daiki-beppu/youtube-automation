from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.commands.uploads._upload_cli_error_boundary import run_upload_cli
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
            "youtube_automation.commands.uploads.youtube_auto_uploader",
            ["yt-upload-auto", "--collection", "collection"],
            {"YouTubeAutoUploader": ValueError("auto failure")},
        ),
        (
            "youtube_automation.commands.uploads.collection_uploader",
            ["yt-upload-collection"],
            {"CollectionUploader": ValueError("collection failure")},
        ),
        (
            "youtube_automation.commands.uploads.short_uploader",
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
            "youtube_automation.commands.uploads.youtube_auto_uploader",
            ["yt-upload-auto"],
            "YouTubeAutoUploader",
            None,
        ),
        (
            "youtube_automation.commands.uploads.collection_uploader",
            ["yt-upload-collection"],
            "CollectionUploader",
            None,
        ),
        (
            "youtube_automation.commands.uploads.short_uploader",
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
        patch_values[f"{module_name}.load_config"] = SimpleNamespace(meta=SimpleNamespace(channel_short="test"))
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
    from youtube_automation.commands.uploads import short_uploader

    uploader = SimpleNamespace(show_plan=MagicMock())
    monkeypatch.setattr("sys.argv", ["yt-upload-shorts", collection, "--plan"])
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object()))

    short_uploader.main()

    uploader.show_plan.assert_called_once_with(expected, short_num=None)


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ("relative-collection", Path.cwd() / "relative-collection"),
        ("/tmp/absolute-collection", Path("/tmp/absolute-collection")),
    ],
)
def test_shorts_cli_normalizes_collection_to_absolute_path_for_upload(monkeypatch, capsys, collection, expected):
    from youtube_automation.commands.uploads import short_uploader

    uploader = SimpleNamespace(upload_short=MagicMock(return_value={"action": "short_uploaded"}))
    monkeypatch.setattr("sys.argv", ["yt-upload-shorts", collection])
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object()))

    short_uploader.main()

    uploader.upload_short.assert_called_once_with(expected, short_num=None)
    assert capsys.readouterr().out


@pytest.mark.parametrize(
    ("option", "expected_action", "preflight"),
    [
        ("--status", "show_status", False),
        ("--plan", "show_plan", True),
        (None, "execute_next_step", True),
    ],
)
def test_collection_cli_dispatches_normal_operation(monkeypatch, option, expected_action, preflight):
    from youtube_automation.commands.uploads import collection_uploader

    target = Path("/collection")
    uploader = SimpleNamespace(
        find_collection=MagicMock(return_value=target),
        ensure_upload_preflight=MagicMock(),
        show_status=MagicMock(),
        show_plan=MagicMock(),
        execute_next_step=MagicMock(),
    )
    argv = ["yt-upload-collection", "--collection", "slug", "--config", "/config.json"]
    if option:
        argv.append(option)
    factory = MagicMock(return_value=uploader)
    clients = object()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(collection_uploader, "CollectionUploader", factory)
    monkeypatch.setattr(
        collection_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=clients),
    )

    assert collection_uploader.main() is None

    factory.assert_called_once_with(config_path="/config.json", youtube_clients=clients)
    uploader.find_collection.assert_called_once_with("slug")
    assert uploader.ensure_upload_preflight.called is preflight
    getattr(uploader, expected_action).assert_called_once_with(target)


def test_collection_cli_daemon_skips_collection_lookup(monkeypatch):
    from youtube_automation.commands.uploads import collection_uploader

    uploader = SimpleNamespace(
        run_automated_schedule=MagicMock(),
        find_collection=MagicMock(),
    )
    monkeypatch.setattr("sys.argv", ["yt-upload-collection", "--daemon"])
    monkeypatch.setattr(collection_uploader, "CollectionUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        collection_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert collection_uploader.main() is None

    uploader.run_automated_schedule.assert_called_once_with()
    uploader.find_collection.assert_not_called()


def test_shorts_cli_failed_result_exits_one(monkeypatch):
    from youtube_automation.commands.uploads import short_uploader

    uploader = SimpleNamespace(upload_short=MagicMock(return_value={"action": short_uploader.ACTION_FAILED}))
    monkeypatch.setattr("sys.argv", ["yt-upload-shorts", "/collection", "--short-num", "2"])
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        short_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    with pytest.raises(SystemExit) as exc_info:
        short_uploader.main()

    assert exc_info.value.code == 1
    uploader.upload_short.assert_called_once_with(Path("/collection"), short_num=2)


@pytest.mark.parametrize(
    ("argv", "method", "expected_args"),
    [
        (["yt-upload-auto", "--collection", "slug"], "upload_collection", ("slug",)),
        (
            ["yt-upload-auto", "--batch", "--status", "ready", "planned"],
            "process_collections_directory",
            (["ready", "planned"],),
        ),
    ],
)
def test_auto_cli_initializes_then_dispatches(monkeypatch, argv, method, expected_args):
    from youtube_automation.commands.uploads import youtube_auto_uploader

    uploader = SimpleNamespace(
        initialize=MagicMock(),
        upload_collection=MagicMock(),
        process_collections_directory=MagicMock(),
    )
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(youtube_auto_uploader, "YouTubeAutoUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        youtube_auto_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert youtube_auto_uploader.main() is None

    uploader.initialize.assert_called_once_with()
    getattr(uploader, method).assert_called_once_with(*expected_args)


def test_auto_cli_without_operation_prints_usage(monkeypatch, capsys):
    from youtube_automation.commands.uploads import youtube_auto_uploader

    uploader = SimpleNamespace(
        initialize=MagicMock(),
        upload_collection=MagicMock(),
        process_collections_directory=MagicMock(),
    )
    monkeypatch.setattr("sys.argv", ["yt-upload-auto"])
    monkeypatch.setattr(youtube_auto_uploader, "YouTubeAutoUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        youtube_auto_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert youtube_auto_uploader.main() is None

    uploader.initialize.assert_called_once_with()
    uploader.upload_collection.assert_not_called()
    uploader.process_collections_directory.assert_not_called()
    assert "使用法:" in capsys.readouterr().out
