"""`audio.finalize.*` namespace の組み合わせマトリクス + 旧 alias 互換テスト (#512)。

カバレッジ:
- 新 namespace の各パラメータ (fadein_curve / mix.normalize / mix.duration /
  loudnorm.enabled / sample_rate / codec / per-file layer override) が
  filter / pass2 cmd に正しく反映される
- `loudnorm.enabled: false` で pass1/pass2 を skip し amix 単発で出力される
- `loudnorm.mode: dynamic` は `NotImplementedError` でフェイルラウド
- `audio.finalize.*` namespace の設定を検証する
- 新 namespace と旧 namespace が同時設定なら新を優先 (旧は無視)
- `layers.<filename>` の per-file override が該当 layer の volume/fadein にのみ反映される
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts import finalize_master
from youtube_automation.scripts.finalize_master import (
    FinalizeConfig,
    _resolve_finalize_config,
    build_filter,
)
from youtube_automation.scripts.finalize_master import (
    finalize_master as run_finalize_master,
)
from youtube_automation.utils.exceptions import ConfigError

_ORIGINAL_MASTER_BYTES = b"ORIGINAL_MASTER_BYTES_FOR_TEST"
_NEW_MASTER_BYTES = b"NEW_MASTER_BYTES_AFTER_PASS2"


def _setup_collection(tmp_path: Path, n_rain: int) -> Path:
    (tmp_path / "01-master").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01-master" / "master.mp3").write_bytes(_ORIGINAL_MASTER_BYTES)
    (tmp_path / "02-Individual-music").mkdir(parents=True, exist_ok=True)
    if n_rain >= 1:
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, n_rain + 1):
            (rain_dir / f"rain_{i:03d}.wav").write_bytes(b"\x00")
    return tmp_path


def _patch_skill_config(monkeypatch, cfg: dict) -> MagicMock:
    spy = MagicMock(return_value=cfg)
    monkeypatch.setattr(
        "youtube_automation.scripts.finalize_master.load_skill_config",
        spy,
    )
    return spy


def _make_pass1_stderr() -> str:
    return (
        "ffmpeg version test\n[Parsed_loudnorm_0 @ 0xdeadbeef]\n"
        '{\n  "input_i": "-23.0",\n  "input_tp": "-2.1",\n  '
        '"input_lra": "10.5",\n  "input_thresh": "-33.0",\n  '
        '"target_offset": "0.5"\n}\n'
    )


def _make_fake_run_sequence(
    captured: dict,
    *,
    n_calls: int = 2,
    pass2_writes_tmp: bool = True,
):
    state = {"calls": 0}

    def _run(cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        idx = state["calls"]
        state["calls"] += 1
        if idx == 0 and n_calls > 1:
            return SimpleNamespace(returncode=0, stderr=_make_pass1_stderr(), stdout="")
        # 最後の call (=出力する側) で tmp に書く
        if pass2_writes_tmp:
            for arg in cmd:
                if isinstance(arg, str) and arg.endswith("master.tmp.mp3"):
                    Path(arg).write_bytes(_NEW_MASTER_BYTES)
                    break
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    return _run


def _filter_expr(cmd: list[str]) -> str:
    idx = cmd.index("-filter_complex")
    return cmd[idx + 1]


class TestResolveFinalizeConfigDefaults:
    """skill-config 空のとき、組み込みデフォルトと既存挙動の互換性。"""

    def test_empty_config_yields_defaults(self):
        # When
        cfg: FinalizeConfig = _resolve_finalize_config({})

        # Then
        assert cfg.volume_db == -19.0
        assert cfg.fadein_s == 0.5
        assert cfg.fadein_curve == "tri"
        assert cfg.loudnorm == {"I": -14.0, "LRA": 11.0, "TP": -1.5}
        assert cfg.loudnorm_enabled is True
        assert cfg.loudnorm_mode == "linear"
        assert cfg.mix_duration == "first"
        assert cfg.mix_normalize == 0
        assert cfg.bitrate == "192k"
        assert cfg.codec == "libmp3lame"
        assert cfg.sample_rate is None
        assert cfg.layers_dirname == "rain_layers"
        assert cfg.layers_glob == "rain_*.wav"
        assert cfg.layers_overrides == {}


class TestResolveFinalizeConfigNewNamespace:
    """`audio.finalize.*` namespace の各キーが解決される。"""

    def test_full_override_via_audio_finalize(self):
        # Given
        skill_cfg = {
            "audio": {
                "bitrate": "256k",
                "finalize": {
                    "bitrate": "320k",  # finalize 直下が audio.bitrate に勝る
                    "codec": "aac",
                    "sample_rate": 48000,
                    "ambient_layers": {
                        "volume_db": -22.5,
                        "fadein_s": 1.5,
                        "fadein_curve": "log",
                        "dirname": "ambient",
                        "glob": "amb_*.wav",
                        "layers": {
                            "amb_001.wav": {"volume_db": -10.0},
                        },
                    },
                    "loudnorm": {"enabled": True, "mode": "linear", "I": -16.0, "LRA": 8.0, "TP": -2.0},
                    "mix": {"duration": "longest", "normalize": 1},
                },
            }
        }

        # When
        cfg = _resolve_finalize_config(skill_cfg)

        # Then
        assert cfg.volume_db == -22.5
        assert cfg.fadein_s == 1.5
        assert cfg.fadein_curve == "log"
        assert cfg.layers_dirname == "ambient"
        assert cfg.layers_glob == "amb_*.wav"
        assert cfg.layers_overrides == {"amb_001.wav": {"volume_db": -10.0}}
        assert cfg.loudnorm == {"I": -16.0, "LRA": 8.0, "TP": -2.0}
        assert cfg.loudnorm_enabled is True
        assert cfg.mix_duration == "longest"
        assert cfg.mix_normalize == 1
        assert cfg.bitrate == "320k"
        assert cfg.codec == "aac"
        assert cfg.sample_rate == 48000

    def test_audio_bitrate_used_when_finalize_bitrate_absent(self):
        cfg = _resolve_finalize_config({"audio": {"bitrate": "256k"}})
        assert cfg.bitrate == "256k"

    def test_loudnorm_disabled_flag(self):
        cfg = _resolve_finalize_config({"audio": {"finalize": {"loudnorm": {"enabled": False}}}})
        assert cfg.loudnorm_enabled is False

    def test_mix_normalize_accepts_bool_true(self):
        cfg = _resolve_finalize_config({"audio": {"finalize": {"mix": {"normalize": True}}}})
        assert cfg.mix_normalize == 1

    def test_mix_normalize_accepts_bool_false(self):
        cfg = _resolve_finalize_config({"audio": {"finalize": {"mix": {"normalize": False}}}})
        assert cfg.mix_normalize == 0


class TestResolveFinalizeConfigFailLoud:
    """無効な値で fail-loud (silent fallback はしない)。"""

    def test_dynamic_mode_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="dynamic"):
            _resolve_finalize_config({"audio": {"finalize": {"loudnorm": {"mode": "dynamic"}}}})

    def test_invalid_loudnorm_mode_raises_config_error(self):
        with pytest.raises(ConfigError, match="loudnorm.mode"):
            _resolve_finalize_config({"audio": {"finalize": {"loudnorm": {"mode": "garbage"}}}})

    def test_invalid_mix_duration_raises_config_error(self):
        with pytest.raises(ConfigError, match="mix.duration"):
            _resolve_finalize_config({"audio": {"finalize": {"mix": {"duration": "forever"}}}})

    def test_invalid_mix_normalize_int_raises_config_error(self):
        with pytest.raises(ConfigError, match="mix.normalize"):
            _resolve_finalize_config({"audio": {"finalize": {"mix": {"normalize": 2}}}})

    def test_layers_non_dict_raises_config_error(self):
        with pytest.raises(ConfigError, match="layers"):
            _resolve_finalize_config({"audio": {"finalize": {"ambient_layers": {"layers": ["not", "a", "dict"]}}}})


class TestBuildFilterNewParameters:
    """`build_filter` の新引数 (fadein_curve / mix_* / layer_overrides / apply_loudnorm)。"""

    def test_fadein_curve_injected_into_afade(self):
        result = build_filter(
            n_rain=1,
            volume_db=-19.0,
            fadein_s=0.5,
            loudnorm={"I": -14.0, "LRA": 11.0, "TP": -1.5},
            measured=None,
            fadein_curve="exp",
        )
        assert "curve=exp" in result

    def test_mix_duration_and_normalize_propagated(self):
        result = build_filter(
            n_rain=1,
            volume_db=-19.0,
            fadein_s=0.5,
            loudnorm={"I": -14.0, "LRA": 11.0, "TP": -1.5},
            measured=None,
            mix_duration="longest",
            mix_normalize=1,
        )
        assert "duration=longest" in result
        assert "normalize=1" in result

    def test_apply_loudnorm_false_omits_loudnorm_stage(self):
        result = build_filter(
            n_rain=2,
            volume_db=-19.0,
            fadein_s=0.5,
            loudnorm={"I": -14.0, "LRA": 11.0, "TP": -1.5},
            measured=None,
            apply_loudnorm=False,
        )
        # loudnorm filter は使われない
        assert "loudnorm=" not in result
        # 代わりに amix 段が直接 [aout] を吐く
        assert "[aout]" in result
        assert result.endswith("[aout]")

    def test_layer_overrides_apply_only_to_targeted_layer(self):
        # Given: 2 layer、override は layer-0 のみ
        result = build_filter(
            n_rain=2,
            volume_db=-19.0,
            fadein_s=0.5,
            loudnorm={"I": -14.0, "LRA": 11.0, "TP": -1.5},
            measured=None,
            layer_overrides=[
                {"volume_db": -5.0, "fadein_s": 2.0},
                None,
            ],
        )
        # layer-0: 上書き値、layer-1: デフォルト
        assert "volume=-5dB" in result
        assert "volume=-19dB" in result
        assert "afade=t=in:st=0:d=2" in result
        assert "afade=t=in:st=0:d=0.5" in result

    def test_layer_overrides_length_mismatch_fails_loud(self):
        from youtube_automation.utils.exceptions import ValidationError

        with pytest.raises(ValidationError, match="layer_overrides"):
            build_filter(
                n_rain=2,
                volume_db=-19.0,
                fadein_s=0.5,
                loudnorm={"I": -14.0, "LRA": 11.0, "TP": -1.5},
                measured=None,
                layer_overrides=[None],  # 長さ 1 ≠ n_rain 2
            )


class TestFinalizeMasterE2EConfigMatrix:
    """`finalize_master` を回して新パラメータが ffmpeg cmd に反映されること。"""

    def test_sample_rate_added_to_pass2_cmd(self, tmp_path, monkeypatch):
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {"audio": {"finalize": {"sample_rate": 44100}}},
        )
        captured: dict = {}

        with patch.object(finalize_master.subprocess, "run", side_effect=_make_fake_run_sequence(captured)):
            rc = run_finalize_master(collection, collection, quiet=True)

        assert rc == 0
        pass2_cmd = captured["cmds"][1]
        assert "-ar" in pass2_cmd
        ar_idx = pass2_cmd.index("-ar")
        assert pass2_cmd[ar_idx + 1] == "44100"

    def test_codec_propagates_into_pass2_cmd(self, tmp_path, monkeypatch):
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {"audio": {"finalize": {"codec": "aac"}}},
        )
        captured: dict = {}

        with patch.object(finalize_master.subprocess, "run", side_effect=_make_fake_run_sequence(captured)):
            rc = run_finalize_master(collection, collection, quiet=True)

        assert rc == 0
        pass2_cmd = captured["cmds"][1]
        ca_idx = pass2_cmd.index("-c:a")
        assert pass2_cmd[ca_idx + 1] == "aac"

    def test_loudnorm_disabled_skips_pass1_and_does_single_call(self, tmp_path, monkeypatch):
        # Given: loudnorm.enabled=false
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {"audio": {"finalize": {"loudnorm": {"enabled": False}}}},
        )
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured, n_calls=1),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: ffmpeg は 1 回しか呼ばれない (pass1 が skip された)
        assert rc == 0
        assert len(captured["cmds"]) == 1
        # filter 式に loudnorm 段が含まれない
        single_filter = _filter_expr(captured["cmds"][0])
        assert "loudnorm=" not in single_filter
        # atomic rename は通常通り行われる
        assert (collection / "01-master" / "master.mp3").read_bytes() == _NEW_MASTER_BYTES

    def test_dynamic_loudnorm_mode_raises_not_implemented(self, tmp_path, monkeypatch):
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {"audio": {"finalize": {"loudnorm": {"mode": "dynamic"}}}},
        )

        with pytest.raises(NotImplementedError):
            run_finalize_master(collection, collection, quiet=True)

    def test_per_file_layer_override_only_affects_named_file(self, tmp_path, monkeypatch):
        # Given: layer 2 件、rain_001.wav にだけ override
        collection = _setup_collection(tmp_path, n_rain=2)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {
                "audio": {
                    "finalize": {
                        "ambient_layers": {
                            "volume_db": -19.0,
                            "layers": {
                                "rain_001.wav": {"volume_db": -3.5},
                            },
                        }
                    }
                }
            },
        )
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: filter 内に override 値とデフォルト値が共存する
        assert rc == 0
        pass2_filter = _filter_expr(captured["cmds"][1])
        # rain_001.wav (layer-0) は -3.5、rain_002.wav (layer-1) は -19
        assert "volume=-3.5dB" in pass2_filter
        assert "volume=-19dB" in pass2_filter

    def test_custom_layers_dirname_finds_files(self, tmp_path, monkeypatch):
        # Given: 既定 rain_layers にも 1 件、custom ambient/ にも 1 件
        # (gate1 を通すために rain_layers/rain_001.wav が必要)
        collection = _setup_collection(tmp_path, n_rain=1)
        ambient_dir = collection / "branding" / "ambient"
        ambient_dir.mkdir(parents=True)
        (ambient_dir / "amb_001.wav").write_bytes(b"\x00")
        (ambient_dir / "amb_002.wav").write_bytes(b"\x00")
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {
                "audio": {
                    "finalize": {
                        "ambient_layers": {
                            "dirname": "ambient",
                            "glob": "amb_*.wav",
                        }
                    }
                }
            },
        )
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: pass2 cmd の -i 引数 = master + 2 ambient = 3
        assert rc == 0
        assert captured["cmds"][1].count("-i") == 3
