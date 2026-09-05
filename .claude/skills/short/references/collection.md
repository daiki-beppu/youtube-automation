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

生成に成功した `01-master/shorts/short-NN-<label>.mp4` の絶対パスと番号を全件列挙し、各動画をプレビューする。`NN` を整数（`01` → `1`）として以下の `<short-num>` に渡す。同じ番号が複数ある場合や生成予定の番号が欠けた場合は投稿前に解消する。番号なしコマンドは legacy `01-master/short.mp4` の単件用で、番号付き生成物の全件投稿には使わない。

番号ごとに plan の動画対象・公開予定を確認する。

```bash
uv run yt-upload-shorts <collection-path> --short-num <short-num> --plan
```

対象番号・動画・投稿内容を提示し、外部投稿の承認を得る。同じ対象・内容についてセッション内で得た承認は再利用する。承認済みの各番号について次を 1 回ずつ実行し、直後に結果を判定する。

```bash
uv run yt-upload-shorts <collection-path> --short-num <short-num>
```

| 結果の `action` | 判定・次の行動 |
|---|---|
| `short_uploaded` | 結果の `details.short_num`・`details.video_id` と `workflow-state.json::post_upload.shorts` の同じ番号の記録を照合する。一致し、`publish_at`・`uploaded_at` が記録されていればその番号は成功 |
| `short_upload_blocked` | 未投稿。`details.reason` と未完了番号を報告し、間隔制約が解消してから同じ番号で再開する。exit 0 でも成功に数えない |
| `short_upload_failed` または非 0 終了 | 失敗。エラーと対象番号を報告する。再試行前に state と投稿 CLI の結果を確認する。投稿成否を確定できない場合は確認が済むまで止め、既に投稿済みの番号を重複投稿しない |

state と結果が一致しない場合も未完了として止め、state を手書きで成功へ変更しない。同じ `short_num` の記録は CLI が置換し、別番号は追加する。

生成した全番号について成功・blocked・失敗・未実行を報告する。成功済み番号は再実行せず、残る番号の再開コマンドを番号付きで示す。collection 型は投稿と state 照合までがこの skill の責務であり、全番号の照合が済むまでは完了としない。

## Gotchas

- `loop.mp4` 経路の既定クロップは中央固定。別位置を選んだ場合は ffmpeg の `crop` x 座標を手動調整する
- `SHORT_COLLECTION_NAME` のアポストロフィは drawtext 用にエスケープする
- 30fps は YouTube Shorts 認識のため常時付与する
- 投稿間隔は `cfg.shorts.min_hours_between_shorts_per_collection` で検査され、bypass フラグはない
