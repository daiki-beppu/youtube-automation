"""画像生成プロバイダーから独立した共通ヘルパー。

旧 `image_generator.py` から以下の関数をプロバイダー中立として移設:
- ``apply_composition_rules``: composition_prefix の自動付加
- ``confirm_cost``: コスト確認プロンプト
- ``resolve_unique_path``: 既存ファイルとの衝突時に -vN 採番
- ``log_image_cost`` / ``print_cost_summary``: cost_tracker への薄いラッパ

また、provider 切替時の構図ルールソース dict を skill-config から解決する
``resolve_composition_source``、skill-config の単価上書きを尊重した
``resolve_cost_per_image``、PNG/JPEG の保存と YouTube サムネ 2MB 上限対応の
``persist_image`` をここに集約する。

CLI 共通ヘルパー（``generate_image`` の出力上書き分岐 / 参照画像解決を集約）:
- ``prompt_overwrite_or_rename``: 既存出力ファイル検出時の上書き確認 / -vN 採番
- ``resolve_reference_paths``: 参照画像パス文字列を絶対 ``Path`` に解決
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import ConfigError

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


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

    print(f"  [Auto]   構図ルール適用: {prefix}")
    return f"{prefix} {prompt}"


def confirm_cost(model: str, cost_per_image: float) -> bool:
    """コスト見積もりを表示してユーザー確認を取る。"""
    print()
    print("=== Image Generation ===")
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
    return parent / f"{base}-v{start + 100}{suffix}"


def log_image_cost(
    model: str,
    image_size: str,
    aspect_ratio: str,
    output_file: Path,
    cost_usd: float | None = None,
    reference_count: int = 0,
) -> dict | None:
    """画像生成 1 件分を cost_tracker 経由で記録する。"""
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


def resolve_composition_source(
    skill_cfg: dict[str, Any],
    provider: str,
    *,
    skill_name: str = "thumbnail",
) -> dict[str, Any]:
    """``apply_composition_rules`` に渡す構図ルールソース dict を解決する。

    通常パスでは ``skill_cfg["image_generation"][provider]`` を返す。

    後方互換: ユーザー override が legacy ``gemini_image:`` のみで
    ``image_generation:`` を持たない場合は legacy section を返す。
    default.yaml が ``image_generation.gemini.*`` を宣言しているため通常マージでは
    default 値で常に non-empty となり、merged 後に判定すると legacy override が
    silently 破棄される (`composition_prefix` / `composition_keywords` /
    `brand_background` 等のユーザー値が apply_composition_rules に届かない)。
    そのため override 単体を ``load_channel_override`` で確認して判定する
    （``load_image_generation_config`` と同じパターン）。

    provider="openai" には旧 namespace が存在しないため legacy 分岐はスキップ。
    """
    from youtube_automation.utils.skill_config import load_channel_override

    if provider == "gemini":
        override = load_channel_override(skill_name)
        legacy = override.get("gemini_image")
        if isinstance(legacy, dict) and not isinstance(override.get("image_generation"), dict):
            return legacy

    section = skill_cfg.get("image_generation", {})
    if not isinstance(section, dict):
        return {}
    source = section.get(provider, {})
    return source if isinstance(source, dict) else {}


def resolve_cost_per_image(
    skill_cfg: dict[str, Any],
    provider: str,
    model: str,
    image_size: str,
) -> float:
    """skill-config の ``cost_per_image_usd`` 上書きを尊重して 1 枚あたり単価を決定する。

    優先順位:
    1. ``skill_cfg["image_generation"][provider]["cost_per_image_usd"]``
    2. （provider="gemini" の場合のみ）legacy ``skill_cfg["gemini_image"]["cost_per_image_usd"]``
    3. ``cost_tracker.estimate_cost(model, quantity=1, image_size=image_size)``（PRICING）
    4. すべて未解決なら 0.0
    """
    custom = None
    image_gen = skill_cfg.get("image_generation")
    if isinstance(image_gen, dict):
        provider_section = image_gen.get(provider)
        if isinstance(provider_section, dict):
            custom = provider_section.get("cost_per_image_usd")
    if custom is None and provider == "gemini":
        legacy = skill_cfg.get("gemini_image")
        if isinstance(legacy, dict):
            custom = legacy.get("cost_per_image_usd")
    if custom is not None:
        return float(custom)
    return cost_tracker.estimate_cost(model, quantity=1, image_size=image_size) or 0.0


def persist_image(image: "PILImage", output_path: Path, *, save_as_png: bool) -> Path:
    """PIL Image を ``output_path`` に保存する（YouTube サムネ 2MB 上限対応）。

    ``save_as_png=True`` 時は PNG ロスレス + JPEG 圧縮版を両方生成し、
    それ以外（``.jpg`` 等）は JPEG のみ保存する。後者で拡張子が ``.jpg`` 以外なら
    元パスのファイルは削除する。

    bytes 入力の provider（OpenAI 等）は呼び出し側で
    ``PIL.Image.open(io.BytesIO(payload))`` を行ってから渡すこと。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb_image = image.convert("RGB")

    if save_as_png:
        image.save(str(output_path), optimize=True)
        png_kb = output_path.stat().st_size // 1024
        print(f"  [Done]   保存完了 → {output_path} ({png_kb} KB)")
        jpg_path = output_path.with_suffix(".jpg")
        rgb_image.save(str(jpg_path), quality=92, optimize=True)
        jpg_kb = jpg_path.stat().st_size // 1024
        print(f"  [Done]   JPEG版   → {jpg_path} ({jpg_kb} KB)")
        return output_path

    jpg_path = output_path.with_suffix(".jpg")
    rgb_image.save(str(jpg_path), quality=92, optimize=True)
    if output_path.suffix != ".jpg" and output_path.exists():
        output_path.unlink()
    size_kb = jpg_path.stat().st_size // 1024
    print(f"  [Done]   保存完了 → {jpg_path} ({size_kb} KB)")
    return jpg_path


