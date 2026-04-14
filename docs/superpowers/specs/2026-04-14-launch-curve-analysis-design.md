# Launch Curve 分析 設計仕様

**日付:** 2026-04-14
**フェーズ:** Phase 1 / 4（分析強化プロジェクト）
**ステータス:** Draft

## 背景

現状の `utils/analytics_analyzer.py`（453 行）は `statistics` モジュールのみで集計しており、`pandas` / `matplotlib` / `seaborn` は依存に含まれているが未使用。日次データ（`dimensions='day'`）も既に API から取得可能だが分析に使われていない。

YouTube アルゴリズムは投稿後 24-48 時間の初速で配信量を決めるため、**「新作の N 日時点の数字が過去ベンチマークと比べて良いか悪いか」を即判定する仕組み** が運営判断に最も効く。これを Phase 1 として独立実装する。

## スコープ（Phase 1）

以下の CLI 1 本を提供する:

```
yt-launch-curve --video VIDEO_ID     # 特定動画 vs 過去ベンチマーク
yt-launch-curve --latest             # 最新公開動画を自動判定
yt-launch-curve --all                # 全動画を重ね描き（ベンチマーク把握用）
```

出力:
- PNG: `data/analytics/launch_curves/YYYY-MM-DD_<video_id>.png`
- stdout: 判定サマリー（例: `7日時点 累積 views 1,234 — 中央値の 1.3倍 (上位25%)`）

**非スコープ（後続 Phase）:**
- チャンネル全体トレンド・異常検知（Phase 2）
- テーマ/コレクション別曲線の平均化（Phase 3）
- サムネ × CTR 相関（Phase 4）

## データパイプライン

### 入力

| ソース | 内容 |
|--------|------|
| YouTube Analytics API (`dimensions='video,day'`) | 動画別・日次の views / impressions / impression_ctr |
| Data API v3 / 既存メタデータ | 各動画の `publishedAt` |

### 現状確認（実装着手前）

既存 `ctr_analytics.py` / `video_analytics.py` が **動画別 × 日次** の粒度でデータを保存しているかを確認する。保存していない場合は collector を拡張し、`data/analytics/daily_per_video/YYYY-MM-DD.json`（または Parquet）として永続化する。

### 変換（新規 util: `launch_curve_data.py`）

```python
def build_launch_curve_frame(data_dir: Path) -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      video_id, published_at, date, days_since_publish,
      daily_views, cumulative_views, daily_impressions, ctr
    """
```

`days_since_publish = (date - published_at).days` を計算し、全動画の時間軸を揃える（= "launch curve"）。

## 分析・可視化

### ベンチマーク計算（`launch_curve_analyzer.py`）

各 `days_since_publish` 値について、全動画の累積 views 分布から:
- 中央値（p50）
- 25 / 75 パーセンタイル（IQR バンド）
- 10 / 90 パーセンタイル（外側バンド、参考表示）

対象動画の判定:
- `対象の累積views / 同日齢の中央値` を倍率として表示
- 四分位で位置づけ（`上位25%` / `中央値付近` / `下位25%`）

### 可視化（`launch_curve_plotter.py`）

matplotlib で以下を 1 枚の PNG に描画:

1. 全動画カーブを薄いグレー線で重ね描き（`alpha=0.3`）
2. 中央値ラインを実線、IQR を塗りバンド（`fill_between`）
3. 対象動画を太線 + マーカーでハイライト
4. タイトルに判定サマリー

対象メトリクス（1 PNG に 3 つのサブプロット）:
- 累積 views
- 日次 impressions
- impression CTR（3 日移動平均で平滑化）

表示窓: デフォルト 0-30 日、`--window N` で拡張可能（BGM チャンネルは寿命が長いため 90 日も想定）。

## モジュール配置

```
src/youtube_automation/utils/
  launch_curve_data.py       # DataFrame 構築（pandas）
  launch_curve_analyzer.py   # ベンチマーク計算・判定ロジック
  launch_curve_plotter.py    # matplotlib 描画
src/youtube_automation/scripts/
  launch_curve.py            # CLI エントリポイント
tests/
  test_launch_curve_data.py
  test_launch_curve_analyzer.py
```

`pyproject.toml` `[project.scripts]` に以下を追加:
```toml
yt-launch-curve = "youtube_automation.scripts.launch_curve:main"
```

既存 `analytics_analyzer.py` には手を入れない。別系統として独立させることで:
- 既存レポートフローに影響を与えない
- pandas ベースの新実装の土台を作る（Phase 2 以降で再利用）

## エラーハンドリング

- 日次動画データが未収集 → 明示的メッセージで `yt-analytics --days N` 実行を案内
- 対象動画が未公開 / publishedAt なし → `ConfigError` 系で早期失敗
- 同日齢ベンチマーク動画数が < 3 → ベンチマーク表示を抑制し「サンプル不足」を表示

## テスト方針

`tests/fixtures/sample_analytics/` に以下を用意:
- 10 動画 × 30 日分の合成日次データ（既知の分布）
- 既知の `published_at`

`test_launch_curve_data.py`:
- DataFrame 構築で `days_since_publish` が正しく計算される
- 欠損日（データなし）の挙動

`test_launch_curve_analyzer.py`:
- 既知分布に対する p50 / IQR が正しい
- 判定テキスト（「上位25%」等）が境界値で正しい

描画テストは PNG 生成の smoke test のみ（pixel diff はしない）。

## 依存

追加依存なし（`pandas` / `matplotlib` は既に `pyproject.toml` に宣言済み）。

## ロールアウト

1. `launch_curve_data.py` + テスト
2. 既存 collector の日次動画データ保存確認／必要なら拡張
3. `launch_curve_analyzer.py` + テスト
4. `launch_curve_plotter.py`（描画のみ、テストは smoke）
5. `scripts/launch_curve.py`（CLI）+ `pyproject.toml` エントリ追加
6. `.claude/skills/analyze/` への案内追記（オプション）

## 将来拡張との接続

- Phase 2（トレンド・異常検知）: `launch_curve_data.py` の DataFrame をチャンネル合計に再集計して再利用
- Phase 3（テーマ別曲線）: ベンチマーク計算関数に `groupby='theme'` を追加
- Phase 4（サムネ相関）: 本 Phase で得られる「N 日時点の累積 views」を目的変数として使用
