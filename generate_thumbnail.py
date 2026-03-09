#!/usr/bin/env python3
"""Gemini API 経由でサムネイル画像を生成する。

2つのモード:
  1. コレクションモード: thumbnail-prompts.md の Primary Prompt を読み込み、10-assets/thumbnail.png に保存
  2. ダイレクトモード: --prompt でテキスト直指定、--output で出力先指定（workflow-state 更新なし）

Usage:
    # コレクションモード
    python3 generate_thumbnail.py <collection-path>
    python3 generate_thumbnail.py <collection-path> -y
    python3 generate_thumbnail.py <collection-path> --variation A

    # ダイレクトモード（/plan プレビュー等）
    python3 generate_thumbnail.py --prompt "A mystical forest..." --output /tmp/preview.png -y

Example:
    python3 generate_thumbnail.py collections/planning/20260219-8bit-rpg-class-vol2-collection
    python3 generate_thumbnail.py --prompt "Celtic harp in moonlight" --output previews/plan-a.png -y
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
# --- 定数 ---
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_COST = 0.04
RETRY_MAX = 3
RETRY_BACKOFF = [10, 30, 60]


def load_config() -> dict:
    """ChannelConfig から gemini_image 設定を読み込む。"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from utils.channel_config import ChannelConfig
        config = ChannelConfig.load()
        return config.raw.get("gemini_image", {"model": DEFAULT_MODEL, "cost_per_image_usd": DEFAULT_COST})
    except Exception:
        return {"model": DEFAULT_MODEL, "cost_per_image_usd": DEFAULT_COST}


def extract_prompt(prompts_md: Path, variation: str | None, use_text_overlay: bool = False) -> str:
    """thumbnail-prompts.md から指定バリエーションのプロンプトを抽出する。

    variation=None  → Primary Prompt（use_text_overlay=True の場合は Text Overlay Prompt を優先）
    variation="A"   → Variation A
    variation="B"   → Variation B
    variation="bg"  → Video Background Prompt
    """
    text = prompts_md.read_text(encoding="utf-8")

    if variation is None:
        if use_text_overlay:
            # ## Text Overlay Prompt セクションを優先（参照画像ワークフロー）
            overlay_pattern = r"## Text Overlay Prompt[^\n]*\n\s*```\n(.*?)\n```"
            overlay_match = re.search(overlay_pattern, text, re.DOTALL)
            if overlay_match:
                return overlay_match.group(1).strip()
            # フォールバック: ## Primary Prompt
        # ## Primary Prompt セクション直後のコードブロック
        pattern = r"## Primary Prompt[^\n]*\n\s*```\n(.*?)\n```"
    elif variation == "bg":
        # ## Video Background Prompt セクション直後のコードブロック
        pattern = r"## Video Background Prompt[^\n]*\n\s*```\n(.*?)\n```"
    else:
        # ### Variation X セクション直後のコードブロック
        pattern = rf"### Variation {re.escape(variation)}[^\n]*\n\s*```\n(.*?)\n```"

    match = re.search(pattern, text, re.DOTALL)
    if not match:
        if variation == "bg":
            label = "Video Background Prompt"
        elif variation:
            label = f"Variation {variation}"
        else:
            label = "Primary Prompt"
        print(f"[ERROR] {label} のプロンプトが見つかりません: {prompts_md}")
        sys.exit(1)

    return match.group(1).strip()


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


def generate_thumbnail(client, prompt: str, model: str, output_path: Path, reference_image: Path | None = None) -> bool:
    """Gemini API で画像を1枚生成して output_path に保存する。成功したら True を返す。"""
    from google.genai import types

    # 参照画像がある場合は画像+テキストで送信
    if reference_image:
        ref_bytes = reference_image.read_bytes()
        mime = "image/jpeg" if reference_image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        ref_part = types.Part.from_bytes(data=ref_bytes, mime_type=mime)
        contents = [ref_part, prompt]
    else:
        contents = [prompt]

    # 出力形式: .png → PNG（ロスレス、動画背景用）、.jpg → JPEG（YouTube サムネイル用）
    save_as_png = output_path.suffix.lower() == ".png"

    for attempt in range(RETRY_MAX):
        try:
            print(f"  [Submit] モデル={model} 解像度=2K" + (f" + 参照画像={reference_image.name}" if reference_image else ""))
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(
                        aspect_ratio="16:9",
                        image_size="2K",
                    ),
                ),
            )

            for part in response.parts:
                if part.inline_data is not None:
                    import io

                    from PIL import Image as PILImage
                    image = PILImage.open(io.BytesIO(part.inline_data.data))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if save_as_png:
                        # PNG ロスレス保存（動画背景・高品質用途）
                        image.save(str(output_path), optimize=True)
                    else:
                        # JPEG 保存（YouTube サムネイル 2MB 上限対応）
                        rgb_image = image.convert("RGB")
                        jpg_path = output_path.with_suffix(".jpg")
                        rgb_image.save(str(jpg_path), quality=92, optimize=True)
                        if output_path.suffix != ".jpg" and output_path.exists():
                            output_path.unlink()
                        output_path = jpg_path
                    size_kb = output_path.stat().st_size // 1024
                    print(f"  [Done]   保存完了 → {output_path} ({size_kb} KB)")
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


