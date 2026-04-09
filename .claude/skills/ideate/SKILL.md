---
name: ideate
description: Use when 新コレクションの企画が必要なとき、データドリブンな意思決定をしたいとき。「次何作る？」「テーマ選び」「コレクション候補」「企画提案」「アイデア」など、新規コンテンツの方向性を決める場面で必ず使用すること
---

## Overview

最新の分析データ + 競合ベンチマークを基に、各ペルソナ向けの企画提案を自動生成します。

## When to Use

- 新コレクションの企画が必要なとき
- 戦略の見直し・次期コンテンツ計画を立てたいとき
- データに基づいた意思決定をしたいとき

## 実行フロー

### Phase 1: 現状分析・データ収集

#### Phase 1-1: チャンネル現状分析
`get_channel_status` でチャンネル統計を取得し、既存コレクション一覧・テーマカバレッジを把握。

```bash
python3 get_channel_status
```

#### Phase 1-2: ベンチマーク分析

**Skill ツールで `/benchmark` を実行** — 3日以上未更新のファイルがあれば YouTube Data API (OAuth) で最新データを自動取得・更新する。最新であればスキップされる。

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
**youtube-video-planner** サブエージェント（Task ツール）で分析結果からCTR改善に最適なテーマ戦略を構築。

### Phase 3: ペルソナベース企画候補生成
**rpg-collection-research-agent** と **rpg-storytelling-agent** サブエージェント（Task ツール）を連携して、各ペルソナ向けの企画候補を生成。

### Phase 4: プレビューサムネイル生成

**重要**: サムネイルを見てからテーマを決定するため、この段階ではユーザーにテーマ選択を求めない。全企画のプレビューを先に生成する。

**4-1: 各企画の本番品質プロンプト生成**
各企画（A〜C）について、`/thumbnail` スキルの Phase 1 と同等の本番品質プロンプトを生成する:
- `channel_config.json` の `gemini_image.prompt_prefix` + `composition_rules` を完全適用
- 英語1段落、誇張表現禁止、16:9 構図、テキスト除外
- **本番品質で生成する**（選択後そのまま `main.png` として使用するため）

**4-2: コスト一括確認**
```
3枚 × $0.04 = $0.120
```
ユーザーが拒否した場合 → テキストのみで提示（プレビューサムネイル生成はブロッキングにしない）

**4-3: generate_image.py でプレビュー生成**

セッション固有のディレクトリを作成し、その中にテーマスラッグ付きで保存する:
```bash
# <YYYYMMDD> は実行日（例: 20260306）
# <SESSION_ID> はセッション開始時に生成した4文字のランダムID
SESSION_ID=$(openssl rand -hex 2)
PREVIEW_DIR="<YYYYMMDD>-${SESSION_ID}"
mkdir -p collections/planning/_plan-previews/${PREVIEW_DIR}
```

**プロンプト構築**:
`gemini_image.generation_mode` を確認:

- **`single_step` の場合**: `diff_prompt_template` をベースに、オブジェクトデザインルールに従って各企画のオリジナルカクテル・キャンドルを指定。
  参照画像（テキスト付き）から**差分のみ指示**する。タイトルテキストも含めて1ステップで完成サムネイルを生成。
  - **背景色**: 常に `channel_config.json` の `brand_background`（pale ice blue）を使用。全コレクション統一。
  - **差別化はオブジェクトで行う**: キャンドルとカクテルは各企画で必ず異なるデザインにする
  - カクテルはオリジナル名+ビジュアル描写、キャンドルは香りのテーマに対応する色+テクスチャ
  ```
  例: "Change the background color to pale ice blue. Change the left candle to a sage green
  glass jar with rich glossy candy-like translucent texture, evoking late-night studio warmth
  and dried paint. Change the right cocktail to an original cocktail called Inkwell — deep amber
  liquid in a rocks glass with a curl of orange peel and a single coffee bean, warm and focused.
  Change the subtitle text below the line to '(テーマに合ったサブタイトル)'.
  Keep the same muted text color matching the new background.
  Keep the same rain window texture. Keep the turntable unchanged."
  ```

