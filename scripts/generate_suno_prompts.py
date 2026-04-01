#!/usr/bin/env python3
"""Generate suno-prompts.md from channel_config.json + suno-patterns.yaml."""

import sys
from pathlib import Path

import yaml  # noqa: E402

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402


def generate(patterns_path: Path) -> str:
    config = ChannelConfig.load()
    suno = config._data.get("suno", {})

    genre_line = suno.get("genre_line", "")
    mood_descriptors = suno.get("mood_descriptors", "")
    exclude_styles = suno.get("exclude_styles", "")
    style_variants = suno.get("style_variants", {})

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
        tempo = pattern.get("tempo")
        scenes = pattern["scenes"]
        style_key = pattern.get("style")

        # Per-pattern style variant override
        if style_key and style_key in style_variants:
            variant = style_variants[style_key]
            effective_style = variant["genre_line"]
            style_label = f" [{style_key}: {variant['name']}]"
        else:
            effective_style = base_style
            style_label = ""

        lines.append("")
        lines.append(f"## Pattern {label}: {name_jp} — {name_en}{style_label}")

        for j, scene in enumerate(scenes, 1):
            lines.append("")
            lines.append(f"### Variation {j}")
            lines.append("**Styles:**")
            lines.append("```")
            if tempo:
                lines.append(f"{tempo}, 5 minutes,")
            lines.append(f"{effective_style},")
            lines.append(scene)
            lines.append("```")

            if exclude_styles:
                lines.append("")
                lines.append("**Exclude Styles:**")
                lines.append("```")
                lines.append(exclude_styles)
                lines.append("```")

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
