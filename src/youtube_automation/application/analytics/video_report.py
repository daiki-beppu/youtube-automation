"""動画解析の audit report を構造化運用文書として公開する。"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.application.documents.migration import (
    DocumentWriteResult,
    MarkdownMigrationDecision,
    write_operational_document,
)
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.media.video_analyzer import VIDEO_ANALYSIS_DIRNAME, VideoAnalysisReport


def write_video_analysis_report(
    *,
    reports_dir: Path,
    slug: str,
    results: list[dict[str, object]],
    failures: list[dict[str, object]],
    migration_decision: MarkdownMigrationDecision,
) -> tuple[Path, DocumentWriteResult]:
    """slug 単位の監査 JSON 正本と同 basename HTML を一操作で保存する。"""
    out_dir = reports_dir / VIDEO_ANALYSIS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.json"
    document = VideoAnalysisReport.document(slug=slug, results=results, failures=failures)
    state = write_operational_document(
        out_path,
        RepositorySchema.AUDIT_REPORT,
        lambda: document,
        migration_decision,
    )
    return out_path, state
