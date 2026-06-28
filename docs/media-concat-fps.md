# fps 違い素材を concat するときの注意

自前イントロ動画や外部編集した素材を、ツールが出力した本編 MP4 と後段で結合する場合の運用メモ。

## 症状

FFmpeg の concat demuxer で `-c copy` のまま結合すると、入力素材の fps や timebase が違うときに尺がずれることがある。

典型例:

- イントロは 24fps、本編は 30fps
- 片方だけ VFR（可変フレームレート）
- `ffprobe` 上の `r_frame_rate` / `avg_frame_rate` / `time_base` が一致しない

この状態で stream copy すると、再生時間、音声同期、チャプター位置が期待とずれる可能性がある。

## 確認方法

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=r_frame_rate,avg_frame_rate,time_base \
  -of default=noprint_wrappers=1 intro.mp4

ffprobe -v error -select_streams v:0 \
  -show_entries stream=r_frame_rate,avg_frame_rate,time_base \
  -of default=noprint_wrappers=1 main.mp4
```

値が揃っていない場合は、stream copy ではなく再エンコード前提で扱う。

## 対処

結合前に素材を同じ fps / 解像度 / 音声形式へ正規化する。

```bash
ffmpeg -i intro.mp4 \
  -vf "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 48000 -ac 2 \
  intro-normalized.mp4
```

その後、正規化済み素材同士を concat する。

```bash
printf "file '%s'\nfile '%s'\n" intro-normalized.mp4 main.mp4 > concat.txt
ffmpeg -f concat -safe 0 -i concat.txt -c copy output.mp4
```

それでも尺がずれる場合は、最終 concat も再エンコードする。

```bash
ffmpeg -f concat -safe 0 -i concat.txt \
  -c:v libx264 -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 48000 -ac 2 \
  output.mp4
```

## スコープ

このドキュメントは自前素材とツール出力を外部で結合する場合の注意点。ツール内の動画生成フロー自体が fps を自動吸収することは扱わない。