- **それ以外の場合**: `prompt_prefix` + `composition_rules` を適用した本番品質プロンプトを生成（従来方式）。

```bash
# 順次実行（API レート制限回避）
# <dir> は上で作成したセッション固有ディレクトリ名（例: 20260306-a3f1）
# <slug> はテーマ名をケバブケースに変換（例: "The Wanderer's Road" → "wanderers-road"）
REF=$(python3 -c "import json; c=json.load(open('config/channel_config.json')); print(c.get('gemini_image',{}).get('reference_images',{}).get('default',''))")
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
2. Read ツールでも各プレビュー画像を表示しながら企画を提示する。
3. 各企画にはサムネイル情報に加え、オリジナルカクテルとキャンドルの名前・ストーリーを併記する。
4. 生成に失敗した分はテキストのみで提示（「プレビュー生成失敗」と明記）。

## ペルソナベース企画フレームワーク

`docs/plans/persona-definition.md` で定義された3ペルソナに対し、各1企画を生成する。
ペルソナの視聴シーン・ユースケースから情景を導出し、差別化軸と掛け合わせてテーマを決定する。

ペルソナ一覧（ローテーション順）:

| ID | ペルソナ | ユースケース |
|----|----------|-------------|
| **A** | ペルソナ A | `docs/plans/persona-definition.md` から読み込み |
| **B** | ペルソナ B | 同上 |
| **C** | ペルソナ C | 同上 |

`docs/plans/persona-definition.md` が存在する場合、そこからペルソナを読み込む。未定義の場合はユーザーにペルソナ定義（`/persona`）を先に実行するよう案内する。

今回のターゲットペルソナに対し、差別化軸の掛け合わせで3候補を生成:

| 企画 | 差別化の切り口 |
|------|---------------|
| **企画1** | 場所 × 時間帯のバリエーション |
| **企画2** | 活動 × ムードのバリエーション |
| **企画3** | 競合の高再生パターンをペルソナ視点で再解釈 |

### カラールール

- **背景色**: 常に `channel_config.json` の `brand_background`（pale ice blue）を使用。全コレクション統一
- **差別化はオブジェクトで行う**: キャンドルとカクテルの色・形状・素材を各企画で変える
- キャンドル・カクテルの色はテーマの情景に合わせる（既存のオブジェクトデザインルールに従う）

各企画には以下を必ず含める:
- **ターゲットペルソナ**: 名前・視聴シーン・ユースケース
- **競合パターン参照**: どの競合の成功パターンを参考にしたか
- **差別化ポイント**: 既存コレクションとどう異なるか
- **情景没入スコア**: サムネイル+タイトルで情景が浮かぶ度合い（高/中/低）
- **オリジナルカクテル**: 名前・レシピ・ストーリー（→ オブジェクトデザインルール参照）
- **キャンドル**: 名前・香りの説明・ストーリー（→ オブジェクトデザインルール参照）

## 企画ルール

`channel_config.json` の `channel.core_message` と `genre.*` からチャンネルの世界観を読み取り、一貫した企画を立案する。

`channel_config.json` の `title.template` に基づくタイトル構造を使用。

### タイトルテンプレート

`channel_config.json` の `title.template` を参照。テーマに合わせて動的要素を調整。

### 差別化軸

`channel_config.json` の `ideate.differentiation_axes` があればそれを使用。なければ以下のデフォルト軸で生成:

| 軸 | 説明 |
|---|---|
| **場所** | シーンの空間設定 |
| **時間帯** | 時間的コンテキスト |
| **活動** | リスナーのユースケース |
| **ムード** | 感情的トーン |

### 競合パターン分析ルール

ベンチマークデータを分析し、以下を企画判断に使う:
- **高再生タイトルの共通要素**: 情景描写の具体性と再生数の相関
- **低再生タイトルの回避要素**: 抽象的・汎用的なテーマは CTR が低い
- 具体的な場所+ムードの組み合わせが視聴者の情景想起を助ける

### OK / NG 例

- ✓ 具体的場所 + 天候/時間帯 + ムード（情景が浮かぶ）
- ✗ 汎用的すぎる、情景なし（`Relaxing Music` 等）
- ✗ 形容詞が抽象的、場所なし（`Beautiful Night Music` 等）
- ✗ カタログ的、世界観なし（`BGM Collection` 等）

## オブジェクトデザインルール

`channel_config.json` に `ideate.objects` セクションがある場合、サムネイルの差し替え可能オブジェクトと固定オブジェクトを定義する。これらはコミュニティ投稿でストーリーを展開するコンテンツ資産でもある。

`ideate.objects` がない場合、このセクションはスキップする。

### オブジェクトデザインの原則

- 各コレクションでオブジェクトを差し替え、視覚的差別化を実現する
- 名前は短く詩的に
- ストーリーは「誰が、どんな場面で、なぜ」を描写
- ビジュアルは具体的に指定（形状・色・質感）

### コミュニティ投稿での展開

オブジェクトの説明は、YouTube コミュニティ投稿で世界観を広げるコンテンツとして設計する。

### カラーセマンティクスルール（サムネイル全体）

- 背景色は `channel_config.json` の `gemini_image.brand_background` を使用（設定がある場合）
- 差別化は差し替え可能オブジェクトで行う

## オリジナリティ保証ルール

- 競合の既存タイトル・テーマとの直接的な類似は禁止
- ベンチマークから学ぶのは「パターン（構造）」であり「テーマそのもの」ではない
- 既存コレクションと類似度が高い場合は警告表示
- 各企画に「競合パターン参照元」と「差別化ポイント」を明記

## リファレンス

コレクション作成の詳細ライフサイクル（ディレクトリ構造、段階別手順、チェックリスト）は `references/collection-lifecycle.md` を参照。

## 意思決定支援

### ペルソナローテーション

`/ideate` は**1つのペルソナに絞って3つの企画候補**を生成する。次回の `/ideate` では次のペルソナに移る。

```
ローテーション: A (Maya) → B (Alex) → C (Kai) → A (Maya) → ...
```

**今回のターゲットペルソナ判定**:
1. `collections/` 配下の全 `workflow-state.json` から `planning.target_persona` を収集
2. 直近の選択ペルソナの次を今回のターゲットにする
3. 初回 or 不明 → デフォルトは A (Maya)

**3候補の差別化軸**:
同一ペルソナ向けに、差別化軸（場所 × 時間帯 × 活動 × ムード）の掛け合わせを変えて3つのバリエーションを生成する。天候は常に雨（チャンネルコンセプト）。

### 企画レポート保存

企画候補は必ずコレクションの `20-documentation/plan_proposals.md` に保存すること。

保存後、`workflow-state.json` の `planning.generated = true` に更新する。

## Next Step

企画選択時にタイトルも確定する（`workflow-state.json` の `planning.final_title` に記録）。

企画確定後、**選択した企画のプレビュー画像をコレクションの `main.png` にコピー**してからプレビューディレクトリを削除する:
```bash
# 1. 選択した企画のプレビュー画像を main.png としてコピー（複数選択時は各コレクションに対応するプレビューをコピー）
cp collections/planning/_plan-previews/<session-dir>/plan-<x>-<slug>.jpg <collection-path>/10-assets/main.png

# 2. コピー完了後、自セッションのプレビューディレクトリを削除
# <session-dir> は Phase 4-3 で作成したディレクトリ名（例: 20260306-a3f1）
rm -rf collections/planning/_plan-previews/<session-dir>/
```

> **定期クリーンアップ**: 放棄されたセッションのディレクトリが残る場合、7日以上前のものは手動削除可:
> `find collections/planning/_plan-previews/ -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +`

企画選択後:
→ `/thumbnail <theme>` でテキストオーバーレイのみ実行（`main.png` が既に存在するため Phase 2 から開始）
→ サムネイル確定後に `/suno <theme>` で SunoAI 音楽プロンプト生成（テーマ確定後に初めて実行）
