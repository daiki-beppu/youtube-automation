---
name: ideate
description: Use when 新コレクションの企画が必要なとき、データドリブンな意思決定をしたいとき。「次何作る？」「テーマ選び」「コレクション候補」「企画提案」「アイデア」など、新規コンテンツの方向性を決める場面で必ず使用すること
---

## Overview

最新の分析データ + 競合ベンチマークを基に、各ペルソナ向けの企画提案を自動生成する。
設定は `config/skills/ideate.yaml` を参照。

## 前提

以下が揃っていること:

1. `config/channel_config.json` が存在する
2. `config/skills/ideate.yaml` が存在する（配布された `config.default.yaml` をベースにカスタマイズ）
3. サムネイル設定は `config/skills/thumbnail.yaml` を参照する（Phase 4 で使用）

いずれか不足する場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 新コレクションの企画が必要なとき
- 戦略の見直し・次期コンテンツ計画を立てたいとき
- データに基づいた意思決定をしたいとき

## 前提スキル状態確認

Phase 1-2 に入る前に、以下の前提スキルの出力を **上から順に** 確認する。後段は前段の出力に依存するため、並列化せずこの順序で鮮度判定・再実行を判断すること。

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い/未生成の場合 |
|---|---|---|---|---|
| 1 | `/benchmark` | `docs/benchmarks/*.md` + `data/benchmark_YYYYMMDD.json` | mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | `/benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新） |
| 2 | `/persona` | `docs/plans/persona-definition.md` | 生成物ベース。直近参照した `data/benchmark_YYYYMMDD.json` より mtime が古ければ stale（ベンチマーク更新後に再生成が必要） | ユーザーに `/persona` 実行を案内（自動呼び出しはしない — ペルソナ選択に `AskUserQuestion` が必要なため） |
| 3 | `/viewing-scene` | `docs/plans/viewing-scene-matrix.md` | 生成物ベース。`docs/plans/persona-definition.md` より mtime が古ければ stale（ペルソナ更新後に再生成が必要） | ユーザーに `/viewing-scene` 実行を案内（自動呼び出しはしない — シーン選択に `AskUserQuestion` が必要なため） |

### 同期ポイント

- **順序依存が存在するため並列実行は禁止**: persona は最新ベンチマークのタグデータを読み込み、viewing-scene は `persona-definition.md` を入力とする
- 1 を完了 → 2 の鮮度判定 → 3 の鮮度判定、の順に直列で通過させる
- 2 または 3 が stale だった場合は、その時点で Phase 1-2 を中断し、該当スキルの実行をユーザーに促す

### 判定擬似コード

```bash
# 1. benchmark — /benchmark スキル内の鮮度チェックに委譲
#    （freshness_days より古い md があれば自動更新）

# 2. persona
BENCHMARK_JSON=$(ls -t data/benchmark_*.json 2>/dev/null | head -1)
if [ ! -f docs/plans/persona-definition.md ]; then
  echo "persona 未定義 → /persona を案内"
elif [ -n "$BENCHMARK_JSON" ] && [ "$BENCHMARK_JSON" -nt docs/plans/persona-definition.md ]; then
  echo "persona stale（benchmark 更新後）→ /persona 再実行を案内"
fi

# 3. viewing-scene
if [ ! -f docs/plans/viewing-scene-matrix.md ]; then
  echo "viewing-scene 未定義 → /viewing-scene を案内"
elif [ docs/plans/persona-definition.md -nt docs/plans/viewing-scene-matrix.md ]; then
  echo "viewing-scene stale（persona 更新後）→ /viewing-scene 再実行を案内"
