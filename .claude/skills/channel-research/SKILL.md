---
name: channel-research
description: "Use when /benchmark と /viewer-voice の TTP ベンチマークデータを徹底分析するとき。「競合分析」「チャンネルリサーチ」「TTP 対象抽出」で発動。データ収集・更新は /benchmark（未実行なら先に案内）"
---

## Overview

`/benchmark` と `/viewer-voice` で収集したベンチマークデータ + コメントデータを読み込み、徹底的に分析してレポートを生成する。
初回チャンネル開設フローは `/channel-new` で TTP 対象確認まで完結するため、本スキルは深掘り分析や方向性の再検討が必要なときに追加で実行する。

## 完了条件

Step 2〜5 の分析結果を `docs/channel-research.md` に保存し（Step 6）、Step 7 の次アクション案内を提示した時点で完了。

## Subagent 委譲ゲート

メインエージェントは Step 0 の入力データ存在確認、成果物存在確認、次アクション案内だけを担当する。`data/benchmark_*.json`、`data/comments_*.json`、`docs/benchmarks/*.md`、`docs/benchmarks/thumbnails/` の読み込みと Step 2〜6 の分析・レポート生成は channel-research subagent へ委譲する。

メインエージェントは競合データやコメント生データ、ベンチマーク Markdown 全文、サムネイル画像を直接 Read しない。subagent は `docs/channel-research.md` を生成し、完了報告では成果物パス、分析した入力パス、主要な TTP パターンと推奨事項の要約だけを返す。生データ本文やコメント本文の大量引用をメイン会話へ返さない。

## 前提

`/channel-new` で TTP 対象確認が完了し、`/benchmark` と `/viewer-voice` を実行済みで、以下のデータが存在すること:

- `data/benchmark_YYYYMMDD.json` — 競合チャンネルの動画データ（無ければ先に `/benchmark` を案内して停止）
- `data/comments_YYYYMMDD.json` — 競合動画のコメント（無ければ先に `/viewer-voice` を案内して停止）
- `docs/benchmarks/*.md` — 各チャンネルの個別レポート（無ければ先に `/benchmark` を案内して停止）
- `docs/benchmarks/thumbnails/` — サムネイル画像（ある場合。無ければ Step 4 は `.md` 内の `thumbnail_analysis` 参照に切り替え）

存在確認は Step 0 で機械的に行い、欠けている種別が 1 つでもあれば Step 1 以降へ進まない。

## TTP 原則（ベンチマーク参照）

ベンチマーク分析の根本姿勢は **TTP（徹底的にパクる）**。
パクるのは「テーマそのもの」ではなく、競合動画に内在する **構造・パターン・型** —
タイトルのフォーマット、サムネイルの構図、動画尺の分布、投稿スケジュール、
コメントに現れる利用シーンの語彙、勝ち動画の共通要素。
これらをそのまま自チャンネルの初期値として転写し、差別化はその上に重ねる。

既存実装の参照: `.claude/skills/thumbnail/SKILL.md` の `single_step` モード（TTP 推奨実装）、
`src/youtube_automation/utils/metadata_generator.py` の TTP 形式タイトル生成。

## Instructions

**実行場所**: リポジトリルート（チャンネルの独立リポジトリ）

### Step 0: 入力データ存在確認（必須）

```bash
ls data/benchmark_*.json data/comments_*.json docs/benchmarks/*.md
```

欠けているデータ種別ごとに以下を案内して停止する:

- `data/benchmark_*.json` が無い → 先に `/benchmark` を実行するよう案内
- `docs/benchmarks/*.md` が無い → 先に `/benchmark` を実行するよう案内
- `data/comments_*.json` が無い → 先に `/viewer-voice` を実行するよう案内

全種別が揃っている場合のみ Step 1 へ進む。

### Step 1: 分析 subagent への委譲

メインエージェントは以下の入力パスを subagent に渡す。読み込みは subagent が担当し、メインエージェントは中身を直接 Read しない:

1. `data/` 内の更新時刻が最新の `benchmark_*.json`（`ls -t data/benchmark_*.json | head -1` で取得できるもの）
2. `data/` 内の更新時刻が最新の `comments_*.json`（`ls -t data/comments_*.json | head -1` で取得できるもの）
3. `docs/benchmarks/` 内の全 `.md` ファイル
4. 存在する場合は `docs/benchmarks/thumbnails/`

