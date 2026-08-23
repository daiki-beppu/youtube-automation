# マスター動画 review

`/video --generate` は `config/skills/video.yaml::generate.review.preview_required` を解決する。`true` なら全尺生成前の `*-Preview.mp4`、全尺生成後は `*-Master.mp4` を `yt-master-video-review` へ渡す。

```bash
uv run yt-master-video-review \
  --collection "$COLLECTION_DIR" \
  --kind preview \
  --background-route "$BACKGROUND_ROUTE" \
  --effect "$EFFECT_SUMMARY" \
  --overlays "$OVERLAY_SUMMARY" \
  --full-output-outlook "$FULL_OUTPUT_OUTLOOK"
```

各表示値は `generate_videos.sh` が同じ実行で解決・出力した値を渡し、別に設定を再解決しない。HTMLはrun後も再参照できる `20-documentation/reviews/master-video-preview.html` / `master-video-full.html` へatomic overwriteし、標準video player、duration、resolution、codec、filesize、背景経路、effect、overlay、Full output outlookを表示する。previewは短尺確認、fullは完成動画と明示する。

HTML生成直後、親 orchestrator は絶対pathのMarkdown linkと、区分、動画名、duration / resolution、背景経路、effect / overlayを確認対象として要約する。手動経路は提示後にreviewを待ち、承認完了までstateを進めない。`--automatic` でも永続HTML linkと確認結果を完了報告へ含める。

- preview承認までは `assets.master_video` を変更しない。fullのprobeと承認が成功したときだけowner APIでファイル名を記録する
- renderer、browser、media参照、probe、digest、allowlist、replayの失敗時は正規動画とstateを変更しない
- Webを使えない場合も黙って自動承認せず、Codex / Claude の同じsessionで `--transport terminal` を付け、返されたIDを `--candidate-id` に明示する
- HTMLやbrokerから任意path、command、state patchを受け取らない
- `preview_required: false` の自動経路はpreview用CLIを呼ばず、HTML/broker/確認待ちを作らない。full確認も運用設定で自動承認する場合だけ `--automatic` を明示し、probeと同じstate ownerは省略しない
