# bench/

perf #131 計測フェーズ用のマイクロベンチ群。

`time` ベースでホットスポットを実測し、改善余地を定量化する。結果は `bench/results/<session>/` に JSON で残し、`REPORT.md` で集約する。`bench/results/` は `.gitignore` 対象。

## 実行

```bash
# 全 bench（課金 API 含む、推定 ≈ $0.64）
uv run python -m bench.main

# API 不要ベンチのみ（コスト 0）
uv run python -m bench.main --no-real-apis

# 単一 bench
uv run python -m bench.main --only cost_tracker
```

## 同梱ベンチ

| ファイル | 計測対象 | 実 API |
|---|---|---|
| `bench_cost_tracker.py` | `cost_tracker.log_generation` のフル JSON 書き戻し（156/500/1000 件） | なし |
| `bench_strategic_analytics.py` | `get_video_analytics_by_id` 逐次 vs `ThreadPoolExecutor`（モック 50ms） | なし |
| `bench_smooth_loop.py` | `veo_generator.smooth_loop` の libx264 preset 別 ffmpeg 時間 | なし |
| `bench_skill_size.py` | `.claude/skills/*/SKILL.md` の行数集計 | なし |
| `bench_video_daily.py` | `video_daily_analytics.get_video_daily_analytics` 28d/90d | YouTube Analytics |
| `bench_generate_image.py` | OpenAI gpt-image-1 `n=1` vs `n=4`（batch 活用） | OpenAI |
| `bench_veo_poll.py` | Veo 3.1 fast 1 request + poll 間隔短縮の試算 | Veo |
| `bench_benchmark_collector.py` | `channels.list` 1 件 × N vs 50 件カンマ区切り | YouTube Data |

## section logger との連携

`YT_PROFILE=1` を併用すると各 bench 内の section 計測 (`utils/profile.py`) も stderr に流れる。詳細プロファイルを JSONL で取りたい場合:

```bash
YT_PROFILE=1 YT_PROFILE_OUT=/tmp/profile.jsonl \
  uv run python -m bench.main --no-real-apis
```

## 結果の見方

`bench/results/<session>/REPORT.md` にケース別 `n / p50_ms / p95_ms / max_ms` の表が出る。個別 JSON は `samples_ms` を含むので、後段で外れ値や分布を見られる。

完了後は `REPORT.md` の表を epic #131 にコメントとして貼り付ける（手動）。
