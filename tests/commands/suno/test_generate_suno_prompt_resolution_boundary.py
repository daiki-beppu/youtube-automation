from pathlib import Path

import yaml

from youtube_automation.commands.suno import generate_suno_prompts
from youtube_automation.domains.suno import prompt_resolution


def test_markdown_and_json_paths_preserve_two_resolution_calls(monkeypatch, tmp_path: Path):
    channel_dir = tmp_path / "channel"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(
        yaml.safe_dump(
            {
                "title": "Focus Set",
                "mode": "instrumental",
                "tracks": 2,
                "patterns": [
                    {
                        "name_jp": "集中",
                        "name_en": "Focus",
                        "tempo": "slow",
                        "scenes": ["soft piano and brushed drums"],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    real_resolve_from_path = prompt_resolution.resolve_from_path
    resolved_paths: list[Path] = []

    def resolve_from_path(path: Path, **loaders) -> prompt_resolution.ResolvedPrompts:
        resolved_paths.append(path)
        return real_resolve_from_path(path, **loaders)

    monkeypatch.setattr(prompt_resolution, "resolve_from_path", resolve_from_path)

    entries = generate_suno_prompts.build_prompt_entries(patterns_path)
    markdown = generate_suno_prompts.generate(patterns_path)

    assert resolved_paths == [patterns_path, patterns_path]
    assert entries[0]["name"] == "集中 — Focus"
    assert "### 集中 — Focus" in markdown


def test_legacy_command_loader_patches_govern_both_resolution_calls(monkeypatch, tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(
        yaml.safe_dump(
            {
                "title": "Vocal Set",
                "mode": "vocal",
                "patterns": [
                    {
                        "name_jp": "集中",
                        "name_en": "Focus",
                        "tempo": "slow",
                        "scenes": ["soft vocal"],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (patterns_path.parent / "suno-lyrics.json").write_text("{}", encoding="utf-8")
    calls = {"config": 0, "override": 0, "lyrics": 0}

    def load_skill_config(_name: str):
        calls["config"] += 1
        return {
            "genre_line": "patched vocal jazz",
            "exclude_styles": "noise",
            "style_variants": {},
            "style_variation": {"enabled": False, "pools": {}},
            "banned_artists": [],
        }

    def load_channel_override(_name: str):
        calls["override"] += 1
        return {}

    def load_suno_lyrics_by_name(path: Path):
        calls["lyrics"] += 1
        assert path == patterns_path.parent / "suno-lyrics.json"
        return {"集中 — Focus": "patched lyrics"}

    def deny_domain_loader(*_args, **_kwargs):
        raise AssertionError("command-local patch seam was bypassed")

    monkeypatch.setattr(generate_suno_prompts, "load_skill_config", load_skill_config)
    monkeypatch.setattr(generate_suno_prompts, "load_channel_override", load_channel_override)
    monkeypatch.setattr(generate_suno_prompts, "load_suno_lyrics_by_name", load_suno_lyrics_by_name)
    monkeypatch.setattr(prompt_resolution, "load_skill_config", deny_domain_loader)
    monkeypatch.setattr(prompt_resolution, "load_channel_override", deny_domain_loader)
    monkeypatch.setattr(prompt_resolution, "load_suno_lyrics_by_name", deny_domain_loader)

    entries = generate_suno_prompts.build_prompt_entries(patterns_path)
    markdown = generate_suno_prompts.generate(patterns_path)

    assert calls == {"config": 3, "override": 2, "lyrics": 2}
    assert entries[0]["lyrics"] == "patched lyrics"
    assert "patched vocal jazz" in markdown
