---
name: discover-competitors
description: Use when 新規チャンネルの競合候補を YouTube Data API で自動発掘したいとき、複数のニッチ仮説を並行検証したいとき。「競合候補」「競合発掘」「ニッチ検証」「ライバル探し」「discover-competitors」など、ニッチキーワードから競合候補リストを自動生成する場面で使用すること。/channel-new Step 5 の前段としても、独立した並行検証ツールとしても使える
---

## Overview

ニッチキーワード（複数可）を渡すと、登録者数レンジ・最終投稿日でフィルタしたうえで
キーワード一致率・エンゲージメント率・更新頻度・登録者帯近さの 4 軸スコアで
競合候補チャンネルをランキング化する CLI ラッパー。

- 入力: ニッチキーワード（カンマ区切り）+ フィルタ条件
- 出力: ランキング付き Markdown + 同名 CSV（スコア内訳列付き）
- 想定時間: 5 分以内（API quota 約 660 units / 実行）

`/channel-new` Step 5 で競合 URL を人手で集めていた工程を置き換える。複数のニッチ仮説を
並行検証したい場合は、このスキルを単独で何度も走らせる。

## Instructions

### Step 1: キーワード設計

ユーザーから対象ニッチを聞き出し、3-5 個の検索キーワードに分解する:

- ジャンル名そのもの（例: `lo-fi study`）
- 用途・シーン（例: `chill beats`, `study music`）
- 雰囲気・ムード（例: `cozy jazz`, `rainy afternoon`）

英語で 1-3 単語のクエリが最も精度が高い（YouTube 検索の挙動に倣う）。

### Step 2: フィルタ条件の決定

| フラグ | 既定値 | 推奨用途 |
|-------|--------|---------|
| `--min-subscribers` | 0 | 小規模チャンネルも拾うなら 0、競合検証なら 10K 以上推奨 |
| `--max-subscribers` | 10,000,000 | 自分の目標帯の 10 倍以内に絞ると参考にしやすい |
| `--posted-within-days` | 30 | 「動いている競合」のみ。1 年単位で見たいなら 365 |
| `--top` | 20 | レポートに出す件数 |
| `--per-keyword` | 20 | search.list の maxResults（合計クエリ数 = keywords × per-keyword） |

### Step 3: 実行

チャンネルディレクトリ配下から実行する（`auth/token.json` が存在する前提）:

```bash
uv run yt-discover-competitors \
  --keywords "lo-fi study,chill beats,study music" \
  --min-subscribers 10000 --max-subscribers 1000000 \
  --posted-within-days 30 --top 20 \
  --output research/lo-fi-discovery.md
```

出力ペア:
- `research/lo-fi-discovery.md` — Markdown ランキングテーブル
- `research/lo-fi-discovery.csv` — スコア内訳付き CSV（14 列）

### Step 4: 結果の活用

- ユーザーに Markdown を提示し、承認を得る
- 採用した候補を `config/channel/analytics.json` の `benchmark.channels` に追加（`/channel-new` Step 5 と合流）
- 並行検証なら、ニッチ仮説ごとに `--output research/{niche}-discovery.md` で別ファイルに分けて比較する

## API コスト

1 回実行あたり概ね 660 units（10,000/日 quota の 6.6%）:
- search.list × keywords: 100 units × N
- channels.list: 1 unit × 候補数（バッチ）
- videos.list: 1 unit × 候補数（直近 5 本まとめて 1 リクエスト）

並行検証で連発するときは quota 残量に注意。

## スコープ外（他スキルへバトン）

- 競合の動画詳細分析 → `/benchmark`
- 視聴者コメント分析 → `/viewer-voice`
- 方向性決定・config 生成 → `/channel-direction` / `/channel-setup`
- ベンチマーク再収集 → `/benchmark`

このスキルは **発掘**だけに責任を持つ。深堀分析は専用スキルにバトンを渡す。

## Cross References

- `/channel-new` Step 5: 新チャンネル開設フロー内での前段呼び出し
- `/benchmark`: 発掘済みチャンネルのベンチマークデータ収集
- `/channel-research`: 収集データの徹底分析
