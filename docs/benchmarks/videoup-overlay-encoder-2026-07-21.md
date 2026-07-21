# videoup overlay encoder benchmark — 2026-07-21

## Decision

既定の直接 `libx264 medium` 経路を維持する。今回の Apple Silicon 実機では、二段化・software preset 調整・VideoToolbox のいずれも採用基準の wall-clock 20%短縮に達しなかった。hardware encoder は環境差を考慮して明示 opt-in として提供するが、自動有効化しない。

## Environment and reproduction

- Apple Silicon macOS、Homebrew FFmpeg（`libx264` / `h264_videotoolbox` 有効、`h264_nvenc` 非搭載）
- 1920x1080、24 fps、60秒、H.264 MP4、AAC、`showfreqs` visualizer overlay
- 各候補3回。wall-clock は `/usr/bin/time -p`、表は中央値

```bash
VIDEOUP_BENCH_DURATION=60 VIDEOUP_BENCH_RUNS=3 \
  bash .claude/skills/videoup/references/benchmark_overlay_encoders.sh
```

比較条件と codec options は [FFmpeg Codecs Documentation](https://ffmpeg.org/ffmpeg-codecs.html) およびローカル build の `ffmpeg -h encoder=<name>` を正とした。

## Results

| Candidate | Median wall | Baseline比 | Size | SSIM vs baseline | Decision |
|---|---:|---:|---:|---:|---|
| direct libx264 medium / CRF 20 | 4.04s | baseline | 1,402,435 B | 1.000000 | 維持 |
| direct libx264 veryfast / CRF 20 | 3.65s | 9.7% faster | 1,464,752 B | 0.999968 | 20%未達、+4.4% size |
| two-stage cold | 5.18s | 28.2% slower | 1,402,435 B | 1.000000 | 不採用 |
| two-stage cached median | 4.19s | 3.7% slower | 1,402,435 B | 1.000000 | 不採用。後段全尺 encode が残る |
| h264_videotoolbox | 6.45s | 59.7% slower | 1,515,101 B | 0.999964 | 自動採用しない |
| h264_videotoolbox `realtime` + `prio_speed` | 8.16s | 102.0% slower | 1,515,101 B | 0.999964 | 不採用 |
| h264_nvenc | N/A | N/A | N/A | N/A | この実機の FFmpeg build に encoder なし |

全出力は ffprobe で H.264、1920x1080、24/1 fps、60.000秒、AAC を確認した。10秒地点の三方式を横並びで目視し、visualizer の位置・形状・opacity に差異は認めなかった。

## Production contract

- `overlays.encoder.codec` の既定値は `libx264`。
- `hardware` は VideoToolbox → NVENC の利用可能な候補を選ぶ。`h264_videotoolbox` / `h264_nvenc` の明示指定も可能。
- encoder 一覧にない場合、または 1-frame 起動 probe が失敗した場合は実出力前に `libx264` へ fallback する。
- overlay 無効経路、preview、batch、effect + overlays の filter graph は変更しない。
