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
import concurrent.futures
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
    print_cost_summary,
    prompt_overwrite_or_rename,
    resolve_composition_source,
    resolve_cost_per_image,
    resolve_reference_paths,
    select_reference,
    validate_forbid_keywords,
    validate_single_step_references,
    validate_single_step_request_references,
)
from youtube_automation.utils.image_provider.config import replace_model
from youtube_automation.utils.profile import section
from youtube_automation.utils.thumbnail_references import (
    format_reference_assignment,
    plan_ttp_reference_assignments,
    resolve_dedup_recent_collections,
)

# Gemini 用の解像度オプション（OpenAI provider 時は無視される）
_GEMINI_VALID_IMAGE_SIZES = ("1K", "2K", "4K")
_GEMINI_DEFAULT_IMAGE_SIZE = "2K"

# attempt ループ並列化のデフォルト並列度。Gemini / OpenAI のレート制限に
# 抵触しないよう控えめに固定する（CLI --max-workers で上書き可能）。
_DEFAULT_MAX_WORKERS = 3

# resolve_unique_path と同じ -vN 採番規則を事前計画でも使うための正規表現。
_VERSION_RE = re.compile(r"^(.+)-v(\d+)$")
_AB_PATTERN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _channel_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


def _required_mapping(value: object, key: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{key} は object で指定してください")
    return value


def _required_non_empty_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} は空でない文字列で指定してください")
    return value


def resolve_ab_test_patterns(skill_cfg: dict) -> list[dict[str, str]]:
    """A/B テストの pattern 定義を検証して返す。

    無効・未設定なら空リストを返し、従来の単一サムネイル経路を維持する。
    有効時は YouTube Test & compare の上限に合わせて 1〜3 件に制限する。
    """
    ab_test = skill_cfg.get("ab_test")
    if ab_test is None:
        return []
    ab_test = _required_mapping(ab_test, "ab_test")

    enabled = ab_test.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("ab_test.enabled は boolean で指定してください")
    if not enabled:
        return []

    patterns = ab_test.get("patterns")
    if not isinstance(patterns, list):
        raise ConfigError("ab_test.enabled=true の場合、ab_test.patterns は list で指定してください")
    if not patterns:
        raise ConfigError("ab_test.enabled=true の場合、ab_test.patterns を 1 件以上指定してください")
    if len(patterns) > 3:
        raise ConfigError("ab_test.patterns は YouTube Test & compare の上限である 3 件以内にしてください")

    resolved: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for index, raw_pattern in enumerate(patterns):
        key = f"ab_test.patterns[{index}]"
        pattern = _required_mapping(raw_pattern, key)
        name = _required_non_empty_string(pattern.get("name"), f"{key}.name").strip()
        if not _AB_PATTERN_NAME_RE.fullmatch(name):
            raise ConfigError(f"{key}.name は英小文字・数字・ハイフン・アンダースコアで指定してください")
        if name in seen_names:
            raise ConfigError(f"ab_test.patterns の name={name!r} が重複しています")
        variation = _required_non_empty_string(pattern.get("variation"), f"{key}.variation").strip()
        resolved.append({"name": name, "variation": variation})
        seen_names.add(name)
    return resolved


def apply_ab_test_pattern(prompt: str, patterns: list[dict[str, str]], pattern_name: str | None) -> str:
    """選択 pattern の variation clause をプロンプト末尾へ合成する。"""
    if pattern_name is None:
        return prompt
    if not patterns:
        raise ConfigError("--ab-pattern は ab_test.enabled=true の場合だけ指定できます")
    pattern = next((item for item in patterns if item["name"] == pattern_name), None)
    if pattern is None:
        available = ", ".join(item["name"] for item in patterns)
        raise ConfigError(f"--ab-pattern={pattern_name!r} は未定義です（有効値: {available}）")
    return f"{prompt.rstrip()}\n{pattern['variation']}"


