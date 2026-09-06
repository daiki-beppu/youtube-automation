"""Truth Eye 訓練記録と封印分析のドメイン規則。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from youtube_automation.core.errors import ValidationError


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

_VIDEO_FIELDS = ("video_id", "title", "views", "published_at", "duration")
_SAFE_STEM_PART = re.compile(r"^[A-Za-z0-9._-]+$")


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


def validate_sealed_draft(text: str) -> list[str]:
    """封印分析の固定フォーマットについて欠落項目を返す。"""
    missing: list[str] = []
    lines = text.splitlines()
    for viewpoint in VIEWPOINTS:
        matching = [line for line in lines if re.match(rf"^\|\s*{viewpoint.id}\s*\|", line)]
        if not matching:
            missing.append(viewpoint.id)
            continue
        cells = [cell.strip() for cell in matching[0].strip().strip("|").split("|")]
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
        "schema_version": 1,
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


def _render_record(metadata: dict) -> str:
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    rows = ["| 観点 ID | 観点名 | 伸びた側 | 伸びなかった側 |", "|---|---|---|---|"]
    rows.extend(f"| {item.id} | {item.name} |  |  |" for item in VIEWPOINTS if item.required)
    phases = ["## Phase 0", "## Phase 1\n\n" + "\n".join(rows)]
    phases.extend(f"## Phase {number}" for number in range(2, 6))
    return f"---\n{frontmatter}\n---\n\n" + "\n\n".join(phases) + "\n"


def _read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
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
