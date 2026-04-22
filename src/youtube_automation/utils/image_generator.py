"""Gemini API 画像生成の共有コア。

generate_thumbnail.py と generate_image.py から共通利用される関数群。
"""

import io
import re
import time
from pathlib import Path

from youtube_automation.utils import cost_tracker

# --- 定数 ---
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_IMAGE_SIZE = "2K"
VALID_IMAGE_SIZES = ("1K", "2K", "4K")
RETRY_MAX = 3
RETRY_BACKOFF = [10, 30, 60]


def load_gemini_config() -> dict:
    """thumbnail skill-config から gemini_image 設定を読み込む。"""
    try:
        from youtube_automation.utils.skill_config import load_skill_config  # noqa: E402

        cfg = load_skill_config("thumbnail")
        return cfg.get("gemini_image", {"model": DEFAULT_MODEL})
    except Exception:
        return {"model": DEFAULT_MODEL}


def apply_composition_rules(prompt: str, config: dict) -> str:
    """channel_config の構図ルールをプロンプトに自動適用する。

    composition_keywords のいずれも含まれていない場合、composition_prefix を冒頭に付加。
    テキストオーバーレイ系プロンプト（参照画像への編集指示）はスキップする。
    """
    prefix = config.get("composition_prefix", "")
    keywords = config.get("composition_keywords", [])

    if not prefix or not keywords:
        return prompt

    # テキストオーバーレイ/編集系プロンプトはスキップ
    lower = prompt.lower().lstrip()
    if lower.startswith("use this image") or "do not change the background" in lower or lower.startswith("edit this"):
        return prompt

    # 既にキーワードが含まれていればそのまま返す
    for kw in keywords:
        if kw.lower() in lower:
            return prompt

    # プレフィックスを冒頭に付加
    print(f"  [Auto]   構図ルール適用: {prefix}")
    return f"{prefix} {prompt}"


def confirm_cost(model: str, cost_per_image: float) -> bool:
    """コスト見積もりを表示してユーザー確認を取る。"""
    print()
    print("=== Gemini Thumbnail Generation ===")
    print(f"モデル:     {model}")
    print("生成枚数:   1 image")
    print(f"推定コスト: ${cost_per_image:.3f}")
    print()
    try:
        answer = input("続行しますか? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n中止しました。")
        return False
    return answer in ("y", "yes")


def resolve_unique_path(output_path: Path) -> Path:
    """出力パスが既存の場合、-v2, -v3 ... と自動採番して一意なパスを返す。"""
    if not output_path.exists():
        return output_path
    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    # 既に -vN が付いている場合はベース名を取り出す
    base_match = re.match(r"^(.+)-v(\d+)$", stem)
    if base_match:
        base = base_match.group(1)
        start = int(base_match.group(2)) + 1
    else:
        base = stem
        start = 2
    for n in range(start, start + 100):
        candidate = parent / f"{base}-v{n}{suffix}"
        if not candidate.exists():
            return candidate
    # fallback: should never reach here
    return parent / f"{base}-v{start + 100}{suffix}"


def _normalize_references(reference_image: "Path | list[Path] | None") -> list[Path]:
    """単一 Path / Path リスト / None を Path リストに正規化する。"""
    if reference_image is None:
        return []
    if isinstance(reference_image, Path):
        return [reference_image]
    return list(reference_image)


def log_image_cost(
    model: str,
    image_size: str,
    aspect_ratio: str,
    output_file: Path,
    cost_usd: float | None = None,
    reference_count: int = 0,
) -> dict | None:
    """画像生成1件分を cost_tracker 経由で記録する。cost_usd 省略時は PRICING で算出。"""
    return cost_tracker.log_generation(
        "image",
        model=model,
        quantity=1,
        cost_usd=cost_usd,
        metadata={
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "reference_count": reference_count,
            "output_file": cost_tracker.relative_to_channel_dir(output_file),
        },
    )


def print_cost_summary() -> None:
    """画像生成カテゴリのサマリを表示する。"""
    cost_tracker.print_summary("image")


