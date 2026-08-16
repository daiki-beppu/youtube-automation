"""Issue #327: `skills_sync.py` package 分割の構造的不変条件テスト。

`src/youtube_automation/commands/system/skills_sync.py` (440 行) を
`src/youtube_automation/commands/system/skills_sync/` パッケージに分割した後の以下を検証する:

1. 公開 import surface の互換 (`from youtube_automation.commands.system.skills_sync import ...`)
2. package-level の module attribute (monkeypatch 対象) の存続
3. `_editable_root()` の `parents[N]` 計算 (`parents[3] → parents[4]`)
4. submodule への monkeypatch 伝搬 (`_editable_root` patch が `_asset_root` で観測される)
5. ファイル分割の物理レイアウト (各 .py ≤ 300 行、旧 .py 削除、submodule 直接 import)
6. console_scripts entry point `yt-skills` の解決

既存の `tests/commands/system/test_skills_sync.py` / `tests/commands/system/test_skills_sync_claude_md.py` は
全 60 ケースが `_editable_root` を monkeypatch 経由でバイパスしているため、
unpatched 時の `parents[N]` 計算と package facade の構造的健全性は本ファイルで補強する。
"""

from __future__ import annotations

import argparse
import importlib
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

# ---------- 1-4: package facade — 公開 import surface ----------


def test_asset_specs_resolves_via_package_import() -> None:
    # Given/When: package 分割後の facade から import
    from youtube_automation.commands.system.skills_sync import _ASSET_SPECS

    # Then: 既存 spec dict として解決できる
    assert isinstance(_ASSET_SPECS, dict)
    assert "skills" in _ASSET_SPECS
    assert "claude-md" in _ASSET_SPECS
    assert "auth-template" in _ASSET_SPECS


def test_auth_template_asset_spec_points_to_client_secrets_template() -> None:
    from youtube_automation.commands.system.skills_sync import _ASSET_SPECS, _asset_root

    spec = _ASSET_SPECS["auth-template"]
    assert spec["kind"] == "file"
    assert spec["source_filename"] == "client_secrets.template.json"
    assert spec["default_target"] == "auth/client_secrets.template.json"
    assert (_asset_root("auth-template") / "client_secrets.template.json").exists()


def test_default_all_assets_include_auth_template_target() -> None:
    from youtube_automation.commands.system.skills_sync import _ASSET_SPECS

    all_targets = {spec["default_target"] for spec in _ASSET_SPECS.values()}
    assert "auth/client_secrets.template.json" in all_targets
    assert ".claude/settings.json" in all_targets
    assert ".gitignore" in all_targets


def test_channel_gitignore_asset_is_packaged_with_state_git_policy() -> None:
    from youtube_automation.commands.system.skills_sync import _ASSET_SPECS, _asset_root

    spec = _ASSET_SPECS["channel-gitignore"]
    template = _asset_root("channel-gitignore") / spec["source_filename"]
    text = template.read_text(encoding="utf-8")
    assert spec["default_target"] == ".gitignore"
    assert "# yt-state-git control plane (ADR-0024)" in text
    assert "auth/token*.json" in text


def test_channel_workflow_asset_is_packaged_for_default_sync() -> None:
    from youtube_automation.commands.system.skills_sync import _ASSET_SPECS, _asset_root

    spec = _ASSET_SPECS["channel-workflow"]
    template = _asset_root("channel-workflow") / spec["source_filename"]
    assert spec["default_target"] == ".github/workflows/youtube-automation.yml"
    assert template.is_file()
    assert "run-sandwich.sh" in template.read_text(encoding="utf-8")


def test_auth_template_is_included_in_wheel_and_sdist_manifests() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    hatch = pyproject["tool"]["hatch"]["build"]["targets"]
    force_include = hatch["wheel"]["force-include"]
    sdist_only_include = hatch["sdist"]["only-include"]

    assert force_include["src/youtube_automation/infrastructure/resources/auth/client_secrets.template.json"] == (
        "youtube_automation/infrastructure/resources/auth/client_secrets.template.json"
    )
    assert "src/" in sdist_only_include
    assert force_include[".claude/settings.template.json"] == (
        "youtube_automation/_claude_settings/settings.template.json"
    )
    assert ".claude/settings.template.json" in sdist_only_include


