# 分析モード

## Overview

`/benchmark` と `/viewer-voice` で収集したベンチマークデータ + コメントデータを読み込み、徹底的に分析してレポートを生成する。
初回チャンネル開設フローは TTP 対象確認まで完結するため、分析モードは深掘り分析や方向性の再検討が必要なときに追加で実行する。

## 完了条件

Step 2〜5 の分析結果を `docs/channel-research.md` に保存し、Step 4 のテキスト分析を `docs/benchmarks/thumbnail-text-profile.md` に保存し（Step 6）、Step 7 の次アクション案内を提示した時点で完了。

`thumbnail-text-profile.md` には競合のチャンネル名、コレクション名、シリーズ名、ロゴ文字列、コピー原文を転写しない。必ず抽象パターンだけを記録する。

## Subagent 委譲ゲート

メインエージェントは Step 0 の入力データ存在確認、成果物存在確認、次アクション案内だけを担当する。`data/benchmark_*.json`、`data/comments_*.json`、`docs/benchmarks/*.md`、`docs/benchmarks/thumbnails/` の読み込みと Step 2〜6 の分析・レポート生成は channel-research subagent へ委譲する。

メインエージェントは競合データやコメント生データ、ベンチマーク Markdown 全文、サムネイル画像を直接 Read しない。subagent は `docs/channel-research.md` と `docs/benchmarks/thumbnail-text-profile.md` を生成し、完了報告では成果物パス、分析した入力パス、主要な TTP パターンと推奨事項の要約だけを返す。生データ本文やコメント本文の大量引用をメイン会話へ返さない。

## 前提成果物ガード

後続 Step に入る前に、以下の前提を確認する。**停止する fail** が 1 件でもあれば、記載した前工程スキルを案内して停止し、解消するまで後続 Step に進まない。**許容する fail** は停止条件に含めない。

### 停止する fail

- `data/benchmark_*.json` が無い → 前工程 `/benchmark` を案内して停止する
- `docs/benchmarks/*.md` から `thumbnail-text-profile.md` を除外した個別レポートが 0 件 → 前工程 `/benchmark` を案内して停止する
- `data/comments_*.json` が無い → 前工程 `/viewer-voice` を案内して停止する

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

1 件の勝ちパターンにつき **具体 ⇄ 抽象の往復を最低 3 回** 行う。1 回を「具体観察 → 欲求への抽象化 → 自チャンネルへの具体化 → 同じ欲求を満たすかの再抽象化」と数え、各回で表面表現を変える。3 回とも同じ欲求を説明できなければ、その抽象化は再現可能な勝ちパターンとして採用しない。`docs/channel-research.md` には各回の「観察した具体 / 抽出した欲求 / 自チャンネルへの翻訳案 / 再抽象化による検証」を記録する。

### 欲求語彙のソース

欲求語彙の選択、欠落時の継続条件、`推定` と根拠の記録は `.claude/skills/channel-new/references/desire-vocabulary.md` をそのまま適用する。

既存実装の参照: `.claude/skills/thumbnail/SKILL.md` の `single_step` モード（TTP 推奨実装）、
`src/youtube_automation/domains/metadata/service.py` の TTP 形式タイトル生成。

## Instructions

**実行場所**: リポジトリルート（チャンネルの独立リポジトリ）

### Step 0: 入力データ存在確認（必須）

```bash
benchmark_json=$(find data -maxdepth 1 -type f -name 'benchmark_*.json' -print -quit 2>/dev/null)
comments_json=$(find data -maxdepth 1 -type f -name 'comments_*.json' -print -quit 2>/dev/null)
benchmark_report=$(find docs/benchmarks -maxdepth 1 -type f -name '*.md' ! -name 'thumbnail-text-profile.md' -print -quit 2>/dev/null)
test -n "$benchmark_json" &&
  test -n "$comments_json" &&
  test -n "$benchmark_report"
```

`benchmark_json`、`comments_json`、`benchmark_report` がすべて空でないことを確認する。`thumbnail-text-profile.md` は前回の分析モード成果物であり、個別レポートの存在判定には数えない。

