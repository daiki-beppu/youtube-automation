from __future__ import annotations

import json

from youtube_automation.commands.analytics.truth_eye import main
from youtube_automation.domains.analytics.truth_eye import VIEWPOINTS


def _draft() -> str:
    rows = ["| 観点 ID | 伸びた側 | 伸びなかった側 |", "|---|---|---|"]
    rows.extend(f"| {item.id} | winner | loser |" for item in VIEWPOINTS)
    return "\n".join(rows) + "\n## 抽象化\nprinciple\n## 再生数差への寄与順位\n1. V01\n2. V02\n3. V03\n"


def test_seal_failure_prints_missing_items_as_json(tmp_path, capsys):
    pair = tmp_path / "pair.json"
    pair.write_text(
        json.dumps(
            {
                "channel": "reference",
                "winner": {
                    "video_id": "win",
                    "title": "W",
                    "views": 10,
                    "published_at": "2026-01-01",
                    "duration": "PT1M",
                },
                "loser": {
                    "video_id": "lose",
                    "title": "L",
                    "views": 1,
                    "published_at": "2026-01-01",
                    "duration": "PT1M",
                },
            }
        ),
        encoding="utf-8",
    )
    draft = tmp_path / "draft.md"
    draft.write_text(_draft().replace("| V07 | winner | loser |\n", ""), encoding="utf-8")

    exit_code = main(["seal", "--pair", str(pair), "--sealed-draft", str(draft), "--channel-dir", str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert output == {"ok": False, "missing": ["V07"]}
    assert draft.exists()


def test_verify_cli_returns_nonzero_and_hashes_after_tamper(tmp_path, capsys):
    sealed = tmp_path / "record.sealed.md"
    sealed.write_text("changed", encoding="utf-8")
    record = tmp_path / "record.md"
    record.write_text("---\nsealed:\n  path: record.sealed.md\n  sha256: deadbeef\n---\n", encoding="utf-8")

    exit_code = main(["verify", str(record)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert output["ok"] is False
    assert output["expected"] == "deadbeef"
    assert len(output["actual"]) == 64
