#!/usr/bin/env python3
"""Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml."""

import argparse
from pathlib import Path

import yaml

from youtube_automation.utils.skill_config import load_skill_config  # noqa: E402


def generate(patterns_path: Path) -> str:
    suno = load_skill_config("suno")

    genre_line = suno.get("genre_line", "")
    mood_descriptors = suno.get("mood_descriptors", "")
    exclude_styles = suno.get("exclude_styles", "")
    style_variants = suno.get("style_variants", {})
    style_influence = suno.get("style_influence", 50)

    base_parts = [genre_line]
    if mood_descriptors:
        base_parts.append(mood_descriptors)
    base_style = ", ".join(base_parts)

    with open(patterns_path) as f:
        data = yaml.safe_load(f)

    title = data.get("title", "Suno Prompts")
    patterns = data.get("patterns", [])

    vocal_keywords = ("vocals", "vocal", "singing", "rap", "sings", "sung")
    auto_vocal = any(kw in genre_line.lower() for kw in vocal_keywords)
    mode = data.get("mode", "vocal" if auto_vocal else "instrumental")
    is_vocal = mode == "vocal"

    lines = [
        f"# Suno Prompts — {title}",
        "",
        "## SunoAI 推奨設定",
        "",
        "| パラメータ | 値 |",
        "|-----------|-----|",
        "| Mode | Custom |",
        "| Weirdness | 20% |",
        f"| Style Influence | {style_influence}% |",
        f"| Instrumental | {'OFF（ボーカルモード）' if is_vocal else 'ON（インストモード）'} |",
        f"| Lyrics | {'各パターンの Lyrics 欄を投入' if is_vocal else '(空)'} |",
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
        lyrics = pattern.get("lyrics")
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
            parts = []
            if tempo:
                parts.append(tempo)
            parts.append(effective_style)
            lines.append(", ".join(parts) + ",")
            lines.append(scene)
            lines.append("```")

            if exclude_styles:
                lines.append("")
                lines.append("**Exclude Styles:**")
                lines.append("```")
                lines.append(exclude_styles)
                lines.append("```")

            if is_vocal and lyrics:
                lines.append("")
                lines.append("**Lyrics:**")
                lines.append("```")
                lines.append(lyrics.rstrip())
                lines.append("```")

        lines.append("")
        lines.append("---")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Generate suno-prompts.md from config/skills/suno.yaml + suno-patterns.yaml",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="collection path or patterns.yaml path (default: CWD/20-documentation/suno-patterns.yaml)",
    )
    args = parser.parse_args()

    path = args.path or Path.cwd()
    patterns_path = path if path.is_file() else path / "20-documentation" / "suno-patterns.yaml"

    if not patterns_path.exists():
        parser.error(f"{patterns_path} not found")

    output_path = patterns_path.parent / "suno-prompts.md"
    content = generate(patterns_path)
    output_path.write_text(content)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
