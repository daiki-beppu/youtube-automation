"""any-usage-gate.sh 用ヘルパー: Python ファイル中で Any が実際に参照されている行番号を解決する。

テキスト正規表現ではなく AST を使うのは、コメント・docstring・文字列リテラル中の
"Any"（型使用ではない）を構造的に除外するため。`from typing import Any`（複数行
import・as alias 含む）と `import typing` 経由の `typing.Any` 修飾アクセスの
両方を検出する。標準入力から Python ソースを受け取り、Any が参照されている行番号を
1 行 1 つずつ標準出力へ書き出す。
"""

import ast
import sys


def main() -> None:
    try:
        tree = ast.parse(sys.stdin.read())
    except SyntaxError:
        return

    bare_any_names: set[str] = set()
    typing_module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                if alias.name == "Any":
                    bare_any_names.add(alias.asname or alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "typing":
                    typing_module_names.add(alias.asname or alias.name)

    violation_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in bare_any_names:
            violation_lines.add(node.lineno)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "Any"
            and isinstance(node.value, ast.Name)
            and node.value.id in typing_module_names
        ):
            violation_lines.add(node.lineno)

    for lineno in sorted(violation_lines):
        print(lineno)


if __name__ == "__main__":
    main()
