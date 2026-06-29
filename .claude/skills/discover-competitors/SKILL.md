---
name: discover-competitors
description: "Use when 新規チャンネルの追加競合候補を YouTube Data API で自動発掘したいとき、複数のニッチ仮説を並行検証したいとき。「競合候補」「競合発掘」「ニッチ検証」「ライバル探し」「discover-competitors」など、ニッチキーワードから競合候補リストを自動生成する場面で使用すること。/channel-new で TTP 対象を確認した後の任意後続スキルとしても、独立した並行検証ツールとしても使える"
---

## Overview

ニッチキーワード（複数可）を渡すと、登録者数レンジ・最終投稿日でフィルタしたうえで
キーワード一致率・エンゲージメント率・更新頻度・登録者帯近さの 4 軸スコアで
競合候補チャンネルをランキング化する CLI ラッパー。

- 入力: ニッチキーワード（カンマ区切り）+ フィルタ条件
- 出力: ランキング付き Markdown + 同名 CSV（スコア内訳列付き）
- 想定時間: 5 分以内（API quota 約 660 units / 実行）

`/channel-new` の標準フローでは実行しない。TTP 対象確認後に追加の競合候補を広げたい場合や、複数のニッチ仮説を
並行検証したい場合に、このスキルを任意で走らせる。

## Instructions

### Step 1: キーワード設計

ユーザーから対象ニッチを聞き出し、**3-5 個（多くて 8 個まで）の検索キーワード**に分解する。
キーワード数は API コストに線形効くので、ニッチが鮮明なら 3 個で十分。

#### 1-A. シード語の収集元

既存チャンネルの場合と新規チャンネル企画の場合で seed の抽出元が異なる:

| ケース | 抽出元 | 具体的な参照先 |
|--------|--------|---------------|
| **既存チャンネル**で競合再発掘 | チャンネル config | `config/channel/content.json` の `genre` / `tags.base` / `descriptions.template_note` |
| **既存チャンネル**で類似帯探索 | 既存ベンチマーク | `config/channel/analytics.json` の `benchmark.channels` を YouTube で開いてタイトル頻出語を抽出 |
| **新規チャンネル企画** | `/channel-new` の TTP メモと初期 config | ニッチ仮説の `genre_keywords` / `target_scene` |
| **完全に手探り** | ユーザー宣言 | 「夜カフェ系の lo-fi」のような自然文を Claude が分解 |

config からの抽出例（rjn）:
- `genre`: `Lo-fi Jazz Bar, Late Night Lofi, Lounge Lo-fi` → seed: `lofi jazz bar`, `late night lofi`, `lounge lofi`
- `tags.base`: `lofi jazz`, `late night lofi`, `chill jazz` → そのまま seed として流用可能

#### 1-B. クエリ展開の 4 軸

シード語をそのまま使うだけでは取りこぼしが出るので、以下の 4 軸で揺らぎを足す:

| 軸 | 例（lo-fi jazz bar 軸） |
|----|-----------------------|
| **ジャンル直接** | `lofi jazz`, `lo-fi jazz` |
| **用途・シーン** | `study music`, `focus music`, `作業用bgm` |
| **雰囲気・ムード** | `late night lofi`, `cozy jazz`, `rainy lofi` |
| **アクティビティ** | `lofi for reading`, `lofi cafe` |

#### 1-C. 多言語展開（必要に応じて）

ターゲット視聴者が多言語にまたがるなら、**主要 2-3 言語の組み合わせ**を seed に加える:

| 言語 | lo-fi 例 |
|------|---------|
| en | `lofi`, `chill beats` |
| ja | `作業用bgm`, `集中用bgm` |
| zh | `轻音乐`, `白噪音` |
| ko | `로파이`, `집중 음악` |

ただし英語キーワードのほうが視聴者規模が大きく、API 検索が安定するので、英語 + 自言語の 2 言語混在で十分なケースが多い。

#### 1-D. NG パターン

- ❌ **広すぎる**: `music`, `bgm` 単独 → 関係ないチャンネルが大量にヒット
- ❌ **狭すぎる**: 固有名詞（`Penicillin Lofi`）→ 0 件か自社しかヒットしない
- ❌ **表記揺れの全部入り**: `lofi`, `lo-fi`, `Lo-Fi`, `LoFi` を全部入れる → API 重複コスト。1 表記に統一
- ❌ **5 単語以上**: YouTube 検索は短いほうが精度高い。1-3 単語が最適

#### 1-E. キーワード設計のチェックリスト

実行前に以下を確認:

- [ ] 3-5 個に絞れているか（8 個超えは API コスト過剰）
- [ ] 4 軸（ジャンル/用途/雰囲気/アクティビティ）のうち 2 軸以上をカバーしているか
- [ ] 1 単語クエリは含まれていないか（`music` のような単独ワード）
- [ ] 表記揺れは 1 つに統一されているか
- [ ] 自分のチャンネル名・固有名詞が混入していないか

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
- 採用した候補を `config/channel/analytics.json` の `benchmark.channels` に追加する場合は、ユーザー承認と relationship メモを必ず残す
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

- `/channel-new`: TTP 対象確認と初期 config 生成。追加競合発掘が必要な場合に本スキルへ委譲
- `/benchmark`: 発掘済みチャンネルのベンチマークデータ収集
- `/channel-research`: 収集データの徹底分析