fi
```

## 実行フロー

### Phase 1: 現状分析・データ収集

#### Phase 1-1: チャンネル現状分析
`yt-channel-status` でチャンネル統計を取得し、既存コレクション一覧・テーマカバレッジを把握。

```bash
uv run yt-channel-status
```

#### Phase 1-2: ベンチマーク分析

**Skill ツールで `/benchmark` を実行** — 3 日以上未更新のファイルがあれば YouTube Data API (OAuth) で最新データを自動取得・更新する。最新であればスキップされる。

更新完了後、`docs/benchmarks/` 配下の全 `.md` ファイルを Read ツールで読み込み、以下を抽出:
- 競合チャンネルの高パフォーマンステーマ（再生数上位）
- 共通成功パターン（`common-patterns.md`）
- 自チャンネルへの戦略的示唆
- 競合がカバー済みのテーマ（差別化のため）

#### Phase 1-3: 統合分析
自チャンネルデータ + ベンチマークデータを統合し:
- テーマカバレッジマップ（自チャンネル vs 競合）
- 未開拓×高ポテンシャルのテーマ候補リスト
- 差別化可能な切り口の特定

### Phase 2: 戦略的企画立案
**youtube-video-planner** サブエージェント（Task ツール）で分析結果から CTR 改善に最適なテーマ戦略を構築。

### Phase 3: ペルソナベース企画候補生成
**rpg-collection-research-agent** と **rpg-storytelling-agent** サブエージェント（Task ツール）を連携して、各ペルソナ向けの企画候補を生成。

### Phase 4: プレビューサムネイル生成

**重要**: サムネイルを見てからテーマを決定するため、この段階ではユーザーにテーマ選択を求めない。全企画のプレビューを先に生成する。

**4-1: 各企画の本番品質プロンプト生成**

`config/skills/ideate.yaml` の `preview.candidate_count`（デフォルト 3）個の企画について、`/thumbnail` スキルの Phase 1 と同等の本番品質プロンプトを生成する:

- `config/skills/thumbnail.yaml` の `gemini_image.prompt_prefix` + `composition_rules` を完全適用
- 英語 1 段落、誇張表現禁止、16:9 構図、テキスト除外
- **本番品質で生成する**（選択後そのまま `main.png` として使用するため）

**4-2: コスト一括確認**

```
3 枚 × $0.04 = $0.120
```

ユーザーが拒否した場合 → テキストのみで提示（プレビューサムネイル生成はブロッキングにしない）

**4-3: generate_image.py でプレビュー生成**

セッション固有のディレクトリを作成し、その中にテーマスラッグ付きで保存する:

```bash
# <YYYYMMDD> は実行日（例: 20260306）
# <SESSION_ID> はセッション開始時に生成したランダム ID
# バイト数は config/skills/ideate.yaml の preview.session_id_bytes（デフォルト 2 → hex 4 文字）
SESSION_ID=$(openssl rand -hex 2)
PREVIEW_DIR="<YYYYMMDD>-${SESSION_ID}"
mkdir -p collections/planning/_plan-previews/${PREVIEW_DIR}
```

**プロンプト構築**:

`config/skills/thumbnail.yaml` の `gemini_image.generation_mode` を確認:

- **`single_step` の場合**: `gemini_image.diff_prompt_template` をベースに、オブジェクトデザインルール（`ideate.objects` が定義されている場合）に従って企画ごとのオリジナルオブジェクトを指定。
  - **背景色**: `gemini_image.brand_background` を使用（定義がある場合）。全コレクション統一
  - **差別化はオブジェクトで行う**: `ideate.objects.swappable` で定義されたスロットを企画ごとに変える
  - 具体的な差分プロンプトの書き方は `references/object-design-examples.md` を参照

- **それ以外の場合**: `gemini_image.prompt_prefix` + `composition_rules` を適用した本番品質プロンプトを生成（従来方式）

```bash
# 順次実行（API レート制限回避）
# <dir> は上で作成したセッション固有ディレクトリ名（例: 20260306-a3f1）
# <slug> はテーマ名をケバブケースに変換（例: "The Wanderer's Road" → "wanderers-road"）
REF=$(uv run python3 -c "from youtube_automation.utils.skill_config import load_skill_config; c=load_skill_config('thumbnail'); print(c.get('gemini_image',{}).get('reference_images',{}).get('default',''))")
uv run yt-generate-image --reference "$REF" --prompt "<企画Aプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-a-<slug>.png -y
uv run yt-generate-image --reference "$REF" --prompt "<企画Bプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-b-<slug>.png -y
uv run yt-generate-image --reference "$REF" --prompt "<企画Cプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-c-<slug>.png -y
```

- 出力先: `collections/planning/_plan-previews/<dir>/plan-{a,b,c}-<slug>.png`
- `_` プレフィックスで通常コレクションと区別
- セッション ID 付きディレクトリで並列実行時の競合を回避
- `-y` 指定時、同名ファイルが既存なら自動で `-v2`, `-v3` ... と採番（追加の安全策）

**4-4: 画像付きで企画を提示**

1. まず `open` コマンドで全枚を同時にプレビューアプリで開く:

   ```bash
   open collections/planning/_plan-previews/<dir>/plan-{a,b,c}-*.jpg
   ```

2. Read ツールでも各プレビュー画像を表示しながら企画を提示する
3. 各企画にはサムネイル情報に加え、`ideate.objects` で定義されたオブジェクトの名前・ストーリーを併記する（`objects` 未定義時は省略）
4. 生成に失敗した分はテキストのみで提示（「プレビュー生成失敗」と明記）

## ペルソナベース企画フレームワーク

`docs/plans/persona-definition.md` で定義されたペルソナに対し、各 1 企画を生成する。
ペルソナの視聴シーン・ユースケースから情景を導出し、差別化軸と掛け合わせてテーマを決定する。

`docs/plans/persona-definition.md` が存在する場合、そこからペルソナを読み込む。鮮度・未生成の判定ルールは冒頭の「前提スキル状態確認」セクションに従う。

**存在しない場合は ideate を進めず、以下を案内して停止する:**

```
❌ docs/plans/persona-definition.md が見つかりません。
   先に `/persona` を実行してターゲットペルソナを定義してください。
   （チャンネル立ち上げ直後なら `/channel-direction` → `/persona` → `/ideate` の順）