def generate_image(
    client,
    prompt: str,
    model: str,
    output_path: Path,
    reference_image: "Path | list[Path] | None" = None,
    aspect_ratio: str = "16:9",
    image_size: str = DEFAULT_IMAGE_SIZE,
    cost_per_image_usd: float | None = None,
) -> bool:
    """Gemini API で画像を1枚生成して output_path に保存する。成功したら True を返す。

    reference_image: 単一 Path、Path のリスト、または None
    image_size: "1K" / "2K" / "4K"
    cost_per_image_usd: カスタム単価。省略時は cost_tracker.PRICING から解像度別に算出
    """
    from google.genai import types
    from PIL import Image as PILImage

    if image_size not in VALID_IMAGE_SIZES:
        print(f"  [Warn]   未知の image_size={image_size} → {DEFAULT_IMAGE_SIZE} にフォールバック")
        image_size = DEFAULT_IMAGE_SIZE

    references = _normalize_references(reference_image)

    # 参照画像がある場合は画像群+テキストで送信
    if references:
        contents = []
        for ref in references:
            ref_bytes = ref.read_bytes()
            mime = "image/jpeg" if ref.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            contents.append(types.Part.from_bytes(data=ref_bytes, mime_type=mime))
        contents.append(prompt)
    else:
        contents = [prompt]

    # 出力形式: .png → PNG（ロスレス、動画背景用）、.jpg → JPEG（YouTube サムネイル用）
    save_as_png = output_path.suffix.lower() == ".png"

    for attempt in range(RETRY_MAX):
        try:
            ref_label = ""
            if references:
                names = ", ".join(r.name for r in references)
                ref_label = f" + 参照画像={names}"
            print(f"  [Submit] モデル={model} 解像度={image_size}{ref_label}")
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )

            for part in response.parts:
                if part.inline_data is not None:
                    image = PILImage.open(io.BytesIO(part.inline_data.data))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    rgb_image = image.convert("RGB")
                    if save_as_png:
                        # PNG ロスレス保存（動画背景・高品質用途）
                        image.save(str(output_path), optimize=True)
                        png_kb = output_path.stat().st_size // 1024
                        print(f"  [Done]   保存完了 → {output_path} ({png_kb} KB)")
                        # JPEG 圧縮版も同時生成
                        jpg_path = output_path.with_suffix(".jpg")
                        rgb_image.save(str(jpg_path), quality=92, optimize=True)
                        jpg_kb = jpg_path.stat().st_size // 1024
                        print(f"  [Done]   JPEG版   → {jpg_path} ({jpg_kb} KB)")
                        saved_path = output_path
                    else:
                        # JPEG 保存（YouTube サムネイル 2MB 上限対応）
                        jpg_path = output_path.with_suffix(".jpg")
                        rgb_image.save(str(jpg_path), quality=92, optimize=True)
                        if output_path.suffix != ".jpg" and output_path.exists():
                            output_path.unlink()
                        output_path = jpg_path
                        size_kb = output_path.stat().st_size // 1024
                        print(f"  [Done]   保存完了 → {output_path} ({size_kb} KB)")
                        saved_path = output_path

                    entry = log_image_cost(
                        model=model,
                        image_size=image_size,
                        aspect_ratio=aspect_ratio,
                        output_file=saved_path,
                        cost_usd=cost_per_image_usd,
                        reference_count=len(references),
                    )
                    cost_tracker.print_last_report(entry)
                    return True

            # 画像なしレスポンス
            text_parts = [p.text for p in response.parts if p.text]
            error_msg = " ".join(text_parts) if text_parts else "no image in response"
            print(f"  [Retry]  画像なし: {error_msg[:120]}")

        except Exception as e:
            error_msg = str(e)
            if "SAFETY" in error_msg.upper() or "RECITATION" in error_msg.upper():
                print(f"  [Skip]   コンテンツポリシー違反: {error_msg[:120]}")
                return False
            print(f"  [Retry]  attempt {attempt + 1}/{RETRY_MAX}: {error_msg[:120]}")

        if attempt < RETRY_MAX - 1:
            backoff = RETRY_BACKOFF[attempt]
            print(f"  [Wait]   {backoff}秒待機...")
            time.sleep(backoff)

    return False
