"""ルート ``scripts/`` と ``.claude/skills/<skill>/references/`` のレイアウト regression を検出する。

Issue #140: skill 固有スクリプト (``generate_videos.sh`` / ``worktree_sync.sh``) を
ルート ``scripts/`` から ``.claude/skills/<skill>/references/`` 配下に canonical 化する整理。

このテストは以下の不変条件を維持する:

1. ルート ``scripts/`` には共通スクリプトのみ（``gcp-bootstrap.sh`` / ``gcp-terraform-apply.sh``）が残り、
   skill 固有スクリプトは存在しない (CLAUDE.md 規約)。
2. skill 配下の参照スクリプトは **実ファイル**（symlink ではない）かつ実行可能。
   逆向き symlink になっていた旧構成への regression を防ぐ。
3. 移動後のスクリプトは ``bash -n`` で構文エラーがない。
4. 各スクリプト先頭 Usage コメントが新パスを案内している。
5. ``audio_formats.py`` docstring 内のパス参照が新パスに追従している。

ファイル配置の整理タスクであり、振る舞いを変更しないため、これら静的アサーションのみで検証する。
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

# ルートに残ってよい共通スクリプト（指示書スコープ外）
_COMMON_SCRIPTS = {"gcp-bootstrap.sh", "gcp-terraform-apply.sh"}

# 移動後パスを参照すべきプロダクションコード
_AUDIO_FORMATS_PY = _REPO_ROOT / "src" / "youtube_automation" / "utils" / "audio_formats.py"


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_available() -> bool:
    return shutil.which("bash") is not None


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


def test_root_scripts_dir_only_contains_common_scripts() -> None:
    """Given Issue #140 の整理後の ``scripts/`` ディレクトリ
    When 直下のエントリを列挙する
    Then 共通スクリプト (``gcp-bootstrap.sh`` / ``gcp-terraform-apply.sh``) のみが残る。

    新規 skill 固有スクリプトを誤ってルートに置いてしまう regression を検出する。
    ``gcp-*`` 以外のシェルスクリプトが追加されたら、配置場所を再検討させる。
    """
    if not _SCRIPTS_DIR.exists():
        pytest.fail(f"{_SCRIPTS_DIR.relative_to(_REPO_ROOT)} が存在しない")

    actual = {entry.name for entry in _SCRIPTS_DIR.iterdir() if entry.is_file()}
    unexpected = actual - _COMMON_SCRIPTS
    assert unexpected == set(), (
        f"scripts/ に共通スクリプト以外が含まれる: {sorted(unexpected)}。"
        " skill 固有スクリプトは .claude/skills/<skill>/references/ に配置すること"
    )


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


# ---------- スクリプト本体の同一性 (内容が壊れていないこと) ----------


def test_generate_videos_keeps_v12_header() -> None:
    """Given Issue #140 の整理後の ``generate_videos.sh``
    When ファイル先頭を読む
    Then v12 を示すヘッダコメントが残っている (内容欠損なし)。
    """
    text = _read(_NEW_GENERATE_VIDEOS)
    assert "generate_videos.sh v12" in text, (
        "ヘッダ `# generate_videos.sh v12.x` が消えている。"
        " ファイル本体が破損または別ファイルに置き換わっている可能性がある"
    )


def test_worktree_sync_keeps_purpose_header() -> None:
    """Given Issue #140 の整理後の ``worktree_sync.sh``
    When ファイル先頭を読む
    Then 用途を示すヘッダコメントが残っている (内容欠損なし)。
    """
    text = _read(_NEW_WORKTREE_SYNC)
    assert "ワークツリー" in text, (
        "ヘッダ用途コメントが消えている。 ファイル本体が破損または別ファイルに置き換わっている可能性がある"
    )


# ---------- スクリプト先頭 Usage コメント ----------


def test_generate_videos_usage_comment_points_to_new_path() -> None:
    """Given Issue #140 の整理後の ``generate_videos.sh``
    When ファイル先頭の Usage コメントを読む
    Then 新パス (``.claude/skills/videoup/references/generate_videos.sh``) を案内している。

    旧 Usage は ``bash automation/generate_videos.sh ...`` で、
    既に存在しない ``automation/`` パスを参照していた。
    """
    text = _read(_NEW_GENERATE_VIDEOS)
    assert ".claude/skills/videoup/references/generate_videos.sh" in text, (
        "Usage コメントが新パスを参照していない。 skill 経由・直接実行の両方で利用者が実行できるパスを示すこと"
    )


def test_generate_videos_usage_comment_drops_legacy_automation_path() -> None:
    """Given Issue #140 の整理後の ``generate_videos.sh``
    When ファイル先頭の Usage コメントを読む
    Then 旧 ``automation/generate_videos.sh`` 参照が削除されている。

    存在しないパスの案内は利用者を混乱させるため除去する。
    """
    text = _read(_NEW_GENERATE_VIDEOS)
    # ファイル先頭 30 行 (Usage 領域) のみを対象に判定 (本体ロジックの誤検出を避ける)
    head = "\n".join(text.splitlines()[:30])
    assert "automation/generate_videos.sh" not in head, (
        "Usage コメントに旧 `automation/generate_videos.sh` 参照が残存している"
    )


def test_worktree_sync_usage_comment_points_to_new_path() -> None:
    """Given Issue #140 の整理後の ``worktree_sync.sh``
    When ファイル先頭の Usage コメントを読む
    Then 新パス (``.claude/skills/lyria/references/worktree_sync.sh``) を案内している。
    """
    text = _read(_NEW_WORKTREE_SYNC)
    assert ".claude/skills/lyria/references/worktree_sync.sh" in text, (
        "Usage コメントが新パスを参照していない。 skill 経由・直接実行の両方で利用者が実行できるパスを示すこと"
    )


# ---------- audio_formats.py docstring パス参照 ----------


def test_audio_formats_docstring_points_to_new_path() -> None:
    """Given Issue #140 の整理後の ``audio_formats.py``
    When モジュール docstring を読む
    Then ``generate_videos.sh`` への参照が新パスに更新されている。
    """
    text = _read(_AUDIO_FORMATS_PY)
    assert ".claude/skills/videoup/references/generate_videos.sh" in text, (
        f"{_AUDIO_FORMATS_PY.relative_to(_REPO_ROOT)} docstring が新パスを参照していない。"
        " 旧 `scripts/generate_videos.sh` を `.claude/skills/videoup/references/generate_videos.sh`"
        " に置換すること (Issue #140)"
    )


def test_audio_formats_docstring_drops_legacy_scripts_path() -> None:
    """Given Issue #140 の整理後の ``audio_formats.py``
    When モジュール docstring を読む
    Then 旧 ``scripts/generate_videos.sh`` 参照が削除されている。

    旧パスはルートから消えているため、案内が残ると利用者を「存在しないファイル」へ導いてしまう。
    """
    text = _read(_AUDIO_FORMATS_PY)
    assert "scripts/generate_videos.sh" not in text, (
        f"{_AUDIO_FORMATS_PY.relative_to(_REPO_ROOT)} docstring に旧パス `scripts/generate_videos.sh` が残存している"
    )
