"""any-usage-gate.sh 用ヘルパー: TypeScript の1行からコメントと文字列の中身を取り除く。

行コメント（// ...）や文字列・テンプレートリテラルの中身に含まれる "any" を
型使用として誤検知しないための事前クリーニング。標準入力から1行を受け取り、
クリーニング後のテキストを標準出力へ書き出す（呼び出し側で候補と判定された
疑わしい行だけに適用する前提の軽量処理で、正規表現ベースの近似）。
"""

import re
import sys

_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'" r"|`(?:[^`\\]|\\.)*`")
_COMMENT_RE = re.compile(r"//.*$")


def clean(line: str) -> str:
    cleaned = _STRING_RE.sub('""', line)
    return _COMMENT_RE.sub("", cleaned)


def main() -> None:
    line = sys.stdin.readline().rstrip("\n")
    sys.stdout.write(clean(line))


if __name__ == "__main__":
    main()
