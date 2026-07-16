---
name: thumbnail-research
description: "Use when 収集済み競合サムネイルだけを再生数上位群 vs 下位群で深掘りし、勝ちパターンを抽出するとき。「サムネイル徹底分析」「競合サムネ分析」「サムネ勝ちパターン」で発動。データ収集は /benchmark、チャンネル全体の TTP 分析は /channel-research、生成は /thumbnail、320px 視認性比較は /thumbnail-compare"
---

## Hard Gates

- `data/benchmark_*.json` と、次のいずれかの視覚情報が必要:
  - `docs/benchmarks/thumbnails/` または `data/thumbnail_compare/benchmark/` の JPEG / PNG / WebP 画像
  - 最新 benchmark JSON の `channels[].videos[].thumbnail_analysis` にある既存分析
- `data/benchmark_*.json` が無い場合は、サムネイル画像の有無にかかわらず、再生数による上位群 / 下位群を決められないため、先に `/benchmark` を案内して停止する。
- benchmark JSON があっても視覚情報が 1 件も無い場合は、`/benchmark` をサムネイル取得あり（`--no-thumbnails` を付けない）で再実行するよう案内して停止する。JSON の `thumbnail_url` だけを画像分析の代わりにしない。
- 視覚情報と JSON を `video_id` で対応付けられる動画が 2 件未満なら、上位群 vs 下位群を比較できないためレポートを生成せず、`/benchmark` で対象データを増やすよう案内して停止する。
- データ収集・画像生成・自チャンネル画像との 320px 比較は行わない。外部 API を呼ばず、既存のローカル成果物だけを分析する。

## 完了条件

- 最新 benchmark JSON と対応する視覚情報を使い、再生数上位群 / 下位群を同じ規則で抽出している
- 構図・配色・テキスト配置・視線誘導・キャラ / 被写体の比較を、件数と割合を添えて記録している
- 上位群と下位群の視覚特徴に加え、各特徴が刺激している欲求とその語彙ソースを記録している
- 上位群と下位群の差から、勝ちパターン・負けパターン・判定保留を分離している
- `/thumbnail` が参照画像選定と差分プロンプト作成に使える推奨事項を含む `docs/benchmarks/thumbnail-analysis.md` を生成している
- 使用した入力パス、対象件数、生成先、主要な勝ちパターンをユーザーへ報告している

## Overview

`/benchmark` が収集した競合動画の再生数とサムネイル視覚情報を対応付け、上位群と下位群の差からサムネイル固有の勝ちパターンを抽出する。出力は `/thumbnail` の TTP 入力であり、サムネイルの生成や自チャンネルとの視認性比較はこのスキルでは行わない。

## 実行フロー

### Step 0: 入力存在確認

リポジトリルート（チャンネルの独立リポジトリ）で、以下を実行する:

```bash
latest_benchmark="$(ls -t data/benchmark_*.json 2>/dev/null | head -1)"
printf '%s\n' "$latest_benchmark"
find docs/benchmarks/thumbnails data/thumbnail_compare/benchmark \
  -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) \
  2>/dev/null | sort
```

`latest_benchmark` が空なら `/benchmark` を案内して停止する。画像一覧が空の場合は、最新 JSON の `channels[].videos[].thumbnail_analysis` に非 null の分析があるか確認する。画像も既存分析も無ければ、`/benchmark` を `--no-thumbnails` なしで再実行するよう案内して停止する。

### Step 1: 分析対象の対応付け

最新 benchmark JSON の `channels[].videos[]` から、各動画の `video_id`、`title`、`views`、`thumbnail_analysis` と、親 channel の `slug`、`name` を取得する。

視覚情報は次の優先順で `video_id` に対応付ける:

1. `docs/benchmarks/thumbnails/{slug}_{video_id}.jpg`
2. `data/thumbnail_compare/benchmark/*_{video_id}.jpg`
3. JSON の `thumbnail_analysis`（ローカル画像が無い動画だけ）

ローカル画像は Read（Codex では同等の画像閲覧機能）で開く。画像も `thumbnail_analysis` も対応付かない動画は対象外とし、除外件数を記録する。`thumbnail_url` は対応確認に使えるメタデータだが、このスキルでは URL からダウンロードしない。

### Step 2: 上位群 / 下位群の確定

対応付け済み動画を `views` の降順で並べる。同数の場合は `video_id` の昇順を tie-break とする。

- 対象件数を `N` とする
- 群サイズを `K = ceil(N / 4)` とする
- 先頭 `K` 件を上位群、末尾 `K` 件を下位群とする
- 上位群と下位群の間にある動画は中間群として、パターン判定の分母に含めない

`N < 2` なら Hard Gate に従って停止する。レポートには `N`、`K`、各群の最小 / 最大再生数、動画 ID を記録する。

### Step 3: 同一ルーブリックで画像を分析

上位群と下位群の全動画を、次のカテゴリで同じ粒度に分類する。観察できない項目を推測せず `判定不能` とする。

