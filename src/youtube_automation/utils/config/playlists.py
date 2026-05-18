"""プレイリスト設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Playlists:
    """`playlists` セクション（optional）.

    `items` は `{"playlist_key": {"playlist_id": ..., "auto_add": ..., ...}, ...}`
    の dict-of-dict. 入力 JSON では string 形式 (`{"main": "PL..."}`) と
    dict 形式 (`{"main": {"playlist_id": "PL...", ...}}`) の両方を許容するが、
    loader (`_build_playlists`) で必ず dict 形式へ正規化された後に格納される。
    string 入力は `{"playlist_id": <元値>, "auto_add": True, "title": None}` に
    展開される（#275）。
    """

    items: dict[str, dict] = field(default_factory=dict)
