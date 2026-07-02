#!/usr/bin/env python3
"""yt-thumbnail-auto-select CLI (#1370)

TTP 参照画像プール (`image_generation.gemini.reference_images.default`) の
特徴量 centroid に最も近い thumbnail 候補を採点し、`10-assets/thumbnail.jpg`
として自動確定する。`image_generation.auto_selection.enabled: true` の
チャンネルだけが対象の opt-in 機能。

Usage:
    yt-thumbnail-auto-select <collection-path> --dry-run [--json]
    yt-thumbnail-auto-select <collection-path> --apply [--force] [--json]

終了コード:
    0 : 選択成功 (dry-run の採点表示 / apply の確定完了)
    1 : 選択失敗 (候補なし・参照画像なし・適格候補なし・上書き不可 など)
    2 : 入力エラー (コレクションディレクトリ不正・auto_selection 無効 など)

Design:
- 解釈フェーズ (`main`): argparse → skill-config → 参照プール解決
- 実行フェーズ: 特徴量抽出 → 採点 → 選択 → (apply) コピー + workflow-state 記録
- 出力フェーズ (`_render_text` / `_render_json`)
- 失敗は silent fallback せず ConfigError / ValidationError で明示する (#1370)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.thumbnail_features import (
    extract_features_from_path,
    feature_centroid,
    feature_distance,
)
from youtube_automation.utils.thumbnail_references import resolve_configured_benchmark_references

SKILL_NAME = "thumbnail"

# SKILL.md「ファイル命名ルール」のテキスト付き候補と同じパターン。
_CANDIDATE_PATTERNS = ("thumbnail-v*.jpg", "thumbnail-v*.png", "thumbnail-codex-v*.png")

_TARGET_ASPECT = 16 / 9
_TARGET_FILENAME = "thumbnail.jpg"
_WORKFLOW_STATE_KEY = "thumbnail_auto_selection"
_JPEG_QUALITY = 95

_DEFAULT_MIN_WIDTH = 1280
_DEFAULT_MIN_HEIGHT = 720
_DEFAULT_ASPECT_TOLERANCE = 0.01


@dataclass(frozen=True)
class AutoSelectionSettings:
    """`image_generation.auto_selection` の解決済み設定。"""

    enabled: bool
    min_width: int
    min_height: int
    aspect_tolerance: float


@dataclass(frozen=True)
class CandidateScore:
    """1 候補分の採点結果。distance は小さいほど参照プールに近い。"""

    path: Path
    width: int
    height: int
    distance: float
    eligible: bool
    reasons: list[str]


# ---------------------------------------------------------------------------
# skill-config からの設定組み立て
# ---------------------------------------------------------------------------


def _image_generation_section(cfg: dict[str, Any]) -> dict[str, Any]:
    section = cfg.get("image_generation") or {}
    if not isinstance(section, dict):
        raise ConfigError(f"thumbnail.image_generation は mapping である必要があります: {section!r}")
    return section


def resolve_auto_selection_settings(cfg: dict[str, Any]) -> AutoSelectionSettings:
    """skill-config から `image_generation.auto_selection` を検証つきで解決する。"""
    raw = _image_generation_section(cfg).get("auto_selection") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"thumbnail.image_generation.auto_selection は mapping である必要があります: {raw!r}")

    def _positive_int(key: str, default: int) -> int:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"auto_selection.{key} は正の整数である必要があります: {value!r}")
        return value

    tolerance = raw.get("aspect_tolerance", _DEFAULT_ASPECT_TOLERANCE)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ConfigError(f"auto_selection.aspect_tolerance は 0 以上の数値である必要があります: {tolerance!r}")

    return AutoSelectionSettings(
        enabled=bool(raw.get("enabled", False)),
        min_width=_positive_int("min_width", _DEFAULT_MIN_WIDTH),
        min_height=_positive_int("min_height", _DEFAULT_MIN_HEIGHT),
        aspect_tolerance=float(tolerance),
    )


def resolve_reference_images(cfg: dict[str, Any], channel_root: Path) -> list[Path]:
    """TTP 参照画像プールを benchmark 契約つきで解決する。

    未設定・placeholder・契約違反・実ファイル欠落はすべて明示エラー。
    """
    gemini = _image_generation_section(cfg).get("gemini") or {}
    if not isinstance(gemini, dict):
        raise ConfigError(f"thumbnail.image_generation.gemini は mapping である必要があります: {gemini!r}")
    reference_images = gemini.get("reference_images") or {}
    default_value = reference_images.get("default") if isinstance(reference_images, dict) else None

    resolution = resolve_configured_benchmark_references(channel_root, default_value)
    problems = list(resolution.invalid_reasons)
    problems.extend(f"placeholder のまま未設定: {value}" for value in resolution.placeholders)
    if problems:
        raise ConfigError("reference_images.default に自動選択で使えない値があります: " + " / ".join(problems))
    if not resolution.references:
        raise ConfigError(
            "自動選択には TTP 参照画像が必須です。"
            "config/skills/thumbnail.yaml の image_generation.gemini.reference_images.default を設定してください。"
        )
    missing = [str(path) for path in resolution.references if not path.exists()]
    if missing:
        raise ConfigError(f"参照画像が見つかりません: {', '.join(missing)}")
    return resolution.references


# ---------------------------------------------------------------------------
# 候補の発見と採点
# ---------------------------------------------------------------------------


def discover_candidates(assets_dir: Path) -> list[Path]:
    """`10-assets/` からテキスト付き thumbnail 候補を列挙する (名前順)。"""
    found: set[Path] = set()
    for pattern in _CANDIDATE_PATTERNS:
        found.update(assets_dir.glob(pattern))
    return sorted(found)


def _eligibility_reasons(width: int, height: int, settings: AutoSelectionSettings) -> list[str]:
    reasons: list[str] = []
    if width < settings.min_width or height < settings.min_height:
        reasons.append(f"解像度不足: {width}x{height} (必要: {settings.min_width}x{settings.min_height} 以上)")
    aspect = width / height if height else 0.0
    if abs(aspect - _TARGET_ASPECT) > settings.aspect_tolerance:
        reasons.append(f"16:9 逸脱: aspect={aspect:.4f} (許容誤差: {settings.aspect_tolerance})")
    return reasons


def score_candidates(
    candidates: list[Path],
    centroid: dict[str, float],
    settings: AutoSelectionSettings,
) -> list[CandidateScore]:
    """候補を採点し distance 昇順 (同点は名前順) で返す。"""
    scores: list[CandidateScore] = []
    for path in candidates:
        with Image.open(path) as img:
            width, height = img.size
        distance = feature_distance(extract_features_from_path(path), centroid)
        reasons = _eligibility_reasons(width, height, settings)
        scores.append(
            CandidateScore(
                path=path,
                width=width,
                height=height,
                distance=distance,
                eligible=not reasons,
                reasons=reasons,
            )
        )
    return sorted(scores, key=lambda s: (s.distance, s.path.name))


def select_best(scores: list[CandidateScore]) -> CandidateScore:
    """適格候補の中から distance 最小の 1 件を返す。適格ゼロは明示エラー。"""
    for score in scores:
        if score.eligible:
            return score
    detail = " / ".join(f"{s.path.name}: {'; '.join(s.reasons)}" for s in scores)
    raise ValidationError(f"16:9・最小解像度を満たす適格候補がありません: {detail}")


# ---------------------------------------------------------------------------
# apply (thumbnail.jpg 確定 + workflow-state 監査ログ)
# ---------------------------------------------------------------------------


def apply_selection(best: CandidateScore, paths: CollectionPaths, *, force: bool) -> Path:
    """選択候補を `10-assets/thumbnail.jpg` として確定する。"""
    existing = paths.find_thumbnail()
    if existing is not None and not force:
        raise ValidationError(
            f"確定済みサムネイルが既に存在します: {existing} (上書きするには --force を明示してください)"
        )
    target = paths.assets_dir / _TARGET_FILENAME
    if best.path.suffix.lower() in (".jpg", ".jpeg"):
        shutil.copyfile(best.path, target)
    else:
        with Image.open(best.path) as img:
            img.convert("RGB").save(target, "JPEG", quality=_JPEG_QUALITY)
    return target


def load_workflow_state(ws_path: Path) -> dict[str, Any] | None:
    """`workflow-state.json` を検証つきで読み込む。

    ファイルが無い場合は None (コレクション初期化前の運用を許容)。
    壊れた JSON は明示エラー。apply の副作用前に呼び、部分適用状態を防ぐ。
    """
    if not ws_path.exists():
        return None
    try:
        state = json.loads(ws_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"workflow-state.json が JSON としてパースできません: {ws_path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValidationError(f"workflow-state.json の root は object である必要があります: {ws_path}")
    return state


def record_workflow_state(
    ws_path: Path,
    state: dict[str, Any],
    *,
    best: CandidateScore,
    scores: list[CandidateScore],
    reference_images: list[Path],
    channel_root: Path,
    executed_at: str,
) -> None:
    """検証済みの workflow-state に選択の監査ログを記録して書き戻す。"""
    state[_WORKFLOW_STATE_KEY] = {
        "schema_version": 1,
        "selected": best.path.name,
        "distance": round(best.distance, 4),
        "ranking": _ranking_payload(scores),
        "reference_images": [_relative_to_channel(path, channel_root) for path in reference_images],
        "executed_at": executed_at,
    }
    ws_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _relative_to_channel(path: Path, channel_root: Path) -> str:
    # 参照画像は resolve 済みパスで届く一方、channel_dir() は env の値を
    # そのまま返すため (macOS の /var → /private/var など)、両方の root で試す。
    for root in (channel_root, channel_root.resolve(strict=False)):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _ranking_payload(scores: list[CandidateScore]) -> list[dict[str, Any]]:
    return [
        {
            "candidate": score.path.name,
            "distance": round(score.distance, 4),
            "width": score.width,
            "height": score.height,
            "eligible": score.eligible,
            "reasons": score.reasons,
        }
        for score in scores
    ]


# ---------------------------------------------------------------------------
# 出力フォーマッタ
# ---------------------------------------------------------------------------


def _render_text(
    *,
    mode: str,
    scores: list[CandidateScore],
    best: CandidateScore,
    target: Path,
    reference_count: int,
    workflow_state_updated: bool | None,
) -> str:
    lines = [f"[auto-select] 候補採点結果 (参照画像 {reference_count} 枚, distance 昇順):"]
    for rank, score in enumerate(scores, start=1):
        status = "OK" if score.eligible else f"除外: {'; '.join(score.reasons)}"
        marker = " *" if score.path == best.path else "  "
        lines.append(f"{marker}{rank}. {score.path.name}  distance={score.distance:.4f}  [{status}]")
    lines.append(f"selected: {best.path.name}")
    if mode == "apply":
        lines.append(f"[APPLY] {target} に確定しました")
        lines.append(f"workflow-state 記録: {'あり' if workflow_state_updated else 'なし (workflow-state.json 不在)'}")
    else:
        lines.append(f"[DRY] --apply で {target} に確定します (ファイルは変更していません)")
    return "\n".join(lines)


def _render_json(
    *,
    mode: str,
    collection: Path,
    scores: list[CandidateScore],
    best: CandidateScore,
    target: Path,
    reference_images: list[Path],
    channel_root: Path,
    workflow_state_updated: bool | None,
) -> str:
    return json.dumps(
        {
            "mode": mode,
            "collection": str(collection),
            "selected": {
                "candidate": best.path.name,
                "path": str(best.path),
                "distance": round(best.distance, 4),
            },
            "target": str(target),
            "ranking": _ranking_payload(scores),
            "reference_images": [_relative_to_channel(path, channel_root) for path in reference_images],
            "workflow_state_updated": workflow_state_updated,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-thumbnail-auto-select",
        description=(
            "TTP 参照画像プールの特徴量 centroid に最も近い thumbnail 候補を "
            "10-assets/thumbnail.jpg として自動確定する (#1370)"
        ),
    )
    parser.add_argument("collection", type=Path, help="コレクションディレクトリ (10-assets/ を含む)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="採点と選択結果の表示のみ (ファイルは変更しない)")
    mode.add_argument("--apply", action="store_true", help="選択候補を 10-assets/thumbnail.jpg に確定する")
    parser.add_argument(
        "--force",
        action="store_true",
        help="確定済み thumbnail.jpg / thumbnail.png があっても上書きする (--apply 時のみ有効)",
    )
    parser.add_argument("--json", action="store_true", help="結果を JSON で標準出力に書き出す")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    collection = args.collection.resolve()
    paths = CollectionPaths(collection)
    if not collection.is_dir() or not paths.assets_dir.is_dir():
        print(f"error: コレクションディレクトリではありません (10-assets/ が必要): {collection}", file=sys.stderr)
        return 2

    try:
        cfg = load_skill_config(SKILL_NAME)
        settings = resolve_auto_selection_settings(cfg)
        if not settings.enabled:
            print(
                "error: image_generation.auto_selection.enabled が false のため自動選択は使えません。"
                "従来どおり手動承認で確定するか、config/skills/thumbnail.yaml で opt-in してください。",
                file=sys.stderr,
            )
            return 2

        from youtube_automation.utils.config import channel_dir

        channel_root = channel_dir()
        reference_images = resolve_reference_images(cfg, channel_root)
        centroid = feature_centroid([extract_features_from_path(path) for path in reference_images])

        candidates = discover_candidates(paths.assets_dir)
        if not candidates:
            patterns = ", ".join(_CANDIDATE_PATTERNS)
            raise ValidationError(f"thumbnail 候補が見つかりません: {paths.assets_dir} (対象: {patterns})")

        scores = score_candidates(candidates, centroid, settings)
        best = select_best(scores)

        target = paths.assets_dir / _TARGET_FILENAME
        workflow_state_updated: bool | None = None
        if args.apply:
            # 壊れた workflow-state はコピー前に検出し、部分適用状態を残さない
            state = load_workflow_state(paths.workflow_state_path)
            target = apply_selection(best, paths, force=args.force)
            if state is not None:
                record_workflow_state(
                    paths.workflow_state_path,
                    state,
                    best=best,
                    scores=scores,
                    reference_images=reference_images,
                    channel_root=channel_root,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
            workflow_state_updated = state is not None
    except (ConfigError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    mode = "apply" if args.apply else "dry-run"
    if args.json:
        print(
            _render_json(
                mode=mode,
                collection=collection,
                scores=scores,
                best=best,
                target=target,
                reference_images=reference_images,
                channel_root=channel_root,
                workflow_state_updated=workflow_state_updated,
            )
        )
    else:
        print(
            _render_text(
                mode=mode,
                scores=scores,
                best=best,
                target=target,
                reference_count=len(reference_images),
                workflow_state_updated=workflow_state_updated,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
