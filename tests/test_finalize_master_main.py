"""finalize_master のオーケストレータ関数 + CLI の振る舞いテスト (subprocess.run mock)。

単体テストレイヤー: 実 ffmpeg は呼ばず、`subprocess.run` を順次差し替えて
pass1 / pass2 のコマンド・終了コード・stderr を制御する。

- pass-through gate: `branding/rain_layers/` 不在 / wav 0 件 → ffmpeg も
  `load_skill_config` も呼ばない (config 検証は gate 通過後にのみ実行する契約)
- atomic rename: pass2 失敗時に元 master が破壊されないことを `read_bytes()`
  比較で直接検証
- two-pass: pass1 stderr の loudnorm JSON が pass2 filter_complex に注入される
  データフローを cmd キャプチャで検証
- defaults / overrides: skill-config の `rain_layer:` namespace 上書きが filter
  に反映されること、未設定時は組み込み defaults が使われること
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from youtube_automation.scripts import finalize_master
from youtube_automation.scripts.finalize_master import (
    finalize_master as run_finalize_master,
)

# pass2 失敗時の master 保護検証用 (元 master のバイト列が変更されないことを assert)。
_ORIGINAL_MASTER_BYTES = b"ORIGINAL_MASTER_BYTES_FOR_TEST"

# pass2 が成功して atomic rename されたことを観測するためのマーカー。
_NEW_MASTER_BYTES = b"NEW_MASTER_BYTES_AFTER_PASS2"


def _setup_collection(tmp_path: Path, n_rain: int) -> Path:
    """tmp_path をコレクション + チャンネルルートとして整える。

    - `01-master/master.mp3` に既知バイト列で書き込み (pass2 失敗時の保護検証用)
    - `02-Individual-music/` も作成 (`resolve_collection_dir` が CWD 判定で
      参照する可能性に備える。CLAUDE.md のディレクトリ構造規約と整合)
    - n_rain >= 1 のとき `branding/rain_layers/rain_NNN.wav` を生成

    Returns:
        コレクション (兼 channel root) ディレクトリ Path
    """
    (tmp_path / "01-master").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01-master" / "master.mp3").write_bytes(_ORIGINAL_MASTER_BYTES)
    (tmp_path / "02-Individual-music").mkdir(parents=True, exist_ok=True)
    if n_rain >= 1:
        rain_dir = tmp_path / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, n_rain + 1):
            (rain_dir / f"rain_{i:03d}.wav").write_bytes(b"\x00")
    return tmp_path


def _make_pass1_stderr(
    *,
    input_i: str = "-23.0",
    input_lra: str = "10.5",
    input_tp: str = "-2.1",
    input_thresh: str = "-33.0",
    target_offset: str = "0.5",
) -> str:
    """ffmpeg pass1 の擬似 stderr を生成する (前置き + 末尾 loudnorm JSON ブロック)。

    `_parse_loudnorm_json` が `rfind('{')` / `rfind('}')` で末尾 JSON を抽出できる
    形に整える (ffmpeg バージョン差異対策の契約と一致)。
    """
    payload = {
        "input_i": input_i,
        "input_tp": input_tp,
        "input_lra": input_lra,
        "input_thresh": input_thresh,
        "output_i": "-14.00",
        "output_tp": "-1.50",
        "output_lra": "5.20",
        "output_thresh": "-24.00",
        "normalization_type": "dynamic",
        "target_offset": target_offset,
    }
    return (
        "ffmpeg version test\n"
        "[Parsed_loudnorm_0 @ 0xdeadbeef]\n"
        + json.dumps(payload, indent=2)
        + "\n"
    )


def _patch_skill_config(monkeypatch, cfg: dict) -> MagicMock:
    """`load_skill_config` を関数自体置換し、呼び出し履歴を spy する。

    `tests/test_generate_master.py` 流儀でプロセス内キャッシュ汚染を回避する。
    Returns:
        MagicMock 化されたスタブ (assert_called_*/呼び出し回数検証に使う)
    """
    spy = MagicMock(return_value=cfg)
    monkeypatch.setattr(
        "youtube_automation.scripts.finalize_master.load_skill_config",
        spy,
    )
    return spy


def _make_fake_run_sequence(
    captured: dict,
    *,
    pass1_stderr: str | None = None,
    pass1_rc: int = 0,
    pass2_rc: int = 0,
    pass2_writes_tmp: bool = True,
):
    """`subprocess.run` を pass1 → pass2 の順に差し替えるファクトリ。

    captured["cmds"] に各呼び出しの cmd を順番に保存する。pass2 が成功扱い
    (rc=0) のとき、cmd 内の `master.tmp.mp3` パスへ `_NEW_MASTER_BYTES` を
    書き込んで atomic rename を観測可能にする。3 回目以降の呼び出しは
    `IndexError` で fail-fast (過剰呼び出し検出)。
    """
    state = {"calls": 0}
    pass1_stderr_default = pass1_stderr or _make_pass1_stderr()

    def _run(cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        idx = state["calls"]
        state["calls"] += 1
        if idx == 0:
            return SimpleNamespace(returncode=pass1_rc, stderr=pass1_stderr_default, stdout="")
        if idx == 1:
            if pass2_rc == 0 and pass2_writes_tmp:
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith("master.tmp.mp3"):
                        Path(arg).write_bytes(_NEW_MASTER_BYTES)
                        break
            return SimpleNamespace(returncode=pass2_rc, stderr="", stdout="")
        raise IndexError(f"unexpected subprocess.run call #{idx + 1}: cmd={cmd}")

    return _run


def _filter_expr(cmd: list[str]) -> str:
    """ffmpeg cmd から `-filter_complex` 直後の filter 式を取り出す。"""
    idx = cmd.index("-filter_complex")
    return cmd[idx + 1]


class TestFinalizeMasterPassThrough:
    """`branding/rain_layers/` の有無で挙動を切り替える pass-through gate。"""

    def test_passthrough_when_branding_rain_layers_dir_missing(self, tmp_path, monkeypatch):
        # Given: branding/rain_layers/ ディレクトリ不在 (未対応チャンネル)
        collection = _setup_collection(tmp_path, n_rain=0)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        cfg_spy = _patch_skill_config(monkeypatch, {})
        run_spy = MagicMock()

        # When
        with patch.object(finalize_master.subprocess, "run", run_spy):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=0 / ffmpeg も skill_config も呼ばれない / master 無傷
        assert rc == 0
        run_spy.assert_not_called()
        cfg_spy.assert_not_called()
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_passthrough_when_rain_wav_files_empty(self, tmp_path, monkeypatch):
        # Given: branding/rain_layers/ は存在するが rain_*.wav が 1 件もない
        collection = _setup_collection(tmp_path, n_rain=0)
        rain_dir = collection / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        (rain_dir / "README.md").write_text("placeholder")
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        cfg_spy = _patch_skill_config(monkeypatch, {})
        run_spy = MagicMock()

        # When
        with patch.object(finalize_master.subprocess, "run", run_spy):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=0 / ffmpeg も skill_config も呼ばれない / master 無傷
        assert rc == 0
        run_spy.assert_not_called()
        cfg_spy.assert_not_called()
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES


class TestFinalizeMasterRun:
    """正常系: pass1 → pass2 → atomic rename の流れと cmd 構造の契約。"""

    def test_one_layer_runs_pass1_pass2_and_replaces_master(self, tmp_path, monkeypatch):
        # Given: rain layer 1 件
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: ffmpeg が 2 回呼ばれ、master が atomic rename で更新され、tmp 残骸なし
        assert rc == 0
        assert len(captured["cmds"]) == 2
        assert (collection / "01-master" / "master.mp3").read_bytes() == _NEW_MASTER_BYTES
        assert not (collection / "01-master" / "master.tmp.mp3").exists()
        # pass2 cmd の `-i` 数 = master + 1 rain = 2
        assert captured["cmds"][1].count("-i") == 2

    def test_three_layers_pass2_has_four_input_args(self, tmp_path, monkeypatch):
        # Given: rain layer 3 件
        collection = _setup_collection(tmp_path, n_rain=3)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: pass2 cmd の `-i` 数 = master + 3 rains = 4
        assert rc == 0
        assert captured["cmds"][1].count("-i") == 4

    def test_passes_pass1_measured_values_into_pass2_filter(self, tmp_path, monkeypatch):
        # Given: pass1 stderr に固有の loudnorm JSON 値
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        pass1_stderr = _make_pass1_stderr(
            input_i="-22.5",
            input_lra="9.7",
            input_tp="-1.8",
            input_thresh="-32.5",
            target_offset="0.42",
        )
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured, pass1_stderr=pass1_stderr),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: pass1 で計測した値が pass2 の filter に注入される (two-pass の本質契約)
        assert rc == 0
        pass2_filter = _filter_expr(captured["cmds"][1])
        assert "measured_I=-22.5" in pass2_filter
        assert "measured_LRA=9.7" in pass2_filter
        assert "measured_TP=-1.8" in pass2_filter
        assert "measured_thresh=-32.5" in pass2_filter
        assert "offset=0.42" in pass2_filter
        assert "linear=true" in pass2_filter

    def test_pass2_uses_skill_config_audio_bitrate(self, tmp_path, monkeypatch):
        # Given: skill-config audio.bitrate に明示値
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {"audio": {"bitrate": "256k"}})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: pass2 cmd の `-b:a` 直後に skill-config の bitrate が入る
        assert rc == 0
        pass2_cmd = captured["cmds"][1]
        assert "-b:a" in pass2_cmd
        ba_idx = pass2_cmd.index("-b:a")
        assert pass2_cmd[ba_idx + 1] == "256k"

    def test_quiet_true_suppresses_stdout_progress(self, tmp_path, monkeypatch, capsys):
        # Given: quiet=True で正常系を通す
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: 進捗ログが stdout に流れない (quiet=True 契約)
        assert rc == 0
        out = capsys.readouterr()
        assert out.out == ""


class TestFinalizeMasterConfig:
    """defaults と skill-config `rain_layer:` namespace 上書きの解決パス。"""

    def test_uses_builtin_defaults_when_no_rain_layer_namespace(self, tmp_path, monkeypatch):
        # Given: skill-config に rain_layer namespace 不在 → 組み込み defaults を採用
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: defaults (volume_db=-19 / fadein_s=0.5 / I=-14 / LRA=11 / TP=-1.5)
        assert rc == 0
        pass2_filter = _filter_expr(captured["cmds"][1])
        assert "volume=-19dB" in pass2_filter
        assert "afade=t=in:st=0:d=0.5" in pass2_filter
        # loudnorm パラメータは `:` 区切りで隣接するため境界文字込みで検証
        assert "I=-14:" in pass2_filter
        assert "LRA=11:" in pass2_filter
        assert "TP=-1.5:" in pass2_filter

    def test_overrides_defaults_via_rain_layer_skill_config(self, tmp_path, monkeypatch):
        # Given: skill-config rain_layer namespace で全パラメータを上書き
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(
            monkeypatch,
            {
                "rain_layer": {
                    "volume_db": -25.5,
                    "fadein_s": 0.75,
                    "loudnorm": {"I": -16.5, "LRA": 9.5, "TP": -2.5},
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

        # Then: override 値が filter に反映される (defaults を完全置換)
        assert rc == 0
        pass2_filter = _filter_expr(captured["cmds"][1])
        assert "volume=-25.5dB" in pass2_filter
        assert "afade=t=in:st=0:d=0.75" in pass2_filter
        assert "I=-16.5:" in pass2_filter
        assert "LRA=9.5:" in pass2_filter
        assert "TP=-2.5:" in pass2_filter


class TestFinalizeMasterFailure:
    """異常系: pass1/pass2 失敗・前提リソース欠落・loudnorm parse 失敗での master 保護。"""

    def test_pass1_failure_returns_rc1_and_preserves_master(self, tmp_path, monkeypatch):
        # Given: pass1 が rc=1 で終了
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(captured, pass1_rc=1),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=1 / 元 master 無傷 / tmp 残骸なし
        assert rc == 1
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES
        assert not (collection / "01-master" / "master.tmp.mp3").exists()

    def test_pass2_failure_returns_rc1_and_preserves_master(self, tmp_path, monkeypatch):
        # Given: pass2 が rc=1 で終了
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        captured: dict = {}

        # When
        with patch.object(
            finalize_master.subprocess,
            "run",
            side_effect=_make_fake_run_sequence(
                captured, pass2_rc=1, pass2_writes_tmp=False
            ),
        ):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=1 / 元 master 無傷 / tmp 残骸なし
        assert rc == 1
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES
        assert not (collection / "01-master" / "master.tmp.mp3").exists()

    def test_finally_cleans_tmp_when_pass2_raises_unexpected_exception(self, tmp_path, monkeypatch):
        # Given: pass2 が tmp を一部書いた状態で OSError を投げる
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})
        state = {"calls": 0}

        def _run(cmd, **kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                return SimpleNamespace(
                    returncode=0, stderr=_make_pass1_stderr(), stdout=""
                )
            tmp = collection / "01-master" / "master.tmp.mp3"
            tmp.write_bytes(b"PARTIAL")
            raise OSError("simulated ffmpeg crash mid-write")

        # When: 例外が握りつぶされても伝搬しても、finally の tmp 掃除契約は同じ
        with patch.object(finalize_master.subprocess, "run", side_effect=_run):
            try:
                run_finalize_master(collection, collection, quiet=True)
            except OSError:
                pass

        # Then: try/finally で tmp が必ず掃除され、master 無傷
        assert not (collection / "01-master" / "master.tmp.mp3").exists()
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_returns_rc1_when_ffmpeg_not_on_path(self, tmp_path, monkeypatch):
        # Given: shutil.which("ffmpeg") が None (ffmpeg 未インストール)
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: None)
        _patch_skill_config(monkeypatch, {})

        # When
        rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=1 / master 無傷
        assert rc == 1
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES

    def test_returns_rc1_when_master_mp3_missing(self, tmp_path, monkeypatch):
        # Given: 01-master/master.mp3 が存在しない (yt-generate-master 未実行)
        collection = _setup_collection(tmp_path, n_rain=1)
        (collection / "01-master" / "master.mp3").unlink()
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})

        # When
        rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=1 (前提リソース欠落)
        assert rc == 1

    def test_returns_rc1_when_pass1_stderr_lacks_loudnorm_json(self, tmp_path, monkeypatch):
        # Given: pass1 が rc=0 だが stderr に loudnorm JSON が無い (異常系)
        collection = _setup_collection(tmp_path, n_rain=1)
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})

        def _run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stderr="ffmpeg pass1 silent", stdout="")

        # When
        with patch.object(finalize_master.subprocess, "run", side_effect=_run):
            rc = run_finalize_master(collection, collection, quiet=True)

        # Then: rc=1 / master 無傷 / tmp 残骸なし
        assert rc == 1
        assert (collection / "01-master" / "master.mp3").read_bytes() == _ORIGINAL_MASTER_BYTES
        assert not (collection / "01-master" / "master.tmp.mp3").exists()


class TestCli:
    """CLI 入口 (`yt-finalize-master`) の到達経路。"""

    def test_main_resolves_collection_dir_from_cwd_when_arg_omitted(self, tmp_path, monkeypatch):
        # Given: CWD = コレクションディレクトリ、引数なし
        collection = _setup_collection(tmp_path, n_rain=0)
        monkeypatch.chdir(collection)
        monkeypatch.setattr("sys.argv", ["yt-finalize-master"])
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})

        # When
        rc = finalize_master.main()

        # Then: pass-through で rc=0 (collection の解決に成功している証左)
        assert rc == 0

    def test_main_resolves_collection_dir_from_explicit_positional_arg(self, tmp_path, monkeypatch):
        # Given: 引数で明示指定、CWD は別の場所
        collection = _setup_collection(tmp_path, n_rain=0)
        other_dir = tmp_path.parent
        monkeypatch.chdir(other_dir)
        monkeypatch.setattr("sys.argv", ["yt-finalize-master", str(collection)])
        monkeypatch.setattr(finalize_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        _patch_skill_config(monkeypatch, {})

        # When
        rc = finalize_master.main()

        # Then: 引数で渡したディレクトリが解決される
        assert rc == 0

    def test_main_returns_rc1_when_collection_cannot_be_resolved(self, tmp_path, monkeypatch, capsys):
        # Given: CWD に 01-master/ が無い、引数なし
        empty_dir = tmp_path / "no-collection-here"
        empty_dir.mkdir()
        monkeypatch.chdir(empty_dir)
        monkeypatch.setattr("sys.argv", ["yt-finalize-master"])

        # When
        rc = finalize_master.main()

        # Then: rc=1 / stderr に何らかのエラーメッセージ
        assert rc == 1
        err = capsys.readouterr().err
        assert err  # stderr に friendly なメッセージが出ること (内容詳細は CLI 仕様次第)
