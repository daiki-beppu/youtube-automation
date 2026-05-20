"""Codex CLI（ChatGPT サブスク認証）経由の画像生成プロバイダー。

`codex exec "..."` でエージェントに `imagegen` ツールを呼ばせ、プロンプト内で
保存パスを指定して PNG を書き出させる。サブスク枠での生成のため API 課金は
発生しない（事前に `codex login` 済みが前提）。

`codex login status` をコンストラクタ初期化時に 1 回だけ実行して認証を確認する。
画像生成 1 回ごとにこのチェックを走らせると agent 起動コストが嵩むため、
プロバイダーインスタンスのライフタイム単位（通常 1 リクエスト = 1 インスタンス）で
確認する設計とする。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import time
from pathlib import Path

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import (
    RETRY_MAX,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from youtube_automation.utils.image_provider.composition import log_image_cost, persist_image
from youtube_automation.utils.image_provider.config import CodexConfig

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Codex は agent 経路で 1 回あたり数十秒〜分単位で遅いため、共通 RETRY_BACKOFF
# (10, 30, 60) より短いリトライ間隔を採用する。
_CODEX_RETRY_BACKOFF: tuple[int, ...] = (5, 10, 20)

# `codex login status` 自体は通常 1 秒以内で完了する軽量チェック。
_LOGIN_STATUS_TIMEOUT = 30


class CodexImageProvider:
    """Codex CLI 経由で画像を 1 枚生成して保存する。"""

    name = "codex"
    supported_aspect_ratios: tuple[str, ...] = ("16:9", "9:16", "1:1")

    def __init__(self, config: CodexConfig) -> None:
        self._config = config
        self._codex_bin = shutil.which("codex") or "codex"
        self._ensure_logged_in()

    def _ensure_logged_in(self) -> None:
        try:
            result = subprocess.run(
                [self._codex_bin, "login", "status"],
                text=True,
                capture_output=True,
                timeout=_LOGIN_STATUS_TIMEOUT,
                check=False,
            )
        except FileNotFoundError as e:
            raise ConfigError(
                f"codex CLI が見つかりません ({self._codex_bin})。"
                "Homebrew / nix 等でインストールし PATH を通してください。"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ConfigError(
                f"`codex login status` が {_LOGIN_STATUS_TIMEOUT} 秒以内に応答しません"
            ) from e

        output = (result.stdout or "") + (result.stderr or "")
        if "Logged in" not in output:
            raise ConfigError(
                "codex login されていません。`codex login` を実行して ChatGPT アカウントで認証してください。"
            )

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """req に従って画像を生成して保存する。"""
        from PIL import Image as PILImage

        if req.aspect_ratio not in self.supported_aspect_ratios:
            raise ConfigError(
                f"Codex image_generation の aspect_ratio={req.aspect_ratio!r} は未対応。"
                f"許容値: {self.supported_aspect_ratios}"
            )

        req.output_path.parent.mkdir(parents=True, exist_ok=True)
        # 前回生成画像が残っていると「ファイル存在」だけでは成功判定できないため事前に削除
        if req.output_path.exists():
            req.output_path.unlink()

        prompt = self._build_prompt(req)
        cmd = [self._codex_bin, "exec", prompt]
        timeout = self._config.timeout_seconds
        model = self._config.model
        save_as_png = req.output_path.suffix.lower() == ".png"

        for attempt in range(RETRY_MAX):
            ref_label = ""
            if req.references:
                names = ", ".join(r.name for r in req.references)
                ref_label = f" + 参照画像={names}"
            print(
                f"  [Submit] codex exec model={model} size={self._config.image_size} "
                f"aspect={req.aspect_ratio}{ref_label}"
            )

            failure_reason: str | None = None
            try:
                result = subprocess.run(
                    cmd,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                failure_reason = f"timeout ({timeout}s)"
                result = None

            if result is not None:
                if result.returncode != 0:
                    stderr_tail = (result.stderr or "")[-200:].strip()
                    failure_reason = f"rc={result.returncode} {stderr_tail}"
                elif not self._is_valid_png(req.output_path):
                    failure_reason = "出力ファイルなし or PNG ヘッダ不正"

            if failure_reason is None:
                pil_image = PILImage.open(io.BytesIO(req.output_path.read_bytes()))
                saved_path = persist_image(pil_image, req.output_path, save_as_png=save_as_png)
                entry = log_image_cost(
                    model=model,
                    image_size=self._config.image_size,
                    aspect_ratio=req.aspect_ratio,
                    output_file=saved_path,
                    reference_count=len(req.references),
                )
                cost_tracker.print_last_report(entry)
                return ImageGenerationResult(success=True, saved_path=saved_path)

            print(f"  [Retry]  attempt {attempt + 1}/{RETRY_MAX}: {failure_reason}")
            # 失敗時は中途半端な出力ファイルを残さない（次回リトライの誤判定を防ぐ）
            if req.output_path.exists():
                req.output_path.unlink()

            if attempt < RETRY_MAX - 1:
                backoff = _CODEX_RETRY_BACKOFF[attempt]
                print(f"  [Wait]   {backoff}秒待機...")
                time.sleep(backoff)

        return ImageGenerationResult(success=False, saved_path=None)

    def _build_prompt(self, req: ImageGenerationRequest) -> str:
        reference_block = ""
        if req.references:
            paths = "\n".join(f"- {p}" for p in req.references)
            reference_block = f"\nReference images (read for style and composition):\n{paths}\n"
        return (
            "Use the imagegen tool to generate exactly one image.\n"
            f"Save the result as PNG to: {req.output_path}\n"
            f"Size: {self._config.image_size}\n"
            f"Aspect ratio: {req.aspect_ratio}\n"
            f"Model: {self._config.model}\n"
            f"{reference_block}"
            "Description:\n"
            f"{req.prompt}\n"
        )

    @staticmethod
    def _is_valid_png(path: Path) -> bool:
        if not path.exists() or path.stat().st_size < len(_PNG_MAGIC):
            return False
        with path.open("rb") as f:
            return f.read(len(_PNG_MAGIC)) == _PNG_MAGIC
