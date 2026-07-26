# AGENTS.md

This file provides guidance to Codex CLI (developers.openai.com/codex) when working with code in this repository.

**プロジェクト概要・アーキテクチャ・開発規約（設定アクセス / エラーハンドリング / Import / 依存ポリシー / スクリプト配置 / テスト / パッケージング / セキュリティ / CHANGELOG ゲート / 開発ワークフロー）は `CLAUDE.md` に一元化している。実装・レビューに着手する前に必ず `CLAUDE.md` を読むこと。**

詳細ドキュメント: `docs/architecture.md`（モジュール構成）/ `docs/development.md`（パッケージング・extensions・品質ゲート）/ `docs/takt-operations.md`（issue / worktree 運用。takt は使用しない）。

## Codex CLI 固有の注意

### skill 探索パス

- スキルの実体は `.claude/skills/`（Claude Code 規約のパス）。Codex 用 alias `.agents/skills` はその **symlink** で、Codex CLI は `$REPO_ROOT/.agents/skills` を skill 探索パスとして読み込む
- スキルを編集するときは **必ず `.claude/skills/` 側を直接編集する**（symlink を貼り替えない）

### SKILL.md frontmatter 規約

- 記法規約は `CLAUDE.md`「### skill frontmatter」を正とする。検証は `uv run yt-skills lint`

### Claude Code 固有表現の読み替え

本リポジトリのスキル群は Claude Code 文脈で設計された記述が多い。Codex 実行時は次のように読み替え、表記が残っていても実装不整合とは扱わない:

- `AskUserQuestion` → 通常のユーザー確認
- `Read ツール` → 画像/ファイル閲覧手段
- `Bash ツール run_in_background=true` → 長時間コマンドを非同期 session で起動して進捗を poll
- `TodoWrite` → Codex の plan/checklist 更新

### 下流チャンネルリポジトリの config

- `config/channel/*.json` は責務別分割。必須ファイルに加え optional として `shorts.json` / `comments.json` / `pinned-comment.json` / `distrokid.json` / `community-draft.json` がある。一覧と構造は `CLAUDE.md`・`docs/architecture.md` を参照

### devShell と worktree

- 対象 checkout（親 checkout / worktree のどちらも）で `nix develop` または direnv に入る。shellHook が `uv sync` を自動実行する
- 品質ゲート（ruff / CHANGELOG / any 型）はローカル git hook ではなく CI で担保される。詳細は `docs/development.md` の「品質ゲート（CI）」
