# Market mode

## Overview

TTP 入替候補・ニッチ仮説の横断比較と、収集済みベンチマーク + コメントの詳細分析を 1 つの入口で扱う。前者は会話内レポート、後者はチャンネル全体の TTP 分析成果物を生成する。

## 自動分岐

`--market` は実行前にローカル成果物を調べ、深さをフラグで増やさず次の 2 branch へ自動分岐する。

| branch | 判定 | 既定成果物 |
|---|---|---|
| `market-comparison` | `data/benchmark_*.json`、検証済み benchmark report、`data/comments_*.json` がすべて 0 件 | 会話内の 7 セクションレポート。明示保存時だけ `docs/research/market-<YYYY-MM-DD>.json` + `.html` |
| `collected-analysis` | 上記 3 種のどれか 1 件以上が存在 | `docs/channel-research.json` + `.html` |

`collected-analysis` で 3 種の一部しか存在しない場合は `market-comparison` へ fallback せず、「前提成果物ガード」に従って不足を案内し停止する。

## Market comparison branch

### Hard Gates

- この branch は **状態を持たない読み取り専用の調査**である。`config/channel/analytics.json::benchmark.channels` を含む config schema、既存 TTP、調査入力を変更しない。TTP の自動入替は行わない。
- 既定の成果物は会話内レポートだけ。ユーザーがこの実行について明示的に「保存して」と依頼した場合だけ `docs/research/market-<YYYY-MM-DD>.json` + `.html` を共通 workflow で生成する。依頼がなければディレクトリもファイルも作らない。
- 保存先に同日ファイルがすでに存在する場合は、上書き前に既存ファイルが置換されることを示し、「上書きする / 会話内だけにする」の明示 2 択で確認する。承認されるまで書き込まない。
- 根拠は URL またはローカルパス、確認日、対応する主張を必ず記録する。`references/report-contract.md` の採用閾値を満たさない候補は「根拠不足」とし、TTP 入替候補や有望ニッチとして推奨しない。
- 調査結果から `/channel-research --discover`、`/channel-research --benchmark`、config 更新を自動実行しない。次アクションとして提案するだけに留める。

### Instructions

1. 会話から調査問い、合計 2 件以上の比較対象、3〜5 個の評価軸、対象市場と観測期間を抽出する。欠けている項目だけを確認し、揃うまで調査を始めない。
2. 現在値を Web 検索または接続済みの一次情報で確認する。ユーザーが Web 検索を禁止した場合はローカル成果物だけを使い、その制約を不確実性へ記録する。根拠ごとに ID、URL またはローカルパス、確認日、観測事実、支える主張を記録し、検索結果の要約や一般知識で補完しない。
3. 比較対象 × 評価軸を `強い` / `中立` / `弱い` / `判定不能` と根拠 ID で比較する。TTP 候補は優位点と劣位点、ニッチ仮説は対象視聴者 / 視聴シーン / 満たす欲求 / 競合との差 / 最小の検証方法を記録する。
4. 分類、根拠数、根拠不足時の扱いは `references/report-contract.md` を適用し、7 セクションを会話内に提示する。
5. 保存依頼がない場合はファイル未生成で終了する。明示依頼がある場合だけ同内容を market report candidate に構造化し、`references/structured-report.md` の移行承認と原子的公開を適用する。

### 完了条件

`references/report-contract.md` の 7 セクションを会話内に提示し、各候補を `候補` / `保留（根拠不足）` / `非推奨` のいずれかに分類し、保存依頼の有無に応じた分岐を完了する。保存ありの場合は同じ根拠を持つ JSON+HTML pair が存在することも確認する。

### Cross References

- 新規チャンネルの TTP seed と branding 初期値は `/setup --channel` Step 1 / 4 / 5 が所有する。詳細は `.claude/skills/setup/references/new-channel-bootstrap.md` と `.claude/skills/setup/references/ttp-seed-and-duration.md` を参照する
- 調査後に方向性を決める場合は `/channel-strategy --direction` へ委譲する。market mode 自身は config や方向性を更新しない

## Collected analysis branch

### 完了条件

