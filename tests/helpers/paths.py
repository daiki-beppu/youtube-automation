from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
TESTS_DIR: Path = REPO_ROOT / "tests"
FIXTURES_DIR: Path = TESTS_DIR / "fixtures"

# worktree の置き場は規約上リポジトリの内側にある(`docs/takt-operations.md`)。
# 1 つ 1 つが完全なチェックアウトなので、リポジトリを全走査する契約テストから見ると
# 本体のファイルと区別が付かない。走査対象から外すための正本。
# `.worktrees/` は旧い置き場で、移行期間中のローカル環境にのみ残る。
WORKTREE_STORE_PREFIXES: tuple[tuple[str, ...], ...] = ((".claude", "worktrees"), (".worktrees",))


def is_inside_worktree_store(path: Path, root: Path = REPO_ROOT) -> bool:
    """`path` が worktree 置き場の配下にあるか判定する。"""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return any(parts[: len(prefix)] == prefix for prefix in WORKTREE_STORE_PREFIXES)