def prompt_overwrite_or_rename(output_path: Path, *, yes: bool) -> Path | None:
    """出力先が既存（かつ非空）の場合に CLI 共通の分岐を 1 箇所に集約する。

    ``yes=True``  → ``resolve_unique_path`` で ``-vN`` を採番した新規パスを返す。
                    自動採番が走った場合は INFO ログを出す。
    ``yes=False`` → 上書き確認プロンプトを表示。
                    ``y``/``yes`` 以外（EOF / KeyboardInterrupt 含む）なら ``None`` を返す。
                    呼び出し側はそれを受けて ``sys.exit(0)`` する。

    既存ファイルが無い／空サイズの場合は元の ``output_path`` をそのまま返す。
    """
    if not (output_path.exists() and output_path.stat().st_size > 0):
        return output_path

    if yes:
        original = output_path
        new_path = resolve_unique_path(output_path)
        if new_path != original:
            print(f"\n[INFO] 既存ファイルあり → 自動採番: {new_path.name}")
        return new_path

    print(f"\n[INFO] 既存ファイルが見つかりました: {output_path.name} ({output_path.stat().st_size:,} bytes)")
    try:
        answer = input("上書きしますか? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n中止しました。")
        return None
    if answer not in ("y", "yes"):
        print("中止しました。")
        return None
    return output_path


def resolve_reference_paths(raw_refs: list[str] | None) -> list[Path]:
    """参照画像パス文字列のリストを絶対 ``Path`` に解決する。

    - ``None`` または空リストは ``[]`` を返す（参照画像なし）。
    - 相対パスは ``Path.cwd()`` 基準で絶対化する。
    - 存在しないパスは ``ConfigError`` を送出（呼び出し側の既存
      ``except ConfigError`` 経路に合流させる）。
    """
    if not raw_refs:
        return []
    resolved: list[Path] = []
    for raw_ref in raw_refs:
        ref_path = Path(raw_ref)
        if not ref_path.is_absolute():
            ref_path = Path.cwd() / ref_path
        if not ref_path.exists():
            raise ConfigError(f"参照画像が見つかりません: {ref_path}")
        resolved.append(ref_path)
    return resolved
