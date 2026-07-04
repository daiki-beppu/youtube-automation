---
name: community-post
description: "Use when コミュニティ投稿テキスト生成から Studio 起動まで行うとき。「コミュニティ投稿」「投稿準備」で発動。/video-upload の最終ステップから自動で呼ばれる"
---

## Overview

`config/channel/community.json` の固定テンプレを展開し、対象コレクションの `20-documentation/community-post.txt` に保存、クリップボードへコピー、YouTube Studio のコミュニティ投稿作成ページを開きます。動画添付と投稿ボタン押下はユーザーが Studio 上で手動実行します。

## 設定読み込みゲート

前提確認や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/community-post/config.default.yaml`
2. `config/skills/community-post.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("community-post")` と同じ順序で default と任意 override を確認する。ただし、この skill の `config.default.yaml` は既存の skill-local raw JSON 例外を明示するためのプレースホルダであり、投稿本文・Studio URL の実データには使わない。実データは必ず `config/channel/community.json` を読む。存在しない override は未設定として扱い、勝手に作成しない。

## 制約・前提

- **macOS 専用**: `pbcopy` / `open` を使用。cross-platform 化は YAGNI で見送り（follow-up 候補）。失敗時は stdout フォールバックで運用継続できるようにする。
- **YouTube Data API にコミュニティ投稿作成エンドポイントは存在しない**: テキスト準備と Studio 起動までを自動化し、添付・投稿は Studio 上で手動。
- **完全固定テンプレ運用**: バリエーション / 多言語 / Studio 自動入力 / 動画 URL 埋め込みは Non-goals。テンプレ本文に変数展開は行わない（ブランドボイスの反復刷り込みが狙い）。
- **設定アクセス**: 本スキルでは `config/channel/community.json` を skill-local raw JSON 例外として `python3 -c "import json; ..."` で直接読む。`utils.config.load_config()` は現時点で `community` section を持たないため、共通 loader へ統合するかは別タスクで判断する。`.claude/skills/community-post/config.default.yaml` と `config/skills/community-post.yaml` は gate で Read するが、`template` / `studio_url` の fallback 元としては使わない。
- `config/channel/community.json` が存在すること。雛形は `examples/channel_config.example/community.example.json`。

## When to Use

- コレクションのアップロード完了後、コミュニティ投稿を貼りたいとき
- 過去動画に紐づけて単発で投稿したいとき（URL 指定）
- `/video-upload` の最終ステップから自動で呼ばれる

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| 動画 URL | テキスト生成のみ（コレクション特定不可なので保存は省略） | `/community-post https://youtu.be/abc123` |
| コレクションパス | テキスト生成 + `20-documentation/community-post.txt` 保存 | `/community-post collections/live/20260511-xxx` |
| 引数なし | `collections/live/` 配下から最新（`YYYYMMDD-*` の辞書順最大）を自動検出 | `/community-post` |

## Instructions

### Step 1: 引数解析

- `$ARGUMENTS` が `http` で始まる → URL モード
- `$ARGUMENTS` がディレクトリパス → コレクションモード
- `$ARGUMENTS` が空 → 自動検出モード（`collections/live/` 配下の `YYYYMMDD-*` ディレクトリのうち辞書順最大のものを選択）

```bash
if [ -z "$ARGUMENTS" ]; then
  COLLECTION_PATH=$(ls -d collections/live/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-* 2>/dev/null | sort | tail -1)
  if [ -z "$COLLECTION_PATH" ]; then
    echo "エラー: collections/live/ に公開済みコレクションがありません。"
    echo "まず /video-upload を実行してコレクションをアップロードしてください。"
    exit 1
  fi
  MODE="collection"
elif [[ "$ARGUMENTS" == http* ]]; then
  MODE="url"
  VIDEO_URL="$ARGUMENTS"
else
  MODE="collection"
  COLLECTION_PATH="$ARGUMENTS"
fi
```

### Step 2: テンプレ読み込み

`config/channel/community.json` から `template` と `studio_url` を読み込む。`config.default.yaml` や `config/skills/community-post.yaml` に同名キーがあっても、この raw JSON 例外では fallback や merge 元にしない。

```bash
TEMPLATE=$(python3 -c "import json; print(json.load(open('config/channel/community.json'))['template'])")
STUDIO_URL=$(python3 -c "import json; print(json.load(open('config/channel/community.json'))['studio_url'])")
```

ファイルが存在しない場合は `examples/channel_config.example/community.example.json` を雛形として案内し、エラー終了する。

### Step 3: テキスト保存（コレクションモード / 自動検出モードのみ）

URL モードでは保存をスキップ。それ以外では Step 1 で確定した `$COLLECTION_PATH` を使う:

```bash
mkdir -p "$COLLECTION_PATH/20-documentation"
python3 -c "import json, sys; open(sys.argv[1] + '/20-documentation/community-post.txt', 'w').write(json.load(open('config/channel/community.json'))['template'])" "$COLLECTION_PATH"
```

### Step 4: クリップボードコピー

```bash
python3 -c "import json; print(json.load(open('config/channel/community.json'))['template'], end='')" | pbcopy
```

`pbcopy` が失敗した場合（非 macOS など）はテンプレを stdout に出力してユーザーに手動コピーを促す。

### Step 5: Studio 起動

```bash
open "$STUDIO_URL"
```

`open` が失敗した場合は `$STUDIO_URL` を stdout に出力してユーザーに手動オープンを促す。

### Step 6: ユーザーへの案内

下記を提示する:

1. テンプレをクリップボードにコピー済み
2. Studio で「投稿を作成」→ テキスト貼り付け
3. 動画を添付（直近アップロード動画を選択）
4. 投稿ボタンで公開

## エラーハンドリング

| 状況 | 対応 |
|---|---|
| `community.json` が存在しない | エラー終了し、`examples/channel_config.example/community.example.json` を雛形として案内する |
| `pbcopy` 失敗 | テンプレを stdout に出力 |
| `open` 失敗 | URL を stdout に出力 |
| 引数なし & `collections/live/` が空 | エラー終了し、`/video-upload` の実行を促す |

## Non-goals（YAGNI）

- バリエーション生成・A/B テスト
- 多言語投稿（JP / EN 切り替え）
- Studio 上での自動入力（DOM 操作・ヘッドレスブラウザ）
- テンプレ内への動画 URL / タイトル / サムネ等の変数展開
- cross-platform 対応（pbcopy / open 以外の clipboard / open 手段）

これらが必要になったら別 issue で扱う。固定テンプレ運用が崩れると Flow365 TTP の前提（ブランドボイス反復刷り込み）が壊れるため、安易な拡張は避ける。

## Cross References

- `/video-upload` — アップロード完了後の最終ステップから本スキルを呼び出す
- `/playlist` — プレイリスト assign は別経路
