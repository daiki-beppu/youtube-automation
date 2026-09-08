"""外部由来の文字列を端末に表示するための共通 primitive。"""

import unicodedata


def format_terminal_text(value: str, *, max_length: int) -> str:
    """制御文字を可視化し、文字数を max_length（3 以上）に制限する。"""
    text = "".join(_escape_character(char) for char in value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _escape_character(char: str) -> str:
    if unicodedata.category(char)[0] == "C":
        return char.encode("unicode_escape").decode("ascii")
    return char
