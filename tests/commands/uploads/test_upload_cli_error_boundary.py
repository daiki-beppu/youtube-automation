from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


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
def test_each_upload_cli_converts_value_error_to_stderr(capsys, module_name, argv, patches):
    module = __import__(module_name, fromlist=["main"])
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
        exit_code = module.main(argv[1:])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("❌ エラー:")


@pytest.mark.parametrize(
    ("module_name", "argv", "patch_target", "expected_code"),
    [
        (
            "youtube_automation.commands.uploads.youtube_auto_uploader",
            ["yt-upload-auto"],
            "YouTubeAutoUploader",
            0,
        ),
        (
            "youtube_automation.commands.uploads.collection_uploader",
            ["yt-upload-collection"],
            "CollectionUploader",
            0,
        ),
        (
            "youtube_automation.commands.uploads.short_uploader",
            ["yt-upload-shorts", "collection"],
            "ShortUploader",
            130,
        ),
    ],
)
def test_each_upload_cli_preserves_interrupt_exit_contract(capsys, module_name, argv, patch_target, expected_code):
    module = __import__(module_name, fromlist=["main"])
    patch_values = {}
    if hasattr(module, "load_config"):
        patch_values[f"{module_name}.load_config"] = SimpleNamespace(meta=SimpleNamespace(channel_short="test"))
    if hasattr(module, "create_authenticated_youtube_clients"):
        patch_values[f"{module_name}.create_authenticated_youtube_clients"] = object()

    with ExitStack() as stack:
        for target, value in patch_values.items():
            stack.enter_context(patch(target, return_value=value))
        stack.enter_context(patch(f"{module_name}.{patch_target}", side_effect=KeyboardInterrupt))
        assert module.main(argv[1:]) == expected_code

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
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object()))

    assert short_uploader.main([collection, "--plan"]) == 0

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
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(short_uploader, "create_authenticated_youtube_clients", MagicMock(return_value=object()))

    assert short_uploader.main([collection]) == 0

    uploader.upload_short.assert_called_once_with(expected, short_num=None)
    assert capsys.readouterr().out


@pytest.mark.parametrize(
    ("option", "expected_action", "preflight"),
    [
        ("--status", "show_status", False),
        # show_plan は表示専用なので CLI が preflight を明示的に依頼する。
        ("--plan", "show_plan", True),
        # execute 経路は upload_collection 内部で 1 回だけ preflight が走る。
        (None, "execute_next_step", False),
    ],
)
def test_collection_cli_dispatches_normal_operation(monkeypatch, option, expected_action, preflight):
    from youtube_automation.commands.uploads import collection_uploader

    target = Path("/collection")
    uploader = SimpleNamespace(
        find_collection=MagicMock(return_value=target),
        preflight_check=MagicMock(),
        show_status=MagicMock(),
        show_plan=MagicMock(),
        execute_next_step=MagicMock(),
    )
    argv = ["--collection", "slug", "--config", "/config.json"]
    if option:
        argv.append(option)
    factory = MagicMock(return_value=uploader)
    clients = object()
    monkeypatch.setattr(collection_uploader, "CollectionUploader", factory)
    monkeypatch.setattr(
        collection_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=clients),
    )

    assert collection_uploader.main(argv) == 0

    factory.assert_called_once_with(
        config_path="/config.json",
        youtube_clients=clients,
        allow_duration_outside_target=False,
    )
    uploader.find_collection.assert_called_once_with("slug")
    assert uploader.preflight_check.called is preflight
    getattr(uploader, expected_action).assert_called_once_with(target)


def test_collection_cli_forwards_duration_override_to_uploader(monkeypatch):
    from youtube_automation.commands.uploads import collection_uploader

    # Given: 対象 collection が見つからない副作用なしの uploader
    uploader = SimpleNamespace(find_collection=MagicMock(return_value=None))
    factory = MagicMock(return_value=uploader)
    clients = object()
    monkeypatch.setattr(collection_uploader, "CollectionUploader", factory)
    monkeypatch.setattr(
        collection_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=clients),
    )

    # When: operator が目標尺外を明示許可する
    assert collection_uploader.main(["--allow-duration-outside-target"]) == 0

    # Then: CLI の opt-in が domain constructor へ伝わる
    factory.assert_called_once_with(
        config_path=None,
        youtube_clients=clients,
        allow_duration_outside_target=True,
    )


def test_collection_cli_daemon_skips_collection_lookup(monkeypatch):
    from youtube_automation.commands.uploads import collection_uploader

    uploader = SimpleNamespace(
        run_automated_schedule=MagicMock(),
        find_collection=MagicMock(),
    )
    monkeypatch.setattr(collection_uploader, "CollectionUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        collection_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert collection_uploader.main(["--daemon"]) == 0

    uploader.run_automated_schedule.assert_called_once_with()
    uploader.find_collection.assert_not_called()


def test_shorts_cli_failed_result_exits_one(monkeypatch):
    from youtube_automation.commands.uploads import short_uploader

    uploader = SimpleNamespace(upload_short=MagicMock(return_value={"action": short_uploader.ACTION_FAILED}))
    monkeypatch.setattr(short_uploader, "ShortUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        short_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert short_uploader.main(["/collection", "--short-num", "2"]) == 1
    uploader.upload_short.assert_called_once_with(Path("/collection"), short_num=2)


@pytest.mark.parametrize(
    ("argv", "method", "expected_args"),
    [
        (["--collection", "slug"], "upload_collection", ("slug",)),
        (
            ["--batch", "--status", "ready", "planned"],
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
    monkeypatch.setattr(youtube_auto_uploader, "YouTubeAutoUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        youtube_auto_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert youtube_auto_uploader.main(argv) == 0

    uploader.initialize.assert_called_once_with()
    getattr(uploader, method).assert_called_once_with(*expected_args)


def test_auto_cli_without_operation_prints_usage(monkeypatch, capsys):
    from youtube_automation.commands.uploads import youtube_auto_uploader

    uploader = SimpleNamespace(
        initialize=MagicMock(),
        upload_collection=MagicMock(),
        process_collections_directory=MagicMock(),
    )
    monkeypatch.setattr(youtube_auto_uploader, "YouTubeAutoUploader", MagicMock(return_value=uploader))
    monkeypatch.setattr(
        youtube_auto_uploader,
        "create_authenticated_youtube_clients",
        MagicMock(return_value=object()),
    )

    assert youtube_auto_uploader.main([]) == 0

    uploader.initialize.assert_called_once_with()
    uploader.upload_collection.assert_not_called()
    uploader.process_collections_directory.assert_not_called()
    assert "使用法:" in capsys.readouterr().out