def expand_thumbnail_prompt_clauses(prompt: str, skill_cfg: dict) -> str:
    """thumbnail skill-config の prompt clause placeholder を展開する。"""
    if "${typography_clause}" not in prompt:
        return prompt

    image_generation = _required_mapping(skill_cfg.get("image_generation"), "image_generation")
    gemini = _required_mapping(image_generation.get("gemini"), "image_generation.gemini")
    single_step = _required_mapping(gemini.get("single_step"), "image_generation.gemini.single_step")
    thumbnail_text = _required_mapping(gemini.get("thumbnail_text"), "image_generation.gemini.thumbnail_text")
    font = _required_mapping(thumbnail_text.get("font"), "image_generation.gemini.thumbnail_text.font")

    typography_clause = _required_non_empty_string(
        single_step.get("typography_clause"),
        "image_generation.gemini.single_step.typography_clause",
    )
    font_description = _required_non_empty_string(
        font.get("copy"),
        "image_generation.gemini.thumbnail_text.font.copy",
    )
    if "{font_description}" not in typography_clause:
        raise ConfigError(
            "image_generation.gemini.single_step.typography_clause は {font_description} を含めてください"
        )

    rendered_clause = typography_clause.replace("{font_description}", font_description)
    return prompt.replace("${typography_clause}", rendered_clause.strip())


def _next_planned_path(output_path: Path, taken: set[Path]) -> Path:
    """``resolve_unique_path`` と同一の -vN 採番規則で次の一意パスを返す。

    逐次実行では直前 attempt が生成したファイルが disk 上に存在することを根拠に
    採番していたが、並列実行ではファイル生成前にパスを確定する必要がある。そこで
    disk 上の存在に加えて ``taken``（既に計画済みのパス）も「使用済み」とみなす。
    """
    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    base_match = _VERSION_RE.match(stem)
    if base_match:
        base = base_match.group(1)
        start = int(base_match.group(2)) + 1
    else:
        base = stem
        start = 2
    for n in range(start, start + 100):
        candidate = parent / f"{base}-v{n}{suffix}"
        if candidate not in taken and not candidate.exists():
            return candidate
    return parent / f"{base}-v{start + 100}{suffix}"


def plan_output_paths(first_path: Path, count: int) -> list[Path]:
    """逐次実行の ``resolve_unique_path`` チェーンと同一の出力パス列を事前確定する。

    先頭は ``first_path``（呼び出し側で一意化済み）。2 件目以降は直前のパスを
    起点に -vN を採番し、計画済みパスを ``taken`` に積むことで逐次時と同じ採番を
    ファイル生成前に再現する。
    """
    if count < 1:
        return []
    paths = [first_path]
    taken = {first_path}
    current = first_path
    for _ in range(count - 1):
        nxt = _next_planned_path(current, taken)
        paths.append(nxt)
        taken.add(nxt)
        current = nxt
    return paths


def plan_reference_assignments(
    reference_images: list[Path],
    count: int,
    rotate: bool,
) -> list[Path | None]:
    """各 attempt に割り当てる参照画像を逐次時と同じ規則で確定する。

    参照画像が無い場合は ``None`` を並べる。ある場合は ``select_reference`` で
    attempt インデックスに応じたローテーション割り当てを再現する。
    """
    if not reference_images:
        return [None] * count
    return [select_reference(reference_images, attempt, rotate) for attempt in range(count)]


def build_requests(
    prompt: str,
    planned_paths: list[Path],
    reference_assignments: list[Path | None],
    *,
    aspect_ratio: str,
    image_size: str,
) -> list[ImageGenerationRequest]:
    """確定済みの出力パス・参照割り当てから attempt 順の生成リクエストを組み立てる。"""
    requests: list[ImageGenerationRequest] = []
    for output_path, selected_ref in zip(planned_paths, reference_assignments, strict=False):
        request_refs = [selected_ref] if selected_ref is not None else []
        requests.append(
            ImageGenerationRequest(
                prompt=prompt,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                references=request_refs,
            )
        )
    return requests


def run_requests_parallel(
    provider,
    requests: list[ImageGenerationRequest],
    *,
    max_workers: int,
    aspect_ratio: str,
) -> tuple[list, list[tuple[int, ConfigError]]]:
    """リクエスト列を ThreadPoolExecutor で並列実行する（API は I/O バウンド）。

    戻り値は ``(results, errors)``。``results`` は attempt 順に整列した結果
    （失敗 attempt は ``None``）、``errors`` は ``(attempt_index, ConfigError)`` の
    リスト。失敗は future の例外として回収し、ここでは ``sys.exit`` しない
    （集約・終了判定は呼び出し側に委ねる）。
    """
    results: list = [None] * len(requests)
    errors: list[tuple[int, ConfigError]] = []
    if not requests:
        return results, errors

    effective_workers = max(1, min(max_workers, len(requests)))

    def _run(request: ImageGenerationRequest):
        with section(
            "image_provider.generate",
            provider=provider.__class__.__name__,
            aspect_ratio=aspect_ratio,
        ):
            return provider.generate(request)

    with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_to_index = {executor.submit(_run, req): idx for idx, req in enumerate(requests)}
        for future in concurrent.futures.as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                results[idx] = future.result()
            except ConfigError as e:
                errors.append((idx, e))

    errors.sort(key=lambda item: item[0])
    return results, errors


