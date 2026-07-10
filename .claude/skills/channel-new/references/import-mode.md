# 既存チャンネル取り込みモード（取り込み Step 1〜8）

`/channel-new` 既存チャンネル取り込みモードの手順詳細。SKILL.md の「モード判別」で本モードと判定された場合に、このファイルの手順どおりに実行する。
本ファイル内の `references/...` は `.claude/skills/channel-new/references/...`（本ファイルと同じディレクトリ配下）を指す。

既に YouTube で運営中のチャンネルの情報をヒアリングし、`config/channel/*.json`（責務別分割、v2.0.0 以降）を生成して自動化システムに取り込む。

**実行場所**: `/setup` 完了後の channel repo ルート。新規開設モードと同じく、テンプレートリポジトリから clone せず今いるディレクトリを使う。

**リポジトリ準備**: `.git` がない場合は新規開設モードの Step 2（現在のディレクトリを repo 初期化）を実行する。automation パッケージ未導入・OAuth クライアント未配置など環境が未整備の場合は、新規開設モードの Step 3 と同じく `uv run yt-doctor --json` で状態を確認し、`/setup` を案内して完了させてから取り込み Step 1 へ進む。

## 取り込み Step 1: 基本情報のヒアリング

ユーザーに以下を確認する:

1. **YouTube チャンネル URL またはハンドル**（例: `@channel-name`）
2. **チャンネル名**（表示名）
3. **短縮名**（3-4文字の略称、例: goa, rjn）

## 取り込み Step 2: ジャンル・世界観のヒアリング

以下を対話的に確認する:

- **ジャンル** (`genre.primary`): 「どんなジャンルのチャンネルですか？」（例: Celtic, Lo-Fi, Jazz, Ambient）
- **スタイル** (`genre.style`): 「スタイルをもう少し具体的に」（例: Fantasy, Smooth, Chill）
- **コンテキスト** (`genre.context`): 「どんな世界観・文脈ですか？」（例: RPG Adventure, Rainy Night Cafe）
- **コアメッセージ** (`channel.core_message`): 「チャンネルが届けたい価値は？」

## 取り込み Step 3: コンテンツ設定のヒアリング

以下を確認する:

1. **音楽エンジン**: Suno / Lyria（`music_engine` に入れる値は `suno` / `lyria` のどちらか。`both` は config 契約外のため選択肢にしない）
2. **動画尺** (`audio.target_duration_min` / `audio.target_duration_max`): 既存動画の標準尺を確認し、固定尺なら min/max を同値にする
3. **タイトルテンプレート**: 既存動画のタイトルパターンを確認し、`{style} {theme} Music - {activity} BGM [{duration_display}]` 形式で提案
4. **タグ** (`tags.base`): ジャンルに適した YouTube 検索タグを 10 個程度提案
5. **テーマ別タグ** (`tags.themes`): 6-10 テーマのタグ群を提案
6. **説明文設定**:
   - `descriptions.opening`: `{style} {primary} music inspired by ...` 形式
   - `descriptions.perfect_for`: 4 項目（例: Study & Focus, Relaxation, Creative Work, Sleep）
   - `descriptions.hashtags`: 5 個程度
7. **Suno 設定**（音楽エンジンが Suno の場合）: `config/skills/suno.yaml` で `workspace_name` / `genre_line` / `exclude_styles` を上書き（ない場合は skill default を使用）

## 取り込み Step 4: config 生成

`references/config-template/*.json`（責務別 5 ファイル: meta / content / youtube / analytics / audio）をベースに、ヒアリング結果で各ファイルの全フィールドを埋めて `config/channel/*.json` を生成する。動画尺は `references/config-template/audio.json` に反映する。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。

## 取り込み Step 5: ディレクトリ構造の確認・補完

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。
既存リポジトリに不足しているディレクトリがあれば作成する。

## 取り込み Step 6: 検証

JSON 構文検証・config ロードテスト（`uv run yt-config-migrate verify`）は **`references/verification.md`** を参照。

## 取り込み Step 7: OAuth 認証と channel_id 取得

`auth/token.json` がない場合、OAuth 認証と channel_id 自動取得を実行。
`config/channel/meta.json::channel.channel_id` が未設定の場合は、認証済みチャンネル ID を必ず取得して保存する。
手順は **`references/verification.md`**（「OAuth 認証」「channel_id の自動取得」）を参照。

## 取り込み Step 8: 次ステップ案内

config 生成・認証完了後、以下を案内:

1. **ブランディング素材**: 未作成の場合は `references/verification.md`（「ブランディング素材生成」）を参照
2. **ベンチマーク設定**: 競合チャンネルを追加したい場合は `config/channel/analytics.json` の `benchmark.channels` を追加し `/benchmark` で収集
3. **ペルソナ定義**: `/viewer-voice` → `/audience-persona-design` → `/viewing-scene` の順で実行
4. **データ収集・分析**: `/analytics-collect` → `/analytics-analyze` で現状のパフォーマンスを把握
5. **コレクション制作**: `/wf-new` で最初のコレクション制作を開始

取り込みモードは、`config/channel/*.json` の生成、`uv run yt-config-migrate verify` の成功、OAuth 認証、`channel_id` の `config/channel/meta.json::channel.channel_id` 保存、次ステップ案内まで到達した時点で完了扱いにできる。新規開設モードの `benchmark.channels`、`ttp-seed-confirmation.md`、branding snapshot、`ttp_wf_new_readiness` は取り込みモードの必須完了条件ではない。
