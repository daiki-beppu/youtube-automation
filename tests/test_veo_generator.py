"""utils.veo_generator の単体テスト。

Issue #186: `trim_tail` / `smooth_loop` の duration 取得 argv に `"--"` sentinel
リグレッションガード。

Issue #358: `build_structured_prompt` のプロンプト構築検証。

Issue #453: generate_loop_video() の resume / KeyboardInterrupt / state lifecycle を検証する。
state は <CHANNEL_DIR>/tmp/veo-operations/<key>.json に決定的に着地する。
CHANNEL_DIR を monkeypatch.setenv で tmp_path に向け config.reset() で再解決させる標準パターンを使う。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils import veo_generator
from youtube_automation.utils.veo_generator import build_structured_prompt


def _install_capture(monkeypatch) -> dict:
    """`subprocess.check_output` を fake 化し、cmd を捕捉して即座に
    `ValueError` を発生させる。`trim_tail` / `smooth_loop` は
    `Exception` 全般を catch して `False` を返すため、これで
    argv 検証だけに絞った最小テストになる。
    """
    captured: dict = {}

    def fake_check_output(cmd, **kwargs):
        captured["cmd"] = cmd
        # float() で ValueError を発生させ、関数を早期 False で抜けさせる。
        return "not-a-number"

    monkeypatch.setattr(veo_generator.subprocess, "check_output", fake_check_output)
    return captured


# ---------- trim_tail ----------


def test_trim_tail_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_trim_tail_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"


# ---------- smooth_loop ----------


def test_smooth_loop_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_smooth_loop_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"


# ---------- compress_loop / smooth_loop crf 引数化 (Issue #175) ----------


def _install_run_capture(monkeypatch) -> dict:
    """`subprocess.run` を fake 化し、argv を捕捉して即座に CalledProcessError を返す。

    rename / stat の副作用に到達する前に失敗で抜けさせ、argv 検証だけに絞る。
    """
    import subprocess as _sp

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise _sp.CalledProcessError(1, cmd, output=b"", stderr=b"forced")

    monkeypatch.setattr(veo_generator.subprocess, "run", fake_run)
    return captured


def test_compress_loop_uses_configured_crf_and_preset(monkeypatch) -> None:
    captured = _install_run_capture(monkeypatch)

    result = veo_generator.compress_loop(Path("/fake.mp4"), crf=22, preset="slow")

    assert result is False
    cmd = captured["cmd"]
    assert cmd[:2] == ["ffmpeg", "-y"]
    # libx264 / -crf 22 / -preset slow / -pix_fmt yuv420p / -an が argv に含まれる
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "22"
    assert cmd[cmd.index("-preset") + 1] == "slow"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "-an" in cmd


def test_compress_loop_uses_custom_crf_value(monkeypatch) -> None:
    """CRF 24（攻める設定）が argv に正しく反映される。"""
    captured = _install_run_capture(monkeypatch)

    veo_generator.compress_loop(Path("/fake.mp4"), crf=24, preset="veryslow")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-crf") + 1] == "24"
    assert cmd[cmd.index("-preset") + 1] == "veryslow"


def test_compress_loop_returns_false_on_ffmpeg_failure(monkeypatch) -> None:
    """ffmpeg 失敗時は False を返す。"""
    _install_run_capture(monkeypatch)

    result = veo_generator.compress_loop(Path("/nonexistent.mp4"))
    assert result is False


def test_smooth_loop_accepts_custom_crf_preset(monkeypatch) -> None:
    """smooth_loop の crf/preset 引数が ffmpeg argv に伝播する（Issue #175）。"""
    import subprocess as _sp

    monkeypatch.setattr(veo_generator.subprocess, "check_output", lambda cmd, **_: "10.0")

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise _sp.CalledProcessError(1, cmd, output=b"", stderr=b"forced")

    monkeypatch.setattr(veo_generator.subprocess, "run", fake_run)

    veo_generator.smooth_loop(Path("/fake.mp4"), crossfade_sec=0.5, crf=22, preset="slow")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "22"
    assert cmd[cmd.index("-preset") + 1] == "slow"


def test_smooth_loop_defaults_to_legacy_crf_18(monkeypatch) -> None:
    """smooth_loop の crf/preset デフォルトは従来の 18 / slow を維持する（後方互換）。"""
    import subprocess as _sp

    monkeypatch.setattr(veo_generator.subprocess, "check_output", lambda cmd, **_: "10.0")

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise _sp.CalledProcessError(1, cmd, output=b"", stderr=b"forced")

    monkeypatch.setattr(veo_generator.subprocess, "run", fake_run)

    veo_generator.smooth_loop(Path("/fake.mp4"))

    cmd = captured["cmd"]
    assert cmd[cmd.index("-crf") + 1] == "18"
    assert cmd[cmd.index("-preset") + 1] == "slow"


