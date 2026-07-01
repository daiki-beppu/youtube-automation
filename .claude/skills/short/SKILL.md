---
name: short
description: "Use when collection 型チャンネル（BGM テイスター）でショート動画を生成・投稿したいとき。CC 動画公開後に 9:16 ショートを 3 本前後生成し多言語ローカライズで投稿。「ショート作って」「shorts」「ショートテイスター」「BGM 切り抜き」「告知ショート」など、本編 CC → ショート誘導に関わる場面で必ず使用すること。release 型（JP+EN クリップ）チャンネルは `/short-release` を使う"
---

## Overview

`config.youtube.content_model.type == "collection"` のチャンネル向けに、CC（Complete Collection）動画の公開後にショート動画を 3 本前後生成し、`localizations.json` の全 supported language にローカライズして投稿する。

素材判定 → ハイライト区間決定 → FFmpeg 一括生成 → アップロードを 1 コマンドで進める。

## 設定読み込みゲート

前提確認や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/short/config.default.yaml`
2. `config/skills/short.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("short")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

- `config/channel/` がロード可能（`load_config()`）
- `config.shorts.enabled == true`（`config/channel/shorts.json`）
- `config.youtube.content_model.type == "collection"`
- CC 動画が YouTube にアップ済みで、`20-documentation/upload_tracking.json::complete_collection.video_url` が記録されている

いずれか欠ける場合は早期に止めて該当 skill / config 更新を案内する（`/channel-import` / `/setup` / `/video-upload`）。

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-upload-shorts <collection-path>` | 全ショートを順次アップロード |
| `uv run yt-upload-shorts <collection-path> --short-num 2` | 2 本目だけアップロード |
| `uv run yt-upload-shorts <collection-path> --plan` | メタデータプレビュー（API 呼ばない） |
| `bash .claude/skills/short/references/generate-shorts.sh <collection-path>` | FFmpeg 一括生成 |
| `bash .claude/skills/short/references/test-crop-positions.sh <master> 30` | loop-mp4 素材時のクロップ位置確認 |
| `uv run yt-shorts-bulk-update-loc <collection-path>` | 投稿済みショートの localizations を一括差し替え |

## Instructions

### Step 1: 前提チェック

```python
from youtube_automation.utils.config import load_config
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

`center` / `x=400` / `x=350` の 3 パターンを `/tmp/short-test-*.jpg` に書き出し `open` で表示。選択結果を `SHORT_CROP_X` 等の env で `generate-shorts.sh` 側に渡す（`crop=ih*9/16:ih:<X>:0`）。

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
- **投稿間隔**: 同コレクションで前回投稿から `cfg.shorts.min_hours_between_shorts_per_collection` 時間以内は新規投稿が block される。テスト中は `--ignore-interval` フラグで bypass 可

## 長時間処理の取り扱い

`generate-shorts.sh` は ffmpeg を本数分（既定 3 本）並列で走らせるため **1〜3 分** 程度かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
bash .claude/skills/short/references/generate-shorts.sh <collection-path> \
  > /tmp/short-$(date +%s).log 2>&1
```

env で渡している `SHORT_STARTS` / `SHORT_LABELS` 等は spawn 前に export しておく。これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ ショート動画 N 本を background 生成中（推定 1〜3 分）。完了まで他の質問にもお答えできます。
> ログ: /tmp/short-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "short" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "short"` + `cmux notify --title "short 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（生成された `short-NN-*.mp4` のパス一覧）をユーザーへ返す。失敗時は ffmpeg のエラー行を抜き出して報告する。`yt-upload-shorts` 本実投稿は API 同期呼び出しなので、ここも同じ background パターンで起動してよい（ただし数秒で完了するため省略可）。

## Next Step

- 投稿済みショートの localizations を一括更新: `uv run yt-shorts-bulk-update-loc <collection-path>`
- 全本数完了後の進捗確認: `/wf-status`
- release 型チャンネルでショートを作りたい場合: `/short-release`
