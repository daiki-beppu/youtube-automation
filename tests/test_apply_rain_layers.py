"""apply_rain_layers の純粋関数 + オーケストレータ + CLI テスト。

issue #510: `post_processing.rain_layers` 駆動の opt-in 雨レイヤー後処理。
`yt-finalize-master` と独立した別 CLI (`yt-apply-rain-layers`) として、
amix のみ・別ファイル出力 (master-rain.wav)・workflow-state ポインタ切替を
担う。subprocess.run は mock し、ffmpeg コマンドの構造と挙動契約を検証する。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts import apply_rain_layers as mod
from youtube_automation.scripts.apply_rain_layers import (
    _resolve_post_processing_config,
    apply_rain_layers,
    build_ffmpeg_command,
    build_filter,
    find_rain_layers,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError

# -19dB の振幅倍率は issue 完了条件で参照される定数。テストでは
# build_filter / build_ffmpeg_command の文字列出現を確認する形で
# 「-19dB 仕様への忠実性」を担保する (10^(-19/20) ≈ 0.1122)。
_DEFAULT_VOLUME_DB = -19.0
_ORIGINAL_MASTER_BYTES = b"ORIGINAL_MASTER_BYTES"
_NEW_OUTPUT_BYTES = b"NEW_MASTER_RAIN_WAV_BYTES"


def _setup_collection(tmp_path: Path, n_rain: int, *, rain_names: list[str] | None = None) -> Path:
    """tmp_path をコレクション + チャンネルルートとして整える。

    - `01-master/master.mp3` を既知バイト列で配置
    - `02-Individual-music/` も作成 (resolve_collection_dir の CWD 判定用)
    - n_rain >= 1 のとき `branding/rain_layers/` 配下に WAV を生成
      rain_names が指定されればその名前で、未指定なら rain_001.wav... と連番
    """
    (tmp_path / "01-master").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01-master" / "master.mp3").write_bytes(_ORIGINAL_MASTER_BYTES)
    (tmp_path / "02-Individual-music").mkdir(parents=True, exist_ok=True)
    if n_rain >= 1:
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True, exist_ok=True)
        names = rain_names or [f"rain_{i:03d}.wav" for i in range(1, n_rain + 1)]
        for name in names:
            (rain_dir / name).write_bytes(b"\x00")
    return tmp_path


def _patch_skill_config(monkeypatch, cfg: dict) -> MagicMock:
    spy = MagicMock(return_value=cfg)
    monkeypatch.setattr(
        "youtube_automation.scripts.apply_rain_layers.load_skill_config",
        spy,
    )
    return spy


def _fake_run_writes_output(captured: dict, *, rc: int = 0, write_output: bool = True):
    """subprocess.run を 1 回呼びで差し替えるファクトリ。

    rc=0 + write_output=True のとき、cmd 末尾の output ファイルへ
    `_NEW_OUTPUT_BYTES` を書き込んで「ffmpeg 生成」を観測可能にする。
    """

    def _run(cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        if rc == 0 and write_output:
            output_path = Path(cmd[-1])
            output_path.write_bytes(_NEW_OUTPUT_BYTES)
        return SimpleNamespace(returncode=rc, stderr="", stdout="")

    return _run


# ---------------------------------------------------------------------------
# 純粋関数: find_rain_layers
# ---------------------------------------------------------------------------


class TestFindRainLayers:
    def test_returns_empty_when_branding_dir_missing(self, tmp_path):
        # Given: branding/rain_layers/ 不在

        # When
        result = find_rain_layers(tmp_path)

        # Then: 空リスト (上位の gate がこれを見て fail-loud / pass の判定をする)
        assert result == []

    def test_returns_empty_when_dir_exists_but_no_wav(self, tmp_path):
        # Given: ディレクトリは在るが WAV が 0 件
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        (rain_dir / "README.md").write_text("placeholder")

        # When
        result = find_rain_layers(tmp_path)

        # Then
        assert result == []

    def test_collects_all_wav_in_sorted_order(self, tmp_path):
        # Given: rain_*.wav 以外の WAV も含めて複数配置 (本 CLI は prefix 制約なし)
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        for name in ["thunder.wav", "rain_002.wav", "ambient.wav", "rain_001.wav"]:
            (rain_dir / name).write_bytes(b"\x00")

        # When
        result = find_rain_layers(tmp_path)

        # Then: 全 WAV をソート済みで返す (finalize_master の rain_*.wav 制約は本 CLI には無い)
        names = [p.name for p in result]
        assert names == ["ambient.wav", "rain_001.wav", "rain_002.wav", "thunder.wav"]


# ---------------------------------------------------------------------------
# 純粋関数: _resolve_post_processing_config
# ---------------------------------------------------------------------------


class TestResolvePostProcessingConfig:
    def test_returns_disabled_when_namespace_missing(self):
        # Given: skill-config に post_processing 自体が無い
        cfg = {"audio": {"bitrate": "192k"}}

        # When
        result = _resolve_post_processing_config(cfg)

        # Then: enabled=False (opt-in: 未設定はゼロ挙動)
        assert result == {"enabled": False}

    def test_returns_disabled_when_rain_layers_missing(self):
        # Given: post_processing は在るが rain_layers が無い
        cfg = {"post_processing": {}}

        # When
        result = _resolve_post_processing_config(cfg)

        # Then
        assert result == {"enabled": False}

    def test_returns_defaults_when_enabled_only(self):
        # Given: enabled=true のみ指定、他は defaults
        cfg = {"post_processing": {"rain_layers": {"enabled": True}}}

        # When
        result = _resolve_post_processing_config(cfg)

        # Then: defaults が埋まる
        assert result["enabled"] is True
        assert result["volume_db"] == _DEFAULT_VOLUME_DB
        assert result["output_name"] == "master-rain.wav"
        assert result["output_codec"] == "pcm_s16le"
        assert result["output_sample_rate"] == 44100

    def test_overrides_each_key(self):
        # Given: 全キー override
        cfg = {
            "post_processing": {
                "rain_layers": {
                    "enabled": True,
                    "volume_db": -22.5,
                    "output_name": "master-storm.wav",
                    "output_codec": "pcm_s24le",
                    "output_sample_rate": 48000,
                }
            }
        }

        # When
        result = _resolve_post_processing_config(cfg)

        # Then: 全 override 値が反映される
        assert result["volume_db"] == -22.5
        assert result["output_name"] == "master-storm.wav"
        assert result["output_codec"] == "pcm_s24le"
        assert result["output_sample_rate"] == 48000

    def test_raises_config_error_when_post_processing_not_mapping(self):
        # Given: post_processing がリスト等の不正型
        cfg = {"post_processing": ["bad"]}

        # When / Then
        with pytest.raises(ConfigError):
            _resolve_post_processing_config(cfg)

    def test_raises_config_error_when_rain_layers_not_mapping(self):
        # Given: rain_layers が文字列等の不正型
        cfg = {"post_processing": {"rain_layers": "yes"}}

        # When / Then
        with pytest.raises(ConfigError):
            _resolve_post_processing_config(cfg)


# ---------------------------------------------------------------------------
# 純粋関数: build_filter
# ---------------------------------------------------------------------------


class TestBuildFilter:
    def test_single_layer_uses_volume_and_amix(self):
        # Given: rain 1 件、デフォルト -19dB

        # When
        result = build_filter(n_rain=1, volume_db=_DEFAULT_VOLUME_DB)

        # Then
        # 各レイヤーに volume=-19dB が当たる
        assert "[1:a]volume=-19dB[r0]" in result
        # master + rain で amix=inputs=2、normalize=0 で正規化抑止
        assert "[0:a][r0]amix=inputs=2:duration=first:normalize=0[aout]" in result
        # finalize_master と違い loudnorm は使わない契約
        assert "loudnorm" not in result
        # aloop も使わない (-stream_loop で吸収する契約)
        assert "aloop" not in result

    def test_three_layers_amix_includes_master_plus_three(self):
        # Given: rain 3 件

        # When
        result = build_filter(n_rain=3, volume_db=_DEFAULT_VOLUME_DB)

        # Then: master + rain*3 = 4 入力、各 rain にラベル
        for i in range(3):
            assert f"[{i + 1}:a]volume=-19dB[r{i}]" in result
        assert "[0:a][r0][r1][r2]amix=inputs=4:duration=first:normalize=0[aout]" in result

    def test_volume_db_propagates_to_each_layer(self):
        # Given: 全レイヤーに同じ override 値を効かせる
        result = build_filter(n_rain=2, volume_db=-22.5)

        # Then: 各レイヤー個別に同じ dB が乗る
        assert result.count("volume=-22.5dB") == 2

    def test_raises_validation_error_for_zero_layers(self):
        # Given: rain 0 件で filter を呼んでも意味がない (fail-fast)
        with pytest.raises(ValidationError):
            build_filter(n_rain=0, volume_db=_DEFAULT_VOLUME_DB)


# ---------------------------------------------------------------------------
# 純粋関数: build_ffmpeg_command
# ---------------------------------------------------------------------------


class TestBuildFfmpegCommand:
    def test_each_rain_input_preceded_by_stream_loop_minus_one(self, tmp_path):
        # Given: master + rain 2 件
        master = tmp_path / "master.mp3"
        master.write_bytes(b"\x00")
        rain1 = tmp_path / "r1.wav"
        rain2 = tmp_path / "r2.wav"
        for r in (rain1, rain2):
            r.write_bytes(b"\x00")

        # When
        cmd = build_ffmpeg_command(
            master,
            [rain1, rain2],
            "FILTER",
            tmp_path / "out.wav",
            output_codec="pcm_s16le",
            output_sample_rate=44100,
        )

        # Then: 各 rain 入力の直前に -stream_loop -1 が来ている (ファイル側ループ)
        for rain in (rain1, rain2):
            idx = cmd.index(str(rain))
            assert cmd[idx - 1] == "-i"
            assert cmd[idx - 2] == "-1"
            assert cmd[idx - 3] == "-stream_loop"
        # master 入力には -stream_loop が付かない (master 尺がそのまま全体尺)
        master_idx = cmd.index(str(master))
        assert cmd[master_idx - 1] == "-i"
        # master の前に -stream_loop は無い (cmd[0] が "ffmpeg" になっているはず)
        assert "-stream_loop" not in cmd[: master_idx - 1]

    def test_output_codec_and_sample_rate_and_channel_count(self, tmp_path):
        # Given: PCM 16-bit / 44.1kHz / stereo の出力指定 (issue #510 仕様)
        master = tmp_path / "master.mp3"
        master.write_bytes(b"\x00")
        rain = tmp_path / "r.wav"
        rain.write_bytes(b"\x00")

        # When
        cmd = build_ffmpeg_command(
            master,
            [rain],
            "FILTER",
            tmp_path / "master-rain.wav",
            output_codec="pcm_s16le",
            output_sample_rate=44100,
        )

        # Then
        assert "-c:a" in cmd
        assert cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
        assert "-ar" in cmd
        assert cmd[cmd.index("-ar") + 1] == "44100"
        assert "-ac" in cmd
        assert cmd[cmd.index("-ac") + 1] == "2"  # stereo
        # 最後の引数が出力パス (build_filter からの [aout] map を伴って)
        assert cmd[-1].endswith("master-rain.wav")
        assert "[aout]" in cmd
        assert "-map" in cmd

    def test_filter_complex_injected_verbatim(self, tmp_path):
        # Given: 任意の filter 文字列が verbatim で渡る
        master = tmp_path / "m.mp3"
        master.write_bytes(b"\x00")
        rain = tmp_path / "r.wav"
        rain.write_bytes(b"\x00")

        # When
        cmd = build_ffmpeg_command(
            master,
            [rain],
            "MY_CUSTOM_FILTER",
            tmp_path / "out.wav",
            output_codec="pcm_s16le",
            output_sample_rate=44100,
        )

        # Then
        idx = cmd.index("-filter_complex")
        assert cmd[idx + 1] == "MY_CUSTOM_FILTER"


# ---------------------------------------------------------------------------
# オーケストレータ: apply_rain_layers
# ---------------------------------------------------------------------------


class TestApplyRainLayersGate:
    """opt-in / fail-loud / dry-run の振り分け契約。"""

    def test_returns_zero_and_no_ffmpeg_when_disabled(self, tmp_path, monkeypatch):
        # Given: enabled=false (デフォルト)
        collection = _setup_collection(tmp_path, n_rain=1)
        _patch_skill_config(monkeypatch, {})
        run_spy = MagicMock()

        # When
        with patch.object(mod.subprocess, "run", run_spy):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: ffmpeg を呼ばずに rc=0 / master 無傷 / 出力なし
        assert rc == 0
        run_spy.assert_not_called()
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES
        assert not (collection / "01-master" / "master-rain.wav").exists()

    def test_fail_loud_when_enabled_but_no_rain_wav(self, tmp_path, monkeypatch, capsys):
        # Given: enabled=true だが rain wav 0 件
        collection = _setup_collection(tmp_path, n_rain=0)
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})

        # When
        rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=1 で fail-loud。stderr に手がかりを出す
        assert rc == 1
        err = capsys.readouterr().err
        assert "rain_layers" in err or "rain" in err

    def test_dry_run_prints_command_and_skips_execution(self, tmp_path, monkeypatch, capsys):
        # Given: enabled=true + rain wav 1 件、dry_run=True
        collection = _setup_collection(tmp_path, n_rain=1)
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        run_spy = MagicMock()

        # When
        with patch.object(mod.subprocess, "run", run_spy):
            rc = apply_rain_layers(collection, collection, dry_run=True, quiet=True)

        # Then: rc=0 / ffmpeg 呼び出しなし / stdout に ffmpeg コマンドが出る
        assert rc == 0
        run_spy.assert_not_called()
        out = capsys.readouterr().out
        assert "ffmpeg" in out
        assert "-stream_loop" in out
        # workflow-state.json は dry-run なので変更されない (元から無い前提だが、出力ファイルも無い)
        assert not (collection / "01-master" / "master-rain.wav").exists()


class TestApplyRainLayersRun:
    """正常系: ffmpeg 実行 + workflow-state 切替の流れ。"""

    def test_one_layer_runs_ffmpeg_and_writes_output(self, tmp_path, monkeypatch):
        # Given: enabled + rain 1 件
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=0 / ffmpeg 1 回 / 出力 wav が生成 / master は無傷
        assert rc == 0
        assert len(captured["cmds"]) == 1
        assert (collection / "01-master" / "master-rain.wav").read_bytes() == _NEW_OUTPUT_BYTES
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_three_layers_command_has_three_stream_loop_pairs(self, tmp_path, monkeypatch):
        # Given: enabled + rain 3 件
        collection = _setup_collection(tmp_path, n_rain=3)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: -stream_loop -1 ペアが rain 数ぶん登場
        assert rc == 0
        cmd = captured["cmds"][0]
        assert cmd.count("-stream_loop") == 3
        # filter_complex に rain*3 + master の amix=inputs=4 が乗る
        filter_expr = cmd[cmd.index("-filter_complex") + 1]
        assert "amix=inputs=4" in filter_expr

    def test_volume_db_minus_nineteen_is_default(self, tmp_path, monkeypatch):
        # Given: defaults だけ。issue #510 の完了条件「-19dB 仕様への忠実性」を文字列で担保
        collection = _setup_collection(tmp_path, n_rain=2)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: filter に volume=-19dB が 2 件 (各レイヤー)
        assert rc == 0
        filter_expr = captured["cmds"][0][captured["cmds"][0].index("-filter_complex") + 1]
        assert filter_expr.count("volume=-19dB") == 2

    def test_output_name_override_changes_output_path(self, tmp_path, monkeypatch):
        # Given: output_name を上書き
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {"post_processing": {"rain_layers": {"enabled": True, "output_name": "master-storm.wav"}}},
        )
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: 出力ファイルが override 名で生成される
        assert rc == 0
        assert (collection / "01-master" / "master-storm.wav").read_bytes() == _NEW_OUTPUT_BYTES
        assert not (collection / "01-master" / "master-rain.wav").exists()

    def test_workflow_state_raw_master_updated_after_success(self, tmp_path, monkeypatch):
        # Given: workflow-state.json が既存、assets.raw_master は元 master を指す
        collection = _setup_collection(tmp_path, n_rain=1)
        wf = collection / "workflow-state.json"
        wf.write_text(
            json.dumps({"assets": {"raw_master": "master.mp3", "master_audio": None}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: assets.raw_master が新出力ファイル名に書き換わる / 他フィールドは保持
        assert rc == 0
        state = json.loads(wf.read_text(encoding="utf-8"))
        assert state["assets"]["raw_master"] == "master-rain.wav"
        assert state["assets"]["master_audio"] is None  # 他フィールドは触らない

    def test_workflow_state_missing_is_not_fatal(self, tmp_path, monkeypatch):
        # Given: workflow-state.json が存在しない (古いコレクション or 別レイアウト)
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(mod.subprocess, "run", side_effect=_fake_run_writes_output(captured)):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: 出力は生成され rc=0 / state は元から無いだけ
        assert rc == 0
        assert (collection / "01-master" / "master-rain.wav").exists()
        assert not (collection / "workflow-state.json").exists()


class TestApplyRainLayersFailure:
    def test_returns_rc1_when_ffmpeg_not_on_path(self, tmp_path, monkeypatch):
        # Given: enabled + rain wav 在り、ffmpeg 未インストール
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: None)
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})

        # When
        rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=1 / master 無傷
        assert rc == 1
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_returns_rc1_when_master_mp3_missing(self, tmp_path, monkeypatch):
        # Given: enabled だが raw master 不在
        collection = _setup_collection(tmp_path, n_rain=1)
        (collection / "01-master" / "master.mp3").unlink()
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})

        # When
        rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=1
        assert rc == 1

    def test_returns_rc1_when_ffmpeg_fails(self, tmp_path, monkeypatch):
        # Given: ffmpeg が non-zero で終了
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(
            mod.subprocess,
            "run",
            side_effect=_fake_run_writes_output(captured, rc=1, write_output=False),
        ):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=1 / 出力ファイルは生成されていない / 元 master 無傷
        assert rc == 1
        assert not (collection / "01-master" / "master-rain.wav").exists()
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_returns_rc1_when_ffmpeg_succeeds_but_output_missing(self, tmp_path, monkeypatch):
        # Given: ffmpeg は rc=0 だが出力ファイルが書かれていない (filter 不整合 等)
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})
        captured: dict = {}

        # When
        with patch.object(
            mod.subprocess,
            "run",
            side_effect=_fake_run_writes_output(captured, rc=0, write_output=False),
        ):
            rc = apply_rain_layers(collection, collection, quiet=True)

        # Then: rc=1 (ffmpeg 成功扱いだが出力欠落を検知)
        assert rc == 1


# ---------------------------------------------------------------------------
# CLI 入口: main()
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_dry_run_with_explicit_collection(self, tmp_path, monkeypatch, capsys):
        # Given: CLI から --dry-run + 明示パスで起動。collection 自身を channel ルートとして使う
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.chdir(tmp_path.parent)
        monkeypatch.setattr("sys.argv", ["yt-apply-rain-layers", "--dry-run", str(collection)])
        monkeypatch.setattr(
            "youtube_automation.scripts.apply_rain_layers.channel_dir",
            lambda: collection,
        )
        _patch_skill_config(monkeypatch, {"post_processing": {"rain_layers": {"enabled": True}}})

        # When
        rc = mod.main()

        # Then: rc=0 / stdout に ffmpeg コマンド
        assert rc == 0
        out = capsys.readouterr().out
        assert "ffmpeg" in out

    def test_main_resolves_cwd_when_arg_omitted(self, tmp_path, monkeypatch):
        # Given: CWD = コレクションディレクトリ、引数なし、disabled (pass-through)
        collection = _setup_collection(tmp_path, n_rain=0)
        monkeypatch.chdir(collection)
        monkeypatch.setattr("sys.argv", ["yt-apply-rain-layers"])
        _patch_skill_config(monkeypatch, {})

        # When
        rc = mod.main()

        # Then: rc=0 (resolve_collection_dir が CWD 判定で通る)
        assert rc == 0

    def test_main_returns_rc1_when_collection_cannot_be_resolved(self, tmp_path, monkeypatch, capsys):
        # Given: CWD に 01-master/ が無い、引数なし
        empty = tmp_path / "no-collection"
        empty.mkdir()
        monkeypatch.chdir(empty)
        monkeypatch.setattr("sys.argv", ["yt-apply-rain-layers"])

        # When
        rc = mod.main()

        # Then: rc=1
        assert rc == 1
        assert capsys.readouterr().err