# =============================================================================
# generate_loop_video: resume / SIGINT / state lifecycle
# Issue #453
# =============================================================================


@pytest.fixture
def channel_tmp(tmp_path: Path, monkeypatch):
    """CHANNEL_DIR を tmp_path に向け config singleton をリセットする標準パターン。

    state ファイルは tmp_path/tmp/veo-operations/<key>.json に着地する。
    """
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    from youtube_automation.utils.config import reset

    reset()
    yield tmp_path
    reset()


@pytest.fixture
def output_mp4(channel_tmp: Path):
    """テスト用の出力パスを返す（ファイルは未作成）。"""
    return channel_tmp / "collections" / "foo" / "10-assets" / "loop.mp4"


def _make_done_operation(name: str = "projects/veo/12345") -> MagicMock:
    """done=True の operation モックを返す。"""
    op = MagicMock()
    op.name = name
    op.done = True
    op.response.generated_videos = [MagicMock()]
    op.response.generated_videos[0].video.video_bytes = b"fake-video-bytes"
    return op


def _patch_genai_types(monkeypatch) -> MagicMock:
    """google.genai.types を sys.modules 経由で差し替える。

    `from google.genai import types` は `sys.modules["google.genai"]` から
    `types` 属性を解決するため、`sys.modules` に直接注入する。
    google-genai パッケージがテスト venv に存在しない環境でも動作する。
    """
    mock_types = MagicMock()
    mock_types.Image.from_file.return_value = MagicMock()
    mock_types.GenerateVideosConfig.return_value = MagicMock()
    mock_types.GenerateVideosOperation.return_value = MagicMock(name="op-resumed", done=False)

    mock_genai = MagicMock()
    mock_genai.types = mock_types

    mock_google = MagicMock()
    mock_google.genai = mock_genai

    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_types)
    return mock_types


