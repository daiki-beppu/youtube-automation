---
name: short
description: "Use when collection 型（BGM テイスター）チャンネルでショートを生成・投稿するとき。「ショート作って」「shorts」「BGM 切り抜き」で発動。release 型は /short-release"
---

## 前後工程

- `前工程`: `/setup`
- `後工程`: `/short-thumbnail`, `/video-upload`

## Overview

`config.youtube.content_model.type == "collection"` のチャンネル向けに、CC（Complete Collection）動画の公開後にショート動画を 3 本前後生成し、`localizations.json` の全 supported language にローカライズして投稿する。

素材判定 → ハイライト区間決定 → FFmpeg 一括生成 → アップロードを 1 コマンドで進める。

## 完了条件

- ショート動画（既定 `shorts.collection.default_count` 本）が `01-master/shorts/` に生成され、プレビュー確認済み
- `uv run yt-upload-shorts` の実投稿が完了し、`workflow-state.json::post_upload.shorts` に投稿分の entry が記録されている

## Subagent Contract

- **入力**: 対象コレクション、映像ソース、確定済みハイライト区間、クロップ位置
- **成果物**: `01-master/shorts/short-*.mp4`
- **委譲しない処理**: 区間・クロップ・プレビュー・投稿の承認。state を更新する実投稿 CLI は承認後にメインが実行し、成果物と tracking を検証する

subagent は `workflow-state.json` へ書き込まず `AskUserQuestion` を実行しない。承認が要る処理は、メインが承認を得るまで委譲しない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラー。成果物の存在検証と state 更新はメインが行う。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/short/config.default.yaml`
2. `config/skills/short.yaml`（存在する場合）

合成規則は `youtube_automation.utils.skill_config.load_skill_config("short")` と同じで、チャンネル上書きが優先される。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

- `config/channel/` がロード可能（`load_config()`）
- `config.shorts.enabled == true`（`config/channel/shorts.json`）
- `config.youtube.content_model.type == "collection"`
- CC 動画が YouTube にアップ済みで、`20-documentation/upload_tracking.json::complete_collection.video_url` が記録されている

いずれか欠ける場合は早期に止めて該当 skill / config 更新を案内する（`/channel-new` 既存チャンネル取り込みモード / `/setup` / `/video-upload`）。

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-upload-shorts <collection-path>` | 全ショートを順次アップロード |
| `uv run yt-upload-shorts <collection-path> --short-num 2` | 2 本目だけアップロード |
| `uv run yt-upload-shorts <collection-path> --plan` | メタデータプレビュー（API 呼ばない） |
| `bash .claude/skills/short/references/generate-shorts.sh <collection-path>` | FFmpeg 一括生成 |
| `bash .claude/skills/short/references/test-crop-positions.sh <master> 30` | loop-mp4 素材時のクロップ位置確認 |
| `uv run yt-shorts-bulk-update-loc [--dry-run]` | 投稿済みショートの localizations を一括差し替え（`collections/live/` 全件走査。個別コレクション指定は不可） |

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本） | 投稿本数（既定 `default_count`。1 Short ≈ videos.insert + thumbnails.set = 1,650 units） | 投稿本数 |
| thumbnails.set（50 units / 本） | 投稿本数分 | — |
| videos.update（50 units、yt-shorts-bulk-update-loc） | 投稿済み Shorts 数（`--dry-run` は API 0） | `collections/live/` の Shorts 総数 |

- 上限 / 承認: `--plan` は API を呼ばないメタデータプレビュー、`--short-num` で 1 本ずつ小出しに投稿できる。ショート生成（ffmpeg）はローカル処理で課金なし。

## Instructions

### Step 1: 前提チェック

```python
from youtube_automation.configuration import load_config
cfg = load_config()
assert cfg.shorts.enabled, "config/channel/shorts.json で shorts.enabled=true にしてください"
assert cfg.youtube.content_model.type == "collection", "release 型は /short-release を使ってください"
```

失敗時は対応 skill を案内して終了。

### Step 2: 素材確認

`generate-shorts.sh` が次の優先順位で映像ソースを自動選択する。最低 1 つ無いと進めない:

| 優先 | ファイル | モード |
|-----|---------|-------|
| 1 | `10-assets/short-loop.mp4` | Veo 9:16 ループ動画（テキスト焼き込み済み） |
| 2 | `10-assets/short.png` | 9:16 静止画 + zoompan |
| 3 | `10-assets/loop.mp4` | 16:9 ループを crop + drawtext で重畳 |

いずれも無ければ `/short-thumbnail` で `short.png` 生成 → `uv run yt-generate-shorts-loop` でループ動画化を案内。

### Step 3: ハイライト区間決定（AskUserQuestion）

`20-documentation/descriptions.md` のチャプター情報を読み、`config.shorts.collection.default_count` 本のハイライトを提案する。各チャプターの先頭 `chapter_offset_sec` 秒経過点を初期値とする。

ユーザーに `AskUserQuestion` で確認:
- 提案された本数・チャプター選択でよいか / 別本数を指定するか
- 「いい感じに」等の指示なら自動選択で進める

### Step 4: クロップ位置確認（loop-mp4 モードのみ）

`loop.mp4` ベースのときは中央クロップでキャラが切れる可能性があるため、毎回必ずテストフレームを生成して `AskUserQuestion` でクロップ位置を選ばせる:

