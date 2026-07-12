"""Shared helpers for yt-suno-verify tests."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import yaml

from youtube_automation.utils.suno_artifact_validation import suno_prompt_entry_names


def write_suno_override(channel: Path, **overrides) -> None:
    (channel / "config" / "skills" / "suno.yaml").write_text(
        yaml.safe_dump(overrides, allow_unicode=True),
        encoding="utf-8",
    )


def docs_dir(collection: Path) -> Path:
    docs = collection / "20-documentation"
    docs.mkdir(parents=True)
    return docs


def write_patterns(
    docs: Path,
    *,
    mode: str | None,
    scenes: list[str],
    tracks: int | None = None,
    style: str | None = None,
) -> None:
    payload: dict = {
        "title": "Verify Test",
        "patterns": [
            {
                "name_jp": "歌もの" if mode == "vocal" else "静かな雨",
                "name_en": "Vocal" if mode == "vocal" else "Quiet Rain",
                "tempo": "slow",
                "scenes": scenes,
            }
        ],
    }
    if mode is not None:
        payload["mode"] = mode
    if tracks is not None:
        payload["tracks"] = tracks
    if style is not None:
        payload["patterns"][0]["style"] = style
    (docs / "suno-patterns.yaml").write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def prompt_names(*, mode: str, scenes_count: int) -> list[str]:
    name_jp = "歌もの" if mode == "vocal" else "静かな雨"
    name_en = "Vocal" if mode == "vocal" else "Quiet Rain"
    return suno_prompt_entry_names(name_jp, name_en, scenes_count)


def write_prompts(docs: Path, names: list[str], *, lyrics: str = "[Instrumental]\n") -> None:
    entries = [
        {
            "name": name,
            "style": f"slow, lo-fi jazz,\nscene {index}",
            "lyrics": lyrics,
        }
        for index, name in enumerate(names, 1)
    ]
    (docs / "suno-prompts.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def write_lyrics(docs: Path, entries: list[dict[str, str]]) -> None:
    (docs / "suno-lyrics.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def write_video_analysis_suno_preset(channel: Path, *, genre_line: str, exclude_styles: str = "") -> None:
    out_dir = channel / "data" / "video_analysis" / "sample"
    out_dir.mkdir(parents=True)
    (out_dir / "sample.json").write_text(
        json.dumps(
            {
                "suno_preset": {
                    "genre_line": genre_line,
                    "exclude_styles": exclude_styles,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_suno_verify_module():
    return importlib.import_module("youtube_automation.scripts.suno_verify")


def run_verify(monkeypatch, collection: Path) -> int:
    module = load_suno_verify_module()
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify", str(collection)])
    return module.main()