Step 2〜5 の分析結果と Step 4 のテキスト分析を `docs/channel-research.json` + `.html` に統合保存し（Step 6）、Step 7 の次アクション案内を提示した時点で完了。

market report の thumbnail profile fields には競合のチャンネル名、コレクション名、シリーズ名、ロゴ文字列、コピー原文を転写しない。必ず抽象パターンだけを記録する。

## Subagent 委譲ゲート

メインエージェントは Step 0 の入力データ存在確認、成果物 pair 確認、次アクション案内だけを担当する。`data/benchmark_*.json`、`data/comments_*.json`、検証済み benchmark report、`docs/benchmarks/thumbnails/` の読み込みと Step 2〜6 の分析・レポート生成は channel-research subagent へ委譲する。

メインエージェントは競合データやコメント生データ、benchmark report 全文、サムネイル画像を直接 Read しない。subagent は `docs/channel-research.json` + `.html` を生成し、完了報告では成果物パス、分析した入力パス、主要な TTP パターンと推奨事項の要約だけを返す。生データ本文やコメント本文の大量引用をメイン会話へ返さない。

## 前提成果物ガード

後続 Step に入る前に、以下の前提を確認する。**停止する fail** が 1 件でもあれば、記載した前工程スキルを案内して停止し、解消するまで後続 Step に進まない。**許容する fail** は停止条件に含めない。

### 停止する fail

- `data/benchmark_*.json` が無い → 前工程 `/channel-research --benchmark` を案内して停止する
- `docs/benchmarks/benchmark-report.json` + `.html` を検証できない → 前工程 `/channel-research --benchmark` を案内して停止する
- `data/comments_*.json` が無い → 前工程 `/channel-research --voice` を案内して停止する

### 許容する fail

- `docs/benchmarks/thumbnails/` が無い → Step 4 は個別レポート内の `## サムネイル分析` または `## サムネイル分析（Gemini API）` 参照に切り替えるため停止しない

存在確認は Step 0 で機械的に行い、停止する fail が 1 つでもあれば Step 1 以降へ進まない。

## TTP 原則（ベンチマーク参照）

ベンチマーク分析の根本姿勢は **TTP（徹底的にパクる）**。
本当の TTP は完成品の表面ではなく、**なぜ伸びたかという理由（抽象）をパクること**。
パクるのは「テーマそのもの」ではなく、競合動画に内在する **構造・パターン・型と、それが刺激している視聴者欲求** —
タイトルのフォーマット、サムネイルの構図、動画尺の分布、投稿スケジュール、
コメントに現れる利用シーンの語彙、勝ち動画の共通要素。
これらを自チャンネルの初期値へ翻訳し、差別化はその上に重ねる。競合の画像・フレーズなど表面要素の直接模写は 1 回きりで再現性がないため、TTP として採用しない。

分析は次の 3 ステップで行う:

1. **具体を見つける**: 高再生動画のタイトル・サムネイル・楽曲 / 音楽性で観察した具体を記録する
2. **抽象化する**: 各具体が「癒されたい」「眠りたい」「集中したい」「不安を軽減したい」など、どの欲求をなぜ刺激するかを言語化する
3. **新しい具体へ翻訳する**: 抽出した欲求を、自チャンネルのタイトル・サムネイル・楽曲 / 音楽性へ別の表面表現で具体化する

1 件の勝ちパターンにつき **具体 ⇄ 抽象の往復を最低 3 回** 行う。1 回を「具体観察 → 欲求への抽象化 → 自チャンネルへの具体化 → 同じ欲求を満たすかの再抽象化」と数え、各回で表面表現を変える。3 回とも同じ欲求を説明できなければ、その抽象化は再現可能な勝ちパターンとして採用しない。market report には各回を evidence と application candidate で対応付ける。

### 欲求語彙のソース

欲求語彙の選択、欠落時の継続条件、`推定` と根拠の記録は `.claude/skills/channel-strategy/references/desire-vocabulary.md` をそのまま適用する。

既存実装の参照: `.claude/skills/thumbnail/SKILL.md` の `single_step` モード（TTP 推奨実装）、
`src/youtube_automation/domains/metadata/service.py` の TTP 形式タイトル生成。

## Instructions

**実行場所**: リポジトリルート（チャンネルの独立リポジトリ）

