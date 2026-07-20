"""HCL / テキスト構造検証用の共通ヘルパー。

`tests/test_terraform_streaming.py` と `tests/test_streaming_healthcheck.py` から
共通利用される。テストモジュール間の cross-import (private helper への到達)
を避けるため、本モジュールに公開名で集約している (Issue #169)。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def strip_hcl_comments(text: str) -> str:
    """行コメント (``#`` / ``//``) と ``/* ... */`` ブロックコメントを除去する。

    HCL の構文解析はせず、コメント行で false-positive のマッチを起こさないための前処理。
    文字列リテラル内の ``#`` などは想定しない（本テスト対象の HCL は素直な構造のみ）。
    """
    # ブロックコメント (greedy にならないよう非貪欲)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 行コメント
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        # `#` が文字列内にあるケースは本テストの対象 HCL では発生しないため単純に切る
        for marker in ("#", "//"):
            idx = line.find(marker)
            if idx >= 0:
                line = line[:idx]
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def read_file(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _iter_blocks(text: str, header_pattern: str) -> Iterator[tuple[str, int]]:
    """``header { ... }`` / ``header = { ... }`` のトップレベルブロックを順に列挙する。

    ``header_pattern`` は header 行（``{`` 直前まで）にマッチする正規表現。
    HCL の ``required_providers`` 内は ``name = { ... }``（オブジェクトリテラル）
    形式のため、ヘッダーと ``{`` の間に任意で ``=`` を許容する。
    ネストした ``{ }`` を深度カウントで辿り、対応する ``}`` までを body として
    ``(body, header_start)`` を yield する。``{`` が閉じないヘッダーは skip する。

    ブロック走査を本関数へ一元化し、``extract_block`` /
    ``find_block_with_position`` は「先頭 1 件」「条件一致」という薄い選択処理に
    留める（重複した brace 深度走査の再実装を避ける）。
    """
    for match in re.finditer(header_pattern + r"\s*=?\s*\{", text):
        start = match.end()  # `{` の直後
        depth = 1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i], match.start()
                    break


def extract_block(text: str, header_pattern: str) -> str | None:
    """``header_pattern`` に一致する最初のトップレベルブロック body を返す。"""
    for body, _ in _iter_blocks(text, header_pattern):
        return body
    return None


def find_block_with_position(
    text: str,
    header_pattern: str,
    required_text: str,
) -> tuple[str, int] | None:
    """``required_text`` を含む最初のブロックの ``(body, header_start)`` を返す。"""
    for body, header_start in _iter_blocks(text, header_pattern):
        if required_text in body:
            return body, header_start
    return None
