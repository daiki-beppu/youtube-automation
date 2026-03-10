#!/usr/bin/env python3
"""Generate suno-prompts.md from channel_config.json + suno-patterns.yaml."""

import json
import sys
from pathlib import Path

import yaml

automation_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(automation_dir))

from utils.channel_config import ChannelConfig


def generate(patterns_path: Path) -> str:
    config = ChannelConfig.load()
    suno = config._data.get("suno", {})

    genre_line = suno.get("genre_line", "")
    mood_descriptors = suno.get("mood_descriptors", "")
    exclude_styles = suno.get("exclude_styles", "")

    base_parts = [genre_line]
    if mood_descriptors:
        base_parts.append(mood_descriptors)
    base_style = ", ".join(base_parts)

    with open(patterns_path) as f:
        data = yaml.safe_load(f)

    title = data.get("title", "Suno Prompts")
    patterns = data.get("patterns", [])

    lines = [
        f"# Suno Prompts — {title}",
        "",
        "## SunoAI 推奨設定",
        "",
        "| パラメータ | 値 |",
        "|-----------|-----|",
        "| Mode | Custom |",
        "| Weirdness | 20% |",
        "| Style Influence | 70% |",
        "| Lyrics | (空) |",
        "",
        "---",
    ]

    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for i, pattern in enumerate(patterns):
        label = labels[i] if i < len(labels) else str(i + 1)
        name_jp = pattern["name_jp"]
        name_en = pattern["name_en"]
        tempo = pattern["tempo"]
        scenes = pattern["scenes"]

        lines.append("")
        lines.append(f"## Pattern {label}: {name_jp} — {name_en}")

        for j, scene in enumerate(scenes, 1):
            lines.append("")
            lines.append(f"### Variation {j}")
            lines.append("**Styles:**")
            lines.append(f"{base_style},")
            lines.append("looping game bgm,")
            lines.append(f"{scene}, {tempo}, 5 minutes")

            if exclude_styles:
                lines.append("")
                lines.append("**Exclude Styles:**")
                lines.append(exclude_styles)

        lines.append("")
        lines.append("---")

    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) < 2:
        patterns_path = Path.cwd() / "20-documentation" / "suno-patterns.yaml"
        if not patterns_path.exists():
            print("Usage: python3 generate_suno_prompts.py <collection-path or patterns.yaml>")
            sys.exit(1)
    else:
        arg = Path(sys.argv[1])
        patterns_path = arg if arg.is_file() else arg / "20-documentation" / "suno-patterns.yaml"

    if not patterns_path.exists():
        print(f"Error: {patterns_path} not found")
        sys.exit(1)

    output_path = patterns_path.parent / "suno-prompts.md"
    content = generate(patterns_path)
    output_path.write_text(content)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
