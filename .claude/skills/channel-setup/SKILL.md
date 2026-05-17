---
name: channel-setup
description: Use when /channel-direction で方向性が確定し、チャンネルのテクニカルセットアップを行いたいとき。「セットアップ」「設定ファイル生成」「config 作成」「チャンネル構築」など、新チャンネルの設定ファイル+ディレクトリ構造の完成に関わる場面で使用すること。/channel-direction の後に実行する
---

## Overview

`/channel-direction` で確定した方向性をもとに、`config/channel/*.json` を完成させ、全設定ファイル+ディレクトリ構造を一括生成する。

**前提**: `/channel-direction` が完了し、`docs/channel/channel-direction.md` が存在すること。

## Instructions

**実行場所**: リポジトリルート（独立リポジトリ）

### Step 1: 方向性ドキュメントの読み込み

`docs/channel/channel-direction.md` を読み、確定した方向性を把握:
- チャンネル名、短縮名、ジャンル、スタイル、コンテキスト
- コアメッセージ、差別化ポイント
- 動画の長さ、投稿頻度、音楽エンジン

### Step 2: 設定内容の提案と承認

`channel-research.md` の分析データも参照しながら、方向性に基づいて config 内容を Claude が生成し提案する。
生成ルールは **`references/config-generation-rules.md`** を参照（tags / descriptions / title / suno の書き方）。
雛形は `references/config-template/*.json`（責務別 4 ファイル: meta / content / youtube / analytics）。

提案をユーザーに見せ、承認 or 修正指示を受ける。

### Step 3: config/channel/*.json の完成

Phase 1 で `/channel-new` が作成した最小 config を完全版に拡張。`references/config-template/` の各ファイルを
`config/channel/` 配下に配置し、全フィールドを埋める。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。
`benchmark.channels` は `/channel-new` で既に設定済み（`config/channel/analytics.json`）。

### Step 4: 残りディレクトリの作成

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。

### Step 5: 残りファイル生成

| ファイル | 生成方法 |
|---------|---------|
| `config/schedule_config.json` | `references/schedule-template.json` をコピー。投稿頻度を方向性に合わせて調整 |
| `config/upload_settings.json` | `references/upload-settings-template.json` をコピー |
| `config/localizations.json` | `references/localizations-template.json` をコピーし、ジャンル情報を反映した具体的な文言に調整。多言語展開しないチャンネルは省略可（`load_config().localizations.supported_languages` は `youtube.api.language` へフォールバック）。`config/localizations.json` が唯一の Canonical ソース |
| `.claude/CLAUDE.md` | `references/claude-md-template.md` の `{{CHANNEL_NAME}}` / `{{DIR_NAME}}` を置換 |

### Step 6: GCP / Vertex AI ブートストラップ

新チャンネルの GCP プロジェクト + API + IAM + `.env` をセットアップする。判断基準・コマンド・リカバリ手順は **`references/gcp-bootstrap.md`** を参照。

ユーザーに以下を確認してから実行する:
- 既存プロジェクトを流用するか / 新規作成するか
- terraform ルート（IaC 管理）を使うか / bootstrap.sh（最速）か
- Billing account ID（新規作成時のみ必要）

実行後、スクリプト出力の Console URL を開き OAuth 2.0 クライアント ID を **手動で 1 回作成**して `auth/client_secrets.json` に配置するよう案内する（gcloud / terraform 双方この手順だけ未サポート）。

### Step 7: 検証

JSON 構文検証・config ロードテスト・channel_id 自動取得コマンドは **`references/verification.md`** を参照。
検証後、生成された全ファイルを一覧で確認する。

### Step 8: 次ステップ案内

1. **YouTube チャンネル作成**（まだの場合）→ `config/channel/meta.json` の `channel.youtube_handle`、`channel.url`、`channel.channel_id` を更新
2. **OAuth 認証と channel_id 取得**: 手順は `references/verification.md`（「OAuth 認証」「channel_id の自動取得」）を参照
3. **ブランディング素材**: 生成手順は `references/verification.md`（「ブランディング素材生成」）を参照
4. **既存チャンネル設定の同期**（オプション）: Step 9 を参照
5. **初回コレクション制作**: `/wf-new` を実行

### Step 9: 既存チャンネル設定の同期（オプション）

OAuth 認証完了後、`config/channel/meta.json` の `youtube_channel` セクション（description / keywords / country / default_language / unsubscribed_trailer / made_for_kids）と `config/localizations.json` を YouTube チャンネルに反映、もしくは YouTube 側から取り込む。

```bash
uv run yt-channel-settings diff               # 読み取り専用: local ↔ remote 差分表示
uv run yt-channel-settings push               # local → YouTube（dry-run）
uv run yt-channel-settings push --apply       # local → YouTube（実反映）
uv run yt-channel-settings pull               # YouTube → local（dry-run）
uv run yt-channel-settings pull --apply       # YouTube → local（実反映: meta.json と localizations.json を書き換え）
```

**API 制約に関する内部実装ノート**:

- `--apply` 実行時は `brandingSettings` / `localizations` / `status` を **別々の `channels().update()` 呼び出し** として個別に発火する。YouTube Data API は `brandingSettings` を他の part と同時送信すると `branding_settings cannot be used with other parts` で 400 エラーを返すため (#230)。
- `localizations` セクションを **完全に空** にして送信すると `Required` 400 エラーになる。`config/localizations.json` の `supported_languages` を全削除して全ローカライゼーションを消したい場合は、少なくとも `default_language` の 1 件はエントリを残して push すること（送信しなかったロケールは YouTube 側で自動削除される）。
- `--no-localizations` を付けると localizations 関連の比較・送信をスキップする。

**運用フロー**:

1. `yt-channel-settings diff` で意図しないずれがないか確認
2. `yt-channel-settings push` の dry-run 出力をレビュー
3. 問題なければ `--apply` で実反映

## Cross References

- `/channel-direction` → 前フェーズ: 方向性決定
- `references/` → テンプレートファイル（同スキルディレクトリ内）
- `/wf-new` → チャンネル完成後の最初のアクション
- `yt-channel-settings` CLI (`src/youtube_automation/scripts/channel_settings_cli.py`) — Step 9 の実装本体
