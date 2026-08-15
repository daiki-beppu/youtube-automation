import json
import sys
from pathlib import Path

import yaml

from youtube_automation.commands.suno import generate_suno_prompts
from youtube_automation.domains.suno import prompt_resolution


def test_main_resolves_once_and_writes_the_existing_markdown_and_json(monkeypatch, tmp_path: Path):
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

    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(patterns_path)])

    generate_suno_prompts.main()

    assert resolved_paths == [patterns_path]
    assert (tmp_path / "suno-prompts.md").read_text(encoding="utf-8") == (
        "# Suno Prompts — Focus Set\n"
        "\n"
        "## SunoAI 推奨設定\n"
        "\n"
        "| パラメータ | 値 |\n"
        "|-----------|-----|\n"
        "| Mode | Custom |\n"
        "| Weirdness | 50% |\n"
        "| Style Influence | 50% |\n"
        "| Instrumental | ON（インストモード） |\n"
        "| Lyrics | (空) |\n"
        "\n"
        "---\n"
        "\n"
        "## Pattern A: 集中 — Focus\n"
        "\n"
        "### 集中 — Focus\n"
        "**Styles:**\n"
        "```\n"
        "slow, ,\n"
        "soft piano and brushed drums\n"
        "```\n"
        "\n"
        "---\n"
    )
    assert json.loads((tmp_path / "suno-prompts.json").read_text(encoding="utf-8")) == {
        "entries": [
            {
                "name": "集中 — Focus",
                "style": "slow, ,\nsoft piano and brushed drums",
                "lyrics": "[Instrumental]\n\n[Extended Outro]",
            }
        ],
        "duration_filter": {"min_sec": 60, "max_sec": 300},
    }


def test_main_loads_each_prompt_input_once_at_the_resolution_boundary(monkeypatch, tmp_path: Path):
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

    monkeypatch.setattr(prompt_resolution, "load_skill_config", load_skill_config)
    monkeypatch.setattr(prompt_resolution, "load_channel_override", load_channel_override)
    monkeypatch.setattr(prompt_resolution, "load_suno_lyrics_by_name", load_suno_lyrics_by_name)
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(patterns_path)])

    generate_suno_prompts.main()

    assert calls == {"config": 1, "override": 1, "lyrics": 1}
    payload = json.loads((tmp_path / "suno-prompts.json").read_text(encoding="utf-8"))
    assert payload["entries"][0]["lyrics"] == "patched lyrics"
    assert "patched vocal jazz" in (tmp_path / "suno-prompts.md").read_text(encoding="utf-8")
