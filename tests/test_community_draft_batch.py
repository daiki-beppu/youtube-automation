from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude/skills/community-draft/references/generate_batch.py"
SKILL = REPO_ROOT / ".claude/skills/community-draft/SKILL.md"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _channel(tmp_path: Path, *, publish_target_at: str | None) -> tuple[Path, Path]:
    channel = tmp_path / "channel"
    shutil.copytree(REPO_ROOT / "tests/fixtures/sample_channel/config", channel / "config")
    _write_json(
        channel / "config/channel/community-draft.json",
        {
            "community_draft": {
                "variables": {"custom_message": "通知をオンにしてお待ちください。"},
                "posts": [
                    {
                        "label": "公開前ティーザー",
                        "template": "🎵 {title} は {date} 公開！\n{custom_message}",
                        "schedule_offset_days": -1,
                        "schedule_time": "18:00",
                        "image": "main.png",
                    }
                ],
            }
        },
    )
    collection = channel / "collections/planning/20260625-rain"
    planning = {"final_title": "Rain Walk", "publish_target_at": publish_target_at}
    _write_json(collection / "workflow-state.json", {"planning": planning})
    (collection / "main.png").write_bytes(b"fixture")
    return channel, collection


def _run(channel: Path, collection: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--batch", "--collection", str(collection)],
        cwd=REPO_ROOT,
        env=os.environ | {"CHANNEL_DIR": str(channel)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_generate_batch_renders_json_with_timezone_schedule(tmp_path: Path) -> None:
    channel, collection = _channel(tmp_path, publish_target_at="2026-06-25T08:00:00+09:00")

    result = _run(channel, collection)

    assert result.returncode == 0, result.stderr
    output_path = collection / "30-promo/community-posts.json"
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "posts": [
            {
                "text": "🎵 Rain Walk は 2026-06-25 公開！\n通知をオンにしてお待ちください。",
                "scheduled_at": "2026-06-24T18:00:00+09:00",
                "image_path": "collections/planning/20260625-rain/main.png",
                "visibility": "public",
            }
        ]
    }


def test_generate_batch_fails_loudly_without_publish_target(tmp_path: Path) -> None:
    channel, collection = _channel(tmp_path, publish_target_at=None)

    result = _run(channel, collection)

    assert result.returncode != 0
    assert "planning.publish_target_at" in result.stderr
    assert not (collection / "30-promo/community-posts.json").exists()


def test_active_community_docs_have_no_legacy_type_markdown_or_clipboard_flow() -> None:
    active_paths = (
        SKILL,
        REPO_ROOT / ".claude/skills/collection-ideate/SKILL.md",
        REPO_ROOT / "src/youtube_automation/scripts/vote_log.py",
        REPO_ROOT / "src/youtube_automation/utils/weekly_vote_log.py",
        REPO_ROOT / "src/youtube_automation/utils/schemas/weekly_vote_log.schema.json",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in active_paths)

    for legacy in ("--type", "community-post-draft.md", "pbcopy"):
        assert legacy not in text
    assert "--batch" in text
    assert "community-posts.json" in text
