---
name: discover-competitors
description: "Use when 追加競合候補の自動発掘やニッチ仮説の並行検証をするとき。「競合候補」「競合発掘」「ニッチ検証」「discover-competitors」で発動"
---

## Overview

ニッチキーワード（複数可）を渡すと、登録者数レンジ・最終投稿日でフィルタしたうえで
キーワード一致率・エンゲージメント率・更新頻度・登録者帯近さの 4 軸スコアで
競合候補チャンネルをランキング化する CLI ラッパー。

- 入力: ニッチキーワード（カンマ区切り）+ フィルタ条件
- 出力: ランキング付き Markdown + 同名 CSV（スコア内訳列付き）
- 想定時間: 5 分以内（初回または強制更新時の API quota 約 660 units。24 時間以内の同一検索条件はキャッシュを利用）

`/channel-new` の標準フローでは実行しない。TTP 対象確認後に追加の競合候補を広げたい場合や、複数のニッチ仮説を
並行検証したい場合に、このスキルを任意で走らせる。

## 完了条件

Step 3 の実行で出力ペア（Markdown ランキング + 同名 CSV）を生成し、Step 4 でユーザーに Markdown パスと候補要約を提示した時点で完了。`config/channel/analytics.json::benchmark.channels` への候補追加はユーザー承認があった場合のみ行う（承認が無ければ提示のみで終了する）。

## Subagent 委譲ゲート

メインエージェントは設定読み込み、キーワード・フィルタ条件の決定、候補追加前のユーザー承認、成果物存在確認だけを担当する。YouTube Data API 呼び出し、候補スコアリング、Markdown + CSV の生成、生成済みランキングの読み込みは subagent へ委譲する。

メインエージェントは `research/*-discovery.md` や同名 `.csv` の全行を直接 Read しない。subagent は成果物パス、候補件数、上位候補の短い要約だけを返す。`config/channel/analytics.json::benchmark.channels` への追記は、メインエージェントが subagent の要約と成果物パスを提示してユーザー承認を得た後にだけ行う。

## 設定読み込みゲート

Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/discover-competitors/config.default.yaml`
2. `config/skills/discover-competitors.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("discover-competitors")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。`yt-discover-competitors` CLI も同じ skill-config をフラグ既定値として読む（CLI フラグ明示指定 > チャンネル上書き > default の優先順位）。

## 前提成果物ガード

後続 Step に入る前に、以下の前提を確認する。**停止する fail** が 1 件でもあれば、記載した前工程スキルを案内して停止し、解消するまで後続 Step に進まない。**許容する fail** は停止条件に含めない。

### 停止する fail

- 実行場所がチャンネルリポジトリ（`CHANNEL_DIR`）配下ではない → `/channel-new` を案内して停止する
- `auth/token.json` が存在しない、または OAuth 認証が無効 → `/setup` の OAuth 認証を案内して停止する

### 許容する fail

- seed 抽出元の `config/channel/content.json` / `config/channel/analytics.json` が無い → 新規チャンネル企画・完全手探りではユーザー宣言のキーワードだけで実行できるため停止しない（Step 1-A の抽出元マトリクス参照）

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3 search.list（100 units/call） | キーワード数 × 1 call（100 units each） | キーワード数（既定 3-5 個、hard_max 8） |
| YouTube Data API v3 channels.list（1 unit/call） | ceil(ユニーク候補チャンネル数/50) call | 候補チャンネル数 |
| YouTube Data API v3 videos.list ほか（1 unit/call） | pre-filter 通過チャンネルあたり約 2 units | フィルタ通過数 |

初回または `--refresh` 実行あたり概ね 660 units（詳細は「API コスト」セクション参照）。

- 上限 / 承認: 同一検索条件の search.list は 24 時間 TTL でキャッシュされ（`--refresh` で無効化）、`--per-keyword` / `--top` / `--min-subscribers` で候補数と quota 消費を絞れる。

## Instructions

### Step 1: キーワード設計

ユーザーから対象ニッチを聞き出し、skill-config `keywords.recommended_min`〜`keywords.recommended_max` 個（既定 3-5 個、多くて `keywords.hard_max` = 既定 8 個まで）の検索キーワードに分解する。
キーワード数は API コストに線形効くので、ニッチが鮮明なら下限で十分。

#### 1-A. シード語の収集元

既存チャンネルの場合と新規チャンネル企画の場合で seed の抽出元が異なる:

| ケース | 抽出元 | 具体的な参照先 |
|--------|--------|---------------|
| **既存チャンネル**で競合再発掘 | チャンネル config | `config/channel/content.json` の `genre` / `tags.base` / `descriptions.perfect_for` |
| **既存チャンネル**で類似帯探索 | 既存ベンチマーク | `config/channel/analytics.json` の `benchmark.channels` を YouTube で開いてタイトル頻出語を抽出 |
| **新規チャンネル企画** | `/channel-new` の TTP メモと初期 config | `config/channel/content.json::genre.{primary,style,context}` / `tags.base` / TTP メモ内の用途・シーン語彙 |
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

