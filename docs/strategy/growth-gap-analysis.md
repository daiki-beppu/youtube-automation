# YouTube 成績向上 — 成長レバー × 既存ツールのギャップ分析

チャンネル成績（インプレッション・CTR・視聴維持・登録者・再生数）を伸ばすために、成長レバーごとに「既存機能で何がカバーされているか / 何が足りていないか」を整理するギャップ分析ドキュメント。

- **想定読者**: チャンネル運営者（リポジトリオーナー）と、改善 issue を起票・実装する AI エージェント
- **更新方針**: 大きな機能追加・戦略転換のタイミングで随時更新
- **関連**: #1802（本ドキュメントの起票 issue）、#1754（TTP・企画リサーチ系トラッキング）

## 0. 前提: 指標取得の構造的制約

すべてのギャップ判断はこの制約を前提にする。「取れないデータ」を前提にした機能要望は実装不能なので、起票前にここを確認すること。

| 制約 | 内容 | 実装上の根拠 |
| --- | --- | --- |
| サムネ CTR / インプレッションは Analytics API v2 で取得不可 | `videoThumbnailImpressions*` は dimensions 全パターンで 400 拒否 | `utils/ctr_analytics.py`, `utils/channel_analytics.py` のコメント |
| CTR / Imp は Reporting API v1 のみ | Reach 系レポート（`channel_reach_basic_a1` 等）の非同期 CSV。**D+2 ラグ・データ保持 60 日・要ジョブ事前作成**（初回は取得まで最大 48h） | `utils/reporting_api.py`, `yt-analytics --include-reporting` |
| 競合の CTR / 視聴維持 / 平均視聴時間は取得不能 | Data API v3 は公開統計（views / likes / comments）のみ | `/benchmark`, `/postmortem` SKILL.md に明記 |
| 競合比較の代替手段 | 自チャンネル中央値との比較（`yt-launch-curve`）+ サムネ視認性の定性比較（`/thumbnail-compare`） | 設計済みの回避策 |

## 1. 成長レバー × 既存機能マッピング

| # | 成長レバー | 対応する既存スキル / CLI | データソース | カバー度 |
| --- | --- | --- | --- | --- |
| L1 | インプレッション獲得 | `/analytics-collect --include-reporting`（動画別 Imp）、traffic source 収集（`insightTrafficSourceType/Detail`）、`/benchmark`（競合の露出獲得パターン）、`/short` `/short-release`（流入面の追加） | Reporting API v1 / Analytics API v2 / Data API v3 | ◯ 計測は可、施策検証は弱い |
| L2 | CTR | `/thumbnail`（TTP ベース生成）、`/thumbnail-compare`（320px 視認性）、`yt-thumbnail-correlate`（特徴量×CTR 相関）、`/alignment-check`（サムネ×タイトル×ムード整合）、`/postmortem`（CTR 閾値ルーブリック） | Reporting API v1 + サムネ画像特徴量 | ◎ 最厚のレバー |
| L3 | 視聴維持 | retention 収集（`audienceWatchRatio` / `relativeRetentionPerformance`）、`/video-analyze`（Gemini によるフック・BGM 展開解析）、`/viewing-scene`（シーン別の最適尺設計） | Analytics API v2 / Vertex AI | ◯ 計測◎、原因照合が手動 |
| L4 | 回遊・セッション | `/playlist`（`yt-playlist-manager`）、`/video-description`（Complete Collection 導線）、カード指標収集（`cardImpressions/Clicks/ClickRate`）、`/pinned-comment` `/comments-reply` `/community-post` | Analytics API v2 / Data API v3 | △ 導線は張れるが効果測定が薄い |
| L5 | 登録転換 | `subscribersGained/Lost` の day・video 単位収集、`yt-channel-trend`（日次 subs 移動平均・z-score 異常検知） | Analytics API v2 | △ データ有り、転換分析なし |
| L6 | SEO・メタデータ | `/video-description`（SEO 最適化概要欄）、`/metadata-audit`、`yt-title-duplicate-check`、localizations 同期（`/channel-new` 設定 push、`yt-shorts-bulk-update-loc`） | ローカル config / Data API v3 | ◯ 生成◎、検索流入との突合なし |
| L7 | 投稿頻度・タイミング | `/benchmark`（競合の投稿間隔）、`yt-launch-curve`（投稿後 N 日の初速比較）、`yt-theme-compare`（テーマ別初速・ロングテール） | Data API v3 / 自チャンネル履歴 | △ 頻度の観測のみ、時刻・曜日分析なし |

