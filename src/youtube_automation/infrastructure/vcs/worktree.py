"""git linked worktree 検知ヘルパ

git worktree では `.git` が `gitdir: <main>/.git/worktrees/<name>` を指す
ファイルになることを利用し、git コマンド非依存で main 作業ツリーのルートを
解決する（`git rev-parse --git-common-dir` 相当）。

gitignore された `auth/` は worktree に複製されないため、認証ファイルの
フォールバック解決（issue #1721）で main 側の実体を参照する用途に使う。
"""

from pathlib import Path

_GITDIR_PREFIX = "gitdir:"


def main_worktree_root(start: Path) -> Path | None:
    """`start` の祖先から linked worktree を検知し、main 作業ツリーのルートを返す。

    `start` から祖先方向に `.git` を探索し、最初に見つかった `.git` が
    linked worktree の pointer ファイルであれば、その `gitdir` 配下の
    `commondir` を辿って main 作業ツリーのルートを返す。

    以下の場合は None（= worktree ではない / 解決不能）:

    - `.git` がディレクトリ（通常の main 作業ツリー）
    - `.git` が祖先に存在しない（git 管理外）
    - `.git` ファイルはあるが `commondir` を持たない（submodule 等）
    - pointer / commondir の読み取りに失敗した
    """
    for parent in [start, *start.parents]:
        git_path = parent / ".git"
        if git_path.is_dir():
            return None
        if not git_path.is_file():
            continue
        try:
            content = git_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not content.startswith(_GITDIR_PREFIX):
            return None
        gitdir = Path(content[len(_GITDIR_PREFIX) :].strip())
        if not gitdir.is_absolute():
            gitdir = (parent / gitdir).resolve()
        # linked worktree の gitdir は commondir を持つ（submodule の gitdir は持たない）
        commondir_file = gitdir / "commondir"
        if not commondir_file.is_file():
            return None
        try:
            common = (gitdir / commondir_file.read_text(encoding="utf-8").strip()).resolve()
        except OSError:
            return None
        root = common.parent
        if root == parent.resolve():
            return None
        return root
    return None
