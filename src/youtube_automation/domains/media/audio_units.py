"""音声モデル → ``cost_tracker.log_generation`` の ``unit`` 解決。

`cost_tracker.log_generation` は Issue #132 で `unit=` を呼び出し側必須化したため、
音楽生成スクリプト群（`generate_music` / `generate_music_dj`）で `unit` を一貫して解決する
共通の場所が必要になった。scripts→scripts の横断 import を避け、cost_tracker と同じ
`utils` 層のドメインヘルパとして提供する。

未知モデルは暗黙補完せず ``ValueError``（F-2: fail-fast）。
"""

from __future__ import annotations

_AUDIO_UNIT_BY_MODEL: dict[str, str] = {
    "lyria-3-pro-preview": "song",
    "lyria-3-clip-preview": "30sec",
}


def unit_for_audio(model: str) -> str:
    """音楽モデル名から log_generation 用の ``unit`` 文字列を解決する。

    未知モデルは ``ValueError``（暗黙補完を禁止する F-2 反映）。
    """
    try:
        return _AUDIO_UNIT_BY_MODEL[model]
    except KeyError as e:
        raise ValueError(f"unknown audio model: {model!r}") from e