横断（レバー非依存）の既存資産: `/analytics-analyze`（全レバーの統合分析・戦略提案）、`/channel-research` + `/viewer-voice` + `/audience-persona-design`（誰に何を作るかの上流）、`/collection-ideate`（企画への落とし込み）、`/postmortem`（不振動画の切り分け）。

## 2. レバー別ギャップ分析

各ギャップに推奨アクション種別を付す: **運用改善**（既存スキルの使い方・頻度の改善）/ **新規開発**（機能追加 issue の起票対象）/ **手動補完**（API 制約等で自動化不能、手順化して人が回す）。

### L1: インプレッション獲得

- **足りないもの**
  - Imp の長期履歴: Reporting API の保持は 60 日。`data/analytics_data_*.json` スナップショットに残るが、スナップショット横断で Imp 推移を引く分析器がない → **新規開発**（G6）
  - トラフィックソース別の露出分析: source type 別 views は取れるが、「ブラウズ/おすすめ面で露出が増えた/減った」をレポートに定型出力する仕組みがない → **運用改善**（`/analytics-analyze` の分析観点に追加）
  - Shorts からロング動画への送客効果測定 → **新規開発**（G6 に含める）

### L2: CTR

- **足りないもの**
  - サムネ A/B テスト: YouTube の Test & Compare は API 非対応。Studio での手動設定 + 結果の手動記録しかない → **手動補完**（G3: 手順とテンプレの整備）
  - `yt-thumbnail-correlate` の母数: 動画数が少ないチャンネルでは相関が出ない。チャンネル横断（複数チャンネルのデータ統合）の相関分析はない → **新規開発**（優先度低。単一チャンネルの動画数増を待つ方が安い）
- **運用上の注意**: Reporting ジョブ未作成のチャンネルは CTR が永遠に欠測する。`/setup`・`yt-doctor` での検知は済みか確認し、新チャンネル開設時のチェックリストに含める → **運用改善**

### L3: 視聴維持

- **足りないもの**
  - retention curve × シーン照合の自動化: `audienceWatchRatio`（elapsedVideoTimeRatio 単位）と `/video-analyze` のシーンタイムライン・BGM 展開は別々に存在し、「drop 地点 = どのシーン/曲か」の突合が手動 → **新規開発**（G2）
  - 維持率からの逆フィードバック: drop 分析の結果を次コレクションの BGM 構成（`/suno` / `/lyria` プロンプト）へ反映する定型経路がない → **運用改善**（`/postmortem` → `/collection-ideate` のバトンに含める）

### L4: 回遊・セッション

- **足りないもの**
  - プレイリスト単位の analytics: `playlist` dimension での views / 平均視聴時間を収集していない。Complete Collection 戦略の効果（プレイリスト経由視聴）が観測できない → **新規開発**(G4)
  - エンドスクリーンの管理・分析: 設定も効果測定も未対応（API は endScreen 編集非対応のため設定は手動）→ 計測側のみ **新規開発**候補、設定は **手動補完**
  - カード指標は収集済みだが `/analytics-analyze` のレポート断面に出ていない → **運用改善**

### L5: 登録転換

- **足りないもの**
  - 動画別の登録転換率（subscribersGained / views）の定点レポート: データは `strategic_analytics.py` で取得済みなのに、どの動画が登録を生むかのランキング・傾向分析がない → **新規開発**（G1。既存データのみで完結、最も安い）
  - `subscribedStatus` dimension（登録済み/未登録視聴者の比率）の未収集: 「未登録者に見られているのに転換しない」のか「登録者しか見ていない」のかを切り分けられない → **新規開発**（G1 に含める）
  - チャンネルページ・トレーラー最適化: 支援機能なし → **手動補完**（優先度低）

