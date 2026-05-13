---
name: channel-new
description: Use when 新しい YouTube チャンネル用の独立リポジトリを作成したいとき。「チャンネル追加」「新チャンネル」「チャンネル開設」「チャンネルセットアップ」「新しいチャンネル作りたい」「TTP 対象を集める」など、新規チャンネルのセットアップに関わる場面で必ず使用すること。競合発掘→分析→方向性決定→セットアップの全工程のエントリポイント
---

## Overview

新チャンネル開設のエントリポイント。新しい独立リポジトリを作成し、ビジョンヒアリング → 競合チャンネル発掘 → 最小セットアップを行う。

**全体フロー（4スキル連携）**:
```
/channel-new       → Phase 1: ビジョン共有 & 競合発掘 + 独立リポジトリ作成 ← このスキル
/channel-research  → Phase 2: ベンチマーク徹底分析
/channel-direction → Phase 3: 方向性ブレスト
/channel-setup     → Phase 4: テクニカルセットアップ + 検証
```

共有テンプレートは `.claude/skills/channel-setup/references/` に配置（`yt-skills sync` で配布）。

## TTP 原則（ベンチマーク参照）

`/channel-new` の競合発掘は **TTP（徹底的にパクる）対象の収集** そのものである。
ここで集める競合チャンネルは、後段の `/channel-research` / `/channel-direction` で
タイトル構造・サムネ構図・動画尺・投稿頻度の **型** を転写する元になる。
発掘の質がそのまま転写素材の質を決める — 関係性メモには「何を TTP したいか」も書く。

## Instructions

**実行場所**: 新リポジトリの親ディレクトリ（例: `~/01-dev/projects/`）

### Step 1: ビジョンヒアリング

ユーザーに以下を質問:

- **どんなチャンネルにしたい？** — ジャンル、雰囲気、世界観のイメージ
- **参考にしたいチャンネルはある？** — YouTube URL や名前を1つ以上もらう
- **仮のチャンネル名** — 後で変更可能
- **リポジトリ名**（`youtube-{ケバブケース}` 形式） — 提案して承認を得る

この時点では genre/style/context は仮決定でよい。`/channel-direction` で確定する。

### Step 2: 独立リポジトリ作成

テンプレートから新リポジトリを作成し、automation パッケージをインストール、スキルを同期:

```bash
gh repo create <short> --template daiki-beppu/youtube-channel-template --private --clone
cd <short>
uv add git+https://github.com/daiki-beppu/youtube-channels-automation.git
uv run yt-skills sync
```

正準ディレクトリ構造は `channel-setup/references/directory-structure.md` を参照（不足分があれば補完）。

### Step 3: 認証セットアップ

`/channel-new` 段階では **リサーチ用の最低限認証** のみ整える（競合ベンチマーク収集のため）。本番用 GCP プロジェクトと OAuth クライアントは `/channel-setup` の GCP / Vertex AI ブートストラップ step で自動化する。

**リサーチ用ショートカット**: 既存チャンネルのトークンをコピーして使用可能（YouTube Data API はチャンネル所有権に関係なく動作）。コピー元は **その場で動的に列挙** する。特定リポジトリ名はハードコードしない:

1. **候補の動的列挙**: 新リポジトリの親ディレクトリ（このリポジトリの 1 つ上、例: `~/01-dev/projects/`）配下の各サブディレクトリを走査し、`auth/token.json` が存在するものをコピー元候補として収集する:

   ```bash
   ls -d ../*/auth/token.json 2>/dev/null
   ```

2. **ユーザーに選択を提示**: 候補が 1 件以上見つかったら、リポジトリ名と最終更新日時を一覧で提示し、どれをコピー元にするかユーザーに選んでもらう。1 件しかない場合も自動採用せず必ず確認する。

3. **明示入力フォールバック**: 候補が 0 件、または提示した候補をユーザーが採用しない場合は、コピー元の `auth/token.json` への **絶対パス** をユーザーに入力してもらう:

   ```
   コピー元の token.json の絶対パスを教えてください（例: /Users/<you>/path/to/some-channel/auth/token.json）
   ```

4. **コピー実行**: 選択 or 入力されたパスを使ってコピー:

   ```bash
   cp <選択されたパス> auth/token.json
   ```