```

今回のターゲットペルソナに対し、差別化軸（`config/skills/ideate.yaml` の `differentiation_axes`、デフォルト: location / time_of_day / activity / mood）の掛け合わせで候補を生成:

| 企画 | 差別化の切り口 |
|------|---------------|
| **企画 1** | 軸 A × 軸 B のバリエーション |
| **企画 2** | 軸 C × 軸 D のバリエーション |
| **企画 3** | 競合の高再生パターンをペルソナ視点で再解釈 |

### カラールール

- **背景色**: `config/skills/thumbnail.yaml` の `gemini_image.brand_background` を使用（定義があれば全コレクション統一）
- **差別化はオブジェクトで行う**: `ideate.objects.swappable` を企画ごとに変える

各企画には以下を必ず含める:
- **ターゲットペルソナ**: 名前・視聴シーン・ユースケース
- **競合パターン参照**: どの競合の成功パターンを参考にしたか
- **差別化ポイント**: 既存コレクションとどう異なるか
- **情景没入スコア**: サムネイル + タイトルで情景が浮かぶ度合い（高/中/低）
- **オブジェクト定義**: `ideate.objects.swappable` 各スロットの具体値（名前・ストーリー・ビジュアル）

## 企画ルール

`channel_config.json` の `channel.core_message` と `genre.*` からチャンネルの世界観を読み取り、一貫した企画を立案する。

`channel_config.json` の `title.template` に基づくタイトル構造を使用。

### タイトルテンプレート

`channel_config.json` の `title.template` を参照。テーマに合わせて動的要素を調整。

### 差別化軸

`config/skills/ideate.yaml` の `differentiation_axes` を使用。デフォルト軸:

| 軸 | 説明 |
|---|---|
| **location** | シーンの空間設定 |
| **time_of_day** | 時間的コンテキスト |
| **activity** | リスナーのユースケース |
| **mood** | 感情的トーン |

### 競合パターン分析ルール

ベンチマークデータを分析し、以下を企画判断に使う:
- **高再生タイトルの共通要素**: 情景描写の具体性と再生数の相関
- **低再生タイトルの回避要素**: 抽象的・汎用的なテーマは CTR が低い
- 具体的な場所 + ムードの組み合わせが視聴者の情景想起を助ける

### OK / NG 例

- ✓ 具体的場所 + 天候/時間帯 + ムード（情景が浮かぶ）
- ✗ 汎用的すぎる、情景なし（`Relaxing Music` 等）
- ✗ 形容詞が抽象的、場所なし（`Beautiful Night Music` 等）
- ✗ カタログ的、世界観なし（`BGM Collection` 等）

## オブジェクトデザインルール

`config/skills/ideate.yaml` に `objects` セクションがある場合、サムネイルの差し替え可能オブジェクトと固定オブジェクトを定義する。これらはコミュニティ投稿でストーリーを展開するコンテンツ資産でもある。

`objects` がない場合、このセクションはスキップする（サムネイル差別化はカラー・構図のみになる）。

### オブジェクトデザインの原則

- 各コレクションでオブジェクトを差し替え、視覚的差別化を実現する
- 名前は短く詩的に
- ストーリーは「誰が、どんな場面で、なぜ」を描写
- ビジュアルは具体的に指定（形状・色・質感）

具体例は `references/object-design-examples.md` を参照。

### コミュニティ投稿での展開

オブジェクトの説明は、YouTube コミュニティ投稿で世界観を広げるコンテンツとして設計する。

## オリジナリティ保証ルール

`config/skills/ideate.yaml` の `originality` を参照:

- 競合の既存タイトル・テーマとの類似度が `originality.max_similarity` を超えたら警告
- ベンチマークから学ぶのは「パターン（構造）」であり「テーマそのもの」ではない
- 既存コレクションと類似度が高い場合は警告表示
- `originality.require_pattern_reference: true` の場合、各企画に「競合パターン参照元」と「差別化ポイント」を明記

## リファレンス

コレクション作成の詳細ライフサイクル（ディレクトリ構造、段階別手順、チェックリスト）は `references/collection-lifecycle.md` を参照。

## 意思決定支援

### ペルソナローテーション

`/ideate` は**1 つのペルソナに絞って `preview.candidate_count` 個の企画候補**を生成する。次回の `/ideate` では次のペルソナに移る。

**今回のターゲットペルソナ判定**:
1. `collections/` 配下の全 `workflow-state.json` から `planning.target_persona` を収集
2. 直近の選択ペルソナの次を今回のターゲットにする
3. 初回 or 不明 → `docs/plans/persona-definition.md` の先頭ペルソナ

**3 候補の差別化軸**:
同一ペルソナ向けに、`differentiation_axes` の掛け合わせを変えてバリエーションを生成する。

### 企画レポート保存

企画候補は必ずコレクションの `20-documentation/plan_proposals.md` に保存すること。

保存後、`workflow-state.json` の `planning.generated = true` に更新する。

## Next Step

企画選択時にタイトルも確定する（`workflow-state.json` の `planning.final_title` に記録）。

企画確定後、**選択した企画のプレビュー画像をコレクションの `main.png` にコピー**してからプレビューディレクトリを削除する:

```bash
# 1. 選択した企画のプレビュー画像を main.png としてコピー
cp collections/planning/_plan-previews/<session-dir>/plan-<x>-<slug>.jpg <collection-path>/10-assets/main.png

# 2. コピー完了後、自セッションのプレビューディレクトリを削除
rm -rf collections/planning/_plan-previews/<session-dir>/
```

> **定期クリーンアップ**: 放棄されたセッションのディレクトリが残る場合、7 日以上前のものは手動削除可:
> `find collections/planning/_plan-previews/ -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +`

企画選択後:
→ `/thumbnail <theme>` でテキストオーバーレイのみ実行（`main.png` が既に存在するため Phase 2 から開始）
→ サムネイル確定後に `/suno <theme>` で SunoAI 音楽プロンプト生成（テーマ確定後に初めて実行）