### Step 0: 入力データ存在確認（必須）

```bash
benchmark_json=$(find data -maxdepth 1 -type f -name 'benchmark_*.json' -print -quit 2>/dev/null)
comments_json=$(find data -maxdepth 1 -type f -name 'comments_*.json' -print -quit 2>/dev/null)
benchmark_report=docs/benchmarks/benchmark-report.json
test -n "$benchmark_json" && test -f "$benchmark_report" && test -f "${benchmark_report%.json}.html" &&
  test -n "$comments_json"
```

`benchmark_json`、`comments_json` が空でなく、benchmark report の JSON+HTML pair を共通 reader で検証できることを確認する。

欠けているデータ種別ごとに以下を案内して停止する:

- `data/benchmark_*.json` が無い → 先に `/channel-research --benchmark` を実行するよう案内
- benchmark report pair を検証できない → 先に `/channel-research --benchmark` を実行するよう案内
- `data/comments_*.json` が無い → 先に `/channel-research --voice` を実行するよう案内

全種別が揃っている場合のみ Step 1 へ進む。

### Step 1: 分析 subagent への委譲

メインエージェントは以下の入力パスを subagent に渡す。読み込みは subagent が担当し、メインエージェントは中身を直接 Read しない:

1. `data/` 内の更新時刻が最新の `benchmark_*.json`（`ls -t data/benchmark_*.json | head -1` で取得できるもの）
2. `data/` 内の更新時刻が最新の `comments_*.json`（`ls -t data/comments_*.json | head -1` で取得できるもの）
3. `docs/benchmarks/benchmark-report.json` を共通 reader で検証し、返された JSON だけを読む。pair が無い・不一致なら `/channel-research --benchmark` を案内して停止する

   ```bash
   # read_published_json_document(..., RepositorySchema.CHANNEL_RESEARCH_REPORT)
   ```

4. 存在する場合は `docs/benchmarks/thumbnails/`
5. 存在する場合は欲求語彙の優先ソースである検証済み `docs/plans/viewer-voice-analysis.json` と `docs/channel/personas/persona-definition.md`

subagent への完了条件は `docs/channel-research.json` + `.html` の生成に絞る。完了報告形式は `status: success | failure`、`inputs`、`artifacts`、`summary`、`errors` とする。

### Step 2: 競合マトリクス作成

テーブル形式で全チャンネルを比較:

```
| チャンネル | 登録者 | 動画数 | 平均再生数 | 日次再生 | ER% | 投稿間隔 | 動画尺 |
```

加えて以下を分析:
- **成長段階**: 各チャンネルの推定フェーズ（立ち上げ/成長/安定/停滞）
- **投稿トレンド**: 加速/減速/安定
- **勝ちパターン**: 高再生数動画の共通点
- **欲求との紐付け**: 勝ちパターンごとに、刺激している欲求と根拠（コメント / タイトル語彙）を `勝ちパターン X ← 欲求 Y（根拠: ...）` の形式で明示
- **TTP 対象**: 上記から自チャンネルに転写すべき構造・パターン・型を明示（後段 `/channel-strategy --direction` 方向性検討モードの入力になる）

### Step 3: コンテンツ戦略分析

**タイトル分析**:
- フォーマットパターン（テーマ+ジャンル+用途+尺 等）
- 頻出ワード・キーワード
- 成功タイトル vs 平均タイトルの違い
- 高再生タイトルが刺激している欲求と、その判断根拠となるタイトル語彙

**楽曲 / 音楽性分析**:
- ベンチマーク入力のタイトル・タグ・説明文に明示されたジャンル、テンポ、楽器、音響、ムードの共通パターンを分析する。音声自体は入力に含まれないため、明示情報から読み取った結果には `推定` と根拠を付け、根拠が無い項目は `判定不能` とする
- 高再生動画の楽曲 / 音楽性が刺激している欲求を、タイトル・タグ・説明文の語彙から推定し、`推定` と判断根拠を明記する。該当語彙が無ければ `判定不能` とする

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
- **テキスト**: 書体分類、ウェイト、縁取り / 影の有無、行数、言語、文字数レンジ、コピーの型、アンカー位置、マージン感
- **共通成功パターン**: 高再生動画のサムネイル特徴
- **刺激している欲求**: 視覚特徴がどの欲求を刺激しているかと、その判断根拠
- **差別化の余地**: 競合がやっていないスタイル