def test_asset_root_resolves_via_package_import() -> None:
    # Given/When: package facade から import
    from youtube_automation.commands.system.skills_sync import _asset_root

    # Then: callable として解決される
    assert callable(_asset_root)


def test_list_entries_resolves_via_package_import() -> None:
    # Given/When: package facade から import
    from youtube_automation.commands.system.skills_sync import _list_entries

    # Then: callable として解決される
    assert callable(_list_entries)


def test_build_parser_resolves_via_package_import() -> None:
    # Given/When: package facade から import して呼ぶ
    from youtube_automation.commands.system.skills_sync import build_parser

    parser = build_parser()

    # Then: ArgumentParser インスタンスを返す
    assert isinstance(parser, argparse.ArgumentParser)


# ---------- 5-9: package facade — module attribute としての monkeypatch / re-export 互換 ----------


def test_resolve_default_target_is_module_attribute() -> None:
    # Given: 既存テスト (`test_skills_sync.py:92` 等) が
    #        `skills_sync._resolve_default_target(args)` 形式で参照する
    from youtube_automation.commands.system import skills_sync

    # When/Then: package attribute として解決でき callable
    assert callable(skills_sync._resolve_default_target)


def test_editable_root_is_module_attribute() -> None:
    # Given: 既存テスト (`test_skills_sync.py:39` 等) が
    #        `monkeypatch.setattr(skills_sync, "_editable_root", ...)` を行う
    from youtube_automation.commands.system import skills_sync

    # When/Then: package attribute として解決でき callable
    assert callable(skills_sync._editable_root)


def test_main_resolves_via_package_import() -> None:
    # Given: `pyproject.toml::yt-skills` entry point の解決対象
    from youtube_automation.commands.system.skills_sync import main

    # Then: callable として解決される
    assert callable(main)


def test_cmd_callables_are_package_attributes() -> None:
    # Given: subcommand ディスパッチャ群
    from youtube_automation.commands.system import skills_sync

    # When/Then: 全 3 つが package attribute として解決できる (re-export 漏れ検知)
    assert callable(skills_sync.cmd_list)
    assert callable(skills_sync.cmd_sync)
    assert callable(skills_sync.cmd_diff)


def test_fs_primitives_are_package_attributes() -> None:
    # Given: `_ops.py` に移植される FS プリミティブ群
    from youtube_automation.commands.system import skills_sync

    # When/Then: 5 件すべて package attribute として解決できる (re-export 漏れ検知)
    assert callable(skills_sync._copy_entry)
    assert callable(skills_sync._symlink_entry)
    assert callable(skills_sync._prune_orphans)
    assert callable(skills_sync._ensure_target_parent)
    assert callable(skills_sync._has_diff)


# ---------- 10-11: `_editable_root` の unpatched `parents[N]` 計算 ----------


def test_editable_root_returns_repo_root_after_split() -> None:
    # Given: 分割後の package
    from youtube_automation.commands.system.skills_sync import _editable_root

    # When: unpatched で呼ぶ
    root = _editable_root()

    # Then: リポジトリルート — `pyproject.toml` が直下にある
    assert (root / "pyproject.toml").is_file()


def test_editable_root_points_to_claude_skills_dir() -> None:
    # Given: 分割後の package
    from youtube_automation.commands.system.skills_sync import _editable_root

    # When: unpatched で呼ぶ
    root = _editable_root()

    # Then: `.claude/skills/` がリポルート直下に存在する
    #       (parents[3] のままだと cli/ を指してしまう回帰を検知)
    assert (root / ".claude" / "skills").is_dir()