def print_provider_fallback_hint(provider_name: str) -> None:
    """画像生成プロバイダー失敗時に、手動切替の次アクションを表示する。"""
    print()
    print("  代替プロバイダーの候補:")
    if provider_name == "gemini":
        print("  - GCP 課金や Gemini API 障害が疑われる場合:")
        print("      config/skills/thumbnail.yaml の image_generation.provider を codex に変更")
        print("      生成は .claude/skills/thumbnail/references/codex-image.sh 経由で実行")
        print("  - OPENAI_API_KEY がある場合:")
        print("      image_generation.provider を openai に変更して再試行")
    elif provider_name == "openai":
        print("  - OpenAI 側の障害や quota が疑われる場合:")
        print("      image_generation.provider を gemini または codex に変更して再試行")
    else:
        print("  - provider 固有の手順を確認し、gemini / openai / codex のいずれかへ切り替え")
    print("  詳細: .claude/skills/thumbnail/SKILL.md の「障害時の provider fallback」")


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
        "--ab-pattern",
        type=str,
        default=None,
        help="ab_test.patterns の name。対応する variation clause を最終プロンプトへ追加する",
    )
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
        "--ttp-strict-references",
        action="store_true",
        help=(
            "thumbnail TTP 候補生成用の strict 参照契約を有効化する。"
            "候補数分のユニークな benchmark 参照、同一チャンネル、path escape 拒否を生成前に検証する"
        ),
    )
    parser.add_argument(
        "--reference-index",
        type=int,
        default=None,
        help="複数参照画像のうち特定のインデックスのみ使用（attempt ループ無効）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help=(
            "複数 attempt を並列生成するときの最大同時実行数。"
            f"未指定時は {_DEFAULT_MAX_WORKERS}（レート制限を考慮した控えめな固定値）。"
            "attempt 数より大きい値は attempt 数に丸められる"
        ),
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

    try:
        skill_cfg = load_skill_config("thumbnail")
        composition_source = resolve_composition_source(skill_cfg, cfg.provider)
        ab_test_patterns = resolve_ab_test_patterns(skill_cfg)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # single_step モード情報は TTP strict の事前検証と attempt 解決に使う。
    gemini_section = skill_cfg.get("image_generation", {}).get("gemini", {})
    generation_mode = gemini_section.get("generation_mode") if isinstance(gemini_section, dict) else None

    if args.no_composition or args.reference:
        prompt = args.prompt
    else:
        prompt = apply_composition_rules(args.prompt, composition_source)
    try:
        prompt = expand_thumbnail_prompt_clauses(prompt, skill_cfg)
        prompt = apply_ab_test_pattern(prompt, ab_test_patterns, args.ab_pattern)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # NG ワード事前検査 (#1664): 最終プロンプト確定直後・生成 API 呼び出し前に実施。
    # ヒットしたキーワードは要件どおり標準エラーへ列挙する。
    try:
        validate_forbid_keywords(prompt, skill_cfg)
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    # provider 別にモデル ID と画像サイズキーを解決
    if cfg.provider == "gemini":
        assert cfg.gemini is not None
        model = cfg.gemini.model
        image_size = args.size
    elif cfg.provider == "openai":
        assert cfg.openai is not None
        model = cfg.openai.model
        image_size = cfg.openai.quality
    elif cfg.provider == "gemini_cli":
        assert cfg.gemini_cli is not None
        model = cfg.gemini_cli.model
        image_size = args.size
    else:
        print(f"[ERROR] provider={cfg.provider!r} は yt-generate-image では未対応です")
        sys.exit(1)

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

    # single_step preflight は既存出力確認・コスト確認・provider 初期化より前に済ませる。
    if generation_mode == "single_step" and not args.reference:
        try:
            validate_single_step_references(skill_cfg)
            validate_single_step_request_references(generation_mode, [])
        except ConfigError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

    try:
        reference_images = resolve_reference_paths(args.reference)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    try:
        validate_single_step_request_references(generation_mode, reference_images)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    if args.reference_index is not None:
        if not reference_images:
            print("[ERROR] --reference-index 指定には参照画像が必要です（--reference で指定してください）")
            sys.exit(1)
        if not (0 <= args.reference_index < len(reference_images)):
            print(f"[ERROR] --reference-index={args.reference_index} は参照画像範囲外 (0..{len(reference_images) - 1})")
            sys.exit(1)
        reference_images = [reference_images[args.reference_index]]
        cli_max_attempts = 1

    try:
        if args.ttp_strict_references:
            benchmark_root = _channel_root() / "data" / "thumbnail_compare" / "benchmark"
            gemini_config = skill_cfg.get("image_generation", {}).get("gemini", {})
            reference_config = gemini_config.get("reference_images", {})
            dedup_recent_collections = resolve_dedup_recent_collections(
                reference_config.get("dedup_recent_collections")
            )
            reference_assignments = plan_ttp_reference_assignments(
                reference_images,
                cli_max_attempts,
                rotate,
                benchmark_root=benchmark_root,
                channel_dir=_channel_root(),
                dedup_recent_collections=dedup_recent_collections,
            )
        else:
            benchmark_root = None
            reference_assignments = plan_reference_assignments(reference_images, cli_max_attempts, rotate)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # コスト算出: skill-config の cost_per_image_usd を尊重。未設定なら None。
    cost_per_image = resolve_cost_per_image(skill_cfg, cfg.provider)

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

    try:
        provider = get_provider(cfg)
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # 並列度: レート制限を考慮した控えめなデフォルト。1 attempt なら 1。
    max_workers = args.max_workers if args.max_workers is not None else _DEFAULT_MAX_WORKERS
    if max_workers < 1:
        max_workers = 1

    # 出力パス（-vN）と参照画像をループ前に全 attempt ぶん確定し、
    # resolve_unique_path の直列依存を排除してから並列 submit する。
    planned_paths = plan_output_paths(output_path, cli_max_attempts)
    if reference_assignments:
        print()
        print("参照割当:")
        for attempt, selected_ref in enumerate(reference_assignments, start=1):
            if selected_ref is None:
                print(f"  attempt {attempt}: 参照画像なし")
            else:
                print(f"  attempt {attempt}: {format_reference_assignment(selected_ref, benchmark_root)}")

    # attempt>0 のヘッダは並列実行前にまとめて表示し、stdout の交錯を避ける。
    for attempt in range(1, cli_max_attempts):
        selected_ref = reference_assignments[attempt]
        print()
        print(f"--- attempt {attempt + 1}/{cli_max_attempts} ---")
        print(f"出力先:       {planned_paths[attempt]}")
        if selected_ref is not None:
            print(f"参照画像:     {format_reference_assignment(selected_ref, benchmark_root)}")

    requests = build_requests(
        prompt,
        planned_paths,
        reference_assignments,
        aspect_ratio=args.aspect_ratio,
        image_size=image_size,
    )

    total_start = time.monotonic()
    results, errors = run_requests_parallel(
        provider,
        requests,
        max_workers=max_workers,
        aspect_ratio=args.aspect_ratio,
    )
    elapsed = time.monotonic() - total_start

    # ConfigError はループ外に集約して終了する（1 件でも失敗ならプロセスを落とす）。
    if errors:
        for attempt, error in errors:
            prefix = f"attempt {attempt + 1}: " if cli_max_attempts > 1 else ""
            print(f"[ERROR] {prefix}{error}")
        print_provider_fallback_hint(cfg.provider)
        sys.exit(1)

    saved_paths: list[Path] = []
    success_flags: list[bool] = []
    for attempt, result in enumerate(results):
        if result.success:
            saved_paths.append(result.saved_path or planned_paths[attempt])
        success_flags.append(result.success)

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
        print_provider_fallback_hint(cfg.provider)
    print("===========================================")
    print()

    sys.exit(0 if any(success_flags) else 1)


if __name__ == "__main__":
    main()
