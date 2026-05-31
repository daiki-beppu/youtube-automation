"""gemini CLI 経由（サブスク認証）の画像生成プロバイダー。

ADC 課金の ``GeminiImageProvider`` と異なり、Google AI Pro/Ultra サブスクで
認証された ``gemini`` CLI（``@google/gemini-cli``）を subprocess で非対話起動し、
保存パスをプロンプトに埋め込んで画像ファイルを書き出させる。GCP 従量課金を
発生させずに枚数の多いサムネ生成のコストを抑える用途 (#474)。

設計:
- CLI 存在確認は ``shutil.which("gemini")``（未導入なら ``ConfigError``）
- ``gemini --yolo -m <model> -p <prompt>`` で非対話起動。プロンプトに output_path /
  aspect_ratio / image_size / 参照画像を埋め込む
- 終了後に出力ファイルの存在と PNG 妥当性（PIL で open）を検証し、``persist_image``
  で PNG ロスレス + JPEG 圧縮版に正規化する
- 指数バックオフで ``RETRY_MAX`` 回までリトライ。SAFETY/RECITATION 検出時は即時失敗
- サブスク枠のためコストは ``log_image_cost`` 経由で記録（per-call の推定額は付かない）
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import (
    RETRY_BACKOFF,
    RETRY_MAX,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from youtube_automation.utils.image_provider.composition import log_image_cost, persist_image
from youtube_automation.utils.image_provider.config import GeminiCliConfig

GEMINI_CLI_BINARY = "gemini"


class GeminiCliImageProvider:
    """gemini CLI（サブスク認証）で画像を 1 枚生成して保存する。"""

    name = "gemini_cli"
    # GeminiImageProvider 同様にアスペクト比を制限しない（branding/icon.png 用途で 1:1 等を許容）
    supported_aspect_ratios: tuple[str, ...] = ()

    def __init__(self, config: GeminiCliConfig, *, runner=subprocess.run) -> None:
        self._config = config
        # subprocess.run をテストから差し替え可能にする（mock ベースの unit test 用）
        self._runner = runner

    def _ensure_cli_available(self) -> None:
        """gemini CLI が PATH 上に存在することを確認する（未導入なら ConfigError）。"""
        if shutil.which(GEMINI_CLI_BINARY) is None:
            raise ConfigError(
                "gemini CLI が見つかりません。`npm install -g @google/gemini-cli` で導入し、"
                "Google AI Pro/Ultra アカウントでログイン済みにしてください"
            )

    def _build_prompt(self, req: ImageGenerationRequest, image_size: str) -> str:
        """gemini CLI に渡す非対話プロンプトを組み立てる。

        agentic CLI に対し、出力パスへ画像ファイルを書き出すよう明示的に指示する。
        """
        output_path = req.output_path.resolve()
        lines = [
            "You are an image generation assistant. Generate a single image from the "
            "description below and write it as a PNG file to this absolute path:",
            f"  {output_path}",
            f"Aspect ratio: {req.aspect_ratio}. Target resolution: {image_size}.",
        ]
        references = list(req.references)
        if references:
            ref_list = ", ".join(str(Path(r).resolve()) for r in references)
            lines.append(f"Use these local reference images for style/content guidance: {ref_list}")
        lines.append(f"Description: {req.prompt}")
        lines.append(f"Do not print anything else. Just create the image file at {output_path}.")
        return "\n".join(lines)

    def _build_command(self, prompt: str) -> list[str]:
        """非対話・自動承認（--yolo）で gemini CLI を起動するコマンド列を返す。"""
        return [GEMINI_CLI_BINARY, "--yolo", "-m", self._config.model, "-p", prompt]

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """req に従って gemini CLI で画像を生成して保存する。"""
        from PIL import Image as PILImage

        self._ensure_cli_available()

        image_size = req.image_size or self._config.image_size
        prompt = self._build_prompt(req, image_size)
        cmd = self._build_command(prompt)
        save_as_png = req.output_path.suffix.lower() == ".png"

        for attempt in range(RETRY_MAX):
            # 前回試行の残骸を除去してから起動する（古いファイルを成功と誤認しないため）
            if req.output_path.exists():
                req.output_path.unlink()

            print(f"  [Submit] gemini CLI モデル={self._config.model} 解像度={image_size}")
            try:
                proc = self._runner(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._config.timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                print(f"  [Retry]  タイムアウト ({self._config.timeout_seconds}s) attempt {attempt + 1}/{RETRY_MAX}")
                self._sleep_backoff(attempt)
                continue
            except OSError as e:
                print(f"  [Retry]  gemini CLI 起動失敗: {str(e)[:120]}")
                self._sleep_backoff(attempt)
                continue

            stderr = (proc.stderr or "").strip()
            if proc.returncode != 0:
                upper = stderr.upper()
                if "SAFETY" in upper or "RECITATION" in upper:
                    print(f"  [Skip]   コンテンツポリシー違反: {stderr[:120]}")
                    return ImageGenerationResult(success=False, saved_path=None)
                print(f"  [Retry]  exit={proc.returncode}: {stderr[:120]}")
                self._sleep_backoff(attempt)
                continue

            if not req.output_path.exists():
                print(f"  [Retry]  出力ファイルが生成されませんでした: {req.output_path}")
                self._sleep_backoff(attempt)
                continue

            try:
                with PILImage.open(req.output_path) as opened:
                    opened.load()
                    image = opened.copy()
            except (OSError, ValueError) as e:
                print(f"  [Retry]  生成ファイルが妥当な画像ではありません: {str(e)[:120]}")
                self._sleep_backoff(attempt)
                continue

            saved_path = persist_image(image, req.output_path, save_as_png=save_as_png)
            entry = log_image_cost(
                model=self._config.model,
                image_size=image_size,
                aspect_ratio=req.aspect_ratio,
                output_file=saved_path,
                reference_count=len(req.references),
            )
            cost_tracker.print_last_report(entry)
            return ImageGenerationResult(success=True, saved_path=saved_path)

        return ImageGenerationResult(success=False, saved_path=None)

    def _sleep_backoff(self, attempt: int) -> None:
        if attempt < RETRY_MAX - 1:
            backoff = RETRY_BACKOFF[attempt]
            print(f"  [Wait]   {backoff}秒待機...")
            time.sleep(backoff)
