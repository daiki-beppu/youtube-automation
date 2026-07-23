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
from collections.abc import Sequence
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


def confirm_cost(model: str, cost_per_image: float | None) -> bool:
    """コスト見積もりを表示してユーザー確認を取る。

    `cost_per_image=None` は skill-config に `cost_per_image_usd` が指定されておらず、
    事前見積もりが出せない状態。その場合も y/N 確認自体は維持し、表示は「不明」とする。
    """
    print()
    print("=== Image Generation ===")
    print(f"モデル:     {model}")
    print("生成枚数:   1 image")
    if cost_per_image is None:
        print("推定コスト: 不明 (skill-config の cost_per_image_usd 未設定)")
    else:
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
    reference_count: int = 0,
) -> dict | None:
    """画像生成 1 件分を cost_tracker 経由で記録する。"""
    return cost_tracker.log_generation(
        "image",
        model=model,
        quantity=1,
        unit="image",
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
) -> dict[str, Any]:
    """``apply_composition_rules`` に渡す構図ルールソース dict を解決する。

    ``skill_cfg["image_generation"][provider]`` を返す。
    """
    section = skill_cfg.get("image_generation", {})
    if not isinstance(section, dict):
        return {}
    source = section.get(provider, {})
    return source if isinstance(source, dict) else {}


def resolve_cost_per_image(
    skill_cfg: dict[str, Any],
    provider: str,
) -> float | None:
    """skill-config の ``cost_per_image_usd`` を尊重して 1 枚あたり単価を決定する。

    ``skill_cfg["image_generation"][provider]["cost_per_image_usd"]`` を返す。
    """
    custom = None
    image_gen = skill_cfg.get("image_generation")
    if isinstance(image_gen, dict):
        provider_section = image_gen.get(provider)
        if isinstance(provider_section, dict):
            custom = provider_section.get("cost_per_image_usd")
    if custom is None:
        return None
    return float(custom)


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


def select_reference(refs: list[Path], attempt: int, rotate: bool) -> Path:
    """attempt インデックスに応じて参照画像を 1 枚選択する。

    ``rotate=True`` かつ ``len(refs) > 1`` のときは ``refs[attempt % len(refs)]``、
    それ以外は ``refs[0]`` を返す。``refs`` が空のときは ``ValueError``。
    """
    if not refs:
        raise ValueError("参照画像リストが空です")
    if rotate and len(refs) > 1:
        return refs[attempt % len(refs)]
    return refs[0]


def validate_single_step_references(skill_cfg: dict[str, Any]) -> None:
    """``generation_mode == "single_step"`` 時に参照画像未設定を検知して ``ConfigError`` を送出する。

    判定:
      ``image_generation.gemini.generation_mode`` が ``"single_step"`` のとき
      ``image_generation.gemini.reference_images.default`` が未設定・空文字列・空リスト
      のいずれかなら ``ConfigError`` を送出する。
      他モード（``two_phase`` 等）では何もしない。
    """
    image_gen = skill_cfg.get("image_generation")
    if not isinstance(image_gen, dict):
        return
    gemini = image_gen.get("gemini")
    if not isinstance(gemini, dict):
        return
    if gemini.get("generation_mode") != "single_step":
        return

    reference_images = gemini.get("reference_images")
    default = None
    if isinstance(reference_images, dict):
        default = reference_images.get("default")

    is_empty_str = isinstance(default, str) and not default.strip()
    is_empty_list = isinstance(default, list) and not default
    if default is None or is_empty_str or is_empty_list:
        raise ConfigError(
            "single_step モードには image_generation.gemini.reference_images.default の設定が必須です"
            "（文字列 1 件、または list で複数件指定）。"
            "ベンチマークサムネを data/thumbnail_compare/benchmark/ 等に配置し、"
            "config/skills/thumbnail.yaml で参照してください。"
        )

def validate_single_step_request_references(generation_mode: object, references: Sequence[Path]) -> None:
    """``single_step`` 実行 request に参照画像が含まれることを検証する。"""
    if generation_mode != "single_step":
        return
    if references:
        return
    raise ConfigError(
        "single_step モードでは --reference の指定が必須です。"
        "skill-config の image_generation.gemini.reference_images.default を CLI へ展開し、"
        "--reference <path> で参照画像を 1 件以上渡してください。"
    )


def resolve_forbid_keywords(skill_cfg: dict[str, object]) -> list[str]:
    """``image_generation.gemini.forbid_keywords`` を ``list[str]`` に正規化して返す。

    未設定・空リストは ``[]``（no-op）。list 以外や非文字列要素は ``ConfigError``。
    空白のみの要素は除外する。キーは gemini namespace に置くが、検査自体は
    provider 非依存（Gemini / OpenAI / gemini_cli / codex の全入口で共通）。
    """
    image_gen = skill_cfg.get("image_generation")
    if not isinstance(image_gen, dict):
        return []
    gemini = image_gen.get("gemini")
    if not isinstance(gemini, dict):
        return []
    raw = gemini.get("forbid_keywords")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("image_generation.gemini.forbid_keywords は list[str] で指定してください")
    keywords: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ConfigError(f"image_generation.gemini.forbid_keywords の要素は文字列で指定してください: {item!r}")
        stripped = item.strip()
        if stripped:
            keywords.append(stripped)
    return keywords


def find_forbidden_keywords(prompt: str, keywords: list[str]) -> list[str]:
    """プロンプトに含まれる NG キーワードを検出して返す（大小文字無視の部分一致）。"""
    lower = prompt.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def validate_forbid_keywords(prompt: str, skill_cfg: dict[str, object]) -> None:
    """最終プロンプトが forbid_keywords にヒットしたら ``ConfigError`` を送出する。

    workflow-state.json::planning.music.* 等の他ドメイン値がチャンネル規約違反の
    まま画像 prompt に転写される事故（#1664）を生成 API 呼び出し前に止める。
    forbid_keywords 未設定時は何もしない（no-op）。
    """
    hits = find_forbidden_keywords(prompt, resolve_forbid_keywords(skill_cfg))
    if hits:
        raise ConfigError(
            "プロンプトが forbid_keywords に一致したため生成を中止しました: "
            + ", ".join(hits)
            + "（config/skills/thumbnail.yaml の image_generation.gemini.forbid_keywords を確認し、"
            "プロンプトから該当表現を除いて再実行してください）"
        )