### L6: SEO・メタデータ

- **足りないもの**
  - 検索流入キーワードの分析: `insightTrafficSourceDetail`（YT_SEARCH）で検索語データは収集し得るが、「どのキーワードで流入 → どのタイトル/タグに反映すべきか」のレポートがない → **新規開発**（G5）
  - 多言語（localizations）の効果測定: 言語別・国別の視聴データ（`country` dimension は収集済み）と localizations 設定の突合がない → **運用改善**（`/analytics-analyze` の観点追加）

### L7: 投稿頻度・タイミング

- **足りないもの**
  - 時間帯・曜日別のパフォーマンス分析: 現収集は day 単位のみで、公開時刻と初速の関係を観測できない（Analytics API に時刻 dimension がなく、公開時刻メタデータ × 初日 views の突合になる）→ **新規開発**（優先度低: BGM 系は evergreen 消費でタイミング感度が低い仮説。まず `yt-launch-curve` で公開曜日別の初速差を手動確認 → 差が出たら起票）
  - 投稿頻度 × 成長率の相関: `/benchmark` で競合の投稿間隔は取れているが、自チャンネルの頻度変化と subs/views 成長の関係分析がない → **運用改善**（`yt-channel-trend` の結果と突き合わせる分析観点を `/analytics-analyze` へ）

### 横断ギャップ

- **TTP トラッキングの統合不在**（#1754 の領域): 「どの競合のどのパターンを、どの企画に転写し、どんな成果（CTR/Views）だったか」が `plan_proposals.md` / `workflow-state.json` / `weekly-vote-log.json` に断片化。パターン単位の勝率が測れない → **新規開発**（G7）
- **成長 KPI の単一ビュー不在**: 各レバーの現在値と前週比を 1 枚で見る定点ダッシュボードがない。`reports/analysis_*.md` は都度生成の読み物で、レバー別 KPI の時系列俯瞰ではない → **新規開発**（G6 と統合可能）

## 3. 推奨運用ループ

既存スキルだけで today から回せる標準ループ。`docs/workflow-cheatsheet.md` の制作フェーズ図を成長運用側から補完するもの。

```
┌─────────────────── 週次ループ（成績向上のコア） ───────────────────┐
│                                                                      │
│  /analytics-collect --include-reporting     … データ最新化（CTR は D+2 ラグ考慮）
│        ↓                                                             │
│  /analytics-analyze                         … 分析 + 戦略提案（reports/analysis_*.md）
│        ↓                                                             │
│  不振動画あり？ ── yes → /postmortem        … CTR/Imp/Ret で症状切り分け
│        │                     ↓                                       │
│        │              /thumbnail-compare or /alignment-check or /video-analyze
│        │                     ↓ （原因に応じた個別監査）              │
│        ↓ no                  ↓                                       │
│  /collection-ideate ←────────┘              … 分析結果を次企画へ反映
│        ↓                                                             │
│  制作（/wf-new → /wf-next → /thumbnail → 公開 /video-upload）        │
│        ↓                                                             │
│  公開直後: /playlist・/pinned-comment・/community-post（回遊導線）   │
│        ↓                                                             │
│  T+7: yt-launch-curve で初速を過去中央値と比較 → 週次ループ先頭へ    │
└──────────────────────────────────────────────────────────────────────┘

月次: /benchmark → /channel-research         … 競合追従・機会領域の再確認
      /viewer-voice                          … コメントから視聴者インサイト更新

四半期 or 方向性見直し時:
      /audience-persona-design（+ viewing-scene）… ペルソナ・視聴シーン再設計
      /discover-competitors                  … 競合プールの入れ替え
      /alignment-check                       … チャンネル全体の整合性監査
```

運用ルール:

