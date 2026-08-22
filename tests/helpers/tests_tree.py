"""実 `tests/` ツリーを触るテスト同士を直列化する reader-writer lock。

`tests/repo/test_pytest_lane_contract.py` の relocation probe だけが、契約検証のために
`tests/` 配下の実ファイルを一時的に別 path へ動かす writer になる（lane 判定は
`tests/conftest.py` の配下でしか効かないので tmp_path へ逃がせない）。一方で `tests/`
を全走査する契約テストと `.github/scripts/select-affected-tests.py` は reader にあたる。

`-n auto` では両者が別 worker で同時に走るため、writer の窓に reader が重なると走査
結果からモジュールが欠けたり、rglob 直後の `read_text` が `FileNotFoundError` になる。
selector はそれを OSError として掴んで `ALL` へ fail-safe するので、症状は「計画が
ALL に化ける」形で現れる。

reader 同士は互いに干渉しないので `LOCK_SH` で並行させ、writer だけ `LOCK_EX` で
締め出す。全部を `LOCK_EX` にすると `-n auto` の並列度を無駄に削る。

公開名を `test` で始めてはならない。pytest の既定 `python_functions = test*` は
アンダースコアを要求しないグロブなので、`tests_tree_read_lock` のような名前は
import した先の module で「テスト関数」として収集されてしまう。
"""

from __future__ import annotations

import fcntl
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# プロセス跨ぎで共有する必要があるので tmp 配下の固定 path に置く。flock は fd の
# close で必ず解放されるため、異常終了しても stale lock は残らない。
TESTS_TREE_LOCK: Path = Path(tempfile.gettempdir()) / "pytest-tests-tree.lock"


@contextmanager
def _flock(mode: int) -> Iterator[None]:
    with TESTS_TREE_LOCK.open("a+") as lock_file:
        fcntl.flock(lock_file, mode)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


@contextmanager
def shared_tests_tree_lock() -> Iterator[None]:
    """`tests/` を走査する間、実ファイルを動かす writer を締め出す。"""
    with _flock(fcntl.LOCK_SH):
        yield


@contextmanager
def exclusive_tests_tree_lock() -> Iterator[None]:
    """`tests/` 配下の実ファイルを一時的に動かす間、走査側を締め出す。

    同一プロセスでも fd が違えば別の lock holder として扱われるため、この lock の
    内側から `shared_tests_tree_lock()` を取ると自己 deadlock する。内側では
    `*_without_lock` 系の非ロック版を呼ぶこと。
    """
    with _flock(fcntl.LOCK_EX):
        yield