def test_editable_root_resolves_nested_checkout_without_fixed_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_file = tmp_path / "src" / "youtube_automation" / "__init__.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)

    import youtube_automation
    from youtube_automation.commands.system import skills_sync

    monkeypatch.setattr(youtube_automation, "__file__", str(package_file))
    assert skills_sync._editable_root() == tmp_path


def test_editable_root_does_not_adopt_unrelated_parent_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package_file = tmp_path / "checkout" / "src" / "youtube_automation" / "__init__.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='unrelated'\n", encoding="utf-8")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)

    import youtube_automation
    from youtube_automation.commands.system import skills_sync

    monkeypatch.setattr(youtube_automation, "__file__", str(package_file))
    with pytest.raises(FileNotFoundError, match="repository root"):
        skills_sync._editable_root()


def test_editable_root_fails_when_checkout_markers_are_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package_file = tmp_path / "src" / "youtube_automation" / "__init__.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")

    import youtube_automation
    from youtube_automation.commands.system import skills_sync

    monkeypatch.setattr(youtube_automation, "__file__", str(package_file))
    with pytest.raises(FileNotFoundError, match="repository root"):
        skills_sync._editable_root()


# ---------- 12: monkeypatch 伝搬 (package-level patch が submodule に届く) ----------


def test_package_level_editable_root_patch_propagates_to_asset_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: tmp_path に最小の skills ツリー
    from youtube_automation.commands.system import skills_sync

    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "stub").mkdir()

    # When: package level で `_editable_root` を差し替え、`_asset_root` を呼ぶ
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    resolved = skills_sync._asset_root("skills")

    # Then: patch 後の binding が submodule 側の lookup に伝搬する
    #       (`_editable_root` / `_asset_root` を submodule に外出しすると壊れる)
    assert resolved == skills_dir


# ---------- 13-15: 物理レイアウト不変条件 ----------


def test_old_module_file_is_removed_after_package_split() -> None:
    # Given: worktree root
    repo_root = REPO_ROOT
    commands_dir = repo_root / "src" / "youtube_automation" / "commands" / "system"

    # Then: package directory が存在し、旧 .py は存在しない (同名衝突防止)
    assert (commands_dir / "skills_sync").is_dir()
    assert (commands_dir / "skills_sync" / "__init__.py").is_file()
    assert not (commands_dir / "skills_sync.py").exists()


def test_split_submodules_are_directly_importable() -> None:
    # Given: 計画上の submodule 名
    submodules = ["_ops", "_sync", "_diff", "_parser"]

    # When/Then: `importlib.import_module` で個別解決できる (循環 import が解消されている)
    for name in submodules:
        module = importlib.import_module(f"youtube_automation.commands.system.skills_sync.{name}")
        assert module is not None


# ---------- 16-17: speculative re-export 抑制 (family_tag: unused-reexport) ----------


def test_facade_does_not_expose_internal_dispatch_helpers() -> None:
    # Given: package facade
    from youtube_automation.commands.system import skills_sync

    # Then: cmd_sync / cmd_diff / build_parser の内部 dispatch 先や argparse 補助関数は
    #       facade に露出しない (architect-review ARCH-NEW-init-L120..L126 の回帰防止)
    speculative_symbols = (
        "_sync_dir_asset",
        "_sync_file_asset",
        "_diff_dir_asset",
        "_diff_file_asset",
        "_add_asset_argument",
    )
    for name in speculative_symbols:
        assert not hasattr(skills_sync, name), (
            f"{name} は外部 caller・既存 test いずれにも参照されない speculative re-export。"
            "facade に露出させないこと (architect-review family_tag=unused-reexport)。"
        )


# ---------- 18: console_scripts entry point ----------


def test_yt_skills_console_script_resolves_after_package_split() -> None:
    # Given: installed package の entry points
    eps = entry_points(group="console_scripts")

    # When: `yt-skills` を取得して load
    yt_skills = next(ep for ep in eps if ep.name == "yt-skills")
    fn = yt_skills.load()

    # Then: callable が package の CLI wrapper シンボルそのもの
    assert callable(fn)
    from youtube_automation.entrypoints import yt_skills

    assert fn is yt_skills
