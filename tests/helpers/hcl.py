"""HCL / テキスト構造検証用の共通ヘルパー。

`tests/test_terraform_streaming.py` と `tests/test_streaming_healthcheck.py` から
共通利用される。テストモジュール間の cross-import (private helper への到達)
を避けるため、本モジュールに公開名で集約している (Issue #169)。
"""

from __future__ import annotations

import re
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


def extract_block(text: str, header_pattern: str) -> str | None:
    """``header { ... }`` または ``header = { ... }`` のトップレベルブロックを 1 つ抜き出す。

    ``header_pattern`` は header 行（``{`` 直前まで）にマッチする正規表現。
    ネストした ``{ }`` を 1 段までカウントしてマッチ範囲を確定する。
    HCL の ``required_providers`` 内は ``name = { ... }``（オブジェクトリテラル）
    形式のため、ヘッダーと ``{`` の間に任意で ``=`` を許容する。
    """
    match = re.search(header_pattern + r"\s*=?\s*\{", text)
    if not match:
        return None
    start = match.end()  # `{` の直後
    depth = 1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None


def find_block_with_position(
    text: str,
    header_pattern: str,
    required_text: str,
) -> tuple[str, int] | None:
    """繰り返しブロックから本文を識別し、ヘッダー開始位置とともに返す。"""
    for match in re.finditer(header_pattern + r"\s*=?\s*\{", text):
        start = match.end()
        depth = 1
        for i in range(start, len(text)):
            char = text[i]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body = text[start:i]
                    if required_text in body:
                        return body, match.start()
                    break
    return None