欲求語彙の選択、欠落時の継続条件、`推定` と根拠の記録は `.claude/skills/channel-research/references/desire-vocabulary.md` をそのまま適用する。

| カテゴリ | 記録する項目 |
|---|---|
| 構図 | 主役位置（左 / 中央 / 右）、主役の画面占有率（小: 33% 未満 / 中: 33〜66% / 大: 66% 超）、奥行き、余白位置 |
| 配色 | 支配色、アクセント色、暖色 / 寒色 / 混合、明 / 中 / 暗、高彩度 / 中彩度 / 低彩度、主役と背景のコントラスト |
| テキスト配置 | 文字なし / 1〜10 文字 / 11 文字以上、言語、書体の印象、上 / 中央 / 下、左 / 中央 / 右、縁取りや影の有無 |
| 視線誘導 | 最初に見る要素、2 番目に見る要素、その移動方向、視線を作る明暗・人物の目線・指差し・パース線 |
| キャラ / 被写体 | 種別、人数 / 個数、顔の向き、カメラ目線の有無、表情、動作、背景との分離度 |
| 刺激している欲求 | 視覚特徴が刺激する欲求、そう判断した理由、欲求語彙のソース（viewer voice / persona / 競合コメント / 競合タイトル） |

各分類値について、上位群と下位群それぞれの `該当件数 / 判定可能件数` と割合を集計する。`判定不能` は割合の分母から除き、件数だけを別記する。

### Step 4: 勝ちパターン判定

分類値ごとに、上位群割合と下位群割合の差を percentage point（pp）で計算する。

- **勝ちパターン**: 上位群で 60% 以上、かつ `上位群割合 - 下位群割合 >= 20pp`
- **負けパターン**: 下位群で 60% 以上、かつ `下位群割合 - 上位群割合 >= 20pp`
- **判定保留**: 上記のどちらにも該当しない、またはいずれかの群で判定可能件数が 0

各勝ち / 負けパターンには、両群の件数・割合・差分、代表動画の `video_id` と画像パス（画像が無い場合は `thumbnail_analysis`）を根拠として添える。再生数との因果関係とは断定せず、この benchmark 母集団で観測した相関として記述する。

### Step 5: レポート生成

`docs/benchmarks/thumbnail-analysis.md` を次の構造で生成する:

```markdown
# ベンチマークサムネイル分析
生成日: YYYY-MM-DD

## 入力とサンプル定義
- benchmark JSON: ...
- 画像ディレクトリ: ...
- 対応付け済み / 除外: N 件 / N 件
- 上位群 / 下位群: K 件 / K 件

## 上位群 vs 下位群
### 構図
### 配色
### テキスト配置
### 視線誘導
### キャラ / 被写体
### 刺激している欲求

## 勝ちパターン
[件数・割合・差分・代表例]

## 負けパターンと判定保留
[件数・割合・差分・代表例]

## /thumbnail への TTP 推奨事項
### 転写基準
### 維持する構造
### テーマに合わせて差し替える要素
### 避ける要素
### 参照候補
[video_id / views / 画像パス / 採用理由]

## データ上の制約
[サンプル数、欠損、相関であり因果ではない旨]
```

`/thumbnail` への推奨事項は、勝ちパターン判定で根拠が出た項目だけを書く。各推奨には、転写対象となる欲求訴求の構造、刺激する欲求、欲求語彙のソースと根拠を含める。転写するのは欲求訴求の構造であり、競合の画像・フレーズなど表面要素の模写は 1 回きりで再現性がないため採用しない。競合のロゴ・透かし・署名・チャンネル固有キャラクターも TTP 対象にせず、構図・配色・文字量・視線誘導と、それらが欲求を刺激する関係へ抽象化する。

### Step 6: 完了報告

次をユーザーへ報告する:

- 使用した benchmark JSON と画像ディレクトリ
- 対応付け済み件数、上位群 / 下位群件数、除外件数
- `docs/benchmarks/thumbnail-analysis.md` の生成
- 主要な勝ちパターンと、`/thumbnail` で参照する次アクション

## 障害時ガイダンス

| 状況 | 対処 |
|---|---|
| benchmark JSON が無い | `/benchmark` を実行してから再実行する |
| JSON はあるが画像も `thumbnail_analysis` も無い | `/benchmark` を `--no-thumbnails` なしで再実行する |
| JSON と画像の `video_id` が対応しない | 最新 JSON と同じ収集結果の画像か確認し、`/benchmark` で揃え直す |
| 対応付けが 2 件未満 | `/benchmark` の対象チャンネル / 収集結果を確認し、比較可能な件数を用意する |

## Cross References

- `/benchmark` → 前工程: 競合動画データとサムネイル画像の収集・更新
- `/thumbnail` → 後工程: `docs/benchmarks/thumbnail-analysis.md` の勝ちパターンと参照候補を TTP 入力として生成
- `/thumbnail-compare` → 生成候補と競合を並べた 320px 視認性比較
- `/channel-research` → タイトル・動画尺・投稿・コメントを含むチャンネル全体の TTP 分析