サムネイル画像がない場合は subagent が検証済み benchmark report の thumbnail evidence を参照する。HTML や旧 Markdown を fallback 入力にしない。

Step 4 のテキスト分析は、以下の fields を market report の `thumbnail_text_profile` に保存する。必須キーは変更・省略せず、値を判定できないキーは `unknown` とする。

```markdown
# Thumbnail Text Profile
schema_version: 1
generated_at: YYYY-MM-DD

## font_tendency
- typeface_classification: <書体分類>
- weight: <ウェイト傾向>
- outline: <present | absent | mixed | unknown>
- shadow: <present | absent | mixed | unknown>

## text_content_pattern
- line_count_range: <最小行数>..<最大行数>
- languages: <言語の抽象リスト>
- character_count_range: <最小文字数>..<最大文字数>
- copy_pattern: <コピーの抽象パターン>

## placement_tendency
- anchor_position: <アンカー位置の傾向>
- margin: <外縁からのマージン傾向>
```

`copy_pattern` は「2 行構成・短い英語キャッチ」のように抽象化する。競合のチャンネル名、コレクション名、シリーズ名、ロゴ文字列、コピー原文は、プロファイルのメタデータや例にも記録しない。

### Step 5: 視聴者インサイト分析

コメントデータから以下を抽出:

**利用シーン**: いつ・どこで・何をしながら聴いているか
**感情反応**: どんな感情を表現しているか（癒し、懐かしさ、集中等）
**リクエスト**: 視聴者が求めているもの（テーマ、長さ、頻度等）
**言語分布**: コメントの言語割合（国際性の指標）
**エンゲージメント**: 深いコメント vs 浅いコメントの比率

抽出したコメント由来の欲求を Step 2〜4 の勝ちパターンへ接続する。タイトル・サムネイル・楽曲 / 音楽性の各要素について `勝ちパターン X ← 欲求 Y（根拠: コメント / タイトル語彙）` を作り、欲求、`推定` / `判定不能`、根拠には `.claude/skills/channel-strategy/references/desire-vocabulary.md` の適用結果をそのまま記録する。

### Step 6: 成果物生成

subagent は全分析結果を `report_type=market` の candidate JSON に構造化し、`docs/channel-research.json` + `.html` へ共通 workflow で保存する:

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

## 欲求レイヤーと具体⇄抽象の往復
- 勝ちパターンと欲求の対応（タイトル / サムネイル / 楽曲・音楽性）
- 欲求語彙のソースと根拠
- 各勝ちパターンで最低 3 回行った「観察した具体 / 抽出した欲求 / 自チャンネルへの翻訳案 / 再抽象化による検証」

## 機会領域（ブルーオーシャン）
- 競合がカバーしていないテーマ
- 未開拓のフォーマット
- 差別化可能なスタイル

## 推奨事項
- ポジショニング案（3案程度）
- リスクと機会
```

加えて、Step 4 のテキスト分析を Step 4 の fields どおり同じ market report に保存する。公開前にすべての必須キーがあり、固有文字列を転写していないことを確認する。

### Step 7: 次アクション案内

メインエージェントは `docs/channel-research.json` + `.html` の対応を検証し、subagent の要約をもとに次を案内する:

「分析レポートが完成しました。方向性を見直す場合は `/channel-strategy --direction`（方向性検討モード）、現在の方針で制作に進む場合は `/wf-new` に進めます。」

## 障害時ガイダンス

競合データはローカルの `data/` / `docs/benchmarks/` を分析するため外部 API には依存しない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/channel-research --benchmark`・`/analytics --collect` 等を実行して入力を用意 |

## Cross References

- `/channel-research --benchmark` → 前提: 承認済み TTP 対象の動画データ収集
- `/channel-research --voice` → 前提: コメント収集と視聴者インサイト分析
- `/channel-strategy --direction`（方向性検討モード） → 任意: 方向性の再検討
- `/wf-new` → 初回コレクション制作
