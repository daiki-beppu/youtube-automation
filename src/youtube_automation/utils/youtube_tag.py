"""YouTube タグ関連のユーティリティ."""

from __future__ import annotations


def youtube_tag_chars(tags: list[str]) -> int:
    """YouTube が判定する真のタグ文字数を計算する.

    YouTube はスペースを含むタグを引用符で囲んだ上で `,` 結合した長さで
    500 文字制限を判定する（実測で確認）。`len(','.join(tags))` だけでは
    `400 The request metadata specifies invalid video keywords` を取りこぼす。
    """
    parts = [f'"{t}"' if " " in t else t for t in tags]
    return len(",".join(parts))
