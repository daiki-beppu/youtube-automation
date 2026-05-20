"""CodexImageProvider の単体テスト（codex CLI 経由のサブスク認証）。

`subprocess.run` をモックして以下を検証する:

1. コンストラクタで `codex login status` が実行される
2. 未ログイン状態は `ConfigError`
3. codex CLI が見つからない場合は `ConfigError`
4. 正常系で `codex exec` が呼ばれ PNG + JPG 派生が保存される
5. タイムアウト時はリトライ、後続で成功
6. 出力ファイル未生成 / PNG ヘッダ不正はリトライして最終失敗
7. プロンプトに output_path / size / aspect_ratio / reference が含まれる
8. 成功時に `log_image_cost` が呼ばれる
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import ImageGenerationRequest
from youtube_automation.utils.image_provider.codex import CodexImageProvider
from youtube_automation.utils.image_provider.config import CodexConfig

# ---------- ヘルパー ----------


def _png_bytes() -> bytes:
    """16x16 のダミー PNG バイナリ。"""
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (16, 16), color=(200, 220, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _login_ok_result(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=cmd, returncode=0, stdout="Logged in using ChatGPT (sub@example.com)", stderr=""
    )


def _login_not_logged_result(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=cmd, returncode=1, stdout="", stderr="Not logged in. Run `codex login`."
    )


def _extract_save_path_from_prompt(prompt: str) -> Path | None:
    """`Save the result as PNG to: <path>` 行から保存パスを抽出する。"""
    for line in prompt.splitlines():
        if line.startswith("Save the result as PNG to:"):
            return Path(line.split(":", 1)[1].strip())
    return None


class _ExecRunner:
    """`codex exec` 呼び出し時の挙動を制御する side_effect ファクトリ。

    sequence で複数回呼び出しの挙動を順次切り替える。各エントリは:
      - "ok"      : PNG を書いて rc=0
      - "no-file" : ファイル書かずに rc=0（出力ファイル未生成シナリオ）
      - "bad-png" : PNG マジック以外を書いて rc=0（ヘッダ不正シナリオ）
      - "rc-fail" : ファイル書かずに rc=1（rc != 0 シナリオ）
      - "timeout" : `subprocess.TimeoutExpired` を raise
    """

    def __init__(self, login_ok: bool, sequence: list[str]):
        self.login_ok = login_ok
        self.sequence = list(sequence)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        # cmd は ["codex", "login", "status"] または ["codex", "exec", <prompt>]
        if len(cmd) >= 2 and cmd[1] == "login":
            return _login_ok_result(cmd) if self.login_ok else _login_not_logged_result(cmd)

        # exec 呼び出し
        action = self.sequence.pop(0) if self.sequence else "ok"
        prompt = cmd[2] if len(cmd) >= 3 else ""
        save_path = _extract_save_path_from_prompt(prompt)

        if action == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 1))
        if action == "rc-fail":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="imagegen error")
        if action == "no-file":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done", stderr="")
        if action == "bad-png":
            if save_path is not None:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(b"NOT_A_PNG_FILE_CONTENT" + b"\x00" * 64)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done", stderr="")
        # "ok"
        if save_path is not None:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(_png_bytes())
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done", stderr="")


# ---------- フィクスチャ ----------


@pytest.fixture
def codex_config() -> CodexConfig:
    return CodexConfig(
        model="gpt-image-1",
        image_size="1024x1024",
        aspect_ratio="16:9",
        timeout_seconds=60,
    )


@pytest.fixture
def request_factory(tmp_path: Path):
    def _make(
        *,
        prompt: str = "a quiet cafe with steaming coffee",
        references: list[Path] | None = None,
        aspect_ratio: str = "16:9",
        image_size: str = "1024x1024",
        output_name: str = "out.png",
    ) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            prompt=prompt,
            output_path=tmp_path / output_name,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            references=list(references or []),
        )

    return _make


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """リトライバックオフを高速化。"""
    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.codex.time.sleep",
        lambda s: None,
    )


@pytest.fixture(autouse=True)
def _stub_codex_which(monkeypatch):
    """`shutil.which("codex")` を fake パスに固定。"""
    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.codex.shutil.which",
        lambda _name: "/fake/codex",
    )


def _patch_subprocess(runner: _ExecRunner):
    return patch(
        "youtube_automation.utils.image_provider.codex.subprocess.run",
        side_effect=runner,
    )


# ---------- 認証チェック ----------


class TestLoginStatusCheck:
    def test_login_status_checked_in_constructor(self, codex_config: CodexConfig):
        # Given
        runner = _ExecRunner(login_ok=True, sequence=[])

        # When
        with _patch_subprocess(runner):
            CodexImageProvider(codex_config)

        # Then: 最初の subprocess 呼び出しが `codex login status`
        assert runner.calls, "subprocess.run が呼ばれていない"
        first_call = runner.calls[0]
        assert first_call[0] == "/fake/codex"
        assert first_call[1:] == ["login", "status"]

    def test_unauthenticated_raises_config_error(self, codex_config: CodexConfig):
        # Given: `codex login status` が Not logged in を返す
        runner = _ExecRunner(login_ok=False, sequence=[])

        # When / Then
        with _patch_subprocess(runner), pytest.raises(ConfigError, match="codex login"):
            CodexImageProvider(codex_config)

    def test_codex_binary_not_found_raises_config_error(self, codex_config: CodexConfig):
        # Given: subprocess.run が FileNotFoundError を投げる
        with patch(
            "youtube_automation.utils.image_provider.codex.subprocess.run",
            side_effect=FileNotFoundError("codex"),
        ):
            # When / Then
            with pytest.raises(ConfigError, match="codex CLI が見つかりません"):
                CodexImageProvider(codex_config)

    def test_login_status_timeout_raises_config_error(self, codex_config: CodexConfig):
        # Given: subprocess.run が TimeoutExpired を投げる
        with patch(
            "youtube_automation.utils.image_provider.codex.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="codex login status", timeout=30),
        ):
            # When / Then
            with pytest.raises(ConfigError, match="codex login status"):
                CodexImageProvider(codex_config)


# ---------- 生成成功系 ----------


class TestGenerateSuccess:
    def test_generate_success_creates_png_and_jpg(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given
        runner = _ExecRunner(login_ok=True, sequence=["ok"])
        req = request_factory(output_name="out.png")

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert result.saved_path == req.output_path
        # PNG が存在
        assert req.output_path.exists()
        # JPG 派生も生成（既存 persist_image の挙動）
        jpg_path = req.output_path.with_suffix(".jpg")
        assert jpg_path.exists(), f"JPG 派生 {jpg_path} が生成されていない"

    def test_generate_timeout_then_success(self, codex_config: CodexConfig, request_factory):
        # Given: 1 回目 timeout → 2 回目 ok
        runner = _ExecRunner(login_ok=True, sequence=["timeout", "ok"])
        req = request_factory()

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is True
        # exec が 2 回呼ばれている（login 1 回 + exec 2 回 = 計 3 回）
        exec_calls = [c for c in runner.calls if len(c) >= 2 and c[1] == "exec"]
        assert len(exec_calls) == 2


# ---------- 生成失敗系 ----------


class TestGenerateFailures:
    def test_generate_no_output_file_retries_then_fails(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given: 全リトライで exec rc=0 だが出力ファイル未生成
        runner = _ExecRunner(login_ok=True, sequence=["no-file", "no-file", "no-file"])
        req = request_factory()

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is False
        assert result.saved_path is None
        # 3 回 exec を試行
        exec_calls = [c for c in runner.calls if len(c) >= 2 and c[1] == "exec"]
        assert len(exec_calls) == 3

    def test_generate_invalid_png_header_fails(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given: PNG マジック以外のバイトを書く
        runner = _ExecRunner(login_ok=True, sequence=["bad-png", "bad-png", "bad-png"])
        req = request_factory()

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is False

    def test_generate_rc_nonzero_retries_then_fails(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given: 全リトライで rc != 0
        runner = _ExecRunner(login_ok=True, sequence=["rc-fail", "rc-fail", "rc-fail"])
        req = request_factory()

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is False

    def test_generate_rejects_unsupported_aspect_ratio(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given: imagegen は 16:9 / 9:16 / 1:1 のみ
        runner = _ExecRunner(login_ok=True, sequence=[])
        req = request_factory(aspect_ratio="4:3")

        # When / Then
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            with pytest.raises(ConfigError, match="aspect_ratio"):
                provider.generate(req)


# ---------- プロンプト構築 ----------


class TestPromptConstruction:
    def test_prompt_contains_output_path_size_and_aspect_ratio(
        self, codex_config: CodexConfig, request_factory
    ):
        # Given
        runner = _ExecRunner(login_ok=True, sequence=["ok"])
        req = request_factory(prompt="MAGIC_PROMPT_TOKEN_123", aspect_ratio="9:16")

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            provider.generate(req)

        # Then: exec 呼び出しのプロンプト引数に必須要素が含まれる
        exec_calls = [c for c in runner.calls if len(c) >= 2 and c[1] == "exec"]
        assert exec_calls, "codex exec が呼ばれていない"
        prompt_arg = exec_calls[0][2]
        assert str(req.output_path) in prompt_arg
        assert codex_config.image_size in prompt_arg
        assert "9:16" in prompt_arg
        assert "MAGIC_PROMPT_TOKEN_123" in prompt_arg
        assert codex_config.model in prompt_arg
        # 保存パス指示行を明示
        assert "Save the result as PNG to:" in prompt_arg

    def test_prompt_includes_reference_images_when_provided(
        self, codex_config: CodexConfig, request_factory, tmp_path: Path
    ):
        # Given: 参照画像 2 枚
        ref1 = tmp_path / "ref-a.png"
        ref2 = tmp_path / "ref-b.png"
        ref1.write_bytes(_png_bytes())
        ref2.write_bytes(_png_bytes())
        runner = _ExecRunner(login_ok=True, sequence=["ok"])
        req = request_factory(references=[ref1, ref2])

        # When
        with _patch_subprocess(runner):
            provider = CodexImageProvider(codex_config)
            provider.generate(req)

        # Then
        exec_calls = [c for c in runner.calls if len(c) >= 2 and c[1] == "exec"]
        prompt_arg = exec_calls[0][2]
        assert "Reference images" in prompt_arg
        assert str(ref1) in prompt_arg
        assert str(ref2) in prompt_arg


# ---------- コスト記録 ----------


class TestCostLogging:
    def test_log_image_cost_called_on_success(self, codex_config: CodexConfig, request_factory):
        # Given
        runner = _ExecRunner(login_ok=True, sequence=["ok"])
        req = request_factory()

        # When
        with _patch_subprocess(runner), patch(
            "youtube_automation.utils.image_provider.codex.log_image_cost",
            return_value={"category": "image", "cost_usd": 0.0},
        ) as mock_log, patch(
            "youtube_automation.utils.image_provider.codex.cost_tracker.print_last_report",
        ):
            provider = CodexImageProvider(codex_config)
            result = provider.generate(req)

        # Then
        assert result.success is True
        assert mock_log.call_count == 1
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["model"] == codex_config.model
        assert call_kwargs["image_size"] == codex_config.image_size
        assert call_kwargs["aspect_ratio"] == req.aspect_ratio
        assert call_kwargs["reference_count"] == 0