1. **週次ループを止めない**ことが最優先。`/collection-ideate` は analytics 鮮度切れで停止する設計（`freshness_days` 既定 7 日）なので、収集→分析を週 1 で回すこと自体が制作パイプラインの前提になる
2. CTR 判断は **D+2 ラグ**を踏まえ、公開後 3 日未満の動画では下さない（`/postmortem` のルーブリックに従う）
3. ペルソナ系（viewer-voice → audience-persona-design → viewing-scene）は硬い依存チェーン。未整備だと `/collection-ideate` が fallback/minimal mode に劣化するため、新チャンネルでは最初の四半期内に一巡させる

## 4. ギャップ優先度（効果 × 実装コスト）

効果 = 成績指標への期待インパクト、コスト = 実装・運用の手間。**1 ギャップ = 1 issue** で起票できる粒度で記述する。

| ID | ギャップ | レバー | 種別 | 効果 | コスト | 優先度 | 起票 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | 登録転換分析（動画別転換率 + subscribedStatus） | L5 | 新規開発 | 中〜高 | **低** | ★★★ | #1816 |
| G2 | retention drop × シーン/BGM 自動照合 | L3 | 新規開発 | 高 | 中 | ★★★ | #1817 |
| G3 | サムネ A/B（Test & Compare）手動運用の手順化 | L2 | 手動補完 | 高 | **低** | ★★★ | #1808 |
| G4 | プレイリスト単位 analytics 収集 | L4 | 新規開発 | 中 | 低 | ★★ | #1818 |
| G5 | 検索流入キーワードレポート | L6 | 新規開発 | 中 | 低〜中 | ★★ | #1804 |
| G6 | 成長 KPI 定点ビュー（Imp 長期履歴・レバー別週次推移） | L1・横断 | 新規開発 | 中 | 中 | ★★ | #1819 |
| G7 | TTP トラッキング統合（参照パターン → 企画 → 成果） | L2・横断 | 新規開発 | 高 | 中〜高 | ★★ | #1754 で継続検討 |
| G8 | 時間帯・曜日別の公開タイミング分析 | L7 | 新規開発 | 低〜中 | 中 | ★ | 未起票（手動確認が先） |

### 上位ギャップの起票粒度メモ

- **G1 登録転換分析**: `strategic_analytics.py` の video 単位 `subscribersGained` と views から転換率ランキングを算出し `/analytics-analyze` のレポート断面に追加する。あわせて `subscribedStatus` dimension の収集 Mixin を追加。期待効果: 「登録を生む動画の型」が特定でき、企画選定（`/collection-ideate`）の入力になる。既存データで完結するため最安
- **G2 retention × シーン照合**: `retention_analytics.py` の `audienceWatchRatio`（elapsedVideoTimeRatio）と `data/video_analysis/<slug>/<id>.json` の scene_timeline / bgm_arc を突合し、drop 地点のシーン・曲を特定するレポートを `/postmortem` または `/video-analyze` に追加。期待効果: 視聴維持の改善が「どの曲・どの展開を変えるか」の具体アクションに変わる
- **G3 サムネ A/B 手順化**: Studio の Test & Compare 設定手順・対象選定基準（postmortem で CTR 起因と判定された動画を優先）・結果記録テンプレ（`docs/plans/` 配下）をスキル or ドキュメント化。期待効果: CTR レバーに API 制約を回避した実験経路が通る。実装は文書のみで最安
- **G4 プレイリスト analytics**: Analytics API の `playlist` dimension で views / 平均視聴時間を収集する Mixin を追加し、Complete Collection 戦略の効果を可視化。期待効果: 回遊レバー（L4）に初めて計測が通る

## 5. このドキュメントの使い方

1. 改善 issue を起票する前に §0（制約）と §4（優先度表）を確認し、既存 issue・レバーとの重複を避ける
2. 起票は `/issue`（1 ギャップ = 1 issue、§4 のメモを概要に転写）
3. 機能追加・戦略転換で状況が変わったら §1 のマッピング表と §4 の表を更新する
