"""YouTube タグ関連のユーティリティ."""

from __future__ import annotations


def normalize_youtube_tags(raw_tags: list[str]) -> list[str]:
    """タグリストから先頭・末尾のダブルクォートを除去する."""
    return [t.strip('"') for t in raw_tags]


def parse_youtube_tags(raw: str) -> list[str]:
    """descriptions.md のタグ欄テキストからタグリストを生成する.

    改行・カンマ混在の生テキストを分割し、空要素を除去した上で
    ``normalize_youtube_tags`` でダブルクォートを除去して返す。
    """
    return normalize_youtube_tags([t.strip() for t in raw.replace("\n", ",").split(",") if t.strip()])


def youtube_tag_chars(tags: list[str]) -> int:
    """YouTube が判定する真のタグ文字数を計算する.

    YouTube はスペースを含むタグを引用符で囲んだ上で `,` 結合した長さで
    500 文字制限を判定する（実測で確認）。`len(','.join(tags))` だけでは
    `400 The request metadata specifies invalid video keywords` を取りこぼす。
    """
    parts = [f'"{t}"' if " " in t else t for t in tags]
    return len(",".join(parts))
