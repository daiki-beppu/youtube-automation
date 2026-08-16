# Community mode

## 前後工程

- `前工程`: `/publish --upload`, `/publish`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/20-documentation/community-post.txt`, `collections/<id>/30-promo/community-posts.json`
- `読み込む`: `config/skills/publish.yaml::community`, `config/channel/community-draft.json`, `collections/<id>/workflow-state.json`

## Overview

`config/channel/community.json` の固定テンプレを展開し、対象コレクションの `20-documentation/community-post.txt` に保存、クリップボードへコピー、YouTube Studio のコミュニティ投稿作成ページを開きます。動画添付と投稿ボタン押下はユーザーが Studio 上で手動実行します。

`--batch` 指定時は `config/channel/community-draft.json::community_draft` の投稿テンプレートから `30-promo/community-posts.json` を決定的に生成し、単発フローは実行しません。

## 完了条件

- **単発**: Step 6 のユーザー案内（クリップボードコピー済み + Studio での貼り付け・添付・投稿手順）を提示した時点。実際の投稿はユーザーの Studio 手動操作であり、完了条件に含まない。`pbcopy` / `open` が失敗した場合も、stdout フォールバック（テンプレ本文と Studio URL の表示）まで到達すれば完了扱いとする。
- **`--batch`**: generator が exit 0 で終了し、`30-promo/community-posts.json` の全投稿が Batch modifier の出力契約を満たした時点。Studio は開かない。

## チェーンからの呼出

フラグなし `/publish <collection>` から呼ばれた場合も Step 1〜6 と完了条件は同じで、単独発動を無効化しない。チェーンへ完了を返すのは Step 6 到達後だけとし、失敗時は出力成果物を完了扱いにしない。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/publish/config.default.yaml::community`
2. `config/skills/publish.yaml::community`（存在する場合）

読み込み後は `youtube_automation.configuration.skills.load_skill_config("publish")["community"]` と同じ順序で default と任意 override を確認する。旧 `community-post.yaml` は `yt-skills migrate-config` で `publish.yaml::community` へ移行でき、移行前も互換 loader で同じ値を読む。ただし、この community 節は既存の skill-local raw JSON 例外を明示するためのプレースホルダであり、投稿本文・Studio URL の実データには使わない。実データは必ず `config/channel/community.json` を読む。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

以下は `--batch` なしの単発だけで確認する。`--batch` は Batch modifier の Hard Gates だけを適用する。

- `config/channel/community.json` が存在すること。存在しない場合は雛形 `examples/channel_config.example/community.example.json` を案内してエラー終了する（Step 2 参照）
- 引数なしの自動検出モードでは、`collections/live/` に公開済みコレクション（`YYYYMMDD-*`）が 1 件以上存在すること。存在しない場合は先に `/publish --upload` の実行を案内して停止する
- macOS であること（`pbcopy` / `open` を使用）。非 macOS では stdout フォールバックで運用継続する

## 単発の制約

- **macOS 専用**: `pbcopy` / `open` を使用。cross-platform 化は YAGNI で見送り（follow-up 候補）。失敗時は stdout フォールバックで運用継続できるようにする。
- **YouTube Data API にコミュニティ投稿作成エンドポイントは存在しない**: テキスト準備と Studio 起動までを自動化し、添付・投稿は Studio 上で手動。
- **完全固定テンプレ運用**: バリエーション / 多言語 / Studio 自動入力 / 動画 URL 埋め込みは Non-goals。テンプレ本文に変数展開は行わない（ブランドボイスの反復刷り込みが狙い）。
- **設定アクセス**: 本 mode では `config/channel/community.json` を skill-local raw JSON 例外として `python3 -c "import json; ..."` で直接読む。`configuration.load_config()` は現時点で `community` section を持たないため、共通 loader へ統合するかは別タスクで判断する。`.claude/skills/publish/config.default.yaml::community` と `config/skills/publish.yaml::community` は gate で Read するが、`template` / `studio_url` の fallback 元としては使わない。

## When to Use