- [ ] `keywords.recommended_min`〜`recommended_max` 個（既定 3-5 個）に絞れているか（`hard_max` = 既定 8 個超えは API コスト過剰）
- [ ] 4 軸（ジャンル/用途/雰囲気/アクティビティ）のうち 2 軸以上をカバーしているか
- [ ] 1 単語クエリは含まれていないか（`music` のような単独ワード）
- [ ] 表記揺れは 1 つに統一されているか
- [ ] 自分のチャンネル名・固有名詞が混入していないか

### Step 2: フィルタ条件の決定

各フラグの既定値は skill-config の `search.*`（`config.default.yaml` 参照。チャンネル側は `config/skills/discover-competitors.yaml` で恒久上書き可能）:

| フラグ | skill-config キー | 推奨用途 |
|-------|------------------|---------|
| `--min-subscribers` | `search.min_subscribers`（既定 0） | 小規模チャンネルも拾うなら 0、競合検証なら 10K 以上推奨 |
| `--max-subscribers` | `search.max_subscribers`（既定 10,000,000） | 自分の目標帯の 10 倍以内に絞ると参考にしやすい |
| `--posted-within-days` | `search.posted_within_days`（既定 30） | 「動いている競合」のみ。1 年単位で見たいなら 365 |
| `--top` | `search.top`（既定 20） | レポートに出す件数 |
| `--per-keyword` | `search.per_keyword`（既定 20） | search.list の maxResults（合計クエリ数 = keywords × per-keyword） |
| `--refresh` | — | 24 時間の TTL 内でも検索キャッシュを無視して search.list を再実行 |

### Step 3: 実行

チャンネルディレクトリ配下からの実行を subagent へ委譲する（`auth/token.json` が存在する前提）:

```bash
uv run yt-discover-competitors \
  --keywords "lo-fi study,chill beats,study music" \
  --min-subscribers 10000 --max-subscribers 1000000 \
  --posted-within-days 30 --top 20 \
  --output research/lo-fi-discovery.md
```

同じ keyword と `--per-keyword` の組み合わせによる `search.list` 結果は、チャンネル配下の
`.cache/youtube-automation/discover-competitors-search.json` に 24 時間保存される。最新結果が必要な場合だけ
上記コマンドへ `--refresh` を追加する。`config/channel/analytics.json::benchmark.channels` に登録済みの
channel ID は候補から除外される。

出力ペア:
- `research/lo-fi-discovery.md` — Markdown ランキングテーブル
- `research/lo-fi-discovery.csv` — スコア内訳付き CSV（14 列）

### Step 4: 結果の活用

- メインエージェントは subagent から受け取った Markdown パス、CSV パス、候補件数、上位候補の短い要約をユーザーに提示し、承認を得る
- 採用した候補を `config/channel/analytics.json` の `benchmark.channels` に追加する場合は、ユーザー承認と relationship メモを必ず残す
- 並行検証なら、ニッチ仮説ごとに `--output research/{niche}-discovery.md` で別ファイルに分けて比較する

### 委譲プロンプト要件

subagent へは次を具体値で渡す:

- 入力パス: `.claude/skills/discover-competitors/config.default.yaml`、存在する場合は `config/skills/discover-competitors.yaml`、キーワード抽出に使う `config/channel/content.json` / `config/channel/analytics.json`（存在する場合）
- 実行する作業: `uv run yt-discover-competitors ... --output research/{niche}-discovery.md`
- 期待成果物: `research/{niche}-discovery.md` と同名の `research/{niche}-discovery.csv`
- 完了報告: `status: success | failure`、`command`、`artifacts`、`candidate_count`、`top_candidates_summary`、`errors`

## API コスト

初回または `--refresh` 実行あたり概ね 660 units（10,000/日 quota の 6.6%）。同一条件の search.list は 24 時間キャッシュされる:
- search.list × keywords: 100 units × N
- channels.list: 1 unit × 候補数（バッチ）
- videos.list: 1 unit × 候補数（直近 5 本まとめて 1 リクエスト）

並行検証で連発するときは quota 残量に注意。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える。初回または `--refresh` は約 660 units を消費するため、並行検証の連発を控え、キーワード数や `--per-keyword` を減らして次回リセット後に再実行する |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |
| 同一 `--output` での再実行 | 前回の `.md` / `.csv` の内容が消える | 仕様どおりの動作。出力ペア（`.md` + 同名 `.csv`）は再実行時に全体が上書きされ、部分結果のマージ・保持はされない（API 呼び出しが途中で失敗した場合はファイルは書き込まれず、前回の出力がそのまま残る）。結果を比較したい場合は実行ごとに `--output` を別ファイル名にする |

## スコープ外（他スキルへバトン）

- 競合の動画詳細分析 → `/benchmark`
- 視聴者コメント分析 → `/viewer-voice`
- 方向性決定・config 生成 → `/channel-new`（方向性検討モード）/ `/channel-new`（再生成モード）
- ベンチマーク再収集 → `/benchmark`

このスキルは **発掘**だけに責任を持つ。深堀分析は専用スキルにバトンを渡す。

## Cross References

- `/channel-new`: TTP 対象確認と初期 config 生成。追加競合発掘が必要な場合に本スキルへ委譲
- `/benchmark`: 発掘済みチャンネルのベンチマークデータ収集
- `/channel-research`: 収集データの徹底分析
