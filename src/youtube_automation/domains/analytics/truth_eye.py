"""Truth Eye 訓練記録と封印分析のドメイン規則。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from statistics import median

import yaml

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.analytics.benchmark import is_live_benchmark_video, is_short_benchmark_video


@dataclass(frozen=True)
class Viewpoint:
    id: str
    name: str
    required: bool


VIEWPOINTS: tuple[Viewpoint, ...] = (
    Viewpoint("V01", "主役と占有率", True),
    Viewpoint("V02", "構図・視線の流れ", True),
    Viewpoint("V03", "配色", True),
    Viewpoint("V04", "文字", True),
    Viewpoint("V05", "表情・感情", True),
    Viewpoint("V06", "縮小耐性", True),
    Viewpoint("V07", "小道具・状況", False),
    Viewpoint("V08", "季節感・時間帯", False),
    Viewpoint("V09", "余白", False),
    Viewpoint("V10", "シリーズ性", False),
    Viewpoint("V11", "サムネ外の要因", False),
    Viewpoint("V12", "刺激している欲求", False),
)

TRAINING_RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PairThresholds:
    gap_days: tuple[int, int, int] = (5, 14, 30)
    maturity_days: int = 14
    min_ratio: float = 3
    min_loser_views: int = 100
    min_pool_size: int = 10
    max_rejections: int = 3


PAIR_THRESHOLDS = PairThresholds()

_STAGE_POPULATION = "母集団"
_STAGE_MIN_POOL = "最小プール通過"
_STAGE_UNSEEN = "既出除外後"
_STAGE_MISSING_IMAGE = "画像欠落除外後"
_STAGE_REJECTED = "却下後"
_GAP_STAGE_SUFFIX = " 日段"

_POPULATION_ADVICE = "母集団がありません。channel-research --benchmark で benchmark を収集してください"
_MIN_POOL_ADVICE = (
    "走査プールが最小本数に届く競合がありません。channel-research --benchmark で走査本数を増やしてください"
)
_GAP_ADVICE = "日差の近いペアがありません。channel-research --benchmark で benchmark を更新するか競合を追加してください"
_UNSEEN_ADVICE = (
    "候補が過去の訓練記録と重複しています。benchmark に競合を追加するか、兄弟チャンネル連携を増やしてください"
)
_MISSING_IMAGE_ADVICE = (
    "サムネイルが未取得です。対象リポジトリで uv run yt-benchmark-collect --force -y を実行してください"
)
_REJECTED_ADVICE = "却下で候補が尽きました。benchmark に競合を追加するか、次のセッションで再実行してください"
_BOTTLENECK_ADVICE = {
    _STAGE_MIN_POOL: _MIN_POOL_ADVICE,
    _STAGE_UNSEEN: _UNSEEN_ADVICE,
    _STAGE_MISSING_IMAGE: _MISSING_IMAGE_ADVICE,
    _STAGE_REJECTED: _REJECTED_ADVICE,
}

_VIDEO_FIELDS = ("video_id", "title", "views", "published_at", "duration")
_SAFE_STEM_PART = re.compile(r"^[A-Za-z0-9._-]+$")
_VIEWPOINT_ID = re.compile(r"V(?:0[1-9]|1[0-2])")


@dataclass(frozen=True)
class SealResult:
    record: Path
    sealed: Path
    sha256: str
    sealed_at: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    expected: str
    actual: str


@dataclass(frozen=True)
class IncompleteTrainingRecord:
    record: Path
    resume_phase: int
    phase2_turns: int


@dataclass(frozen=True)
class TrainingStatus:
    incomplete: tuple[IncompleteTrainingRecord, ...]
    last_next_try: dict | None
    recurring_ai_only_viewpoints: tuple[dict, ...]
    completed_count: int
    incomplete_count: int


@dataclass(frozen=True)
class TrainingRecord:
    path: Path
    metadata: dict
    phases: tuple[str, ...]


def validate_sealed_draft(text: str) -> list[str]:
    """封印分析の固定フォーマットについて欠落項目を返す。"""
    missing: list[str] = []
    rows = _viewpoint_rows(text)
    for viewpoint in VIEWPOINTS:
        cells = next((row for row in rows if row[0] == viewpoint.id), None)
        if cells is None:
            missing.append(viewpoint.id)
            continue
        if len(cells) < 3 or not cells[1]:
            missing.append(f"{viewpoint.id}:winner")
        if len(cells) < 3 or not cells[2]:
            missing.append(f"{viewpoint.id}:loser")

    abstraction = _section_body(text, "抽象化")
    if not abstraction:
        missing.append("abstraction")
    contribution = _section_body(text, "再生数差への寄与順位")
    ranked_ids = re.findall(r"\bV(?:0[1-9]|1[0-2])\b", contribution)
    if len(ranked_ids) < 3 or len(set(ranked_ids[:3])) < 3:
        missing.append("contribution_rank_top_3")
    return missing


def seal_training_record(
    pair: dict,
    sealed_draft: Path,
    channel_dir: Path,
    *,
    now: datetime | None = None,
) -> SealResult:
    """検証済み下書きを封印し、人間が記入する訓練記録を生成する。"""
    pair_metadata = _validate_pair(pair)
    draft_text = sealed_draft.read_text(encoding="utf-8")
    missing = validate_sealed_draft(draft_text)
    if missing:
        raise ValidationError(f"封印分析の必須項目が不足しています: {', '.join(missing)}")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    channel = pair_metadata["channel"]
    winner_id = pair_metadata["winner"]["video_id"]
    stem = f"{timestamp:%Y%m%d}-thumbnail-{channel}-{winner_id}"
    training_dir = channel_dir / "docs" / "benchmarks" / "training"
    record = training_dir / f"{stem}.md"
    sealed = training_dir / f"{stem}.sealed.md"
    if record.exists() or sealed.exists():
        raise ValidationError(f"同名の訓練記録または封印分析が既に存在します: {stem}")

    digest = hashlib.sha256(sealed_draft.read_bytes()).hexdigest()
    sealed_at = timestamp.isoformat().replace("+00:00", "Z")
    metadata = {
        "schema_version": TRAINING_RECORD_SCHEMA_VERSION,
        "menu": "thumbnail",
        "channel": channel,
        "pair": {side: pair_metadata[side] for side in ("winner", "loser")},
        "sealed": {"path": sealed.name, "sha256": digest, "sealed_at": sealed_at},
        "next_try": None,
    }
    training_dir.mkdir(parents=True, exist_ok=True)
    sealed_draft.replace(sealed)
    record.write_text(_render_record(metadata), encoding="utf-8")
    return SealResult(record, sealed, digest, sealed_at)


def verify_training_record(record: Path) -> VerificationResult:
    """記録 frontmatter と隣接する封印分析の sha256 を照合する。"""
    metadata = _read_frontmatter(record)
    sealed = metadata.get("sealed")
    if not isinstance(sealed, dict):
        raise ValidationError("frontmatter.sealed が object ではありません")
    expected = sealed.get("sha256")
    relative_path = sealed.get("path")
    if not isinstance(expected, str) or not expected:
        raise ValidationError("frontmatter.sealed.sha256 がありません")
    if not isinstance(relative_path, str) or Path(relative_path).name != relative_path:
        raise ValidationError("frontmatter.sealed.path は同じディレクトリのファイル名で指定してください")
    actual = hashlib.sha256((record.parent / relative_path).read_bytes()).hexdigest()
    return VerificationResult(expected == actual, expected, actual)


def collect_training_status(channel_dir: Path) -> TrainingStatus:
    """チャンネル内の訓練記録から再開状態と成長トラッキングを集計する。"""
    training_dir = channel_dir / "docs" / "benchmarks" / "training"
    paths = (
        sorted(path for path in training_dir.glob("*.md") if not path.name.endswith(".sealed.md"))
        if training_dir.is_dir()
        else []
    )
    records = [read_training_record(path) for path in paths]
    completed = [record for record in records if record.metadata.get("next_try") is not None]
    incomplete_records = [record for record in records if record.metadata.get("next_try") is None]
    incomplete = tuple(
        IncompleteTrainingRecord(
            record=record.path,
            resume_phase=_resume_phase(record.phases),
            phase2_turns=_phase_two_turns(record.phases[2]),
        )
        for record in incomplete_records
    )

    latest = completed[-1] if completed else None
    last_next_try = latest.metadata["next_try"] if latest is not None else None
    counts: Counter[str] = Counter()
    for record in completed[-5:]:
        counts.update(set(_ai_only_viewpoint_ids(record.phases[4])))
    names = {viewpoint.id: viewpoint.name for viewpoint in VIEWPOINTS}
    recurring = tuple(
        {"viewpoint_id": viewpoint_id, "name": names[viewpoint_id], "count": counts[viewpoint_id]}
        for viewpoint_id in (viewpoint.id for viewpoint in VIEWPOINTS)
        if counts[viewpoint_id] >= 2
    )
    return TrainingStatus(incomplete, last_next_try, recurring, len(completed), len(incomplete))


def read_training_record(path: Path) -> TrainingRecord:
    """訓練記録の frontmatter と Phase 0〜5 を読み戻す。"""
    text = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(text)
    if metadata.get("schema_version") != TRAINING_RECORD_SCHEMA_VERSION:
        raise ConfigError(f"未対応の訓練記録 schema_version です: {metadata.get('schema_version')}")
    phases = tuple(_section_body(text, f"Phase {number}") for number in range(6))
    return TrainingRecord(path, metadata, phases)


def select_pair_candidates(
    competitors: list[dict],
    used_video_ids: set[str],
    rejected_video_ids: tuple[str, ...],
    today: date,
) -> dict:
    """走査済み競合群から固定閾値に従って訓練ペア候補を選ぶ。"""
    eligible_competitors = _eligible_competitors(competitors)
    pairs = [
        pair
        for competitor, pool, pool_median in eligible_competitors
        for pair in _competitor_pairs(competitor, pool, pool_median, today)
    ]
    unseen_pairs = [pair for pair in pairs if _pair_is_unseen(pair, used_video_ids)]
    selected_tier = _selected_gap_tier(unseen_pairs)
    unseen = [pair for pair in unseen_pairs if pair["reason"]["gap_tier"] == selected_tier]
    with_images = [pair for pair in unseen if _pair_images_exist(pair)]
    final = _exclude_rejected(with_images, rejected_video_ids)
    final.sort(key=lambda pair: (pair["reason"]["past_sessions"], -pair["reason"]["ratio"]))
    funnel_tier = selected_tier if selected_tier is not None else _selected_gap_tier(pairs)
    funnel = _pair_funnel(competitors, eligible_competitors, pairs, funnel_tier, unseen, with_images, final)
    return {"candidates": final, "funnel": funnel, "bottleneck": _bottleneck(funnel), "warnings": []}


def _eligible_competitors(competitors: list[dict]) -> list[tuple[dict, list[dict], float]]:
    eligible_competitors: list[tuple[dict, list[dict], float]] = []
    for competitor in competitors:
        pool = [
            video
            for video in competitor["videos"]
            if not is_live_benchmark_video(video) and not is_short_benchmark_video(video)
        ]
        if len(pool) >= PAIR_THRESHOLDS.min_pool_size:
            eligible_competitors.append((competitor, pool, float(median(int(video["views"]) for video in pool))))
    return eligible_competitors


def _competitor_pairs(competitor: dict, pool: list[dict], pool_median: float, today: date) -> list[dict]:
    per_winner: dict[str, dict] = {}
    for first_index, first in enumerate(pool):
        for second in pool[first_index + 1 :]:
            candidate = _candidate_for_video_pair(competitor, first, second, pool_median, today)
            if candidate is None:
                continue
            winner_id = str(candidate["winner"]["video_id"])
            current = per_winner.get(winner_id)
            candidate_rank = (candidate["reason"]["day_gap"], -candidate["reason"]["ratio"])
            current_rank = None if current is None else (current["reason"]["day_gap"], -current["reason"]["ratio"])
            if current_rank is None or candidate_rank < current_rank:
                per_winner[winner_id] = candidate
    return list(per_winner.values())


def _candidate_for_video_pair(
    competitor: dict, first: dict, second: dict, pool_median: float, today: date
) -> dict | None:
    winner, loser = sorted((first, second), key=lambda video: int(video["views"]), reverse=True)
    if (today - max(_published_date(winner), _published_date(loser))).days < PAIR_THRESHOLDS.maturity_days:
        return None
    loser_views = int(loser["views"])
    winner_views = int(winner["views"])
    if loser_views < PAIR_THRESHOLDS.min_loser_views:
        return None
    ratio = winner_views / loser_views
    if ratio < PAIR_THRESHOLDS.min_ratio or winner_views < pool_median or loser_views > pool_median:
        return None
    day_gap = abs((_published_date(winner) - _published_date(loser)).days)
    tier = next((tier for tier in PAIR_THRESHOLDS.gap_days if day_gap <= tier), None)
    return None if tier is None else _pair_payload(competitor, winner, loser, day_gap, tier, ratio, pool_median)


def _selected_gap_tier(pairs: list[dict]) -> int | None:
    return next(
        (tier for tier in PAIR_THRESHOLDS.gap_days if any(pair["reason"]["gap_tier"] == tier for pair in pairs)),
        None,
    )


def _pair_is_unseen(pair: dict, used_video_ids: set[str]) -> bool:
    return pair["winner"]["video_id"] not in used_video_ids and pair["loser"]["video_id"] not in used_video_ids


def _pair_images_exist(pair: dict) -> bool:
    return Path(pair["winner"]["thumbnail_path"]).is_file() and Path(pair["loser"]["thumbnail_path"]).is_file()


def _exclude_rejected(pairs: list[dict], rejected_video_ids: tuple[str, ...]) -> list[dict]:
    if len(rejected_video_ids) >= PAIR_THRESHOLDS.max_rejections:
        return []
    rejected = set(rejected_video_ids)
    return [pair for pair in pairs if pair["winner"]["video_id"] not in rejected]


def _pair_funnel(
    competitors: list[dict],
    eligible_competitors: list[tuple[dict, list[dict], float]],
    pairs: list[dict],
    selected_tier: int | None,
    unseen: list[dict],
    with_images: list[dict],
    final: list[dict],
) -> list[dict]:
    gap_funnel = [
        {"stage": f"{tier}{_GAP_STAGE_SUFFIX}", "count": sum(pair["reason"]["gap_tier"] == tier for pair in pairs)}
        for tier in PAIR_THRESHOLDS.gap_days
        if selected_tier is None or tier <= selected_tier
    ]
    return [
        {"stage": _STAGE_POPULATION, "count": len(competitors)},
        {"stage": _STAGE_MIN_POOL, "count": len(eligible_competitors)},
        *gap_funnel,
        {"stage": _STAGE_UNSEEN, "count": len(unseen)},
        {"stage": _STAGE_MISSING_IMAGE, "count": len(with_images)},
        {"stage": _STAGE_REJECTED, "count": len(final)},
    ]


def _pair_payload(
    competitor: dict,
    winner: dict,
    loser: dict,
    day_gap: int,
    tier: int,
    ratio: float,
    pool_median: float,
) -> dict:
    def video_payload(video: dict) -> dict:
        return {
            "video_id": video["video_id"],
            "title": video["title"],
            "views": int(video["views"]),
            "published_at": video["published_at"],
            "duration": video["duration_iso"],
            "thumbnail_path": str(
                (Path(competitor["thumbnails_dir"]) / f"{competitor['slug']}_{video['video_id']}.jpg").resolve()
            ),
        }

    return {
        "competitor": {key: competitor[key] for key in ("slug", "name", "id", "source")},
        "winner": video_payload(winner),
        "loser": video_payload(loser),
        "reason": {
            "day_gap": day_gap,
            "gap_tier": tier,
            "ratio": round(ratio, 1),
            "pool_median": pool_median,
            "past_sessions": int(competitor.get("past_sessions", 0)),
        },
    }


def _published_date(video: dict) -> date:
    return datetime.strptime(str(video["published_at"])[:10], "%Y-%m-%d").date()


def _bottleneck(funnel: list[dict]) -> dict:
    drops = [(before["count"] - after["count"], after["stage"]) for before, after in pairwise(funnel)]
    stage = max(drops, key=lambda drop: drop[0], default=(0, _STAGE_POPULATION))[1]
    return {"stage": stage, "advice": _bottleneck_advice(stage)}


def _bottleneck_advice(stage: str) -> str:
    if stage.endswith(_GAP_STAGE_SUFFIX):
        return _GAP_ADVICE
    return _BOTTLENECK_ADVICE.get(stage, _POPULATION_ADVICE)


def _validate_pair(pair: dict) -> dict:
    if not isinstance(pair, dict):
        raise ValidationError("pair JSON は object で指定してください")
    channel = pair.get("channel")
    if not isinstance(channel, str) or not _SAFE_STEM_PART.fullmatch(channel):
        raise ValidationError("channel はファイル名に使える競合 slug で指定してください")
    normalized: dict = {"channel": channel}
    for side in ("winner", "loser"):
        video = pair.get(side)
        if not isinstance(video, dict):
            raise ValidationError(f"{side} は object で指定してください")
        absent = [field for field in _VIDEO_FIELDS if field not in video]
        if absent:
            raise ValidationError(f"{side} の必須項目が不足しています: {', '.join(absent)}")
        video_id = video["video_id"]
        if not isinstance(video_id, str) or not _SAFE_STEM_PART.fullmatch(video_id):
            raise ValidationError(f"{side}.video_id はファイル名に使える値で指定してください")
        normalized[side] = {field: video[field] for field in _VIDEO_FIELDS}
    return normalized


def _section_body(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _viewpoint_rows(text: str) -> list[list[str]]:
    """先頭セルが観点 ID の Markdown テーブル行を、セル配列にして返す。"""
    return [
        cells
        for cells in (
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in text.splitlines()
            if line.lstrip().startswith("|")
        )
        if _VIEWPOINT_ID.fullmatch(cells[0])
    ]


def _resume_phase(phases: tuple[str, ...]) -> int:
    for number, body in enumerate(phases):
        if not _phase_has_content(number, body):
            return number
    return 5


def _phase_has_content(number: int, body: str) -> bool:
    """Phase 1 は空欄のままの照合表を未記入として扱い、他の Phase は本文の有無で判定する。"""
    if number != 1:
        return bool(body.strip())
    rows = _viewpoint_rows(body)
    if not rows:
        return bool(body.strip())
    # Phase 1 の列は 観点 ID | 観点名 | 伸びた側 | 伸びなかった側。
    return any(len(cells) >= 4 and (cells[2] or cells[3]) for cells in rows)


def _phase_two_turns(body: str) -> int:
    """Phase 2 の回答見出し（`A:` / `A1:` / `回答:`）を数え、往復数とする。

    見出しの書式は skill 側テンプレート（#4990）が正本なので、テンプレート確定時に一致を確認する。
    """
    return len(re.findall(r"^(?:[-*]\s*)?(?:\*\*)?(?:A\d*|回答)(?:\*\*)?\s*[:：]", body, re.MULTILINE))


def _ai_only_viewpoint_ids(body: str) -> tuple[str, ...]:
    """Phase 4 照合表（観点 ID | 区分 | 人間の記述 | AI の記述）から「AI だけ」の観点 ID を返す。"""
    return tuple(cells[0] for cells in _viewpoint_rows(body) if len(cells) >= 4 and cells[1] == "AI だけ")


def _render_record(metadata: dict) -> str:
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    rows = ["| 観点 ID | 観点名 | 伸びた側 | 伸びなかった側 |", "|---|---|---|---|"]
    rows.extend(f"| {item.id} | {item.name} |  |  |" for item in VIEWPOINTS if item.required)
    phases = ["## Phase 0", "## Phase 1\n\n" + "\n".join(rows)]
    phases.extend(f"## Phase {number}" for number in range(2, 6))
    return f"---\n{frontmatter}\n---\n\n" + "\n\n".join(phases) + "\n"


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return _parse_frontmatter(text)


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValidationError("訓練記録に YAML frontmatter がありません")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValidationError("訓練記録の YAML frontmatter が閉じられていません")
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as error:
        raise ValidationError(f"訓練記録の YAML frontmatter が不正です: {error}") from error
    if not isinstance(metadata, dict):
        raise ValidationError("訓練記録の YAML frontmatter は object で指定してください")
    return metadata