def update_workflow_state(workflow_state: Path, approved: bool = False):
    """workflow-state.json の thumbnail ステータスを更新する。"""
    if not workflow_state.exists():
        return

    with open(workflow_state) as f:
        state = json.load(f)

    state.setdefault("steps", {}).setdefault("thumbnail", {})["generated"] = True
    if approved:
        state["steps"]["thumbnail"]["approved"] = True

    with open(workflow_state, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Gemini API でサムネイル画像を生成")
    parser.add_argument(
        "collection_path", nargs="?", default=None, help="コレクションのパス（例: collections/planning/xxx）"
    )
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument(
        "--variation",
        choices=["A", "B", "C", "bg"],
        default=None,
        help="使用するプロンプトバリエーション（省略時は Primary Prompt、bg は動画背景用）",
    )
    parser.add_argument("--prompt", type=str, default=None, help="プロンプトテキストを直接指定（ダイレクトモード）")
    parser.add_argument("--output", type=str, default=None, help="出力パス（--prompt 時必須）")
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（例: gemini-3.1-flash-image-preview）")
    parser.add_argument(
        "--reference", type=str, default=None, help="参照画像パス（main.png等）。画像+プロンプトで Gemini に送信"
    )
    args = parser.parse_args()

    # --- ダイレクトモード ---
    direct_mode = args.prompt is not None
    if direct_mode:
        if not args.output:
            parser.error("--prompt 使用時は --output も必須です")
        prompt = args.prompt
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        workflow_state = None

        config = load_config()
        model = args.model or config.get("model", DEFAULT_MODEL)
        cost_per_image = config.get("cost_per_image_usd", DEFAULT_COST)

        print("\nモード:       ダイレクト")
        print(f"プロンプト:   {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        print(f"出力先:       {output_path}")
        if args.reference:
            print(f"参照画像:     {args.reference}")

    # --- コレクションモード ---
    elif args.collection_path:
        collection_path = Path(args.collection_path)
        if not collection_path.is_absolute():
            collection_path = REPO_ROOT / collection_path
        if not collection_path.exists():
            print(f"[ERROR] コレクションが見つかりません: {collection_path}")
            sys.exit(1)

        prompts_md = collection_path / "20-documentation" / "thumbnail-prompts.md"
        if args.variation == "bg":
            filename = "main.png"
        elif args.variation:
            filename = f"thumbnail-{args.variation.lower()}.png"
        else:
            filename = "thumbnail.jpg"
        output_path = collection_path / "10-assets" / filename
        workflow_state = collection_path / "workflow-state.json"

        if not prompts_md.exists():
            print(f"[ERROR] thumbnail-prompts.md が見つかりません: {prompts_md}")
            print("  先に /thumbnail スキルを実行してプロンプトを生成してください。")
            sys.exit(1)

        config = load_config()
        model = args.model or config.get("model", DEFAULT_MODEL)
        cost_per_image = config.get("cost_per_image_usd", DEFAULT_COST)
        use_text_overlay = args.reference is not None and args.variation is None
        prompt = extract_prompt(prompts_md, args.variation, use_text_overlay=use_text_overlay)

        if args.variation == "bg":
            label = "Video Background Prompt"
        elif args.variation:
            label = f"Variation {args.variation}"
        elif use_text_overlay:
            label = "Text Overlay Prompt"
        else:
            label = "Primary Prompt"
        print(f"\nコレクション: {collection_path.name}")
        print(f"プロンプト:   {label}")
        print(f"出力先:       {output_path.relative_to(REPO_ROOT)}")
        if args.reference:
            print(f"参照画像:     {args.reference}")

    else:
        parser.error("collection_path または --prompt が必要です")

    # 既存ファイル確認
    if output_path.exists() and output_path.stat().st_size > 0:
        if args.yes:
            # -y 時は自動バージョニング（並列エージェント安全）
            original = output_path
            output_path = resolve_unique_path(output_path)
            if output_path != original:
                print(f"\n[INFO] 既存ファイルあり → 自動採番: {output_path.name}")
        else:
            print(f"\n[INFO] 既存ファイルが見つかりました: {output_path.name} ({output_path.stat().st_size:,} bytes)")
            try:
                answer = input("上書きしますか? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n中止しました。")
                sys.exit(0)
            if answer not in ("y", "yes"):
                print("中止しました。")
                sys.exit(0)

    # コスト確認
    if not args.yes:
        if not confirm_cost(model, cost_per_image):
            sys.exit(0)

    # API キー確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 環境変数が設定されていません。")
        print("  export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)

    # SDK インポート
    try:
        from google import genai
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  pip3 install google-genai Pillow --break-system-packages")
        sys.exit(1)

    # 参照画像解決
    reference_image = None
    if args.reference:
        reference_image = Path(args.reference)
        if not reference_image.is_absolute():
            reference_image = Path.cwd() / reference_image
        if not reference_image.exists():
            print(f"[ERROR] 参照画像が見つかりません: {reference_image}")
            sys.exit(1)

    # 生成実行
    client = genai.Client()
    start_time = time.monotonic()
    success = generate_thumbnail(client, prompt, model, output_path, reference_image=reference_image)
    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  サムネイル生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  コスト:   ${cost_per_image:.3f}")
        print(f"  時間:     {elapsed:.1f}秒")
        if workflow_state:
            update_workflow_state(workflow_state)
    else:
        print("  サムネイル生成: 失敗")
        print("  --variation A や --variation B で別プロンプトを試してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
