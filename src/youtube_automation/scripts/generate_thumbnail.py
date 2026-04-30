#!/usr/bin/env python3
"""コレクションサムネイル画像を画像生成プロバイダー（Gemini / OpenAI）で生成する。

thumbnail-prompts.md の Primary Prompt を読み込み、10-assets/ に保存。
provider 切り替えは ``config/skills/thumbnail.yaml`` の
``image_generation.provider`` で行う。
ダイレクトモード（プロンプト直指定）は generate_image.py を使用してください。

Usage:
    yt-generate-thumbnail <collection-path>
    yt-generate-thumbnail <collection-path> -y
    yt-generate-thumbnail <collection-path> --variation A
    yt-generate-thumbnail <collection-path> --variation bg
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider import (
    ImageGenerationRequest,
    get_provider,
    load_image_generation_config,
)
from youtube_automation.utils.image_provider.composition import (
    apply_composition_rules,
    confirm_cost,
    prompt_overwrite_or_rename,
    resolve_composition_source,
    resolve_cost_per_image,
    resolve_reference_paths,
)
from youtube_automation.utils.image_provider.config import replace_model

# Thumbnail スキルは 16:9 固定（order.md 「期待する動作 1」: thumbnail スキルは 16:9 固定）
_THUMBNAIL_ASPECT_RATIO = "16:9"


def _channel_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


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
            overlay_pattern = r"## Text Overlay Prompt[^\n]*\n\s*```\n(.*?)\n```"
            overlay_match = re.search(overlay_pattern, text, re.DOTALL)
            if overlay_match:
                return overlay_match.group(1).strip()
        pattern = r"## Primary Prompt[^\n]*\n\s*```\n(.*?)\n```"
    elif variation == "bg":
        pattern = r"## Video Background Prompt[^\n]*\n\s*```\n(.*?)\n```"
    else:
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

    parser = argparse.ArgumentParser(description="画像生成プロバイダーでコレクションサムネイル画像を生成")
    parser.add_argument("collection_path", help="コレクションのパス（例: collections/planning/xxx）")
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument(
        "--variation",
        choices=["A", "B", "C", "bg"],
        default=None,
        help="使用するプロンプトバリエーション（省略時は Primary Prompt、bg は動画背景用）",
    )
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（skill-config の値を上書き）")
    parser.add_argument(
        "--reference",
        type=str,
        action="append",
        default=None,
        help="参照画像パス（複数指定可）",
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

    try:
        cfg = load_image_generation_config()
    except ConfigError as e:
        print(f"[ERROR] skill-config 読み込み失敗: {e}")
        sys.exit(1)

    if args.model:
        cfg = replace_model(cfg, args.model)

    from youtube_automation.utils.skill_config import load_skill_config

    skill_cfg = load_skill_config("thumbnail")

    if cfg.provider == "gemini":
        assert cfg.gemini is not None
        model = cfg.gemini.model
        image_size = cfg.gemini.image_size
    else:
        assert cfg.openai is not None
        model = cfg.openai.model
        image_size = cfg.openai.quality

    composition_source = resolve_composition_source(skill_cfg, cfg.provider)

    cost_per_image = resolve_cost_per_image(skill_cfg, cfg.provider, model, image_size)

    use_text_overlay = args.reference is not None and args.variation is None
    raw_prompt = extract_prompt(prompts_md, args.variation, use_text_overlay=use_text_overlay)
    prompt = apply_composition_rules(raw_prompt, composition_source)

    if args.variation == "bg":
        label = "Video Background Prompt"
    elif args.variation:
        label = f"Variation {args.variation}"
    elif use_text_overlay:
        label = "Text Overlay Prompt"
    else:
        label = "Primary Prompt"
    print(f"\nコレクション: {collection_path.name}")
    print(f"プロバイダー: {cfg.provider}")
    print(f"プロンプト:   {label}")
    print(f"出力先:       {output_path.relative_to(_channel_root())}")
    if args.reference:
        print(f"参照画像:     {', '.join(args.reference)}")

    resolved_path = prompt_overwrite_or_rename(output_path, yes=args.yes)
    if resolved_path is None:
        sys.exit(0)
    output_path = resolved_path

    if not args.yes and not confirm_cost(model, cost_per_image):
        sys.exit(0)

    try:
        reference_images = resolve_reference_paths(args.reference)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    try:
        provider = get_provider(cfg)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    request = ImageGenerationRequest(
        prompt=prompt,
        output_path=output_path,
        aspect_ratio=_THUMBNAIL_ASPECT_RATIO,
        image_size=image_size,
        references=reference_images,
        cost_per_image_usd=cost_per_image,
    )

    start_time = time.monotonic()
    try:
        result = provider.generate(request)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    elapsed = time.monotonic() - start_time

    print()
    print("===========================================")
    if result.success:
        print("  サムネイル生成: 完了")
        saved = result.saved_path or output_path
        try:
            print(f"  ファイル: {saved.relative_to(_channel_root())}")
        except ValueError:
            print(f"  ファイル: {saved}")
        print(f"  コスト:   ${cost_per_image:.3f}")
        print(f"  時間:     {elapsed:.1f}秒")
        update_workflow_state(workflow_state)
    else:
        print("  サムネイル生成: 失敗")
        print("  --variation A や --variation B で別プロンプトを試してください。")
    print("===========================================")
    print()

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
