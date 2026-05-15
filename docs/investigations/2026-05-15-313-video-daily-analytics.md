# `video_daily_analytics` HttpError 400 切り分け調査 (2026-05-15)

Issue: [#313 investigate: video_daily_analytics で HttpError 400 が出るケースの切り分け](https://github.com/d-bep/yt-channels/issues/313)
親 epic: [#131](https://github.com/d-bep/yt-channels/issues/131)

## 1. 概要

`src/youtube_automation/utils/video_daily_analytics.py` の `VideoDailyAnalyticsMixin.get_video_daily_analytics` を rjn チャンネル（`UCgSH7gY_7bBHut9o8mm2uHQ`）で `video_ids` 未指定のまま呼び出すと、YouTube Analytics API が `HttpError 400 The query is not supported.` を返す。本ドキュメントは原因仮説 4 件を順に検証し、issue #313 のコメント材料（および follow-up issue 起票時の根拠資料）として残すことを目的とする。本 issue は調査用であり、コード修正は本ドキュメントの「推奨アクション」を踏まえた別 issue で実施する。

## 2. 失敗クエリと再現経路

issue #313 本文に記載された失敗クエリは以下:

```
metrics=views
dimensions=video,day
ids=channel==UCgSH7gY_7bBHut9o8mm2uHQ
startDate=2026-04-17 endDate=2026-05-15
maxResults=10000
```

28d / 90d どちらの期間でも同じエラー。`filters` パラメータは付いていない。

リポジトリ内の再現経路は `bench/bench_video_daily.py:35`:

```python
rows = len(collector.get_video_daily_analytics(start.isoformat(), end.isoformat()))
```

`video_ids` を渡していないため `get_video_daily_analytics`（`src/youtube_automation/utils/video_daily_analytics.py:20-66`）の以下分岐をスキップし、`filters` 無しのまま `.execute()` に到達する:

```python
if video_ids:
    query_kwargs["filters"] = "video==" + ",".join(video_ids)
```

一方、本番経路 `src/youtube_automation/scripts/analytics_system.py:128-150` は `get_all_channel_videos()` で全動画 ID を集めて `video_ids=...` に渡すため `filters=video==...` が必ず付与される。

## 3. 仮説検証結果

### 仮説 1: `dimensions=video,day` の組合せが Channel reports で公式サポートされていない

**結論: おおむね真。`filter 無しの channel-wide` 呼び出しは Channel reports として未文書化で拒否される。**

YouTube Analytics API の Channel Reports ([公式](https://developers.google.com/youtube/analytics/channel_reports)) で文書化されている主な動画関連レポートと dimensions の組合せは以下:

| レポート | dimensions | filters | 備考 |
|---|---|---|---|
| Time-Based User Activity | `day` or `month` | `video==<id>` 等 | `video` は dimension ではなく filter |
| Top N Videos | `video` | （optional） | `sort` 必須、`maxResults <= 10` |
| User Activity by Day for a Specific Video | `day` | `video==<id>` 必須 | 単一動画ピン留め |

`dimensions=video,day` を **filter 無し**で許容する Channel report は文書化されていない。経験則として `filters=video==<id1>,<id2>,...` で動画をピン留めすれば cardinality が制約されるため API は受理する（本番経路 `analytics_system.py:128-150` が正常動作する根拠）。

### 仮説 2: rjn チャンネル特有の条件（owner じゃない / 動画数不足 / マネタイズ未承認 等）

**結論: 本ワークフローでは検証不能。仮説 1 が十分な根拠を持つため副次的位置付け。**

takt サンドボックスから OAuth 経路で実 API を呼べないため、他チャンネル（bobble / deepfocus365 等）での再現確認は手動フォローアップに残す（§7）。仮説 1 が満たされている以上、rjn 固有要因がさらに重畳しているかは「修正の必要性」には影響しない。

### 仮説 3: `filters` 未指定で全動画を返そうとして API 上限に達している

**結論: 部分的に真。仮説 1 と組み合わせると、API は `dimensions=video,day` × filter 無しの組合せを Channel reports として未サポート扱いで 400 を返す、と説明できる。**

- 失敗クエリ（issue 本文）には `filters` が無い
- `bench/bench_video_daily.py:35` は `video_ids` 未指定 → `filters` が付かない → 再現経路
- `src/youtube_automation/scripts/analytics_system.py:128-150` は `video_ids=[v["video_id"] for v in get_all_channel_videos()]` 経由で `filters=video==...` を付与 → 本番経路は正常
- ただし `analytics_system.py:149-150` の `except Exception: logger.warning(...)` で握り潰すため、API が 400 を返した場合は warning ログのみで上位処理は継続し、成果物 JSON が欠落する
- 副次リスク: `filters=video==id1,id2,...` を全動画分連結すると **URL 長制限**（HTTP リクエスト URL は ~8KB 上限）に達する。動画 ID は 11 文字 + 区切り 1 文字なので、おおむね 600 本超のチャンネルで `URI Too Long` 系のエラーに切り替わる可能性がある

### 仮説 4: launch curve 分析 CLI（`yt-launch-curve` 等）で同じエラーが出るか

**結論: 直接は出ない。間接的には「snapshot 欠落」エラーとして現れる。**

- `src/youtube_automation/scripts/launch_curve.py:188` は `load_latest_daily_snapshot(channel_dir / "data")` で保存済み JSON を読むだけで API を直叩きしない
- 上流 `yt-analytics --save-data` の動画×日次保存ブロック（`analytics_system.py:128-150`）が 400 を warning として握ったまま完了するため、**動画×日次スナップショット JSON が生成されない**
- 結果として `launch_curve.py:189-190` が `ConfigError("日次データが見つかりません。先に \`yt-analytics\` を実行してください。")` で停止する
- すなわち `yt-launch-curve` のエラーは "Bad query" ではなく "snapshot 欠落"。根本原因は上流の握り潰し

## 4. API 仕様の根拠

- **`dimensions=video,day` は Channel reports に未文書化**。
  Channel Reports ドキュメント（[https://developers.google.com/youtube/analytics/channel_reports](https://developers.google.com/youtube/analytics/channel_reports)）で `video` は Top N Videos のみ dimension として登場し、それ以外は filter としてのみ許容される。
- **Channel-wide で動画×日次データを取得する公式経路は YouTube Reporting API v1 の `channel_basic_a3`**。
  Reporting API のレポート定義（[https://developers.google.com/youtube/reporting/v1/reports/channel_reports](https://developers.google.com/youtube/reporting/v1/reports/channel_reports)）で `channel_basic_a3` の dimensions は `date`, `channel_id`, `video_id`, `live_or_on_demand`, `subscribed_status`, `country_code`。
- 本リポジトリには既に Reporting API クライアントの基盤がある: `src/youtube_automation/utils/reporting_api.py`（thumbnail impressions/CTR 取得用に Reach 系レポートを利用中）。`channel_basic_a3` への拡張は同モジュールの延長線上で実装可能。
- 既存の dimensions/メトリクス制約根拠コメントの書き口は `src/youtube_automation/utils/ctr_analytics.py:1-18` を参照（Analytics API の制約 → Reporting API への代替経路 → 仕様上の制約列挙、という構造）。

## 5. 影響の現状

| 経路 | 振る舞い | 影響 |
|---|---|---|
| `bench/bench_video_daily.py` | `video_ids` 未指定で呼び出し → 400 → `[FAIL] {days}d: ...` を print して継続 | bench 数値が記録されないだけで他に波及しない |
| `analytics_system.py:128-150` | `try/except + warning` で握り潰す | 動画×日次スナップショット JSON が欠落するが上位処理は完了する |
| `launch_curve.py:188-190` | 保存済み snapshot を `load_latest_daily_snapshot` で読むだけ | 上流の snapshot 欠落で `ConfigError("日次データが見つかりません...")` 停止 |
| URL 長リスク | `filters=video==id1,id2,...` を全動画連結 | チャンネル規模が大きいと URL 長 ~8KB を超えて別系統のエラーが発生する可能性 |

## 6. 推奨アクション（follow-up issue 候補）

実際の issue 起票は本ドキュメントの公開後、手動で実施する。

1. **(a) `get_video_daily_analytics` の API 契約強化**
   - `video_ids=None` を `ConfigError` 化、または `filters` 必須化
   - 同時に「ID 数が一定以上のときは URL 長制限を超えないようにチャンクに分割して複数回 query を発行し、結果をマージ」する仕組みを導入
   - 関連: `src/youtube_automation/utils/video_daily_analytics.py:20-66`
2. **(b) `bench/bench_video_daily.py` の呼び方修正**
   - `video_ids` を事前取得（`get_all_channel_videos()`）してから渡す呼び方に変更
   - もしくは bench 自体を Reporting API ベース（後述 (c)）に切り替え
   - 関連: `bench/bench_video_daily.py:28-40`
3. **(c) 大規模チャンネル向けの収集経路を Reporting API `channel_basic_a3` に寄せる検討**
   - 既存 `src/youtube_automation/utils/reporting_api.py` の Reach 系レポート取得パターンを `channel_basic_a3`（`views` を含む）へ拡張
   - Reporting API は非同期 CSV bulk download（D+2、過去 60 日保持、ジョブ作成後 ~48h backfill）という運用制約があるため、launch curve のように直近データが必要なユースケースとの折り合いを設計フェーズで決める

## 7. 未検証事項（手動フォローアップ）

仮説 2（チャンネル固有要因の有無）は実 API による再現確認が必要。以下を bobble / deepfocus365 等で順次実行する:

```bash
CHANNEL_DIR=/path/to/<channel> uv run python -m bench.bench_video_daily
```

- 期待結果: いずれのチャンネルでも 28d / 90d ともに `[FAIL] ... The query is not supported.` が出る（仮説 1 が真であれば一様に失敗）
- 結果が分かれた場合: rjn 固有要因の存在を別途調査する必要がある（仮説 2 へ戻る）

手動結果は本 issue（#313）のコメントに集約し、follow-up issue 起票時の根拠とする。