- コレクションのアップロード完了後、コミュニティ投稿を貼りたいとき
- 過去動画に紐づけて単発で投稿したいとき（URL 指定）
- `/publish --upload` の最終ステップから自動で呼ばれる
- config テンプレートから複数の投稿予定を JSON 生成したいとき（`--batch`）

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| 動画 URL | テキスト生成のみ（コレクション特定不可なので保存は省略） | `/publish --community https://youtu.be/abc123` |
| コレクションパス | テキスト生成 + `20-documentation/community-post.txt` 保存 | `/publish --community collections/live/20260511-xxx` |
| 引数なし | `collections/live/` 配下から最新（`YYYYMMDD-*` の辞書順最大）を自動検出 | `/publish --community` |

## Instructions

`--batch` があれば、以下の「Batch modifier」だけを実行する。なければ Step 1〜6 の単発フローを実行する。

## Batch modifier

### Hard Gates

- `config/channel/community-draft.json` が存在し、`load_config().community_draft.posts` が空でないこと。欠落時は `examples/channel_config.example/community-draft.example.json` をコピーしてチャンネル値へ書き換えるよう案内し、設定が完了するまで停止する。
- 対象 collection の `workflow-state.json::planning.final_title` と `planning.publish_target_at` が非空であること。`final_title` 欠落時は `/wf-new` 経由で企画を確定するよう案内して停止する。`publish_target_at` 欠落時は planned YouTube publish datetime を timezone 付き ISO 8601 の JSON string とし、`uv run yt-workflow-state --collection <collection-path> set-planning publish_target_at <json-value>` で記録してから続行する。
- 対象 collection は `CHANNEL_DIR` 配下の実在パスを指定する。

変数解決・日時計算・path 検証・JSON schema の単一ソースは `references/generate_batch.py` とし、本文で再実装しない。

```bash
uv run python .claude/skills/publish/references/generate_batch.py \
  --batch \
  --collection <collection-dir>
```

generator が exit 0 で終了し、`<collection>/30-promo/community-posts.json` の全投稿に `text`、timezone 付き `scheduled_at`、channel root 相対 `image_path`、`visibility: public` が存在すれば完了。Studio への転記・投稿は後工程の責務です。

### 出力

```json
{
  "posts": [
    {
      "text": "展開済みテキスト",
      "scheduled_at": "2026-06-24T18:00:00+09:00",
      "image_path": "collections/planning/20260625-rain/main.png",
      "visibility": "public"
    }
  ]
}
```

## Single-post flow

### Step 1: 引数解析

- `$ARGUMENTS` が `http` で始まる → URL モード
- `$ARGUMENTS` がディレクトリパス → コレクションモード
- `$ARGUMENTS` が空 → 自動検出モード（`collections/live/` 配下の `YYYYMMDD-*` ディレクトリのうち辞書順最大のものを選択）

```bash
if [ -z "$ARGUMENTS" ]; then
  COLLECTION_PATH=$(ls -d collections/live/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-* 2>/dev/null | sort | tail -1)
  if [ -z "$COLLECTION_PATH" ]; then
    echo "エラー: collections/live/ に公開済みコレクションがありません。"
    echo "まず /publish --upload を実行してコレクションをアップロードしてください。"
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

`config/channel/community.json` から `template` と `studio_url` を読み込む。`config.default.yaml::community` や `config/skills/publish.yaml::community` に同名キーがあっても、この raw JSON 例外では fallback や merge 元にしない。

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
| 引数なし & `collections/live/` が空 | エラー終了し、`/publish --upload` の実行を促す |

## Non-goals（YAGNI）

- バリエーション生成・A/B テスト
- 多言語投稿（JP / EN 切り替え）
- Studio 上での自動入力（DOM 操作・ヘッドレスブラウザ）
- テンプレ内への動画 URL / タイトル / サムネ等の変数展開
- cross-platform 対応（pbcopy / open 以外の clipboard / open 手段）

これらが必要になったら別 issue で扱う。固定テンプレ運用が崩れると Flow365 TTP の前提（ブランドボイス反復刷り込み）が壊れるため、安易な拡張は避ける。

## Cross References

- `/publish --upload` — アップロード完了後、設定済みなら `/publish`、未設定なら本スキルを案内する
- `/publish` — 統合チェーンから対象 collection を引き継いで本 mode を呼び出す
- `/publish --playlist` — プレイリスト assign は別経路
- `/publish --community --batch` — config テンプレートから JSON 投稿バッチを生成
