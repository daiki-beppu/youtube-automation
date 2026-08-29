# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`docs/architecture.md` の「## プロジェクト用語集」** — 本リポジトリの用語と決定の**正本グロッサリ**。ルート `CONTEXT.md` はここへ統合済みで、ファイルとしては存在しない。skills が `CONTEXT.md` と言ったらこの節に読み替える
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If a referenced file doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) resolves terms and decisions lazily — in this repo, new entries go into `docs/architecture.md`「プロジェクト用語集」, not a new root `CONTEXT.md`.

## File structure

This repo is **single-context**:

```
/
├── docs/architecture.md   ← 「## プロジェクト用語集」= グロッサリ正本（旧 CONTEXT.md 統合済み）
├── docs/adr/              ← 既存の ADR 群（0001〜）
└── src/youtube_automation/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `docs/architecture.md`「プロジェクト用語集」（tayk / cutover / dogfood / MCP tool / workflow tool 等）. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`, which appends to `docs/architecture.md`「プロジェクト用語集」).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_

本リポジトリでは特に ADR-0021（separate-repo-restart — 削除済み `packages/` の復活禁止・TypeScript 境界）と矛盾する提案は必ず明示すること。