5. **コピー可能なトークンが用意できない場合**: 本 Step はスキップし、本番認証の整備をそのまま `/channel-setup` の GCP / Vertex AI ブートストラップ step に委ねる。リサーチ用ベンチマーク収集は本番認証が整ったあとに実行する。

本番用の GCP プロジェクト作成 / API 有効化 / Vertex AI 設定 / `.env` 書き出しは `/channel-setup` の GCP ブートストラップ step で AI セッション内完結させる（判断フローは `channel-setup/references/gcp-bootstrap.md`）。

### Step 4: 最小 config 作成

`benchmark_collector.py` 実行に必要な最小限の `config/channel/*.json` を Write ツールで作成:

`config/channel/meta.json`:
```json
{
  "channel": {
    "name": "{仮チャンネル名}",
    "short": "{仮SHORT}",
    "youtube_handle": "",
    "url": ""
  }
}
```

`config/channel/content.json`:
```json
{
  "genre": { "primary": "TBD", "style": "TBD", "context": "TBD" },
  "tags": { "base": [], "themes": {} },
  "descriptions": { "opening": "", "perfect_for": [], "hashtags": [] },
  "title": { "template": "" }
}
```

`config/channel/youtube.json`:
```json
{
  "youtube": { "category_id": "10", "privacy_status": "public", "language": "en" }
}
```

`config/channel/analytics.json`:
```json
{
  "benchmark": {
    "channels": [],
    "scan_recent": 50,
    "min_views": 10000,
    "freshness_days": 3,
    "analyze_thumbnails": true
  }
}
```

### Step 5: 競合チャンネル発掘

**目標: 5-10 チャンネルを発見**

**最初に試すこと**: `yt-discover-competitors` で発掘候補を自動生成する。
ニッチキーワードを 3-5 個渡すと、登録者数レンジ・最終投稿日でフィルタした
ランキング付き Markdown + CSV が出力される（詳細は `/discover-competitors` skill 参照）:

```bash
uv run yt-discover-competitors \
  --keywords "{キーワード1},{キーワード2},{キーワード3}" \
  --min-subscribers 10000 --max-subscribers 1000000 \
  --posted-within-days 30 --top 20 \
  --output research/discovery.md
```

ユーザーに結果を提示して承認を得る → そのまま下記の `benchmark.channels` 反映へ進む。

**自動発掘で不足する場合の補完手順**（任意キーワードで結果が乏しいときのみ）:

1. ユーザーの参考チャンネルのジャンル・特徴を把握
2. WebSearch で類似チャンネルを探す:
   - `"youtube channels similar to {参考チャンネル}" {ジャンル} music`
   - `best {ジャンル} music youtube channels`
   - `{ジャンル} BGM youtube` 等
3. 見つかったチャンネルの **channel_id** を特定:
   - チャンネル URL を WebFetch → HTML ソースから `"channelId":"UC..."` を抽出
   - または `"externalId":"UC..."` パターン
4. 各チャンネルの概要情報（登録者数、動画数、特徴）を簡単に収集

発掘したチャンネルをテーブル形式でユーザーに提示:

```
| # | チャンネル名 | 登録者 | 動画数 | 特徴 | 関係性メモ |
|---|-------------|--------|--------|------|-----------|
```

ユーザーの承認後、`config/channel/analytics.json` の `benchmark.channels` に全チャンネルを追加:

```json
{
  "id": "UC...",
  "slug": "channel-slug",
  "name": "Channel Name",
  "relationship": "ユーザーのメモ or 自動分類"
}
```

### Step 6: ベンチマーク・コメントデータ収集

ベンチマークデータは **`/benchmark` スキル** に委譲する（詳細はそちら参照）。初回は全チャンネル強制更新 + サムネイル画像保持で:

```bash
uv run yt-benchmark-collect --force --keep-thumbnails -v
```

続けてコメントも収集:

```bash
uv run yt-benchmark-comments --min-views 5000
```

- 出力: `data/benchmark_YYYYMMDD.json`, `data/comments_YYYYMMDD.json`, `docs/benchmarks/{slug}.md`

### Step 7: 次フェーズへの案内

「データ収集が完了しました。次は `/channel-research` で徹底分析を行います。」

## Cross References

- `/channel-research` → 次フェーズ: 収集データの徹底分析
- `/channel-direction` → Phase 3: 方向性ブレスト
- `/channel-setup` → Phase 4: テクニカルセットアップ
