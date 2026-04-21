#!/usr/bin/env python3
"""コレクションサムネイル画像を Gemini API で生成する。

thumbnail-prompts.md の Primary Prompt を読み込み、10-assets/ に保存。
ダイレクトモード（プロンプト直指定）は generate_image.py を使用してください。

Usage:
    python3 generate_thumbnail.py <collection-path>
    python3 generate_thumbnail.py <collection-path> -y
    python3 generate_thumbnail.py <collection-path> --variation A
    python3 generate_thumbnail.py <collection-path> --variation bg

Example:
    python3 generate_thumbnail.py collections/planning/20260219-8bit-rpg-class-vol2-collection
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path


# --- パス解決 ---
def _channel_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


from youtube_automation.utils.exceptions import ConfigError  # noqa: E402
from youtube_automation.utils.image_generator import (  # noqa: E402
    DEFAULT_MODEL,
    apply_composition_rules,
    confirm_cost,
    generate_image,
    load_gemini_config,
    resolve_unique_path,
)


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

    parser = argparse.ArgumentParser(description="Gemini API でコレクションサムネイル画像を生成")
    parser.add_argument("collection_path", help="コレクションのパス（例: collections/planning/xxx）")
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument(
        "--variation",
        choices=["A", "B", "C", "bg"],
        default=None,
        help="使用するプロンプトバリエーション（省略時は Primary Prompt、bg は動画背景用）",
    )
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（例: gemini-3.1-flash-image-preview）")
    parser.add_argument(
        "--reference",
        type=str,
        action="append",
        default=None,
        help="参照画像パス（複数指定可。画像+プロンプトで Gemini に送信）",
    )
    args = parser.parse_args()

    collection_path = Path(args.collection_path)
    if not collection_path.is_absolute():
        collection_path = _channel_root() / collection_path
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

    config = load_gemini_config()
    model = args.model or config.get("model", DEFAULT_MODEL)
    cost_per_image = config.get("cost_per_image_usd", 0.04)
    use_text_overlay = args.reference is not None and args.variation is None
    raw_prompt = extract_prompt(prompts_md, args.variation, use_text_overlay=use_text_overlay)
    prompt = apply_composition_rules(raw_prompt, config)

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
    print(f"出力先:       {output_path.relative_to(_channel_root())}")
    if args.reference:
        print(f"参照画像:     {', '.join(args.reference)}")

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

    try:
        from youtube_automation.utils.genai_client import create_genai_client
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  pip3 install google-genai Pillow --break-system-packages")
        sys.exit(1)

    # 参照画像解決（複数対応）
    reference_images: list[Path] = []
    for raw_ref in args.reference or []:
        ref_path = Path(raw_ref)
        if not ref_path.is_absolute():
            ref_path = Path.cwd() / ref_path
        if not ref_path.exists():
            print(f"[ERROR] 参照画像が見つかりません: {ref_path}")
            sys.exit(1)
        reference_images.append(ref_path)

    # 生成実行
    try:
        client = create_genai_client()
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    start_time = time.monotonic()
    success = generate_image(
        client,
        prompt,
        model,
        output_path,
        reference_image=reference_images or None,
        cost_per_image_usd=cost_per_image,
    )
    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  サムネイル生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(_channel_root())}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  コスト:   ${cost_per_image:.3f}")
        print(f"  時間:     {elapsed:.1f}秒")
        update_workflow_state(workflow_state)
    else:
        print("  サムネイル生成: 失敗")
        print("  --variation A や --variation B で別プロンプトを試してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
