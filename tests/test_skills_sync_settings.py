from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.cli import skills_sync


def _template(root: Path) -> None:
    claude = root / ".claude"
    claude.mkdir()
    (claude / "settings.template.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Agent", "Bash(uv run yt-upload-auto*)"], "deny": ["Read(.env)"]},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [{"type": "command", "command": "block-secrets"}],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _run(root: Path, target: Path, monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: root)
    return skills_sync.main(["sync", "--asset", "settings", "--target", str(target), *extra])


def test_settings_merge_preserves_local_values_and_accepts_hooks(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "downstream" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "env": {"LOCAL": "1"},
                "permissions": {"allow": ["LocalRule"], "deny": []},
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "local"}]}]},
            }
        ),
        encoding="utf-8",
    )

    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["env"] == {"LOCAL": "1"}
    assert merged["permissions"]["allow"] == ["LocalRule", "Agent", "Bash(uv run yt-upload-auto*)"]
    assert merged["permissions"]["deny"] == ["Read(.env)"]
    assert len(merged["hooks"]["PreToolUse"]) == 2

    before = target.read_bytes()
    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 0
    assert target.read_bytes() == before


def test_settings_noninteractive_skips_hooks_but_merges_permissions(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    assert _run(tmp_path, target, monkeypatch) == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["permissions"]["allow"]
    assert "hooks" not in merged


def test_settings_invalid_target_is_not_overwritten(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    target.write_text("{broken", encoding="utf-8")
    before = target.read_bytes()
    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 1
    assert target.read_bytes() == before


def test_dev_only_skills_are_listed_but_not_distributed(tmp_path, monkeypatch, capsys) -> None:
    skills = tmp_path / ".claude" / "skills"
    for name in ("normal", "automation-release", "shadcn"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)

    assert skills_sync.bundled_skill_names() == ["normal"]
    assert skills_sync.main(["list", "--asset", "skills"]) == 0
    output = capsys.readouterr().out
    assert "automation-release (開発専用・downstream 配布対象外)" in output
    assert "shadcn (開発専用・downstream 配布対象外)" in output