class TestGenerateLoopVideoNewSubmit:
    """新規 submit 経路のテスト."""

    def test_saves_state_after_operation_returned(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """Given: state なし / When: generate_loop_video 成功 / Then: state が一時的に作られ成功後に消える。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        operation = _make_done_operation()
        client.models.generate_videos.return_value = operation

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        # Then: 成功したので state は削除済み
        assert result is True
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_does_not_save_state_when_operation_name_is_empty(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch, capsys
    ) -> None:
        """operation.name が空 / None なら save をスキップして [Warn] を出す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        op = _make_done_operation(name="")
        op.name = ""
        client.models.generate_videos.return_value = op

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        out = capsys.readouterr().out
        assert "[Warn]" in out

        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None


class TestGenerateLoopVideoResume:
    """resume 経路（state あり）のテスト."""

    def _write_state(self, channel_tmp: Path, output_mp4: Path, operation_name: str, model: str) -> None:
        from youtube_automation.utils import veo_operation_store as op_store

        op_store.save(output_mp4, operation_name, model, channel_root=channel_tmp)

    def test_skips_generate_videos_when_state_exists(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """Given: state あり / When: generate_loop_video / Then: client.models.generate_videos 未呼び出し。"""
        # Given
        mock_types = _patch_genai_types(monkeypatch)
        client = MagicMock()
        done_op = _make_done_operation("projects/veo/resumed-op")
        mock_types.GenerateVideosOperation.return_value = MagicMock(name="projects/veo/resumed-op", done=True)
        client.operations.get.return_value = done_op
        self._write_state(channel_tmp, output_mp4, "projects/veo/resumed-op", "veo-3.1-fast")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        # Then: 新規発行は呼ばれない
        client.models.generate_videos.assert_not_called()
        # Then: 保存済み operation_name で GenerateVideosOperation を再構築した
        mock_types.GenerateVideosOperation.assert_called_once_with(name="projects/veo/resumed-op")

    def test_warns_on_model_mismatch(self, channel_tmp: Path, output_mp4: Path, monkeypatch, capsys) -> None:
        """保存モデルと引数モデルが違う場合 [Warn] を出す。"""
        mock_types = _patch_genai_types(monkeypatch)
        client = MagicMock()
        done_op = _make_done_operation("projects/veo/op-x")
        mock_types.GenerateVideosOperation.return_value = MagicMock(name="projects/veo/op-x", done=True)
        client.operations.get.return_value = done_op
        # state に保存したモデルと引数モデルを意図的に変える
        self._write_state(channel_tmp, output_mp4, "projects/veo/op-x", "veo-3.1-fast")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-DIFFERENT-model",
                    prompt="test prompt",
                )

        out = capsys.readouterr().out
        assert "[Warn]" in out

    def test_clears_state_on_success(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """resume 成功後に state が削除される。"""
        mock_types = _patch_genai_types(monkeypatch)
        client = MagicMock()
        done_op = _make_done_operation("projects/veo/op-ok")
        mock_types.GenerateVideosOperation.return_value = MagicMock(name="projects/veo/op-ok", done=True)
        client.operations.get.return_value = done_op
        self._write_state(channel_tmp, output_mp4, "projects/veo/op-ok", "veo-3.1-fast")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is True
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None
        # Then: 保存済み operation_name で GenerateVideosOperation を再構築した
        mock_types.GenerateVideosOperation.assert_called_once_with(name="projects/veo/op-ok")

    def test_preserves_state_on_transient_operations_get_error_in_resume(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch
    ) -> None:
        """resume 経路で operations.get が一時障害なら state を保持して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        # resume 経路の operations.get で一時障害
        client.operations.get.side_effect = ConnectionError("connection reset by peer")
        self._write_state(channel_tmp, output_mp4, "projects/veo/resume-transient", "veo-3.1-fast")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        # Then: False を返し、state は保持されている（一時障害なので再試行可能）
        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        state = op_store.load(output_mp4, channel_root=channel_tmp)
        assert state is not None
        assert state["operation_name"] == "projects/veo/resume-transient"

    def test_clears_state_on_not_found_in_resume(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """resume 経路で operations.get が not found なら state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        client.operations.get.side_effect = Exception("operation not found")
        self._write_state(channel_tmp, output_mp4, "projects/veo/resume-not-found", "veo-3.1-fast")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_cost_log_uses_saved_model_on_mismatch(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """resume 時のモデル不一致でも cost_tracker には保存済みモデルを記録する（ai-review-002）。"""
        mock_types = _patch_genai_types(monkeypatch)
        client = MagicMock()
        done_op = _make_done_operation("projects/veo/op-mismatch")
        mock_types.GenerateVideosOperation.return_value = MagicMock(name="projects/veo/op-mismatch", done=True)
        client.operations.get.return_value = done_op
        # state に保存したモデルと引数モデルを意図的に変える
        saved_model = "veo-3.1-fast"
        self._write_state(channel_tmp, output_mp4, "projects/veo/op-mismatch", saved_model)

        mock_cost = MagicMock()
        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=mock_cost,
        ):
            with patch("time.sleep"):
                veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-DIFFERENT-model",
                    prompt="test prompt",
                )

        # Then: cost_tracker.log_generation は保存済みモデルで呼ばれる
        mock_cost.log_generation.assert_called_once()
        call_args = mock_cost.log_generation.call_args
        # log_generation("video", model=...) なので keyword で渡される
        assert call_args.kwargs.get("model") == saved_model


class TestGenerateLoopVideoSubmitInterrupt:
    """generate_videos() 実行中の KeyboardInterrupt テスト（ai-review-003）."""

    def test_returns_false_on_submit_keyboard_interrupt(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch, capsys
    ) -> None:
        """generate_videos() の Ctrl+C は resume 不可メッセージを出して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        client.models.generate_videos.side_effect = KeyboardInterrupt

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                try:
                    result = veo_generator.generate_loop_video(
                        client,
                        output_mp4.parent / "main.png",
                        output_mp4,
                        model="veo-3.1-fast",
                        prompt="test prompt",
                    )
                except KeyboardInterrupt:
                    pytest.fail("generate_loop_video が submit 中の KeyboardInterrupt を捕捉していない")

        assert result is False
        out = capsys.readouterr().out
        assert "[Interrupt]" in out

    def test_does_not_save_state_on_submit_keyboard_interrupt(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch
    ) -> None:
        """generate_videos() の Ctrl+C では operation_name 未取得のため state を保存しない。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        client.models.generate_videos.side_effect = KeyboardInterrupt

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                try:
                    veo_generator.generate_loop_video(
                        client,
                        output_mp4.parent / "main.png",
                        output_mp4,
                        model="veo-3.1-fast",
                        prompt="test prompt",
                    )
                except KeyboardInterrupt:
                    pytest.fail("generate_loop_video が submit 中の KeyboardInterrupt を捕捉していない")

        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None


class TestGenerateLoopVideoKeyboardInterrupt:
    """KeyboardInterrupt 受信時のテスト."""

    def test_preserves_state_on_keyboard_interrupt(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """SIGINT (KeyboardInterrupt) 受信時に state を保持したまま False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/interrupt-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op
        # operations.get で KeyboardInterrupt を発生させる
        client.operations.get.side_effect = KeyboardInterrupt

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                try:
                    result = veo_generator.generate_loop_video(
                        client,
                        output_mp4.parent / "main.png",
                        output_mp4,
                        model="veo-3.1-fast",
                        prompt="test prompt",
                    )
                except KeyboardInterrupt:
                    # 実装前: KeyboardInterrupt が関数の外へ漏れる場合は失敗扱い。
                    # 実装後: except KeyboardInterrupt が関数内に追加されてここには来ない。
                    pytest.fail("generate_loop_video が KeyboardInterrupt を捕捉していない")

        # Then: False を返す
        assert result is False

        # Then: state は保持されている（再開可能）
        from youtube_automation.utils import veo_operation_store as op_store

        state = op_store.load(output_mp4, channel_root=channel_tmp)
        assert state is not None
        assert state["operation_name"] == "projects/veo/interrupt-op"

    def test_prints_interrupt_resume_state_messages(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch, capsys
    ) -> None:
        """SIGINT 時に [Interrupt] / [Resume] / [State] <state_path> が stdout に出る。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/interrupt-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op
        client.operations.get.side_effect = KeyboardInterrupt

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                try:
                    veo_generator.generate_loop_video(
                        client,
                        output_mp4.parent / "main.png",
                        output_mp4,
                        model="veo-3.1-fast",
                        prompt="test prompt",
                    )
                except KeyboardInterrupt:
                    pytest.fail("generate_loop_video が KeyboardInterrupt を捕捉していない")

        # Then: [Interrupt] / [Resume] / [State] <state_path> が stdout に含まれる
        from youtube_automation.utils import veo_operation_store as op_store

        expected_path = op_store.state_path(output_mp4, channel_root=channel_tmp)
        out = capsys.readouterr().out
        assert "[Interrupt]" in out
        assert "[Resume]" in out
        assert f"[State] {expected_path}" in out


class TestGenerateLoopVideoStateLifecycle:
    """state ライフサイクル（成功 / タイムアウト / 空レスポンス / operations.get 例外）のテスト."""

    def test_clears_state_on_empty_response(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """operation.response が空なら state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        op = MagicMock()
        op.name = "projects/veo/empty-resp"
        op.done = True
        op.response = None  # 空レスポンス
        client.models.generate_videos.return_value = op

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_clears_state_on_generated_videos_empty(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """generated_videos が空リストなら state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        op = MagicMock()
        op.name = "projects/veo/no-videos"
        op.done = True
        op.response.generated_videos = []
        client.models.generate_videos.return_value = op

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_clears_state_on_operations_get_exception(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """client.operations.get が not found 例外（失効 operation）なら state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/expired-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op
        client.operations.get.side_effect = Exception("operation not found")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_preserves_state_on_transient_operations_get_error(
        self, channel_tmp: Path, output_mp4: Path, monkeypatch
    ) -> None:
        """client.operations.get が一時障害（接続エラー等）なら state を保持して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/transient-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op
        # 接続エラー等の一時障害 — "not found" / "404" を含まない
        client.operations.get.side_effect = ConnectionError("connection reset by peer")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        # Then: False を返し、state は保持されている（再試行可能）
        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        state = op_store.load(output_mp4, channel_root=channel_tmp)
        assert state is not None
        assert state["operation_name"] == "projects/veo/transient-op"

    def test_clears_state_on_404_operations_get_error(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """client.operations.get が 404 エラーなら state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/expired-404-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op
        client.operations.get.side_effect = Exception("404 NOT_FOUND: resource not found")

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_preserves_state_on_timeout(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """MAX_POLL_SEC タイムアウト時は state を保持する（API 側は継続中）。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        submitted_op = MagicMock()
        submitted_op.name = "projects/veo/timeout-op"
        submitted_op.done = False
        client.models.generate_videos.return_value = submitted_op

        polling_op = MagicMock()
        polling_op.name = "projects/veo/timeout-op"
        polling_op.done = False
        client.operations.get.return_value = polling_op

        # monotonic を操作して即タイムアウトさせる
        import youtube_automation.utils.veo_generator as vg

        monkeypatch.setattr(vg, "MAX_POLL_SEC", -1)  # 即タイムアウト

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        # state は保持されている
        state = op_store.load(output_mp4, channel_root=channel_tmp)
        assert state is not None
        assert state["operation_name"] == "projects/veo/timeout-op"

    def test_clears_state_on_missing_video_bytes(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """video_bytes が None の場合 state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        op = MagicMock()
        op.name = "projects/veo/no-bytes"
        op.done = True
        op.response.generated_videos = [MagicMock()]
        op.response.generated_videos[0].video.video_bytes = None  # bytes なし
        client.models.generate_videos.return_value = op

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None

    def test_clears_state_on_empty_video_bytes(self, channel_tmp: Path, output_mp4: Path, monkeypatch) -> None:
        """video_bytes が空 bytes の場合 state を削除して False を返す。"""
        _patch_genai_types(monkeypatch)
        client = MagicMock()
        op = MagicMock()
        op.name = "projects/veo/empty-bytes"
        op.done = True
        op.response.generated_videos = [MagicMock()]
        op.response.generated_videos[0].video.video_bytes = b""  # 空 bytes
        client.models.generate_videos.return_value = op

        with patch.multiple(
            "youtube_automation.utils.veo_generator",
            strip_audio=MagicMock(),
            cost_tracker=MagicMock(),
        ):
            with patch("time.sleep"):
                result = veo_generator.generate_loop_video(
                    client,
                    output_mp4.parent / "main.png",
                    output_mp4,
                    model="veo-3.1-fast",
                    prompt="test prompt",
                )

        assert result is False
        from youtube_automation.utils import veo_operation_store as op_store

        assert op_store.load(output_mp4, channel_root=channel_tmp) is None


# ---------- build_structured_prompt (Issue #358) ----------

_TEMPLATE = (
    "Static composition. The scene is a living painting: {static_clause} remain exactly as in the source image. "
    "The only motion is {motion_clause} — subtle, gentle. {base_rules} Loop seamlessly."
)
_BASE_RULES = "Preserve the original lighting."


class TestBuildStructuredPrompt:
    def test_expands_both_motion_and_static(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["slow leaves swaying", "subtle steam"],
            static_targets=["the character", "two animals (count remains 2)"],
            template=_TEMPLATE,
            base_rules=_BASE_RULES,
        )
        assert "slow leaves swaying and subtle steam" in prompt
        assert "the character and two animals (count remains 2)" in prompt
        assert "Preserve the original lighting." in prompt
        assert "{motion_clause}" not in prompt
        assert "{static_clause}" not in prompt
        assert "{base_rules}" not in prompt

    def test_oxford_comma_for_three_or_more_motion_items(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves", "steam", "candle flicker"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "leaves, steam, and candle flicker" in prompt

    def test_single_item_renders_without_conjunction(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["slow leaves swaying"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "The only motion is slow leaves swaying" in prompt
        assert " and slow leaves" not in prompt

    def test_empty_static_falls_back_to_rest_of_scene(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=[],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "the rest of the scene remain exactly as in the source image" in prompt

    def test_empty_motion_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="motion_targets"):
            build_structured_prompt(
                motion_targets=[],
                static_targets=["character"],
                template=_TEMPLATE,
                base_rules="",
            )

    def test_whitespace_only_motion_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="motion_targets"):
            build_structured_prompt(
                motion_targets=["", "  ", "\t"],
                static_targets=["character"],
                template=_TEMPLATE,
                base_rules="",
            )

    def test_strips_and_filters_empty_items(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["  leaves  ", "", "  steam"],
            static_targets=["  character  ", "  "],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "leaves and steam" in prompt
        # static_targets は strip 後にそのまま join される（自動冠詞補完なし）
        assert "character remain exactly as in the source image" in prompt

    def test_empty_base_rules_renders_cleanly(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "{base_rules}" not in prompt
        # base_rules 空時に連続スペースが残らない (re.sub で正規化)
        assert "  " not in prompt

    def test_template_with_brace_in_english_text_is_safe(self) -> None:
        # Veo 英文に {curly} を含めても .format() ではなく .replace() なので壊れない
        template = (
            "Style: {motion_clause}; static: {static_clause}; rules: {base_rules}; note: this is { not a placeholder }."
        )
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=["character"],
            template=template,
            base_rules="",
        )
        assert "{ not a placeholder }" in prompt
