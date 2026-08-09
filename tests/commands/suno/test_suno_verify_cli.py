"""yt-suno-verify CLI 配線の契約テスト."""

from __future__ import annotations

import sys
import tomllib

import pytest

from tests.helpers.paths import REPO_ROOT
from tests.helpers.suno_verify import load_suno_verify_module
from youtube_automation.core.errors import ConfigError, ValidationError


def test_pyproject_registers_yt_suno_verify_script():
    """Given pyproject.toml
    When project.scripts を読む
    Then yt-suno-verify が集約 entrypoint に登録されている。
    """
    root = REPO_ROOT
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["scripts"].get("yt-suno-verify") == ("youtube_automation.entrypoints:yt_suno_verify")


def test_cli_entrypoint_routes_to_suno_verify_module(monkeypatch):
    """Given entrypoints の yt_suno_verify
    When console script wrapper を呼ぶ
    Then suno_verify module の main へ委譲する。
    """
    from youtube_automation import entrypoints

    seen: dict[str, str] = {}

    def fake_run(module_path: str, function_name: str = "main") -> str:
        seen["module_path"] = module_path
        seen["function_name"] = function_name
        return "called"

    monkeypatch.setattr(entrypoints, "_run", fake_run)

    assert entrypoints.yt_suno_verify() == "called"
    assert seen == {
        "module_path": "youtube_automation.commands.suno.suno_verify",
        "function_name": "main",
    }


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """Given --help
    When yt-suno-verify を起動する
    Then usage を表示して exit 0 する。
    """
    module = load_suno_verify_module()
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_collection_resolution_failure_returns_one_and_prints_error(monkeypatch, capsys):
    """REQ-2729-08: collection 入口解決失敗は traceback ではなく exit 1 と ERROR を返す."""
    module = load_suno_verify_module()
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "missing"])
    monkeypatch.setattr(
        module,
        "_resolve_collection_argument",
        lambda _collection: (_ for _ in ()).throw(ValidationError("collection missing")),
    )

    assert module.main() == 1
    assert capsys.readouterr().out == "ERROR: collection missing\n"


def test_config_loading_failure_returns_one_and_prints_error(monkeypatch, capsys, tmp_path):
    """REQ-2729-09: 設定読込失敗も exit 1 と ERROR に正規化する."""
    module = load_suno_verify_module()
    collection = tmp_path / "collection"
    collection.mkdir()
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", str(collection)])
    monkeypatch.setattr(module, "resolve_collection_dir", lambda _collection: collection)
    monkeypatch.setattr(
        module,
        "load_skill_config",
        lambda _skill: (_ for _ in ()).throw(ConfigError("suno config invalid")),
    )

    assert module.main() == 1
    assert capsys.readouterr().out == "ERROR: suno config invalid\n"


def test_bare_collection_name_prefers_planning_over_live(monkeypatch, tmp_path):
    """bare name が planning / live の両方にある場合は planning を検証する."""
    module = load_suno_verify_module()
    channel = tmp_path / "channel"
    planning = channel / "collections" / "planning" / "same-name"
    live = channel / "collections" / "live" / "same-name"
    planning.mkdir(parents=True)
    live.mkdir(parents=True)
    seen: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "same-name"])
    monkeypatch.setattr(module, "channel_dir", lambda: channel)
    monkeypatch.setattr(module, "load_skill_config", lambda _skill: {})
    monkeypatch.setattr(module, "resolve_suno_config", lambda _config: object())

    def fake_verify(collection, config, infer_mode):
        seen.update(collection=collection, config=config, infer_mode=infer_mode)
        return [], "verified"

    monkeypatch.setattr(module, "verify_suno_collection", fake_verify)

    assert module.main() == 0
    assert seen["collection"] == planning.resolve()


def test_bare_collection_name_falls_back_to_live(monkeypatch, tmp_path):
    """bare name が planning に無く live にある場合は live を検証する."""
    module = load_suno_verify_module()
    channel = tmp_path / "channel"
    live = channel / "collections" / "live" / "live-only"
    live.mkdir(parents=True)
    seen: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "live-only"])
    monkeypatch.setattr(module, "channel_dir", lambda: channel)
    monkeypatch.setattr(module, "load_skill_config", lambda _skill: {})
    monkeypatch.setattr(module, "resolve_suno_config", lambda _config: object())
    monkeypatch.setattr(
        module,
        "verify_suno_collection",
        lambda collection, _config, _infer_mode: (seen.update(collection=collection) or [], "verified"),
    )

    assert module.main() == 0
    assert seen["collection"] == live.resolve()


@pytest.mark.parametrize("path_kind", ["relative", "absolute"])
def test_explicit_collection_path_is_preserved(monkeypatch, tmp_path, path_kind):
    """既存の相対パス・絶対パス指定は collection-name 探索へ置換しない."""
    module = load_suno_verify_module()
    collection = tmp_path / "explicit"
    collection.mkdir()
    monkeypatch.chdir(tmp_path)
    argument = "explicit" if path_kind == "relative" else str(collection)
    seen: dict[str, object] = {}

    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", argument])
    monkeypatch.setattr(module, "channel_dir", lambda: tmp_path / "channel")
    monkeypatch.setattr(module, "load_skill_config", lambda _skill: {})
    monkeypatch.setattr(module, "resolve_suno_config", lambda _config: object())
    monkeypatch.setattr(
        module,
        "verify_suno_collection",
        lambda resolved, _config, _infer_mode: (seen.update(collection=resolved) or [], "verified"),
    )

    assert module.main() == 0
    assert seen["collection"] == collection.resolve()


def test_missing_bare_collection_name_returns_one_and_prints_error(monkeypatch, capsys, tmp_path):
    """planning / live に無い bare name は ERROR と exit 1 に正規化する."""
    module = load_suno_verify_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", "missing"])
    monkeypatch.setattr(module, "channel_dir", lambda: tmp_path / "channel")

    assert module.main() == 1
    assert capsys.readouterr().out == (
        "ERROR: コレクション 'missing' が collections/planning/ にも collections/live/ にも見つかりません\n"
    )