subagent への完了条件は `docs/channel-research.md` の生成に絞る。完了報告形式は `status: success | failure`、`inputs`、`artifacts`、`summary`、`errors` とする。

### Step 2: 競合マトリクス作成

テーブル形式で全チャンネルを比較:

```
| チャンネル | 登録者 | 動画数 | 平均再生数 | 日次再生 | ER% | 投稿間隔 | 動画尺 |
```

加えて以下を分析:
- **成長段階**: 各チャンネルの推定フェーズ（立ち上げ/成長/安定/停滞）
- **投稿トレンド**: 加速/減速/安定
- **勝ちパターン**: 高再生数動画の共通点
- **TTP 対象**: 上記から自チャンネルに転写すべき構造・パターン・型を明示（後段 `/channel-new` 方向性検討モードの入力になる）

### Step 3: コンテンツ戦略分析

**タイトル分析**:
- フォーマットパターン（テーマ+ジャンル+用途+尺 等）
- 頻出ワード・キーワード
- 成功タイトル vs 平均タイトルの違い

**動画尺の傾向**:
- チャンネル別の平均尺
- 尺と再生数の相関

**テーマ・世界観**:
- 頻出タグ分析
- 各チャンネルの世界観マッピング
- 未開拓のテーマ領域（ブルーオーシャン）

**投稿スケジュール**:
- 曜日・時間帯の傾向（published_at から推定）

### Step 4: サムネイル分析

subagent が `docs/benchmarks/thumbnails/` のサムネイル画像を Read（Codex では同等の画像閲覧機能）で読み込み:

- **構図パターン**: キャラ配置、テキスト位置、背景スタイル
- **色使い**: 暖色/寒色、明暗、彩度
- **テキスト**: フォント感、文字数、言語
- **共通成功パターン**: 高再生動画のサムネイル特徴
- **差別化の余地**: 競合がやっていないスタイル

サムネイル画像がない場合は subagent が `docs/benchmarks/*.md` 内の `thumbnail_analysis` セクションを参照。

### Step 5: 視聴者インサイト分析

コメントデータから以下を抽出:

**利用シーン**: いつ・どこで・何をしながら聴いているか
**感情反応**: どんな感情を表現しているか（癒し、懐かしさ、集中等）
**リクエスト**: 視聴者が求めているもの（テーマ、長さ、頻度等）
**言語分布**: コメントの言語割合（国際性の指標）
**エンゲージメント**: 深いコメント vs 浅いコメントの比率

### Step 6: レポート生成

subagent は全分析結果を `docs/channel-research.md` に保存:

```markdown
# チャンネルリサーチレポート
生成日: YYYY-MM-DD

## 競合マトリクス
[Step 2 のテーブル]

## コンテンツ戦略
[Step 3 の分析]

## サムネイルパターン
[Step 4 の分析]

## 視聴者インサイト
[Step 5 の分析]

## 機会領域（ブルーオーシャン）
- 競合がカバーしていないテーマ
- 未開拓のフォーマット
- 差別化可能なスタイル

## 推奨事項
- ポジショニング案（3案程度）
- リスクと機会
```

### Step 7: 次アクション案内

メインエージェントは `docs/channel-research.md` の存在を確認し、subagent の要約をもとに次を案内する:

「分析レポートが完成しました。方向性を見直す場合は `/channel-new`（方向性検討モード）、現在の方針で制作に進む場合は `/wf-new` に進めます。」

## 障害時ガイダンス

競合データはローカルの `data/` / `docs/benchmarks/` を分析するため外部 API には依存しない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/benchmark`・`/analytics-collect` 等を実行して入力を用意 |

## Cross References

- `/channel-new` → 前提: TTP 対象確認 / 初回 config / persona / branding
- `/benchmark` → 前提: 承認済み TTP 対象の動画データ収集
- `/viewer-voice` → 前提: コメント収集と視聴者インサイト分析
- `/channel-new`（方向性検討モード） → 任意: 方向性の再検討
- `/wf-new` → 初回コレクション制作
