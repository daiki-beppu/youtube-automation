"""Issue #137: `.claude/skills/masterup/references/finalize_master.py` CLI / 副作用層 (F 節)。

`finalize` (CLI) と `parse_loudnorm_json` の振る舞いを subprocess.run mock
で検証する。ffmpeg バイナリは呼ばない。
"""

from __future__ import annotations

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
) -> tuple[Path, Path]:
    """tmp_path に repo + collection ツリーを組む。

    Returns:
        (repo_root, collection_dir)
    """
    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")

    # SFX wav
    if with_sfx:
        sfx_dir = repo / "branding" / "intro_sfx"
        sfx_dir.mkdir(parents=True)
        for name in ["cup_v3.wav", "paper.wav", "vinyl_v4.wav"]:
            (sfx_dir / name).write_bytes(b"\x00")

    # rain layers
    rain_dir = repo / "branding" / "rain_layers"
    rain_dir.mkdir(parents=True)
    for i in range(n_rain):
        (rain_dir / f"rain_{i:02d}.wav").write_bytes(b"\x00")

    # collection + master_raw
    collection = repo / "collections" / "planning" / "20260101-test"
    (collection / "01-master").mkdir(parents=True)
    if with_master:
        (collection / "01-master" / "master_raw.mp3").write_bytes(b"\x00")
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


# ---------- F-1: pass1 + pass2 が両方走る ----------


def test_finalize_runs_pass1_and_pass2_when_inputs_complete(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given 全 input (master_raw.mp3 + sfx + rain) が揃った状態
    When finalize() を実行
    Then ffmpeg subprocess.run が 2 回 (pass1 + pass2) 呼ばれる。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    pass1_stderr = _make_pass1_stderr()
    call_count: dict[str, int] = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        # 1 回目は loudnorm pass1 -> stderr に JSON
        # 2 回目は実 mix -> 出力ファイルを書く
        if call_count["n"] == 1:
            return SimpleNamespace(returncode=0, stderr=pass1_stderr, stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run):
        rc = finalize_module.finalize(collection, keep_raw=True)

    assert rc == 0, f"finalize が失敗: {rc}"
    assert call_count["n"] == 2, f"ffmpeg が 2 回 呼ばれていない: {call_count['n']}"


# ---------- F-2: master_raw のクリーンアップ / --keep-raw 保持 ----------


def test_finalize_removes_master_raw_by_default(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given finalize 成功
    When keep_raw=False (default)
    Then master_raw.mp3 は削除される。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=2)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    raw_path = collection / "01-master" / "master_raw.mp3"
    assert raw_path.exists()

    pass1_stderr = _make_pass1_stderr()
    state = {"n": 0}

    def fake_run(cmd, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return SimpleNamespace(returncode=0, stderr=pass1_stderr, stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run):
        rc = finalize_module.finalize(collection, keep_raw=False)

    assert rc == 0
    assert not raw_path.exists(), "keep_raw=False で master_raw.mp3 が消えていない"


def test_finalize_keeps_master_raw_with_keep_raw_flag(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given finalize 成功 + keep_raw=True
    When 完了後
    Then master_raw.mp3 は残る。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=2)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    raw_path = collection / "01-master" / "master_raw.mp3"

    pass1_stderr = _make_pass1_stderr()
    state = {"n": 0}

    def fake_run(cmd, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return SimpleNamespace(returncode=0, stderr=pass1_stderr, stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run):
        rc = finalize_module.finalize(collection, keep_raw=True)

    assert rc == 0
    assert raw_path.exists(), "keep_raw=True なのに master_raw.mp3 が消えた"


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

    pass1_stderr = _make_pass1_stderr()
    state: dict[str, list] = {"cmds": []}

    def fake_run(cmd, **kwargs):
        state["cmds"].append(list(cmd))
        if len(state["cmds"]) == 1:
            return SimpleNamespace(returncode=0, stderr=pass1_stderr, stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    with patch.object(finalize_module.subprocess, "run", side_effect=fake_run):
        rc = finalize_module.finalize(collection, keep_raw=True)

    assert rc == 0
    # pass2 cmd を見る (どちらでも -i count は同じはず)
    assert state["cmds"], "ffmpeg が呼ばれていない"
    inputs = _input_files_in_cmd(state["cmds"][-1])
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


# ---------- F-5: master_raw 不在で exit 1 ----------


def test_finalize_exits_1_when_master_raw_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given master_raw.mp3 が存在しない
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3, with_master=False)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection, keep_raw=True)

    assert rc == 1
    mock_run.assert_not_called()


# ---------- F-6: SFX wav 不在で exit 1 ----------


def test_finalize_exits_1_when_sfx_wav_missing(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/intro_sfx/cup_v3.wav が存在しない
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=3, with_sfx=True)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))
    (repo / "branding" / "intro_sfx" / "cup_v3.wav").unlink()

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection, keep_raw=True)

    assert rc == 1
    mock_run.assert_not_called()


# ---------- F-7: rain_*.wav 0 件で exit 1 ----------


def test_finalize_exits_1_when_rain_layers_empty(
    finalize_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given branding/rain_layers/ ディレクトリは存在するが rain_*.wav が 0 件
    When finalize() を呼ぶ
    Then ffmpeg を呼ばずに rc=1。
    """
    repo, collection = _setup_finalize_collection(tmp_path, n_rain=0)
    monkeypatch.setenv("CHANNEL_DIR", str(repo))

    with patch.object(finalize_module.subprocess, "run") as mock_run:
        rc = finalize_module.finalize(collection, keep_raw=True)

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
        rc = finalize_module.finalize(collection, keep_raw=True)

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
