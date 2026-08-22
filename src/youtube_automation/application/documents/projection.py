"""文書公開と workflow-state 投影の再実行可能な調停点。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

_Published = TypeVar("_Published")


def publish_and_project(
    publish: Callable[[], _Published],
    project: Callable[[_Published], None],
) -> _Published:
    """公開完了後にだけ投影し、失敗時は同じ操作の再実行で収束させる。

    publish callback は既存 pair publisher の再実行可能性を、project callback は
    workflow-state owner の冪等な値設定を利用する。投影が失敗しても公開成果物は
    正本として残るため、呼び出し全体を再実行すると投影だけを安全に再適用できる。
    """
    published = publish()
    project(published)
    return published


__all__ = ["publish_and_project"]