欠けているデータ種別ごとに以下を案内して停止する:

- `data/benchmark_*.json` が無い → 先に `/benchmark` を実行するよう案内
- `thumbnail-text-profile.md` を除く `docs/benchmarks/*.md` が無い → 先に `/benchmark` を実行するよう案内
- `data/comments_*.json` が無い → 先に `/viewer-voice` を実行するよう案内

全種別が揃っている場合のみ Step 1 へ進む。

### Step 1: 分析 subagent への委譲

メインエージェントは以下の入力パスを subagent に渡す。読み込みは subagent が担当し、メインエージェントは中身を直接 Read しない:

1. `data/` 内の更新時刻が最新の `benchmark_*.json`（`ls -t data/benchmark_*.json | head -1` で取得できるもの）
2. `data/` 内の更新時刻が最新の `comments_*.json`（`ls -t data/comments_*.json | head -1` で取得できるもの）
3. 次のコマンドが列挙する `docs/benchmarks/` 内の `.md` ファイル。前回成果物の `thumbnail-text-profile.md` は除外し、出力が 0 件なら `/benchmark` を案内して停止する

   ```bash
   find docs/benchmarks -maxdepth 1 -type f -name '*.md' ! -name 'thumbnail-text-profile.md' -print | sort
   ```

4. 存在する場合は `docs/benchmarks/thumbnails/`
5. 存在する場合は欲求語彙の優先ソース `docs/plans/viewer-voice-analysis.md` と `docs/channel/personas/persona-definition.md`

subagent への完了条件は `docs/channel-research.md` と `docs/benchmarks/thumbnail-text-profile.md` の生成に絞る。完了報告形式は `status: success | failure`、`inputs`、`artifacts`、`summary`、`errors` とする。

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
- **TTP 対象**: 上記から自チャンネルに転写すべき構造・パターン・型を明示（後段 `/channel-new` 方向性検討モードの入力になる）

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

サムネイル画像がない場合は subagent が Step 1 と同じ `find` コマンドで列挙した個別レポート内の `## サムネイル分析` または `## サムネイル分析（Gemini API）` セクションを参照する。`thumbnail-text-profile.md` は fallback 入力にも含めない。

Step 4 のテキスト分析は、以下のスキーマで `docs/benchmarks/thumbnail-text-profile.md` に保存する。見出し名と必須キーは変更・省略しない。値を判定できないキーは省略せず `unknown` とする。

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

抽出したコメント由来の欲求を Step 2〜4 の勝ちパターンへ接続する。タイトル・サムネイル・楽曲 / 音楽性の各要素について `勝ちパターン X ← 欲求 Y（根拠: コメント / タイトル語彙）` を作り、欲求、`推定` / `判定不能`、根拠には `.claude/skills/channel-new/references/desire-vocabulary.md` の適用結果をそのまま記録する。

### Step 6: 成果物生成

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

加えて、Step 4 のテキスト分析を Step 4 のスキーマどおり `docs/benchmarks/thumbnail-text-profile.md` に保存する。保存後に必須見出し 3 件とすべての必須キーがあること、固有文字列を転写していないことを確認する。

### Step 7: 次アクション案内

メインエージェントは `docs/channel-research.md` と `docs/benchmarks/thumbnail-text-profile.md` の存在を確認し、subagent の要約をもとに次を案内する:

「分析レポートが完成しました。方向性を見直す場合は `/channel-new`（方向性検討モード）、現在の方針で制作に進む場合は `/wf-new` に進めます。」

## 障害時ガイダンス

競合データはローカルの `data/` / `docs/benchmarks/` を分析するため外部 API には依存しない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/benchmark`・`/analytics-collect` 等を実行して入力を用意 |

## Cross References

- `/benchmark` → 前提: 承認済み TTP 対象の動画データ収集
- `/viewer-voice` → 前提: コメント収集と視聴者インサイト分析
- `/channel-new`（方向性検討モード） → 任意: 方向性の再検討
- `/wf-new` → 初回コレクション制作
