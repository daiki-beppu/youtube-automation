"""Suno コレクション成果物のパス契約.

`yt-generate-suno`（生成）と `yt-collection-serve`（配信）が同じファイル名・
ディレクトリ名・HTTP サブパスを参照するため、契約文字列をこの 1 箇所に集約する。
"""

from __future__ import annotations

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PATTERNS_FILENAME = "suno-patterns.yaml"
SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"

# yt-collection-serve の suno サブパス（#698 で `/prompts.json` から分離）。
# suno-helper 拡張の fetch URL（extensions/shared/constants.ts の PROMPTS_ROUTE）と対の契約。
SUNO_PROMPTS_ROUTE = "/suno/prompts.json"
