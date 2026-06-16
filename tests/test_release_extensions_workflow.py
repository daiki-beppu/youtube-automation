"""`release-extensions.yml` の配布契約を静的に検証する（Issue #1022）。

統一タグ `ext-v*` で suno-helper / distrokid-helper の両 zip を単一 Release に
添付し、Release 本文にインストール/更新手順テンプレが埋め込まれていることを担保する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "release-extensions.yml"

_RELEASE_TAG_GLOB = "ext-v*"
_GH_RELEASE_ACTION = "softprops/action-gh-release@v2"
_EXTENSIONS = ("suno-helper", "distrokid-helper")
_ZIP_GLOBS = tuple(f"extensions/{name}/.output/*.zip" for name in _EXTENSIONS)
# order.md が要求する手順アンカー。初回インストール（URL + Load unpacked）と
# 更新（リロード）の両セクションが本文に埋め込まれていることを最小限で担保する。
_BODY_REQUIRED_PHRASES = (
    "chrome://extensions",
    "Load unpacked",
    "リロード",
)


def _read_text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _load_workflow() -> dict[str, object]:
    return yaml.safe_load(_read_text(_WORKFLOW_PATH))


def _on_section(workflow: dict[str, object]) -> dict[str, object]:
    # PyYAML は YAML 1.1 に従い `on:` を真偽値 True キーへ変換する。
    section = workflow.get("on", workflow.get(True))
    assert isinstance(section, dict), "on トリガセクションが存在しない"
    return section


def _release_steps() -> list[dict[str, object]]:
    workflow = _load_workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "jobs セクションが存在しない"
    release_job = jobs.get("release")
    assert isinstance(release_job, dict), "release job が存在しない"
    assert release_job.get("runs-on") == "ubuntu-latest"
    steps = release_job.get("steps")
    assert isinstance(steps, list) and steps, "release job に steps が存在しない"
    return steps


def test_triggers_on_unified_extension_tag() -> None:
    """統一タグ `ext-v*` の push のみで起動する契約を固定する。"""
    on_section = _on_section(_load_workflow())
    push = on_section.get("push")
    assert isinstance(push, dict), "push トリガが存在しない"
    assert push.get("tags") == [_RELEASE_TAG_GLOB]


def test_grants_contents_write_permission() -> None:
    """Release 添付には contents: write が必要。"""
    workflow = _load_workflow()
    assert workflow.get("permissions") == {"contents": "write"}


@pytest.mark.parametrize("name", _EXTENSIONS)
def test_builds_and_zips_each_extension(name: str) -> None:
    """両拡張がそれぞれの作業ディレクトリで install → zip される。"""
    steps = _release_steps()
    matched = [
        step
        for step in steps
        if step.get("working-directory") == f"extensions/{name}" and "pnpm zip" in str(step.get("run", ""))
    ]
    assert matched, f"{name} の build/zip ステップが存在しない"
    run_script = str(matched[0]["run"])
    assert "pnpm install --frozen-lockfile" in run_script


def test_attaches_both_zips_to_single_release() -> None:
    """単一の gh-release ステップで両拡張の zip を添付する。"""
    steps = _release_steps()
    release_steps = [step for step in steps if str(step.get("uses", "")).startswith(_GH_RELEASE_ACTION)]
    assert len(release_steps) == 1, "gh-release ステップは 1 個に集約する"

    files_value = str(release_steps[0].get("with", {}).get("files", ""))
    for zip_glob in _ZIP_GLOBS:
        assert zip_glob in files_value, f"{zip_glob} が files に含まれていない"


def test_release_body_embeds_install_and_update_template() -> None:
    """Release 本文に初回インストール/更新手順テンプレが埋め込まれている。"""
    steps = _release_steps()
    release_step = next(step for step in steps if str(step.get("uses", "")).startswith(_GH_RELEASE_ACTION))
    body = str(release_step.get("with", {}).get("body", ""))
    assert body, "Release 本文テンプレ (body) が未設定"
    for phrase in _BODY_REQUIRED_PHRASES:
        assert phrase in body, f"Release 本文テンプレに必須フレーズが欠落: {phrase}"
