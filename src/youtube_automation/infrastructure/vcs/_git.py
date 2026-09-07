"""`infrastructure/vcs/` 内の adapter が共有する git subprocess 実行 helper。"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`repository` を cwd として git を実行し、例外を投げず結果をそのまま返す。"""
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


def parse_status_paths(stdout: str) -> tuple[str, ...]:
    """`git status --porcelain=v1 -z` の出力から変更 path を取り出す。

    `-z` では rename / copy が `XY <to>\\0<from>\\0` の 2 record に分かれ、path の
    C 形式 quoting も行われない。rename は元 path も変更として扱い、copy は複製元が
    無変更なので `<to>` だけを返す。
    """
    records = stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        status = record[:2]
        paths.add(record[3:])
        has_source = "R" in status or "C" in status
        if "R" in status and index + 1 < len(records):
            paths.add(records[index + 1])
        index += 2 if has_source else 1
    return tuple(sorted(paths))


__all__ = ["parse_status_paths", "run_git"]
