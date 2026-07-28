# CLAUDE.md

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、下流のチャンネルリポジトリ（`CHANNEL_DIR`）へ `yt-skills sync` で導入される 2 層構造。

詳細は必要になった時点で参照する: アーキテクチャ・主要モジュール表は `docs/architecture.md`、bootstrap / パッケージング / 品質ゲート / dashboard 開発は `docs/development.md`、issue / worktree 運用は `docs/takt-operations.md`、スキル設計は `docs/skill-design/skill-authoring-guidelines.md`。

## 非自明な規約・落とし穴

- devShell 必須（direnv または `nix develop`。shellHook が `uv sync` を自動実行）。非対話 shell は `nix develop --command <cmd>`
- チャンネル固有値は `load_config` 経由でのみ取得（`config.meta.channel_name` 形式）。ハードコード禁止。新キー追加は dataclass（`configuration/<section>.py`）+ `loader.py::_build_*` + 必須なら `_REQUIRED_KEYS_BY_SECTION` の 3 点セット — 最後の登録を忘れやすい
- 例外は `infrastructure/errors.py` のドメイン例外（`ConfigError`, `YouTubeAPIError` 等）を使う。生の `Exception` / `KeyError` を catch しない
- パッケージ内 import は `from youtube_automation.xxx import ...` の fully-qualified 固定
- 新規 CLI は必ず `yt-*` プレフィックスで `pyproject.toml::[project.scripts]` に登録。CLI は SKILL.md から呼ばれるインターフェースなので、引数は `choices=` / `help=` で自己記述にする
- `google-auth-httplib2` の直 import を新規追加しない（回帰テストで機械担保。経緯は `docs/migration/google-auth-httplib2.md`）
- スクリプトは該当 skill の `.claude/skills/<skill>/references/` 配下に置く。ルート直下に `scripts/` を設けない
- skill の実体は常に `.claude/skills/` 側（`.agents/skills` は Codex 用 symlink — 編集しない）。SKILL.md frontmatter の `description:` は double-quoted 必須（値内の `: ` が strict YAML で誤解釈される）。検証は `uv run yt-skills lint`
- `.claude/skills/` と `.claude/CLAUDE.template.md` は wheel に force-include される。バージョン bump は `pyproject.toml::version` のみ（`__version__` は動的読込）
- 品質ゲート（ruff / CHANGELOG / any 型）はローカル git hook ではなく CI で担保
- TypeScript は `dashboard/` の表示層（ADR-0013）と `extensions/` のみの限定例外。tayk core の実装・削除済み `packages/` の復活は禁止（`docs/adr/0021-separate-repo-restart.md`）。dashboard から `extensions/shared-ui` を import しない

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は絶対にコミットしない
- シークレット解決順: `os.environ` → `op read`（1Password CLI）→ `ConfigError`。参照定義は `utils/secrets.py::_SECRET_REFS`。テストでは `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1`（既定有効）で `op read` をスキップ
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

## 開発ワークフロー

- 開発は必ず issue 専用 linked worktree 上で行う。標準ルートは `/issue-direct <N>`（base branch は main 固定、通常 PR）。takt は使わない（既存 `takt:*` ラベルは履歴メタデータのみ）
- commit は日本語 Conventional Commits + タイトル末尾に `(#<N>)`
- リリースは `/automation-release`（post-release は `/release-notes`）
