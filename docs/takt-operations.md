# takt 運用詳細

CLAUDE.md の「開発ワークフロー」節の詳細版。要点は CLAUDE.md を参照。

## workflow の使い分け（default / lite）

- **`lite`**（`.takt/workflows/lite.yaml`、リポジトリ同梱）: 小〜中規模 issue 用の軽量 3 step（plan → implement → review）。各 step でプロジェクトコンテキスト（CLAUDE.md + skill descriptions 等）が再注入されるため、step 数の削減がそのままトークン削減になる。`takt add` 時に workflow として `lite` を指定する
- **組み込み `default`**（9 step: plan → write_tests → implement → ai-antipattern → 並列 review → supervisor）: 以下に該当する issue は必ず default を使う
  - セキュリティ・認証（OAuth / secrets）・アップロード系に触れる変更
  - 複数スキル・複数モジュールを横断する変更、破壊的変更
  - テスト戦略の設計が必要な新機能
- 導入後に新しい takt バージョンへ上げた場合は `takt workflow doctor lite` で静的検証すること（step スキーマのキー名が変わる可能性がある）

## トークン消費の計測（observability）

`.takt/config.yaml` で有効化済み:

```yaml
observability:
  enabled: true
  usage_events_phase: true
```

- 記録先: `.takt/runs/<run>/logs/<session>-usage-events.phase.jsonl`（step × phase × provider × model 粒度）
- 集計: takt リポジトリ同梱の `npm run analyze:usage -- .takt/runs/<run>`（`--format csv` 可）
- 消費が異常に見えたときは、まず phase JSONL で「どの step のどの phase が食っているか」を特定してから対策する

## worktree の置き場

このリポジトリの開発は必ず worktree 上で行う（メインの作業ツリーで直接ブランチを切らない）。

- **takt 自動生成**: `<repo-parent>/takt-worktrees/<timestamp>-<N>-<slug>/`（takt が自動管理）
- **手動 `git worktree add`**: `$REPO_ROOT/.worktrees/<slug>/`（リポジトリ内・gitignore 済み・`parallel` スキルと共通）
- `<repo-parent>/automation-worktrees/` 等のリポジトリ外手動置き場は非推奨（過去の残骸のみ）

## takt 設定の継承構造

リポジトリ固有 `.takt/config.yaml` は `draft_pr: false` / `base_branch: main` / observability のみ上書きし、provider・model・language・persona はグローバル `~/.takt/config.yaml` を継承する。グローバルは Codex + Opus ハイブリッド（default `provider: claude` / `model: opus 4.6`、doer/planner 系のみ `codex` に override、レビュー系・supervisor は opus、`language: ja`）。

## skill 編集と takt の関係

`.claude/skills/**` を含む `.claude/` 配下は Claude Code の **protected paths**（`acceptEdits` モードでも write 時に必ず prompt が出る領域）に該当する。takt は Claude Agent SDK を `settingSources: ['project']` + `permissionMode: 'acceptEdits'` で呼ぶため prompt に答える人間がおらず、**Claude provider が走る persona から** `.claude/skills/<name>/SKILL.md` 等への Edit/Write は `Claude requested permissions to write to ..., but you haven't granted it yet.` で deny される（`permissions.allow` ルールでは bypass 不可、`bypassPermissions` のみが bypass）。

ただし、**実装を担う `coder` persona を codex provider にしている（グローバル設定から継承）ため**、実装ファイルへの編集は Codex CLI 経由で行われ Claude Code の protected paths 制約を回避できる（Codex は独自のサンドボックスで動作し、`$REPO_ROOT/.agents/skills` を探索パスに含む）。レビュー系 persona は opus（Claude）だが書き込みは行わないため影響しない。そのため、**skill 配下を変更する issue も takt から問題なく回せる**。実際の運用例として、`.claude/skills/videoup/references/generate_videos.sh` 等の skill 配下スクリプト修正も takt 経由で完走実績がある。

逆に `coder` を Claude provider に戻している環境では、従来通り skill 配下の Edit が deny される。その場合は通常の Claude Code 対話セッション（cmux pane 等）で直接編集し、コミット・PR 作成は `commit-convention` / `pr` スキル経由で実施する。

## Codex 共用時の skill 表記読み替え

`.claude/skills/**` は Claude Code / Codex CLI 共用だが、既存 SKILL.md には Claude Code 固有表現が残る。Codex で実行するときは、`AskUserQuestion` は通常のユーザー確認、`Read ツール` は画像/ファイル閲覧手段、`Bash ツール run_in_background=true` は長時間コマンドを非同期 session で起動して進捗を poll、`TodoWrite` は Codex の plan/checklist 更新として読み替える。これらの表記が残っていても実装不整合とは扱わず、同等の Codex 機能で実行する。

## リリース

`/automation-release` スキルで Release PR パターンを自動化（prepare → リリース PR → publish の 2 フェーズ）。post-release の運営者向けガイドと下流追従 issue は `/release-notes` が担当。
