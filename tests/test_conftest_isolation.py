from __future__ import annotations

import os
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from youtube_automation import configuration


@pytest.fixture
def suite_config(request: pytest.FixtureRequest) -> ModuleType:
    expected = Path(__file__).with_name("conftest.py").resolve()
    for _name, plugin in request.config.pluginmanager.list_name_plugin():
        module_path = getattr(plugin, "__file__", None)
        if module_path and Path(module_path).resolve() == expected:
            return plugin
    pytest.fail("tests/conftest.py plugin is not registered")


def test_cleanup_removes_only_stale_owned_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suite_config: ModuleType,
) -> None:
    stale = tmp_path / f"{suite_config._TEST_TMP_PREFIX}999999-stale"
    active = tmp_path / f"{suite_config._TEST_TMP_PREFIX}{os.getpid()}-active"
    foreign = tmp_path / "unrelated"
    stale.mkdir()
    active.mkdir()
    foreign.mkdir()
    symlink = tmp_path / f"{suite_config._TEST_TMP_PREFIX}999998-link"
    symlink.symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(suite_config.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        suite_config,
        "_pid_is_running",
        lambda pid: pid == os.getpid(),
    )

    suite_config._cleanup_stale_isolated_channel_dirs()

    assert not stale.exists()
    assert active.is_dir()
    assert foreign.is_dir()
    assert symlink.is_symlink()


def test_prepare_preserves_explicit_channel_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suite_config: ModuleType,
) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(explicit))
    monkeypatch.delenv(suite_config._ISOLATED_MARKER_ENV, raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    cleanup = Mock()
    monkeypatch.setattr(
        suite_config,
        "_cleanup_stale_isolated_channel_dirs",
        cleanup,
    )

    suite_config._prepare_isolated_channel_dir()

    cleanup.assert_called_once_with()
    assert os.environ["CHANNEL_DIR"] == str(explicit)
    assert suite_config._ISOLATED_MARKER_ENV not in os.environ


def test_prepare_reisolates_controller_directory_for_xdist_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suite_config: ModuleType,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "marker.txt").write_text("fixture", encoding="utf-8")
    controller_dir = tmp_path / "controller"
    controller_dir.mkdir()
    worker_root = tmp_path / "worker-root"
    monkeypatch.setattr(suite_config, "_FIXTURE_CHANNEL_DIR", fixture)
    monkeypatch.setattr(
        suite_config.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(worker_root),
    )
    monkeypatch.setattr(suite_config.atexit, "register", Mock())
    monkeypatch.setattr(
        suite_config,
        "_cleanup_stale_isolated_channel_dirs",
        Mock(),
    )
    monkeypatch.setenv("CHANNEL_DIR", str(controller_dir))
    monkeypatch.setenv(suite_config._ISOLATED_MARKER_ENV, "1")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")

    suite_config._prepare_isolated_channel_dir()

    isolated = Path(os.environ["CHANNEL_DIR"])
    assert isolated == worker_root / "sample_channel"
    assert isolated != controller_dir
    assert (isolated / "marker.txt").read_text(encoding="utf-8") == "fixture"
    assert os.environ[suite_config._ISOLATED_MARKER_ENV] == "1"


def test_reset_fixture_resets_configuration_before_and_after_test(
    monkeypatch: pytest.MonkeyPatch,
    suite_config: ModuleType,
) -> None:
    reset = Mock(wraps=configuration.reset)
    monkeypatch.setattr(configuration, "reset", reset)
    fixture = suite_config._reset_config_singleton.__wrapped__()

    next(fixture)
    assert reset.call_count == 1
    with pytest.raises(StopIteration):
        next(fixture)
    assert reset.call_count == 2
