---
name: channel-new
description: >-
  Use when 新しい YouTube チャンネル用の独立リポジトリを作成したいとき。
  「チャンネル追加」「新チャンネル」「チャンネル開設」「チャンネルセットアップ」
  「新しいチャンネル作りたい」など、新規チャンネルのセットアップに関わる場面で必ず使用すること。
  競合発掘→分析→方向性決定→セットアップの全工程のエントリポイント
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

OAuth クライアントはユーザーが自分で作成する。Google Cloud Console で OAuth 2.0 認証情報を作成し `auth/client_secrets.json` に配置すること。
チャンネル固有トークンは `auth/token.json` に保存され、初回実行時に自動生成される。

リサーチ段階では既存チャンネルのトークンをコピーして使用可能（YouTube Data API はチャンネル所有権に関係なく動作）:

```bash
cp /path/to/existing-channel-repo/auth/token.json auth/token.json
```

デフォルトのコピー元は `youtube-fantasy-celtic-music`。他のチャンネルを使いたい場合はユーザーに確認。

### Step 4: 最小 config 作成

`benchmark_collector.py` 実行に必要な最小限の `channel_config.json` を Write ツールで作成:

```json
{
  "channel": { "name": "{仮チャンネル名}", "short": "{仮SHORT}" },
  "genre": { "primary": "TBD", "style": "TBD", "context": "TBD" },
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

ユーザーの承認後、`channel_config.json` の `benchmark.channels` に全チャンネルを追加:

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
