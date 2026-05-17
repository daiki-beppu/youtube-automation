"""``audio_units.unit_for_audio`` の単体テスト。

Issue #132 で `cost_tracker.log_generation` が `unit=` を呼び出し側必須化したため、
音楽生成スクリプト群から共通利用される ``unit_for_audio`` を `utils/audio_units.py`
に切り出した。

- lyria-3-pro-preview → "song"
- lyria-3-clip-preview → "30sec"
- lyria-002 → "30sec"
- 未知モデル → ValueError (暗黙補完は禁止 / fail-fast)
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.audio_units import unit_for_audio


@pytest.mark.parametrize(
    "model, expected_unit",
    [
        ("lyria-3-pro-preview", "song"),
        ("lyria-3-clip-preview", "30sec"),
        ("lyria-002", "30sec"),
    ],
)
def test_unit_for_audio_returns_expected_unit(model: str, expected_unit: str):
    """Given 既知の音楽モデル
    When unit_for_audio を呼ぶ
    Then 対応する単位文字列を返す。
    """
    assert unit_for_audio(model) == expected_unit


def test_unit_for_audio_unknown_model_raises_value_error():
    """Given 未知の音楽モデル
    When unit_for_audio を呼ぶ
    Then ValueError を送出 (暗黙補完しない / F-2 反映)。
    """
    with pytest.raises(ValueError, match="no-such-model"):
        unit_for_audio("no-such-model")


def test_unit_for_audio_is_publicly_exported():
    """Given utils.audio_units モジュール
    When `unit_for_audio` を import する
    Then underscore-private でなく、scripts 跨ぎ import に耐える公開 API として参照できる。
    """
    from youtube_automation.utils import audio_units

    assert hasattr(audio_units, "unit_for_audio")
    assert audio_units.unit_for_audio.__name__ == "unit_for_audio"
