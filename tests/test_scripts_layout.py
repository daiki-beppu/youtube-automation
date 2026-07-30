"""ルート ``scripts/`` と ``.claude/skills/<skill>/references/`` のレイアウト regression を検出する。

Issue #140: skill 固有スクリプト (``generate_videos.sh`` / ``worktree_sync.sh``) を
ルート ``scripts/`` から ``.claude/skills/<skill>/references/`` 配下に canonical 化する整理。

Issue #388: ``scripts/gcp-bootstrap.sh`` / ``scripts/gcp-terraform-apply.sh`` が
``.claude/skills/channel-new/references/`` 側と MD5 完全一致していたため、
ルート ``scripts/`` 側を削除し canonical path に一本化する整理。

このテストは以下の不変条件を維持する:

1. ルート ``scripts/`` は空であること（skill 固有スクリプトも共通スクリプトも存在しない）。
   Issue #388 で ``gcp-bootstrap.sh`` / ``gcp-terraform-apply.sh`` を削除済み (CLAUDE.md 規約)。
2. ``gcp-bootstrap.sh`` / ``gcp-terraform-apply.sh`` の canonical path は
   ``.claude/skills/channel-new/references/`` 配下に実ファイルとして存在すること。
3. skill 配下の参照スクリプトは **実ファイル**（symlink ではない）かつ実行可能。
   逆向き symlink になっていた旧構成への regression を防ぐ。
4. 移動後のスクリプトは ``bash -n`` で構文エラーがない。

ファイル配置と実行可能性の契約だけを検証する。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

# 整理対象: ルートから削除されるべき skill 固有スクリプト
_OLD_GENERATE_VIDEOS = _SCRIPTS_DIR / "generate_videos.sh"
_OLD_WORKTREE_SYNC = _SCRIPTS_DIR / "worktree_sync.sh"

# 整理対象: skill 配下に実ファイルとして配置されるべきパス
_NEW_GENERATE_VIDEOS = _SKILLS_DIR / "videoup" / "references" / "generate_videos.sh"
_NEW_WORKTREE_SYNC = _SKILLS_DIR / "lyria" / "references" / "worktree_sync.sh"

# Issue #388 で削除済み: scripts/ は現在空。共通スクリプトは存在しない
_COMMON_SCRIPTS: set[str] = set()

# Issue #388 の canonical path: channel-new skill 配下
_CHANNEL_NEW_REFERENCES = _SKILLS_DIR / "channel-new" / "references"
_CANONICAL_GCP_BOOTSTRAP = _CHANNEL_NEW_REFERENCES / "gcp-bootstrap.sh"
_CANONICAL_GCP_TERRAFORM_APPLY = _CHANNEL_NEW_REFERENCES / "gcp-terraform-apply.sh"

# Issue #388 で scripts/ から削除されたパス
_OLD_GCP_BOOTSTRAP = _SCRIPTS_DIR / "gcp-bootstrap.sh"
_OLD_GCP_TERRAFORM_APPLY = _SCRIPTS_DIR / "gcp-terraform-apply.sh"

_LEGACY_CHANNEL_SETUP_REFERENCES = (
    "channel-setup" + "/references",
    ".claude/skills/" + "channel-setup",
)
_STALE_REFERENCE_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".takt",
    ".venv",
    ".worktrees",
    "__pycache__",
    "node_modules",
}
_STALE_REFERENCE_EXCLUDED_FILES = {"CHANGELOG.md"}
_STALE_REFERENCE_EXCLUDED_PATH_PREFIXES = {
    ("docs", "audits"),
    ("docs", "superpowers"),
}


# ---------- 共通ヘルパー ----------


def _bash_available() -> bool:
    return shutil.which("bash") is not None


def _is_stale_reference_scan_target(path: Path) -> bool:
    relative = path.relative_to(_REPO_ROOT)
    if relative.name in _STALE_REFERENCE_EXCLUDED_FILES:
        return False
    if any(relative.parts[: len(prefix)] == prefix for prefix in _STALE_REFERENCE_EXCLUDED_PATH_PREFIXES):
        return False
    return not any(part in _STALE_REFERENCE_EXCLUDED_DIRS for part in relative.parts)


# ---------- ルート scripts/ から skill 固有ファイルが消えているか ----------


def test_root_scripts_generate_videos_is_removed() -> None:
    """Given Issue #140 の整理後の状態
    When ルート ``scripts/generate_videos.sh`` を確認する
    Then ファイル（および broken symlink）として一切存在しない。

    ``Path.exists()`` は broken symlink を ``False`` と扱うため、
    symlink 残骸も検出できるよう ``lexists`` で確認する。
    """
    assert not os.path.lexists(_OLD_GENERATE_VIDEOS), (
        f"{_OLD_GENERATE_VIDEOS.relative_to(_REPO_ROOT)} が残存している。"
        " skill 固有スクリプトはルート scripts/ から削除し、"
        " .claude/skills/videoup/references/ 配下に置くこと (Issue #140)"
    )


def test_root_scripts_worktree_sync_is_removed() -> None:
    """Given Issue #140 の整理後の状態
    When ルート ``scripts/worktree_sync.sh`` を確認する
    Then ファイル（および broken symlink）として一切存在しない。
    """
    assert not os.path.lexists(_OLD_WORKTREE_SYNC), (
        f"{_OLD_WORKTREE_SYNC.relative_to(_REPO_ROOT)} が残存している。"
        " skill 固有スクリプトはルート scripts/ から削除し、"
        " .claude/skills/lyria/references/ 配下に置くこと (Issue #140)"
    )


def test_root_scripts_gcp_bootstrap_is_removed() -> None:
    """Given Issue #388 の整理後の状態
    When ルート ``scripts/gcp-bootstrap.sh`` を確認する
    Then ファイル（および broken symlink）として一切存在しない。

    canonical path は ``.claude/skills/channel-new/references/gcp-bootstrap.sh`` に一本化済み。
    """
    assert not os.path.lexists(_OLD_GCP_BOOTSTRAP), (
        f"{_OLD_GCP_BOOTSTRAP.relative_to(_REPO_ROOT)} が残存している。"
        " canonical path は .claude/skills/channel-new/references/ のみ (Issue #388)"
    )


def test_root_scripts_gcp_terraform_apply_is_removed() -> None:
    """Given Issue #388 の整理後の状態
    When ルート ``scripts/gcp-terraform-apply.sh`` を確認する
    Then ファイル（および broken symlink）として一切存在しない。

    canonical path は ``.claude/skills/channel-new/references/gcp-terraform-apply.sh`` に一本化済み。
    """
    assert not os.path.lexists(_OLD_GCP_TERRAFORM_APPLY), (
        f"{_OLD_GCP_TERRAFORM_APPLY.relative_to(_REPO_ROOT)} が残存している。"
        " canonical path は .claude/skills/channel-new/references/ のみ (Issue #388)"
    )


def test_root_scripts_dir_only_contains_common_scripts() -> None:
    """Given Issue #140 + #388 の整理後の ``scripts/`` ディレクトリ
    When 直下のエントリを列挙する
    Then ファイルが1件も存在しない（scripts/ は空、またはディレクトリ自体が存在しない）。

    Issue #140 で skill 固有スクリプトを削除し、Issue #388 で残っていた
    ``gcp-bootstrap.sh`` / ``gcp-terraform-apply.sh`` も削除された。
    git は空ディレクトリを track しないため、ディレクトリ自体が消えても OK。
    新規スクリプトを誤ってルートに置いてしまう regression を検出する。
    """
    if not _SCRIPTS_DIR.exists():
        return

    actual = {entry.name for entry in _SCRIPTS_DIR.iterdir() if entry.is_file()}
    unexpected = actual - _COMMON_SCRIPTS
    assert unexpected == set(), (
        f"scripts/ にスクリプトが含まれる: {sorted(unexpected)}。"
        " スクリプトは .claude/skills/<skill>/references/ に配置すること"
    )


# ---------- Issue #388: channel-new/references/ の canonical path 検証 ----------


@pytest.mark.parametrize(
    "path",
    [_CANONICAL_GCP_BOOTSTRAP, _CANONICAL_GCP_TERRAFORM_APPLY],
    ids=[
        ".claude/skills/channel-new/references/gcp-bootstrap.sh",
        ".claude/skills/channel-new/references/gcp-terraform-apply.sh",
    ],
)
def test_channel_new_reference_gcp_script_exists(path: Path) -> None:
    """Given Issue #388 の整理後の状態
    When channel-new skill 配下の gcp スクリプトを確認する
    Then 実体ファイルとして存在する。

    scripts/ 側を削除した後も canonical path 側が存在することを保証する。
    """
    assert path.exists(), f"{path.relative_to(_REPO_ROOT)} が存在しない (Issue #388)"


@pytest.mark.parametrize(
    "path",
    [_CANONICAL_GCP_BOOTSTRAP, _CANONICAL_GCP_TERRAFORM_APPLY],
    ids=[
        ".claude/skills/channel-new/references/gcp-bootstrap.sh",
        ".claude/skills/channel-new/references/gcp-terraform-apply.sh",
    ],
)
def test_channel_new_reference_gcp_script_is_real_file_not_symlink(path: Path) -> None:
    """Given Issue #388 の整理後の状態
    When channel-new skill 配下の gcp スクリプトの種別を確認する
    Then symlink ではなく実ファイルである。
    """
    assert not path.is_symlink(), (
        f"{path.relative_to(_REPO_ROOT)} が symlink になっている。 実ファイルとして配置すること (Issue #388)"
    )


@pytest.mark.parametrize(
    "path",
    [_CANONICAL_GCP_BOOTSTRAP, _CANONICAL_GCP_TERRAFORM_APPLY],
    ids=[
        ".claude/skills/channel-new/references/gcp-bootstrap.sh",
        ".claude/skills/channel-new/references/gcp-terraform-apply.sh",
    ],
)
def test_channel_new_reference_gcp_script_is_executable(path: Path) -> None:
    """Given Issue #388 の整理後の状態
    When channel-new skill 配下の gcp スクリプトの実行ビットを確認する
    Then 実行可能である。
    """
    assert os.access(path, os.X_OK), f"{path.relative_to(_REPO_ROOT)} に実行ビットがない (Issue #388)"


# ---------- skill 配下に実ファイルとして存在するか ----------


@pytest.mark.parametrize(
    "path",
    [_NEW_GENERATE_VIDEOS, _NEW_WORKTREE_SYNC],
    ids=[
        ".claude/skills/videoup/references/generate_videos.sh",
        ".claude/skills/lyria/references/worktree_sync.sh",
    ],
)
def test_skill_reference_script_exists(path: Path) -> None:
    """Given Issue #140 の整理後の状態
    When skill 配下のスクリプトを確認する
    Then 実体ファイルとして存在する。
    """
    assert path.exists(), f"{path.relative_to(_REPO_ROOT)} が存在しない"


@pytest.mark.parametrize(
    "path",
    [_NEW_GENERATE_VIDEOS, _NEW_WORKTREE_SYNC],
    ids=[
        ".claude/skills/videoup/references/generate_videos.sh",
        ".claude/skills/lyria/references/worktree_sync.sh",
    ],
)
def test_skill_reference_script_is_real_file_not_symlink(path: Path) -> None:
    """Given Issue #140 の整理後の状態
    When skill 配下のスクリプトの種別を確認する
    Then symlink ではなく実ファイルである。

    旧構成では skill 配下が ``../../../../scripts/...`` への逆向き symlink だった。
    Issue #140 で実体を skill 側に移したため、symlink への逆戻りを禁止する。
    """
    assert not path.is_symlink(), (
        f"{path.relative_to(_REPO_ROOT)} が symlink になっている。 実ファイルとして配置すること (Issue #140)"
    )


@pytest.mark.parametrize(
    "path",
    [_NEW_GENERATE_VIDEOS, _NEW_WORKTREE_SYNC],
    ids=[
        ".claude/skills/videoup/references/generate_videos.sh",
        ".claude/skills/lyria/references/worktree_sync.sh",
    ],
)
def test_skill_reference_script_is_executable(path: Path) -> None:
    """Given Issue #140 の整理後の状態
    When skill 配下のスクリプトの実行ビットを確認する
    Then 実行可能である (``-rwxr-xr-x`` 相当)。

    ``git mv`` ではモードが保たれるため、これを検証することで
    chmod 漏れによる「動かないスクリプト」regression を検出する。
    """
    assert os.access(path, os.X_OK), (
        f"{path.relative_to(_REPO_ROOT)} に実行ビットがない。 移動時に実行ビットを保持すること (chmod +x)"
    )


# ---------- bash 構文チェック ----------


@pytest.mark.parametrize(
    "path",
    [_NEW_GENERATE_VIDEOS, _NEW_WORKTREE_SYNC],
    ids=[
        ".claude/skills/videoup/references/generate_videos.sh",
        ".claude/skills/lyria/references/worktree_sync.sh",
    ],
)
def test_skill_reference_script_passes_bash_syntax_check(path: Path) -> None:
    """Given Issue #140 の整理後の状態
    When ``bash -n`` で移動後のスクリプトを構文チェックする
    Then exit 0 (構文エラーなし)。

    移動・rename 時の改行コード変換やエンコーディング破損を検出する。
    """
    if not _bash_available():
        pytest.skip("bash が PATH 上に存在しない")

    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{path.relative_to(_REPO_ROOT)} の bash 構文チェックに失敗:\n{result.stderr}"
