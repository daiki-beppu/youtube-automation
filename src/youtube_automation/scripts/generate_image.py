#!/usr/bin/env python3
"""画像生成プロバイダー（Gemini / OpenAI）経由で画像を生成する汎用スクリプト。

プロンプトテキストと出力パスを直接指定して画像生成。
provider 切り替えは ``config/skills/thumbnail.yaml`` の
``image_generation.provider`` で行う。
workflow-state.json には触れない。

Usage:
    yt-generate-image --prompt "A mystical forest..." --output /tmp/preview.png -y
    yt-generate-image --prompt "Celtic harp in moonlight" --output previews/plan-a.png
    yt-generate-image --prompt "..." --output out.png --reference ref.png -y
"""

import argparse
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
    print_cost_summary,
    prompt_overwrite_or_rename,
    resolve_composition_source,
    resolve_cost_per_image,
    resolve_reference_paths,
    resolve_unique_path,
    select_reference,
    validate_single_step_references,
)
from youtube_automation.utils.image_provider.config import replace_model
from youtube_automation.utils.profile import section

# Gemini 用の解像度オプション（OpenAI provider 時は無視される）
_GEMINI_VALID_IMAGE_SIZES = ("1K", "2K", "4K")
_GEMINI_DEFAULT_IMAGE_SIZE = "2K"


def _channel_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