```bash
bash .claude/skills/short/references/test-crop-positions.sh "$MASTER_VIDEO" 30
```

`center` / `x=400` / `x=350` の 3 パターンを `/tmp/short-test-*.jpg` に書き出し `open` で表示。`generate-shorts.sh` の loop-mp4 経路は中央クロップ（`crop=ih*9/16:ih`）固定のため、center 以外を選んだ場合は該当 ffmpeg コマンドの `-vf` のクロップ部分を `crop=ih*9/16:ih:<X>:0` に差し替えて手動実行する。

### Step 5: 一括生成

`load_skill_config("short")` の生成パラメータを env に詰めて `generate-shorts.sh` を実行する:

```bash
export SHORT_STARTS="30 3960 6420"
export SHORT_LABELS="chapter1 chapter3 chapter5"
export SHORT_DURATION=20
export SHORT_FADE_IN=1.0
export SHORT_FADE_OUT=1.5
# loop-mp4 モード時のみ
export SHORT_CHANNEL_NAME="Your Channel"
export SHORT_COLLECTION_NAME="Collection Title"

bash .claude/skills/short/references/generate-shorts.sh <collection-path>
```

所要時間とログの扱いは後述「所要時間と完了報告」に従う。

### Step 6: プレビュー → アップロード

```bash
open <collection>/01-master/shorts/short-01-*.mp4
uv run yt-upload-shorts <collection-path> --plan       # メタデータ確認
uv run yt-upload-shorts <collection-path>              # 実投稿
```

`ShortUploader` が自動で行うこと:
- CC `publish_at` 基準で `cfg.shorts.publish_time` 翌日公開時刻を計算
- `cfg.shorts.min_hours_between_shorts_per_collection` で投稿間隔チェック
- `BAHMetadataGenerator.generate_shorts_metadata(cc_video_url)` で EN + 全 supported_languages のメタデータ生成
- `workflow-state.json::post_upload.shorts` に `short_num` をキーに upsert

### Step 7: workflow-state.json 更新

```json
"post_upload": {
  "shorts": [
    {
      "short_num": 1,
      "video_id": "xxx",
      "publish_at": "2026-03-12T08:00:00+09:00",
      "uploaded_at": "2026-03-11T09:12:00+09:00",
      "title": "Morning Light - Whispers Across the Hills #Shorts"
    }
  ]
}
```

`short_num` 未指定で `01-master/short.mp4` を投稿した場合は `short_num: null` の entry として扱う。
同じ `short_num` を再投稿した場合は既存 entry を置換し、別の `short_num` は append する。

## 設定

| 配置 | ファイル | 責務 |
|------|---------|------|
| チャンネル運用 | `config/channel/shorts.json` | enabled / publish_time / mode / 本数（`shorts.collection.default_count`） / 投稿間隔 |
| skill 動作 | `.claude/skills/short/config.default.yaml` | 尺・フェード・フォント・クロップオフセット（生成側パラメータ） |
| チャンネル上書き | `config/skills/short.yaml` | skill-config の差し替え |
| ローカライズ | `config/localizations.json` の `languages.<lang>.short_title_template` / `short_description_template` | 言語別タイトル / 説明テンプレ。テンプレ未定義の言語はスキップ |

## ショート動画仕様

| 項目 | 値 |
|------|-----|
| アスペクト比 | 9:16（1080x1920） |
| 推奨長 | 15-25 秒（`shorts.collection.default_count` × `duration_sec`） |
| 最大長 | 60 秒 |
| フレームレート | 30fps 必須（`fps=30` フィルタ強制） |

## Gotchas

- **drawtext フォント**: Nix FFmpeg は libfreetype 同梱。macOS は `/System/Library/Fonts/Palatino.ttc` を指定すること（`SHORT_FONT` env）
- **drawtext アポストロフィ**: `SHORT_COLLECTION_NAME` に `'` が含まれるとシェルクォートと衝突。アポストロフィを除去するか `'\''` でエスケープしてから渡す
- **fps=30 必須**: マスター動画が静止画ベース（1fps）の場合、`fps=30` フィルタなしで生成すると YouTube がショート認識しない
- **CC video_url 未記録**: `upload_tracking.json::complete_collection.video_url` が空だと CC リンク行が描画欄から省略される（例外は投げない）。完全状態にするには CC 動画アップ後に `yt-upload-collection` の出力で記録を確認
- **投稿間隔**: 同コレクションで前回投稿から `cfg.shorts.min_hours_between_shorts_per_collection` 時間以内は新規投稿が block される。bypass フラグは無いため、テスト中は `config/channel/shorts.json` の `min_hours_between_shorts_per_collection` を一時的に小さくして対応する

## 所要時間と完了報告

`generate-shorts.sh` は ffmpeg を本数分（既定 3 本）並列で走らせるため **1〜3 分**。`SHORT_STARTS` / `SHORT_LABELS` 等の env は spawn 前に export しておく。

ログを `/tmp/short-$(date +%s).log` へ redirect し、完了後は末尾から生成された `short-NN-*.mp4` のパス一覧を報告する。失敗時は ffmpeg のエラー行を抜き出す。

## Next Step

- 投稿済みショートの localizations を一括更新: `uv run yt-shorts-bulk-update-loc`（`collections/live/` 全件対象。`--dry-run` でプレビュー）
- 全本数完了後の進捗確認: `/wf-status`
- release 型チャンネルでショートを作りたい場合: `/short-release`
