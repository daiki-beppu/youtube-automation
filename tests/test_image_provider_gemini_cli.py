"""GeminiCliImageProvider の単体テスト（mock ベース）。

subprocess.run を差し替えて gemini CLI 呼び出しをモックし、以下の振る舞いを検証する:

1. CLI 未導入なら ConfigError
2. 正常終了 + 出力ファイル生成で success=True と保存パスを返す
3. コマンドに model / プロンプト（出力パス埋め込み）が含まれる
4. 参照画像がプロンプトに埋め込まれる
5. 非ゼロ終了はリトライし、全失敗で False
6. stderr に SAFETY/RECITATION を含む失敗は即時 False（リトライしない）
7. タイムアウトはリトライ
8. 出力ファイル未生成 / 壊れた画像はリトライして失敗
9. アスペクト比は制限しない（branding/icon.png 用途）
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import ImageGenerationRequest
from youtube_automation.utils.image_provider.config import GeminiCliConfig
from youtube_automation.utils.image_provider.gemini_cli import (
    RETRY_MAX,
    GeminiCliImageProvider,
)

# ---------- フィクスチャ ----------


def _png_bytes() -> bytes:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (16, 16), color=(0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def cli_config() -> GeminiCliConfig:
    return GeminiCliConfig(model="gemini-2.5-flash-image-preview", image_size="2K", timeout_seconds=300)


@pytest.fixture
def request_factory(tmp_path: Path):
    def _make(
        *,
        prompt: str = "a serene mountain at dawn",
        references: list[Path] | None = None,
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
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
def _cli_available():
    """shutil.which が gemini を見つける状態を既定にする。"""
    with patch(
        "youtube_automation.utils.image_provider.gemini_cli.shutil.which",
        return_value="/usr/local/bin/gemini",
    ):
        yield


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(
        "youtube_automation.utils.image_provider.gemini_cli.time.sleep",
        lambda s: None,
    )


def _runner_writing(output_path: Path, *, returncode: int = 0, stderr: str = "", write: bool = True):
    """出力ファイルを書き出す（または書かない）fake subprocess.run。"""

    def _runner(cmd, **kwargs):
        if write:
            output_path.write_bytes(_png_bytes())
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return MagicMock(side_effect=_runner)


# ---------- CLI 存在チェック ----------


class TestCliAvailability:
    def test_missing_cli_raises_config_error(self, cli_config, request_factory):
        provider = GeminiCliImageProvider(cli_config, runner=_runner_writing(Path("/nonexistent")))
        req = request_factory()
        with patch(
            "youtube_automation.utils.image_provider.gemini_cli.shutil.which",
            return_value=None,
        ):
            with pytest.raises(ConfigError, match="gemini CLI"):
                provider.generate(req)


class TestSingleStepReferenceGuard:
    def test_single_step_without_reference_raises_before_cli_execution(self, request_factory):
        cfg = GeminiCliConfig(
            model="gemini-2.5-flash-image-preview",
            image_size="2K",
            timeout_seconds=300,
            generation_mode="single_step",
        )
        runner = MagicMock()
        provider = GeminiCliImageProvider(cfg, runner=runner)
        req = request_factory(references=[])

        with pytest.raises(ConfigError, match="single_step モードでは --reference"):
            provider.generate(req)

        assert runner.call_count == 0


# ---------- 正常系 ----------


class TestSuccessfulGeneration:
    def test_writes_file_and_returns_success(self, cli_config, request_factory, tmp_path):
        req = request_factory(output_name="result.png")
        provider = GeminiCliImageProvider(cli_config, runner=_runner_writing(req.output_path))

        result = provider.generate(req)

        assert result.success is True
        assert result.saved_path is not None
        assert result.saved_path.exists()
        assert result.saved_path.is_relative_to(tmp_path)

    def test_command_includes_model_and_output_path(self, cli_config, request_factory):
        req = request_factory(output_name="result.png")
        runner = _runner_writing(req.output_path)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        provider.generate(req)

        cmd = runner.call_args.args[0]
        assert cmd[0] == "gemini"
        assert "-m" in cmd
        assert "gemini-2.5-flash-image-preview" in cmd
        # プロンプト（-p の値）に出力パスが埋め込まれている
        prompt = cmd[cmd.index("-p") + 1]
        assert str(req.output_path.resolve()) in prompt

    def test_references_are_embedded_in_prompt(self, cli_config, request_factory, tmp_path):
        ref = tmp_path / "ref.png"
        ref.write_bytes(_png_bytes())
        req = request_factory(references=[ref], output_name="result.png")
        runner = _runner_writing(req.output_path)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        provider.generate(req)

        prompt = runner.call_args.args[0][-1]
        assert str(ref.resolve()) in prompt

    def test_aspect_ratio_not_restricted(self, cli_config, request_factory):
        provider = GeminiCliImageProvider(cli_config, runner=_runner_writing(Path("/x")))
        assert provider.supported_aspect_ratios == ()
        # 1:1 でも ConfigError にならない
        req = request_factory(aspect_ratio="1:1")
        provider2 = GeminiCliImageProvider(cli_config, runner=_runner_writing(req.output_path))
        result = provider2.generate(req)
        assert result.success is True


# ---------- リトライ・失敗系 ----------


class TestRetryAndFailure:
    def test_nonzero_exit_retries_then_fails(self, cli_config, request_factory):
        req = request_factory()
        runner = _runner_writing(req.output_path, returncode=1, stderr="boom", write=False)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is False
        assert runner.call_count == RETRY_MAX

    def test_safety_in_stderr_skips_retry(self, cli_config, request_factory):
        req = request_factory()
        runner = _runner_writing(req.output_path, returncode=1, stderr="SAFETY policy blocked", write=False)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is False
        assert runner.call_count == 1

    def test_timeout_retries_then_fails(self, cli_config, request_factory):
        req = request_factory()
        runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="gemini", timeout=300))
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is False
        assert runner.call_count == RETRY_MAX

    def test_missing_output_file_retries_then_fails(self, cli_config, request_factory):
        req = request_factory()
        # returncode=0 だが出力ファイルを書かない
        runner = _runner_writing(req.output_path, returncode=0, write=False)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is False
        assert runner.call_count == RETRY_MAX

    def test_invalid_image_retries_then_fails(self, cli_config, request_factory):
        req = request_factory()

        def _runner(cmd, **kwargs):
            req.output_path.write_bytes(b"not a real png")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        runner = MagicMock(side_effect=_runner)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is False
        assert runner.call_count == RETRY_MAX

    def test_retries_until_success(self, cli_config, request_factory):
        req = request_factory()
        calls = {"n": 0}

        def _runner(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="transient")
            req.output_path.write_bytes(_png_bytes())
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        runner = MagicMock(side_effect=_runner)
        provider = GeminiCliImageProvider(cli_config, runner=runner)

        result = provider.generate(req)

        assert result.success is True
        assert runner.call_count == 2


# ---------- TTP 方針の透過 (#2071) ----------


def _shipped_thumbnail_default_config() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestTtpPolicyPassthrough:
    """#2071: gemini_cli 経路は #2070 の TTP 方針（codex と同期した既定 prompt）を損なわず透過する。"""

    def test_build_prompt_embeds_request_prompt_verbatim(self, cli_config, request_factory):
        provider = GeminiCliImageProvider(cli_config)
        req = request_factory(prompt="TTP policy line A.\nTTP policy line B.")

        built = provider._build_prompt(req, image_size="2K")

        assert "Description: TTP policy line A.\nTTP policy line B." in built

    def test_provider_switch_keeps_codex_synced_ttp_policy_lines(self, cli_config, request_factory):
        """provider を gemini_cli に切り替えても、既定 diff_prompt_template の TTP 方針行が CLI プロンプトに残る。"""
        config = _shipped_thumbnail_default_config()
        codex_template = config["image_generation"]["codex"]["default_prompt_template"]
        gemini_template = config["image_generation"]["gemini"]["diff_prompt_template"]
        rendered = gemini_template.replace("{title_line1}", "Cozy Jazz").replace("{title_line2}", "Rainy Night")

        provider = GeminiCliImageProvider(cli_config)
        built = provider._build_prompt(request_factory(prompt=rendered), image_size="2K")

        policy_lines = [line for line in codex_template.strip().splitlines() if line and "{title}" not in line]
        assert policy_lines, "codex 既定テンプレートから方針行を抽出できません"
        for line in policy_lines:
            assert line in built

    def test_build_prompt_wrapper_adds_no_divergent_ttp_wording(self, cli_config, request_factory):
        """CLI ラッパー自体は TTP 方針を上書き・複製する文言を持たない（方針の SSOT は skill-config 側）。"""
        provider = GeminiCliImageProvider(cli_config)

        built = provider._build_prompt(request_factory(prompt="plain description"), image_size="2K")

        for phrase in ("TTP", "winning layout", "mood reference"):
            assert phrase not in built