def main():
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(
        description="画像生成プロバイダー（Gemini / OpenAI）で画像を生成（ダイレクトモード）"
    )
    parser.add_argument("--prompt", type=str, default=None, help="プロンプトテキスト")
    parser.add_argument("--output", type=str, default=None, help="出力パス")
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（skill-config の値を上書き）")
    parser.add_argument(
        "--reference",
        type=str,
        action="append",
        default=None,
        help="参照画像パス（複数指定可。複数指定時はスタイルブレンド/合成）",
    )
    parser.add_argument("--aspect-ratio", type=str, default="16:9", help="アスペクト比（例: 16:9, 9:16, 1:1）")
    parser.add_argument(
        "--size",
        type=str,
        choices=list(_GEMINI_VALID_IMAGE_SIZES),
        default=_GEMINI_DEFAULT_IMAGE_SIZE,
        help=(
            f"画像解像度 {_GEMINI_VALID_IMAGE_SIZES}（Gemini provider 用、デフォルト: "
            f"{_GEMINI_DEFAULT_IMAGE_SIZE}）。OpenAI provider では aspect_ratio から自動決定"
        ),
    )
    parser.add_argument("--no-composition", action="store_true", help="composition_prefix の自動付加をスキップ")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help=(
            "single_step モードかつ複数参照画像のときの試行回数。"
            "各 attempt で参照画像をローテーションし、2 回目以降の出力は -vN で別保存。"
            "未指定時は skill-config の image_generation.gemini.single_step.max_attempts を使う"
        ),
    )
    parser.add_argument(
        "--no-rotate",
        action="store_true",
        help="複数参照画像のとき attempt 毎の切替を無効化（先頭固定）",
    )
    parser.add_argument(
        "--reference-index",
        type=int,
        default=None,
        help="複数参照画像のうち特定のインデックスのみ使用（attempt ループ無効）",
    )
    parser.add_argument(
        "--costs",
        action="store_true",
        help="data/image_costs.json から累積コストサマリを表示して終了",
    )
    args = parser.parse_args()

    if args.costs:
        print_cost_summary()
        sys.exit(0)

    if not args.prompt or not args.output:
        parser.error("--prompt と --output は必須です（--costs 単独実行を除く）")

    try:
        cfg = load_image_generation_config()
    except ConfigError as e:
        print(f"[ERROR] skill-config 読み込み失敗: {e}")
        sys.exit(1)

    if cfg.provider == "codex":
        print(
            "[ERROR] image_generation.provider=codex は yt-generate-image の API 経路では実行できません。"
            ".claude/skills/thumbnail/references/codex-image.sh を使ってください。"
        )
        sys.exit(1)

    # provider オーバーライド: --model 指定時は cfg のモデル値を差し替える
    if args.model:
        cfg = replace_model(cfg, args.model)

    # composition_prefix は thumbnail skill-config の image_generation.<provider> 直下で扱われない（旧
    # gemini_image.* と同じ位置にユーザーが置くケースに対応）。channel-side で
    # composition_prefix を提供している場合のみ適用される。
    from youtube_automation.utils.skill_config import load_skill_config

    skill_cfg = load_skill_config("thumbnail")
    composition_source = resolve_composition_source(skill_cfg, cfg.provider)

    # single_step モードのプリフライト: 参照画像未設定の取り違えを早期検知
    gemini_section = skill_cfg.get("image_generation", {}).get("gemini", {})
    generation_mode = gemini_section.get("generation_mode") if isinstance(gemini_section, dict) else None
    if generation_mode == "single_step" and not args.reference:
        try:
            validate_single_step_references(skill_cfg)
        except ConfigError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        print(
            "[ERROR] single_step モードでは --reference の指定が必須です。"
            "skill-config の image_generation.gemini.reference_images.default を CLI へ展開してください。"
        )
        sys.exit(1)

    if args.no_composition or args.reference:
        prompt = args.prompt
    else:
        prompt = apply_composition_rules(args.prompt, composition_source)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    # provider 別にモデル ID と画像サイズキーを解決
    if cfg.provider == "gemini":
        assert cfg.gemini is not None
        model = cfg.gemini.model
        image_size = args.size
    else:
        assert cfg.openai is not None
        model = cfg.openai.model
        image_size = cfg.openai.quality

    # コスト算出: skill-config の cost_per_image_usd を尊重。未設定なら None。
    cost_per_image = resolve_cost_per_image(skill_cfg, cfg.provider)

    # max_attempts / rotate / reference_index の解決（コスト表示前に出すため早期解決）
    single_step_section = gemini_section.get("single_step") if isinstance(gemini_section, dict) else None
    if not isinstance(single_step_section, dict):
        single_step_section = {}
    config_max_attempts = int(single_step_section.get("max_attempts", 1) or 1)
    config_rotate = bool(single_step_section.get("rotate", True))
    cli_max_attempts = args.max_attempts if args.max_attempts is not None else config_max_attempts
    if cli_max_attempts < 1:
        cli_max_attempts = 1
    rotate = (not args.no_rotate) and config_rotate

    print("\nモード:       ダイレクト")
    print(f"プロバイダー: {cfg.provider}")
    print(f"プロンプト:   {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"出力先:       {output_path}")
    print(f"解像度:       {image_size}")
    if args.reference:
        print(f"参照画像:     {', '.join(args.reference)}")
    if cli_max_attempts > 1:
        rotate_label = " (rotate=ON)" if rotate else " (rotate=OFF)"
        print(f"試行回数:     {cli_max_attempts} attempts{rotate_label}")

    # 既存ファイル確認（上書き or -vN 自動採番）
    resolved_path = prompt_overwrite_or_rename(output_path, yes=args.yes)
    if resolved_path is None:
        sys.exit(0)
    output_path = resolved_path

    if not args.yes and not confirm_cost(model, cost_per_image):
        sys.exit(0)

    # 参照画像解決（複数対応）
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

    # --reference-index 指定時は単一参照固定 + attempt=1
    if args.reference_index is not None:
        if not reference_images:
            print("[ERROR] --reference-index 指定には参照画像が必要です（--reference で指定してください）")
            sys.exit(1)
        if not (0 <= args.reference_index < len(reference_images)):
            print(f"[ERROR] --reference-index={args.reference_index} は参照画像範囲外 (0..{len(reference_images) - 1})")
            sys.exit(1)
        reference_images = [reference_images[args.reference_index]]
        cli_max_attempts = 1

    saved_paths: list[Path] = []
    success_flags: list[bool] = []
    total_start = time.monotonic()
    current_output_path = output_path

    for attempt in range(cli_max_attempts):
        if reference_images:
            selected_ref = select_reference(reference_images, attempt, rotate)
            request_refs: list[Path] = [selected_ref]
        else:
            selected_ref = None
            request_refs = []

        if attempt > 0:
            current_output_path = resolve_unique_path(current_output_path)
            print()
            print(f"--- attempt {attempt + 1}/{cli_max_attempts} ---")
            print(f"出力先:       {current_output_path}")
            if selected_ref is not None:
                print(f"参照画像:     {selected_ref.name}")

        request = ImageGenerationRequest(
            prompt=prompt,
            output_path=current_output_path,
            aspect_ratio=args.aspect_ratio,
            image_size=image_size,
            references=request_refs,
        )

        try:
            with section(
                "image_provider.generate",
                provider=provider.__class__.__name__,
                aspect_ratio=args.aspect_ratio,
            ):
                result = provider.generate(request)
        except ConfigError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        if result.success:
            saved_paths.append(result.saved_path or current_output_path)
        success_flags.append(result.success)

    elapsed = time.monotonic() - total_start

    print()
    print("===========================================")
    if any(success_flags):
        succeeded = sum(success_flags)
        print(f"  画像生成: 完了 ({succeeded}/{cli_max_attempts} 成功)")
        for path in saved_paths:
            try:
                print(f"  ファイル: {path.relative_to(_channel_root())}")
            except ValueError:
                print(f"  ファイル: {path}")
        cost_label = f"${cost_per_image:.3f}" if cost_per_image is not None else "不明"
        print(f"  単価:     {cost_label} × {cli_max_attempts}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print(f"  画像生成: 失敗 (0/{cli_max_attempts})")
        print("  プロンプト・参照画像・config を調整して再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if any(success_flags) else 1)


if __name__ == "__main__":
    main()
