"""Issue #137: `.claude/skills/masterup/config.default.yaml` の `intro_audio` 名前空間 (D 節)。

新規追加される `intro_audio:` namespace が
`load_skill_config("masterup")["intro_audio"]` で取得できること、
設計 D の SFX タイミング (cup=6000ms / paper=18000ms / vinyl=10000ms) と
既存の `audio.*` / `suno_download.*` キーへのリグレッション、
channel 上書きの deep-merge 経路を担保する。
"""

from __future__ import annotations

import pytest
import yaml

from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config

# 設計 D の SFX タイミング (ms) と音量 (dB) — 設計の核となる固定値
_EXPECTED_SFX_TIMING = {
    "cup": {"start_ms": 6000, "volume_db": -3},
    "paper": {"start_ms": 18000, "volume_db": -12},
    "vinyl": {"start_ms": 10000, "volume_db": -6},
}

_EXPECTED_INTRO_AUDIO_TOP_KEYS = {
    "song_delay_ms",
    "song_fadein_s",
    "song_volume_db",
    "rain_volume_db",
    "rain_fadein_s",
    "loudnorm",
    "sfx",
}


@pytest.fixture(autouse=True)
def _reset_caches():
    skill_config.reset()
    reset_config()
    yield
    skill_config.reset()
    reset_config()


# ---------- D-1: intro_audio namespace 全 7 キー ----------


def test_load_skill_config_masterup_exposes_intro_audio_namespace() -> None:
    """Given upstream 同梱の masterup/config.default.yaml
    When load_skill_config("masterup") を呼ぶ
    Then intro_audio が dict として取れ、7 つのトップキーを持つ。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    intro_audio = cfg.get("intro_audio")
    assert isinstance(intro_audio, dict), (
        f"intro_audio が dict でない (namespace 未追加の可能性): {type(intro_audio)}"
    )
    missing = _EXPECTED_INTRO_AUDIO_TOP_KEYS - set(intro_audio.keys())
    assert not missing, f"intro_audio に欠落しているキー: {missing}"


def test_intro_audio_song_delay_is_10000_ms() -> None:
    """Given intro_audio.song_delay_ms
    When 値を確認
    Then 設計 D の 10s 遅延に対応する 10000 ms である。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    assert cfg["intro_audio"]["song_delay_ms"] == 10000


def test_intro_audio_song_fadein_is_2_seconds() -> None:
    """Given intro_audio.song_fadein_s
    When 値を確認
    Then 設計 D の 2 秒 fadein である。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    assert cfg["intro_audio"]["song_fadein_s"] == 2


# ---------- D-2: SFX 3 entries (cup / paper / vinyl) ----------


def test_intro_audio_sfx_has_three_entries_with_design_d_timing() -> None:
    """Given intro_audio.sfx
    When cup / paper / vinyl のタイミングと音量を確認
    Then plan 通りの設計 D タイミングで定義されている。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    sfx = cfg["intro_audio"]["sfx"]
    assert isinstance(sfx, dict), f"intro_audio.sfx が dict でない: {type(sfx)}"
    for name, expected in _EXPECTED_SFX_TIMING.items():
        assert name in sfx, f"intro_audio.sfx.{name} が無い"
        entry = sfx[name]
        assert isinstance(entry, dict), f"intro_audio.sfx.{name} が dict でない: {type(entry)}"
        assert entry.get("start_ms") == expected["start_ms"], (
            f"intro_audio.sfx.{name}.start_ms が {expected['start_ms']} でない: "
            f"{entry.get('start_ms')!r}"
        )
        assert entry.get("volume_db") == expected["volume_db"], (
            f"intro_audio.sfx.{name}.volume_db が {expected['volume_db']} でない: "
            f"{entry.get('volume_db')!r}"
        )
        assert entry.get("file"), (
            f"intro_audio.sfx.{name}.file が空 (file 名 default が無い): {entry}"
        )


# ---------- D-3: 既存 audio / suno_download キーへのリグレッション ----------


def test_existing_audio_namespace_keys_preserved() -> None:
    """Given masterup/config.default.yaml の既存 `audio:` namespace
    When intro_audio 追加後にロード
    Then crossfade_duration / bitrate などの既存キーは消えていない。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    audio = cfg.get("audio")
    assert isinstance(audio, dict), f"audio namespace が消えた: {audio!r}"
    assert "crossfade_duration" in audio
    assert "bitrate" in audio


def test_existing_suno_download_namespace_keys_preserved() -> None:
    """Given masterup/config.default.yaml の既存 `suno_download:` namespace
    When intro_audio 追加後にロード
    Then cdn_url_template が残っている (既存 CLI のリグレッション防止)。
    """
    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    suno = cfg.get("suno_download")
    assert isinstance(suno, dict), f"suno_download namespace が消えた: {suno!r}"
    assert "cdn_url_template" in suno


# ---------- D-4: channel override (intro_audio.sfx.cup.file) ----------


def test_channel_override_replaces_intro_audio_sfx_cup_file_via_deep_merge(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given channel override で `intro_audio.sfx.cup.file` のみ指定
    When load_skill_config("masterup") を呼ぶ
    Then default の他キー (start_ms / volume_db) は残り、`file` のみ書き換わる。
    """
    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override_path = channel_dir / "config" / "skills" / "masterup.yaml"
    override_path.write_text(
        yaml.safe_dump({"intro_audio": {"sfx": {"cup": {"file": "ceramic_v9.wav"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    cfg = skill_config.load_skill_config("masterup", use_cache=False)
    cup = cfg["intro_audio"]["sfx"]["cup"]
    assert cup["file"] == "ceramic_v9.wav"
    # default の他キーが merge で消えていない
    assert cup.get("start_ms") == 6000, (
        f"override で start_ms が消えた (deep-merge ではなく list 置換になっている可能性): {cup}"
    )
    assert cup.get("volume_db") == -3
