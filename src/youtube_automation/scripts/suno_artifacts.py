"""Suno コレクション成果物のパス契約.

`yt-generate-suno`（生成）と `yt-suno-serve`（配信）が同じファイル名・
ディレクトリ名を参照するため、契約文字列をこの 1 箇所に集約する。
"""

from __future__ import annotations

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PATTERNS_FILENAME = "suno-patterns.yaml"
SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"
