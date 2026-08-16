# collection 型の手順

## 前提

- CC 動画が YouTube にアップ済みで、`20-documentation/upload_tracking.json::complete_collection.video_url` が記録済み
- `10-assets/short-loop.mp4`、`10-assets/short.png`、`10-assets/loop.mp4` のいずれかと `01-master/*Master*.mp3` が存在する

映像ソースの優先順位は `short-loop.mp4` → `short.png` → `loop.mp4`。無ければ `/short --thumbnail` で `short.png` を作り、必要に応じて `uv run yt-generate-shorts-loop` で動画化する。

## ハイライトとクロップを決める

検証済み `20-documentation/descriptions.json` + 同 basename HTML pair の `tracks` から `config.shorts.collection.default_count` 本を提案する。各チャプター先頭から skill-config の `collection.chapter_offset_sec` 秒後を初期値にし、ユーザーに本数・区間を確認する。

`loop.mp4` の場合は次を実行し、中央 / x=400 / x=350 のテストフレームからクロップ位置を確認する。

```bash
bash .claude/skills/short/references/test-crop-positions.sh "$MASTER_VIDEO" 30
```

## 生成する

`load_skill_config("short")["collection"]` を env に渡す。

```bash
export SHORT_STARTS="30 3960 6420"
export SHORT_LABELS="chapter1 chapter3 chapter5"
export SHORT_DURATION=20
export SHORT_FADE_IN=1.0
export SHORT_FADE_OUT=1.5
export SHORT_FONT="/System/Library/Fonts/Palatino.ttc"
# loop.mp4 のときだけ設定
export SHORT_CHANNEL_NAME="Your Channel"
export SHORT_COLLECTION_NAME="Collection Title"

bash .claude/skills/short/references/generate-shorts.sh <collection-path>
```

`SHORT_STARTS` と `SHORT_LABELS` の件数が違う場合、素材・音声が無い場合、いずれかの ffmpeg が失敗した場合は非 0 で停止する。

## プレビュー・投稿・state を確認する

```bash
open <collection>/01-master/shorts/short-01-*.mp4
uv run yt-upload-shorts <collection-path> --plan
uv run yt-upload-shorts <collection-path>
```

投稿後、`workflow-state.json::post_upload.shorts` に `short_num`, `video_id`, `publish_at`, `uploaded_at`, `title` が upsert されたことを確認する。同じ `short_num` は置換、別番号は append、番号なし投稿は `short_num: null` とする。

## Gotchas

- `loop.mp4` 経路の既定クロップは中央固定。別位置を選んだ場合は ffmpeg の `crop` x 座標を手動調整する
- `SHORT_COLLECTION_NAME` のアポストロフィは drawtext 用にエスケープする
- 30fps は YouTube Shorts 認識のため常時付与する
- 投稿間隔は `cfg.shorts.min_hours_between_shorts_per_collection` で検査され、bypass フラグはない
