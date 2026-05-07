"""Issue #210: `.claude/skills/masterup/references/finalize_master.py` CLI / 副作用層 (F 節)。

`finalize` (CLI) と `parse_loudnorm_json` の振る舞いを subprocess.run mock
で検証する。ffmpeg バイナリは呼ばない。

A2 (atomic rename) / B (intro モード自動切替) / C (SKILL.md 整合) の
新しい振る舞いを担保する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests._skill_loader import load_skill_script
from youtube_automation.utils import skill_config
from youtube_automation.utils.config import reset as reset_config


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


def _setup_finalize_collection(
    tmp_path: Path,
    *,
    n_rain: int = 3,
    with_master: bool = True,
    with_sfx: bool = True,
    with_sfx_dir: bool = True,
    with_rain_dir: bool = True,
    master_content: bytes = b"\x00",
) -> tuple[Path, Path]:
    """tmp_path に repo + collection ツリーを組む。

    Args:
        n_rain: rain_*.wav の生成件数 (with_rain_dir=False のときは無視)。
        with_master: 01-master/master.mp3 を作成するか。
        with_sfx: SFX 3 wav を全て配置するか (with_sfx_dir 必要)。
        with_sfx_dir: branding/intro_sfx/ ディレクトリ自体を作成するか。
        with_rain_dir: branding/rain_layers/ ディレクトリ自体を作成するか。
        master_content: master.mp3 の初期 bytes (atomic rename の同一性検証用)。

    Returns:
        (repo_root, collection_dir)
    """
    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")

    # SFX wav
    if with_sfx_dir:
        sfx_dir = repo / "branding" / "intro_sfx"
        sfx_dir.mkdir(parents=True)
        if with_sfx:
            for name in ["cup_v3.wav", "paper.wav", "vinyl_v4.wav"]:
                (sfx_dir / name).write_bytes(b"\x00")

    # rain layers
    if with_rain_dir:
        rain_dir = repo / "branding" / "rain_layers"
        rain_dir.mkdir(parents=True)
        for i in range(n_rain):
            (rain_dir / f"rain_{i:02d}.wav").write_bytes(b"\x00")

    # collection + master
    collection = repo / "collections" / "planning" / "20260101-test"
    (collection / "01-master").mkdir(parents=True)
    if with_master:
        (collection / "01-master" / "master.mp3").write_bytes(master_content)
    return repo, collection


def _input_files_in_cmd(cmd: list[str]) -> list[str]:
    inputs: list[str] = []
    for i, token in enumerate(cmd):
        if token == "-i":
            inputs.append(cmd[i + 1])
    return inputs


def _make_pass1_stderr() -> str:
    """ffmpeg loudnorm pass1 stderr (loudnorm JSON 部) のサンプル。"""
    return (
        "Some unrelated log lines\n"
        '{"input_i": "-21.5", "input_tp": "-3.2", "input_lra": "9.4", '
        '"input_thresh": "-31.7", "output_i": "-14.0", "output_tp": "-1.5", '
        '"output_lra": "11.0", "output_thresh": "-24.5", "normalization_type": '
        '"dynamic", "target_offset": "0.10"}\n'
    )


def make_fake_run(
    *,
    pass1_stderr: str,
    pass2_rc: int,
    pass2_payload: bytes | None,
    temp_path: Path,
):
    """subprocess.run の fake を組み立てる。

    pass1 (1 回目): rc=0、`pass1_stderr` を stderr に返す。
    pass2 (2 回目): `pass2_payload` が None でなければ `temp_path` に書き込み、
        `pass2_rc` を返す。
    """
    state = {"n": 0}

    def fake_run(cmd, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return SimpleNamespace(returncode=0, stderr=pass1_stderr, stdout="")
        if pass2_payload is not None:
            temp_path.write_bytes(pass2_payload)
        return SimpleNamespace(returncode=pass2_rc, stderr="", stdout="")

    fake_run.state = state  # type: ignore[attr-defined]
    return fake_run


# ---------- F-1: pass1 + pass2 が両方走る ----------


def test_finalize_runs_pass1_and_pass2_when_inputs_complete(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given 全 input (master.mp3 + sfx + rain) が揃った状態
    When finalize() を実行
    Then ffmpeg subprocess.run が 2 回 (pass1 + pass2) 呼ばれる。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    temp = collection / "01-master" / "master.tmp.mp3"
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=0,
        pass2_payload=b"\x00",
        temp_path=temp,
    )

    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        rc = finalize_module.finalize(collection)

    assert rc == 0, f"finalize が失敗: {rc}"
    assert fake.state["n"] == 2, f"ffmpeg が 2 回 呼ばれていない: {fake.state['n']}"


# ---------- F-3: rain layer 1 件で -i count が 5 ----------


def test_finalize_accepts_exactly_one_rain_layer(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given rain layer が 1 件 + sfx 3 + master = 合計 5 input
    When finalize() を実行
    Then ffmpeg cmd の `-i` は 5 回出現する。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=1)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    temp = collection / "01-master" / "master.tmp.mp3"
    cmds: list[list[str]] = []
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=0,
        pass2_payload=b"\x00",
        temp_path=temp,
    )

    def fake_run_with_capture(cmd, **kwargs):
        cmds.append(list(cmd))
        return fake(cmd, **kwargs)

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run_with_capture):
        rc = finalize_module.finalize(collection)

    assert rc == 0
    # pass2 cmd を見る (どちらでも -i count は同じはず)
    assert cmds, "ffmpeg が呼ばれていない"
    inputs = _input_files_in_cmd(cmds[-1])
    # master + cup + paper + vinyl + 1 rain = 5
    assert len(inputs) == 5, f"-i 数が 5 でない: {len(inputs)}\n  inputs={inputs}"


# ---------- F-4: parse_loudnorm_json の堅牢性 ----------


def test_parse_loudnorm_json_extracts_last_json_block(finalize_module) -> None:
    """Given stderr に JSON ブロックが複数含まれる
    When parse_loudnorm_json(stderr) を呼ぶ
    Then 最後の JSON ブロックが返る (loudnorm 自体の出力は最後のもの)。
    """
    stderr = (
        '{"unrelated": "first"}\n'
        'log line\n'
        '{"input_i": "-21.5", "input_tp": "-3.2", "input_lra": "9.4", '
        '"input_thresh": "-31.7", "target_offset": "0.10"}\n'
    )
    result = finalize_module.parse_loudnorm_json(stderr)
    assert isinstance(result, dict)
    # loudnorm 由来の最後の JSON が選ばれていること
    assert result.get("input_i") == "-21.5"


# ---------- F-5: master.mp3 不在で exit 1 ----------


def test_finalize_exits_1_when_master_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given master.mp3 が存在しない
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3, with_master=False)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)

    assert rc == 1
    mock_run.assert_not_called()


# ---------- F-6: SFX wav 不在で exit 1 (dir はあるが中身欠落 = ハーフ実装) ----------


def test_finalize_exits_1_when_sfx_wav_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/intro_sfx/ ディレクトリは存在するが cup_v3.wav が欠ける
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1 (fail-fast、ハーフ実装防止)。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3, with_sfx=True)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    (repo / "branding" / "intro_sfx" / "cup_v3.wav").unlink()

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)

    assert rc == 1
    mock_run.assert_not_called()


# ---------- F-7: rain_*.wav 0 件で exit 1 (dir はあるが中身欠落 = ハーフ実装) ----------


def test_finalize_exits_1_when_rain_layers_empty(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/rain_layers/ ディレクトリは存在するが rain_*.wav が 0 件
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1 (fail-fast、ハーフ実装防止)。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=0)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)

    assert rc == 1
    mock_run.assert_not_called()


# ---------- F-8: pass1 失敗時 exit code 伝播 (pass2 未実行) ----------


def test_finalize_propagates_pass1_nonzero_exit_and_skips_pass2(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given pass1 ffmpeg が exit code 5 で失敗
    When finalize() を呼ぶ
    Then pass2 は呼ばれず、rc != 0 で抜ける。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=2)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    state = {"n": 0}

    def fake_run(cmd, **kwargs):
        state["n"] += 1
        return SimpleNamespace(returncode=5, stderr="ffmpeg failed", stdout="")

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run):
        rc = finalize_module.finalize(collection)

    assert rc != 0, f"pass1 失敗時に rc=0 で返した: {rc}"
    assert state["n"] == 1, f"pass2 が呼ばれてしまった (call count={state['n']})"


# ---------- F-9: parse_loudnorm_json — JSON 不在で RuntimeError ----------


def test_parse_loudnorm_json_raises_runtime_error_when_no_json_block(
    finalize_module,
) -> None:
    """Given stderr に loudnorm JSON ブロックが含まれない
    When parse_loudnorm_json(stderr) を呼ぶ
    Then RuntimeError (パース失敗を握りつぶさない)。
    """
    with pytest.raises(RuntimeError):
        finalize_module.parse_loudnorm_json("plain text without any json")


# ====================================================================
# A2: atomic rename (#1, #2, #7, #8, #15)
# ====================================================================


# ---------- A2-1 (#1): in-place replace via atomic rename ----------


def test_finalize_replaces_master_in_place_with_pass2_output(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given 既知 bytes b"ORIG" を master.mp3 に書き、intro 素材が完全に揃った repo
    When pass2 fake が temp_out (master.tmp.mp3) に b"FINAL" を書いて rc=0 を返す
    Then rc=0、master.mp3 の中身が b"FINAL" に置換される (atomic rename)。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path, n_rain=2, master_content=b"ORIG"
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    temp = collection / "01-master" / "master.tmp.mp3"
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=0,
        pass2_payload=b"FINAL",
        temp_path=temp,
    )
    # When
    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0
    assert master.read_bytes() == b"FINAL", (
        "master.mp3 が pass2 出力 (b'FINAL') に置き換わっていない"
    )


# ---------- A2-2 (#2): temp ファイルが残らない (success path) ----------


def test_finalize_does_not_leave_temp_file_on_success(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given pass2 が成功して master.tmp.mp3 に書く
    When finalize() を実行
    Then 完了後 master.tmp.mp3 は残らない (atomic rename で master.mp3 に昇格)。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path, n_rain=2, master_content=b"ORIG"
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    temp = collection / "01-master" / "master.tmp.mp3"
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=0,
        pass2_payload=b"FINAL",
        temp_path=temp,
    )
    # When
    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0
    assert not temp.exists(), f"成功後に temp ファイルが残っている: {temp}"


# ---------- A2-3 (#7): pass2 失敗時に元 master.mp3 が無傷 ----------


def test_finalize_does_not_clobber_master_when_pass2_fails(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given pass2 fake が temp に b"GARBAGE" を書いて rc=7 で失敗
    When finalize() を呼ぶ
    Then rc=7 が伝播し、元 master.mp3 (b"ORIG") は無傷のまま残る。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path, n_rain=2, master_content=b"ORIG"
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    temp = collection / "01-master" / "master.tmp.mp3"
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=7,
        pass2_payload=b"GARBAGE",
        temp_path=temp,
    )
    # When
    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 7, f"pass2 の rc=7 が伝播していない: {rc}"
    assert master.read_bytes() == b"ORIG", (
        "pass2 失敗時に元 master.mp3 が壊れた (atomic rename の本質を破壊)"
    )


# ---------- A2-3 (#8): pass2 失敗時に temp ファイルが後始末される ----------


def test_finalize_cleans_up_temp_file_when_pass2_fails(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given pass2 fake が temp に書いて rc=7 で失敗
    When finalize() を呼ぶ
    Then 抜けた後に temp (master.tmp.mp3) は best-effort 削除される。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path, n_rain=2, master_content=b"ORIG"
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    temp = collection / "01-master" / "master.tmp.mp3"
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=7,
        pass2_payload=b"GARBAGE",
        temp_path=temp,
    )
    # When
    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        finalize_module.finalize(collection)
    # Then
    assert not temp.exists(), (
        f"pass2 失敗後に temp ファイルが残っている: {temp}"
    )


# ---------- A2 edge (#15): stale temp を再実行で必ず上書きする ----------


def test_finalize_overwrites_stale_temp_with_fresh_pass2_output(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given 前回失敗で残置された master.tmp.mp3 (b"STALE") が事前に存在
    When pass2 が temp に b"FRESH" を書き直して rc=0 を返す
    Then master.mp3 の中身は b"FRESH" になる (stale 内容を昇格させない順序保証)。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path, n_rain=2, master_content=b"ORIG"
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    temp = collection / "01-master" / "master.tmp.mp3"
    temp.write_bytes(b"STALE")  # 前回失敗の残置を再現
    fake = make_fake_run(
        pass1_stderr=_make_pass1_stderr(),
        pass2_rc=0,
        pass2_payload=b"FRESH",
        temp_path=temp,
    )
    # When
    with patch.object(finalize_module.subprocess, "run", side_effect=fake):
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0
    assert master.read_bytes() == b"FRESH", (
        "stale temp 内容が master に昇格してしまった (pass2 が temp を上書きしていない)"
    )


# ====================================================================
# B: intro モード自動切替 (#3, #4, #5, #6)
# ====================================================================


# ---------- B-1 (#3): intro_sfx/ 非存在で pass-through ----------


def test_finalize_pass_through_when_intro_sfx_dir_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/intro_sfx/ ディレクトリが存在しない (rain_layers/ のみ作成)
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=0、master.mp3 の中身は不変。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path,
        n_rain=2,
        with_sfx_dir=False,
        master_content=b"ORIG",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    # When
    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0, f"pass-through で rc=0 を返さない: {rc}"
    mock_run.assert_not_called()
    assert master.read_bytes() == b"ORIG", (
        "pass-through 経路で master.mp3 が変更された (何もしないのが正解)"
    )


# ---------- B-2 (#4): rain_layers/ 非存在で pass-through ----------


def test_finalize_pass_through_when_rain_layers_dir_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/rain_layers/ ディレクトリが存在しない (intro_sfx/ のみ作成)
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=0、master.mp3 の中身は不変。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path,
        with_rain_dir=False,
        master_content=b"ORIG",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    # When
    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0, f"pass-through で rc=0 を返さない: {rc}"
    mock_run.assert_not_called()
    assert master.read_bytes() == b"ORIG", (
        "pass-through 経路で master.mp3 が変更された (何もしないのが正解)"
    )


# ---------- B-1+B-2 OR 短絡 (#5): 両 dir 非存在でも pass-through ----------


def test_finalize_pass_through_when_both_intro_dirs_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/intro_sfx/ も branding/rain_layers/ も存在しない
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=0、master.mp3 の中身は不変 (OR 短絡境界)。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path,
        with_sfx_dir=False,
        with_rain_dir=False,
        master_content=b"ORIG",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    master = collection / "01-master" / "master.mp3"
    # When
    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection)
    # Then
    assert rc == 0
    mock_run.assert_not_called()
    assert master.read_bytes() == b"ORIG"


# ---------- #6: pass-through ログを stderr に出す ----------


def test_finalize_emits_pass_through_log_to_stderr(
    finalize_module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Given intro 素材ディレクトリが存在しない (pass-through 条件)
    When finalize() を呼ぶ
    Then stderr に INFO:/WARN:/WARNING: いずれかの prefix と
        intro/pass を示すワードが出る (寛容検証)。
    """
    # Given
    repo, collection = _setup_finalize_collection(
        tmp_path,
        with_sfx_dir=False,
        master_content=b"ORIG",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    # When
    with patch.object(finalize_module.subprocess, "run"):
        finalize_module.finalize(collection)
    # Then
    err = capsys.readouterr().err
    assert any(prefix in err for prefix in ("INFO:", "WARN:", "WARNING:")), (
        f"pass-through ログ prefix (INFO:/WARN:/WARNING:) が stderr に無い:\n{err!r}"
    )
    # pass-through を示すワードのいずれかが含まれていれば OK (実装の表記揺れ吸収)
    assert "intro" in err.lower() or "pass" in err.lower(), (
        f"pass-through を示すワードが stderr に無い:\n{err!r}"
    )


# ====================================================================
# CLI surface: --keep-raw 削除リグレッション (#10)
# ====================================================================


def test_main_rejects_removed_keep_raw_flag(
    finalize_module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Given finalize_master.py main() に --keep-raw フラグは存在しない
    When sys.argv に --keep-raw を渡して main() を呼ぶ
    Then argparse が SystemExit(rc=2) で拒否し、エラー出力に `--keep-raw` が含まれる。
    """
    # Given
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=2)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    monkeypatch.setattr(
        sys,
        "argv",
        ["finalize_master.py", str(collection), "--keep-raw"],
    )
    # When / Then
    with pytest.raises(SystemExit) as exc_info:
        finalize_module.main()
    assert exc_info.value.code == 2, (
        f"argparse の --keep-raw 拒否で rc=2 が出ていない: {exc_info.value.code}"
    )
    err = capsys.readouterr().err
    assert "--keep-raw" in err, (
        f"argparse のエラー出力に `--keep-raw` が含まれていない (任意の unknown オプションで通る検証になっている):\n{err!r}"
    )
