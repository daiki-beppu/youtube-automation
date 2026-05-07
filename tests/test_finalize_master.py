"""Issue #137: `.claude/skills/masterup/references/finalize_master.py` 純粋関数 (E 節)。

設計 D の filter graph 組み立て (`build_common_parts` / `build_filter`) を
単体検証する。subprocess は呼ばず、文字列 assert のみ。
"""

from __future__ import annotations

from typing import Any

import pytest

from tests._skill_loader import load_skill_script
from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ConfigError

# 設計 D の本質的定数 (これらは固定)
_EXPECTED_SONG_DELAY_MS = 10000
_EXPECTED_SONG_FADEIN_S = 2


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


@pytest.fixture
def finalize_module():
    return load_skill_script("masterup", "finalize_master")


def _make_intro_audio_config(**overrides: Any) -> dict[str, Any]:
    """plan で定義された intro_audio config の最小完全版。"""
    config = {
        "song_delay_ms": _EXPECTED_SONG_DELAY_MS,
        "song_fadein_s": _EXPECTED_SONG_FADEIN_S,
        "song_volume_db": -8,
        "rain_volume_db": -19,
        "rain_fadein_s": 0.5,
        "loudnorm": {"I": -14, "LRA": 11, "TP": -1.5},
        "sfx": {
            "cup": {"file": "cup_v3.wav", "start_ms": 6000, "volume_db": -3},
            "paper": {"file": "paper.wav", "start_ms": 18000, "volume_db": -12},
            "vinyl": {"file": "vinyl_v4.wav", "start_ms": 10000, "volume_db": -6},
        },
    }
    config.update(overrides)
    return config


# ---------- E-1〜E-3: build_common_parts の核 ----------


def test_build_common_parts_emits_sfx_adelay_volume_apad(finalize_module) -> None:
    """Given intro_audio.sfx の cup/paper/vinyl 各 entry
    When build_common_parts(config, n_rain=3) を呼ぶ
    Then 各 SFX に adelay+volume+apad を含むフィルタが生成される。
    """
    cfg = _make_intro_audio_config()
    parts = finalize_module.build_common_parts(cfg, n_rain=3)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    for name, expected in [
        ("cup", 6000), ("paper", 18000), ("vinyl", 10000),
    ]:
        assert f"adelay={expected}|{expected}" in joined, (
            f"{name} の adelay={expected} が見つからない"
        )
    assert "apad" in joined, "apad (尾部 padding) が無い"


def test_build_common_parts_amix_combines_three_sfx(finalize_module) -> None:
    """Given build_common_parts
    When 結果 filter graph を確認
    Then `[cup][paper][vinyl]amix=inputs=3` が出現する。
    """
    cfg = _make_intro_audio_config()
    parts = finalize_module.build_common_parts(cfg, n_rain=3)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    # SFX label の amix (順序は実装依存だが 3 入力であることは固定)
    assert "amix=inputs=3" in joined, "[cup][paper][vinyl] の 3-input amix が無い"


def test_build_common_parts_rain_layer_chain_with_3_inputs(finalize_module) -> None:
    """Given n_rain=3
    When build_common_parts を呼ぶ
    Then rain layer は 4..6 の input index で volume チェーンされて amix される。
    """
    cfg = _make_intro_audio_config()
    parts = finalize_module.build_common_parts(cfg, n_rain=3)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    # input index: 0=master, 1=cup, 2=paper, 3=vinyl, 4..6=rain
    # 各 rain layer に volume= が当たる
    assert "[4:a]" in joined and "[5:a]" in joined and "[6:a]" in joined, (
        f"rain layer の input index 4..6 が見つからない:\n{joined}"
    )


# ---------- E-4: 設計 D の核 (10s 遅延 + 2s afade-in) ----------


def test_build_common_parts_emits_song_with_10s_delay_and_2s_fadein(
    finalize_module,
) -> None:
    """Given intro_audio.song_delay_ms=10000 / song_fadein_s=2 / song_volume_db=-8
    When build_common_parts を呼ぶ
    Then `[0:a]adelay=10000|10000,afade=t=in:st=10:d=2,volume=-8dB[song]` 相当が出る。
    """
    cfg = _make_intro_audio_config()
    parts = finalize_module.build_common_parts(cfg, n_rain=3)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    assert "adelay=10000|10000" in joined, "song の 10s 遅延が見つからない"
    assert "afade=t=in:st=10:d=2" in joined, (
        "設計 D の 2s afade-in (st=10:d=2) が見つからない"
    )
    assert "volume=-8dB" in joined or "volume=-8.0dB" in joined, (
        "song_volume_db=-8 の volume 指定が見つからない"
    )
    assert "[song]" in joined, "song label が無い"


# ---------- E-5: build_filter で 3-source 合成 + loudnorm ----------


def test_build_filter_appends_song_sfx_rain_amix_with_loudnorm(
    finalize_module,
) -> None:
    """Given build_common_parts の結果に build_filter で総合 mix を加える
    When build_filter(config) を呼ぶ
    Then `[song][sfx][rain]amix=inputs=3:duration=first:normalize=0,loudnorm=...[aout]`
        相当の 3 source amix + loudnorm が末尾に出る。
    """
    cfg = _make_intro_audio_config()
    filter_str = finalize_module.build_filter(cfg)

    # [song][sfx][rain] の最終 amix
    assert "amix=inputs=3" in filter_str
    assert "loudnorm" in filter_str, "loudnorm filter が無い"
    assert filter_str.rstrip().endswith("[aout]"), (
        f"最終 label が [aout] でない:\n...{filter_str[-200:]}"
    )


# ---------- E-6: 単一 rain layer 境界 ----------


def test_build_common_parts_works_with_single_rain_layer(finalize_module) -> None:
    """Given n_rain=1 (rain layer が 1 つだけ)
    When build_common_parts を呼ぶ
    Then [4:a] のみで rain チェーンが組まれ、エラーにならない。
    """
    cfg = _make_intro_audio_config()
    parts = finalize_module.build_common_parts(cfg, n_rain=1)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    assert "[4:a]" in joined
    # [5:a] は出ない
    assert "[5:a]" not in joined, (
        f"n_rain=1 のはずなのに [5:a] が出ている:\n{joined}"
    )


# ---------- E-7: config 駆動の伝搬 (override) ----------


def test_build_common_parts_uses_overridden_song_delay_and_fadein(
    finalize_module,
) -> None:
    """Given config を `song_delay_ms=5000 / song_fadein_s=1` で override
    When build_common_parts を呼ぶ
    Then adelay=5000|5000, afade=t=in:st=5:d=1 が反映される (config 駆動の証跡)。
    """
    cfg = _make_intro_audio_config(song_delay_ms=5000, song_fadein_s=1)
    parts = finalize_module.build_common_parts(cfg, n_rain=3)
    joined = ";".join(parts) if isinstance(parts, list) else parts

    assert "adelay=5000|5000" in joined, (
        f"override した song_delay_ms=5000 が反映されていない:\n{joined}"
    )
    assert "afade=t=in:st=5:d=1" in joined, (
        f"override した song_fadein_s=1 が反映されていない (st=5:d=1):\n{joined}"
    )


# ---------- E-8: 必須 namespace 欠落で ConfigError ----------


def test_build_common_parts_raises_config_error_when_intro_audio_missing(
    finalize_module,
) -> None:
    """Given config に必須キーが欠落 (sfx も song_delay_ms も無い)
    When build_common_parts を呼ぶ
    Then ConfigError (境界での解決原則 = Fail Fast)。
    """
    with pytest.raises(ConfigError):
        finalize_module.build_common_parts({}, n_rain=3)
