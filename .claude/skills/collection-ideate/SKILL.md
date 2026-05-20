---
name: collection-ideate
description: Use when 新コレクションの企画が必要なとき、データドリブンな意思決定をしたいとき。「次何作る？」「テーマ選び」「コレクション候補」「企画提案」「アイデア」など、新規コンテンツの方向性を決める場面で必ず使用すること
---

## Overview

最新の分析データ + 競合ベンチマークを基に、各ペルソナ向けの企画提案を自動生成する。
設定は `config/skills/collection-ideate.yaml` を参照。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

`config/skills/collection-ideate.yaml` および `config/skills/thumbnail.yaml`（Phase 4 で使用）はオプション。`yt-skills sync` で配布される `config.default.yaml` がそのまま使われるため、default 動作で問題なければ作成不要。カスタマイズしたい場合のみ `config.default.yaml` をコピーして `config/skills/<skill>.yaml` に置き、必要な値だけ上書きする（deep-merge される）。

`config/channel/` が存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 新コレクションの企画が必要なとき
- 戦略の見直し・次期コンテンツ計画を立てたいとき
- データに基づいた意思決定をしたいとき

## 前提スキル状態確認

Phase 1 に入る前に analyze / benchmark / persona / viewing-scene の状態を確認する。
`/analytics-analyze` と `/benchmark` は独立・並列で鮮度判定（stale 検出）、`/audience-persona` と `/viewing-scene` は
存在チェックのみ（更新タイミングは戦略判断のため人間が決める）。

- `/analytics-analyze` が未生成 or stale → ユーザーに `/analytics-analyze` 実行を案内（必要なら `/analytics-collect` 先行）。**自動呼び出し不可**（AI 推論コスト発生のため）
- `/benchmark` が stale → Skill ツールで実行（内部で差分更新）
- `/audience-persona` が未生成 → ユーザーに案内（更新タイミングは戦略判断のため人間が決める）
- `/viewing-scene` が未生成 → ユーザーに案内（persona 下流のため連動して判断）

判定ルール（鮮度・存在チェックの擬似コード・workflow-state との同期）は
`references/freshness-rules.md` を参照。stale または未生成を検出したら Phase 1 を中断して該当スキルの実行を促すこと。

## 実行フロー

### Phase 1: 現状分析・データ収集

#### Phase 1-1: チャンネル現状 + 戦略ドキュメント

`yt-channel-status` でチャンネル統計を取得し、既存コレクション一覧・テーマカバレッジを把握。

```bash
uv run yt-channel-status
```

続いて戦略ドキュメントを Read で読み込み、チャンネル方向性を把握する:

- `docs/channel/strategy.md` — チャンネル戦略の集約文書
- `docs/channel/channel-direction.md` — 方向性決定の記録

どちらも任意扱い。存在しない場合は warning を表示して進行する（`/channel-direction` で生成できる旨を案内）。

#### Phase 1-2: 自チャンネル Analytics 分析

最新 `reports/analysis_*.md` を Read で読み込み、自チャンネルのパフォーマンス示唆を取り込む。
以下のセクションが `/collection-ideate` 企画立案の直接入力:

- **§ 5 戦略的改善提案** — CTR 改善・コンテンツ最適化の方向性
- **§ 6 推奨される次期コレクション候補** — データから導出されたテーマ候補
- **§ 8 戦略ディスカッション** — 長期視点の示唆

**エラーハンドリング**:

- `reports/analysis_*.md` が存在しない → **即中断**。ユーザーに `/analytics-collect` → `/analytics-analyze` の先行実行を案内
- `reports/` が stale（最新 `data/analytics_data_*.json` のファイル名日付より古い）→ 中断。`/analytics-analyze` 再実行を案内

#### Phase 1-3: 競合ベンチマーク分析

**Skill ツールで `/benchmark` を実行** — `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古いファイルがあれば YouTube Data API (OAuth) で最新データを自動取得・更新する。最新であればスキップされる。

更新完了後、`docs/benchmarks/` 配下の全 `.md` ファイルを Read ツールで読み込み、以下を抽出:
- 競合チャンネルの高パフォーマンステーマ（再生数上位）
- 共通成功パターン（`common-patterns.md`）
- 自チャンネルへの戦略的示唆
- 競合がカバー済みのテーマ（差別化のため）

#### Phase 1-4: 統合分析

Phase 1-1〜1-3 の入力を統合し:

- テーマカバレッジマップ（自チャンネル vs 競合）
- 未開拓 × 高ポテンシャルのテーマ候補リスト（自チャンネル分析の示唆を優先）
- 差別化可能な切り口の特定
- 競合パターン参照と自チャンネル強みの掛け合わせ

### Phase 2: 戦略的企画立案
**youtube-video-planner** サブエージェント（Task ツール）で分析結果から CTR 改善に最適なテーマ戦略を構築。

### Phase 3: ペルソナベース企画候補生成
**rpg-collection-research-agent** と **rpg-storytelling-agent** サブエージェント（Task ツール）を連携して、各ペルソナ向けの企画候補を生成。

### Phase 4: プレビューサムネイル生成

既定では `preview.thumbnail_mode: parallel` ── テキストで `preview.candidate_count` 案（デフォルト 3）を先に提示して合意を取り、その後 `candidate_count` 枚を一括生成して比較選択する。コストを抑えたい場合は `sequential` に切り替えると「テキスト `candidate_count` 案 → 選択 → 選択 1 案だけ生成」フローになる（コスト 1/`candidate_count`、節末「Phase 4 補足: sequential モード (opt-in)」参照）。

以下、本文中の Bash 例・テーブル・採番（A/B/C / plan-a/b/c）はすべて `candidate_count = 3` のときのサンプル。`candidate_count` を変更した場合は連打回数・採番をその値に合わせて調整すること。

両モード共通の前半（4-1〜4-2）でテキスト案提示とコスト合意を済ませてから、後半（4-3〜4-5）で生成・比較・選択に進む。

**4-1: 企画 `candidate_count` 案（プロンプト本文込み）をテキストで提示**

`preview.candidate_count`（デフォルト 3）個の企画について、`/thumbnail` スキルの Phase 1 と同等の本番品質プロンプトを **テキストで** 生成・提示する。この段階では画像は生成しない。

- `config/skills/thumbnail.yaml` の `image_generation.gemini.prompt_prefix` + `composition_rules` を完全適用
- 英語 1 段落、誇張表現禁止、16:9 構図、テキスト除外
- **本番品質で生成する**（選択された企画のプロンプトをそのまま `yt-generate-image` に渡すため、再生成によるばらつきを避ける）

各企画について、テーマ・タイトル・オブジェクト定義・サムネプロンプト全文をユーザーに提示する。プロンプト本文も比較材料に含めることで、視覚出力を見る前にユーザーが意図を把握できる。

**4-2: コスト一括確認**

事前見積もりは `config/skills/thumbnail.yaml` の `image_generation.<provider>.cost_per_image_usd` を
指定したときのみ提示する（Issue #132 以降、ハードコード単価表は撤廃済み）。実コストは GCP Cloud
Console > Billing で確認する。`thumbnail_mode` によって生成枚数が異なるため、ワンライナーで自動分岐させる:

```bash
uv run python3 -c "
from youtube_automation.utils.image_provider import load_image_generation_config
from youtube_automation.utils.skill_config import (
    load_skill_config,
    get_collection_ideate_thumbnail_mode,
    THUMBNAIL_MODE_SEQUENTIAL,
)
ic = load_skill_config('collection-ideate').get('preview', {})
cfg = load_image_generation_config()
mode = get_collection_ideate_thumbnail_mode()
count = 1 if mode == THUMBNAIL_MODE_SEQUENTIAL else ic.get('candidate_count', 3)
if cfg.provider == 'gemini':
    model = cfg.gemini.model
    image_size = cfg.gemini.image_size
else:
    model = cfg.openai.model
    image_size = cfg.openai.quality
tc = load_skill_config('thumbnail').get('image_generation', {}).get(cfg.provider, {})
per = tc.get('cost_per_image_usd')
if per is None:
    print(f'{count} 枚 × 不明 ({mode} / {model} / {image_size}) — config/skills/thumbnail.yaml の cost_per_image_usd 未設定')
else:
    print(f'{count} 枚 × \${per:.3f} = \${count*per:.3f} ({mode} / {model} / {image_size})')
"
```

例（`cost_per_image_usd` が設定済み・parallel・`candidate_count=3` の場合）: `3 枚 × $0.101 = $0.303 (parallel / gemini-3.1-flash-image-preview / 2K)`

**ユーザーが拒否した場合** → サムネ生成を完全スキップしテキストのみで提示（プレビューサムネイル生成はブロッキングにしない）。`main.png` は未生成のまま Next Step に進み、後段の `/thumbnail <theme>` が `main.png` 不在を検出して Phase 1 から本番サムネを新規生成する（Next Step の「コスト拒否 / 生成失敗で main.png が無い場合」参照）。

**4-3: セッションディレクトリ作成**

両モード共通。生成出力先となるセッション固有のディレクトリを作成する:

```bash
# <YYYYMMDD> は実行日（例: 20260306）
# <SESSION_ID> はセッション開始時に生成したランダム ID
# バイト数は config/skills/collection-ideate.yaml の preview.session_id_bytes（デフォルト 2 → hex 4 文字）
SESSION_ID=$(openssl rand -hex 2)
PREVIEW_DIR="<YYYYMMDD>-${SESSION_ID}"
mkdir -p collections/planning/_plan-previews/${PREVIEW_DIR}
```

`_` プレフィックスで通常コレクションと区別。セッション ID 付きディレクトリで並列実行時の競合を回避する。

**4-4: プロンプト構築 + 一括生成（parallel デフォルト）**

`config/skills/thumbnail.yaml` の `image_generation.gemini.generation_mode` を確認:

- **`single_step` の場合**: `image_generation.gemini.diff_prompt_template` をベースに、オブジェクトデザインルール（`ideate.objects` が定義されている場合）に従って企画ごとのオリジナルオブジェクトを指定。
  - **背景色**: `image_generation.gemini.brand_background` を使用（定義がある場合）。全コレクション統一
  - **差別化はオブジェクトで行う**: `ideate.objects.swappable` で定義されたスロットを企画ごとに変える
  - 具体的な差分プロンプトの書き方は `references/object-design-examples.md` を参照

- **それ以外の場合**: 4-1 で生成済みの本番品質プロンプトをそのまま流用

`REF_ARGS` を構築してから `preview.candidate_count` 枚を順次生成する:

```bash
# <dir> は 4-3 で作成したセッション固有ディレクトリ名（例: 20260306-a3f1）
# <slug> はテーマ名をケバブケースに変換（例: "The Wanderer's Road" → "wanderers-road"）
# THEME はコレクションテーマ slug。ideate 段階の暫定値で OK
#   (stock_refs.theme_match="exact" で 0 件なら fallback_when_empty=true で default のみで生成)
THEME="<slug>"

REFS=$(uv run python3 -c "
from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.image_provider.composition import normalize_reference_default
from youtube_automation.utils.stock import resolve_stock_refs

thumb = load_skill_config('thumbnail').get('image_generation', {}).get('gemini', {})
ref_cfg = thumb.get('reference_images', {}) if isinstance(thumb, dict) else {}
ch = channel_dir()
defaults = [str(ch / p) for p in normalize_reference_default(ref_cfg.get('default'))]

# PR-B (#364): preview.stock_refs が true なら stock を ideate_preview role で混ぜる
ideate_cfg = load_skill_config('collection-ideate').get('preview', {})
stock = []
if ideate_cfg.get('stock_refs', True):
    stock_cfg = dict(ref_cfg.get('stock', {}))
    stock_cfg['source_role'] = 'ideate_preview'   # ideate スキル専用に上書き
    stock = [str(p) for p in resolve_stock_refs(ch, stock_refs_config=stock_cfg, theme='$THEME')]

for p in defaults + stock:
    print(p)
")

REF_ARGS=()
while IFS= read -r p; do
  [ -n "$p" ] && REF_ARGS+=(--reference "$p")
done <<< "$REFS"

# 順次実行（API レート制限回避）。以下は candidate_count=3 のサンプル。
# 違う値の場合は連打数と plan-{a,b,c,...} の採番をその値に合わせて調整する。
uv run yt-generate-image "${REF_ARGS[@]}" --prompt "<企画Aプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-a-<slug>.png -y
uv run yt-generate-image "${REF_ARGS[@]}" --prompt "<企画Bプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-b-<slug>.png -y
uv run yt-generate-image "${REF_ARGS[@]}" --prompt "<企画Cプロンプト>" --output collections/planning/_plan-previews/<dir>/plan-c-<slug>.png -y
```

- 全企画とも同じ `REF_ARGS` を共有（stock シャッフル結果も共有）。stock 採用ログは stderr `[INFO] stock 採用: ...` に出る
- 出力先: `collections/planning/_plan-previews/<dir>/plan-<x>-<slug>.png`（`<x>` は a/b/c/... のラベル、`candidate_count` 枚ぶん）
- `-y` 指定時、同名ファイルが既存なら自動で `-v2`, `-v3` ... と採番（追加の安全策）
- stock 合成を止めたい場合は `config/skills/collection-ideate.yaml` の `preview.stock_refs: false`、または thumbnail 側の `image_generation.gemini.reference_images.stock.enabled: false` を上書き

**4-5: 全枚を比較提示 → ユーザー選択**

1. `open` で全枚を同時にプレビューアプリで開く（`candidate_count=3` の例。違う値の場合はブレース展開を調整）:

   ```bash
   open collections/planning/_plan-previews/<dir>/plan-{a,b,c}-*.png
   ```

2. Read ツールでも各プレビュー画像を表示しながら企画を提示する
3. 各企画にはサムネイル情報に加え、`ideate.objects` で定義されたオブジェクトの名前・ストーリーを併記する（`objects` 未定義時は省略）
4. 生成に失敗した分はテキストのみで提示（「プレビュー生成失敗」と明記）

ユーザーから採用企画を番号（A, B, C, ... のラベル）または企画タイトルで受け取る。NG だった場合の戻り経路:

- 同じペルソナで再生成したい → Phase 3 から再実行
- 別ペルソナに切り替えたい → ペルソナローテーション（後述）に従って次ペルソナで再実行
- 個別画像だけ気に入らない → 該当企画を 4-4 のコマンドで単発再生成

parallel モードでは Next Step で `yt-stock-archive` による不採用 (`candidate_count` - 1) 枚の stock 退避が走る（「Next Step」参照）。

---

### Phase 4 補足: sequential モード (opt-in)

`config/skills/collection-ideate.yaml` で `preview.thumbnail_mode: sequential` に切り替えた場合のみ実行する。コストは parallel の 1/`candidate_count`（`candidate_count=3` で例えば `1 枚 × $0.101 = $0.101`）。テキスト案のプロンプト本文だけで企画を絞り込めるときに有効。

**sequential 用 4-1 / 4-2**: 共通。4-2 のコストワンライナーは `mode == sequential` のとき `count = 1` を返すため自動的に `1 枚 × $X` 表示になる。コスト拒否時の挙動も共通。

**sequential 用 4-3 (セッションディレクトリ作成)**: 共通。

**sequential 用 4-4 (選択 → 1 枚生成)**:

先にユーザーから採用企画を番号（A, B, C, ... のラベル）または企画タイトルで受け取り（不採用 (`candidate_count` - 1) 案は破棄、画像は未生成なので副作用なし）、選択 1 案のみ `yt-generate-image` を 1 回呼ぶ:

```bash
# <x> は選択された企画の番号（a/b/c）
uv run yt-generate-image "${REF_ARGS[@]}" \
  --prompt "<選択された企画のプロンプト>" \
  --output collections/planning/_plan-previews/<dir>/plan-<x>-<slug>.png -y
```

**sequential 用 4-5 (1 枚承認)**:

1. `open` で生成 1 枚をプレビューアプリで開く
2. Read ツールでもプレビュー画像を表示する
3. オブジェクトの名前・ストーリーを併記する
4. 承認 NG / 生成失敗の場合は次のいずれかの経路で復帰:
   - 同じ企画で再生成 → 4-4 を再実行
   - 別の企画に切り替え → 4-4 の選択からやり直し

sequential モードでは Next Step で stock 退避は走らない（不採用画像が生成されていない）。

## ペルソナベース企画フレームワーク

`docs/channel/personas/persona-definition.md` で定義されたペルソナに対し、各 1 企画を生成する。
ペルソナの視聴シーン・ユースケースから情景を導出し、差別化軸と掛け合わせてテーマを決定する。

`docs/channel/personas/persona-definition.md` が存在する場合、そこからペルソナを読み込む。鮮度・未生成の判定ルールは冒頭の「前提スキル状態確認」セクションに従う。

**存在しない場合は ideate を進めず、以下を案内して停止する:**

```
❌ docs/channel/personas/persona-definition.md が見つかりません。
   先に `/audience-persona` を実行してターゲットペルソナを定義してください。
   （チャンネル立ち上げ直後なら `/channel-direction` → `/audience-persona` → `/collection-ideate` の順）
```

今回のターゲットペルソナに対し、差別化軸（`config/skills/collection-ideate.yaml` の `differentiation_axes`、デフォルト: location / time_of_day / activity / mood）の掛け合わせで `candidate_count` 個の候補を生成する。以下は `candidate_count=3` のときのテンプレ:

| 企画 | 差別化の切り口 |
|------|---------------|
| **企画 1** | 軸 A × 軸 B のバリエーション |
| **企画 2** | 軸 C × 軸 D のバリエーション |
| **企画 3** | 競合の高再生パターンをペルソナ視点で再解釈 |

`candidate_count` を変えた場合は枠を増減し、各企画ごとに異なる差別化軸の組み合わせ or 競合パターン再解釈を割り当てる。

### カラールール

- **背景色**: `config/skills/thumbnail.yaml` の `image_generation.gemini.brand_background` を使用（定義があれば全コレクション統一）
- **差別化はオブジェクトで行う**: `ideate.objects.swappable` を企画ごとに変える

各企画には以下を必ず含める:
- **ターゲットペルソナ**: 名前・視聴シーン・ユースケース
- **競合パターン参照**: どの競合の成功パターンを参考にしたか
- **差別化ポイント**: 既存コレクションとどう異なるか
- **情景没入スコア**: サムネイル + タイトルで情景が浮かぶ度合い（高/中/低）
- **オブジェクト定義**: `ideate.objects.swappable` 各スロットの具体値（名前・ストーリー・ビジュアル）

## 企画ルール

`config/channel/meta.json` の `channel.core_message` と `config/channel/content.json` の `genre.*` からチャンネルの世界観を読み取り、一貫した企画を立案する。

`config/channel/content.json` の `title.template` に基づくタイトル構造を使用。

### タイトルテンプレート

`config/channel/content.json` の `title.template` を参照。テーマに合わせて動的要素を調整。

### 差別化軸

`config/skills/collection-ideate.yaml` の `differentiation_axes` を使用。デフォルト軸:

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

`config/skills/collection-ideate.yaml` に `objects` セクションがある場合、サムネイルの差し替え可能オブジェクトと固定オブジェクトを定義する。

`objects` がない場合、このセクションはスキップする（サムネイル差別化はカラー・構図のみになる）。

### オブジェクトデザインの原則

- 各コレクションでオブジェクトを差し替え、視覚的差別化を実現する
- 名前は短く詩的に
- ストーリーは「誰が、どんな場面で、なぜ」を描写
- ビジュアルは具体的に指定（形状・色・質感）

具体例は `references/object-design-examples.md` を参照。

## オリジナリティ保証ルール

`config/skills/collection-ideate.yaml` の `originality` を参照:

- 競合の既存タイトル・テーマとの類似度が `originality.max_similarity` を超えたら警告
- ベンチマークから学ぶのは「パターン（構造）」であり「テーマそのもの」ではない
- 既存コレクションと類似度が高い場合は警告表示
- `originality.require_pattern_reference: true` の場合、各企画に「競合パターン参照元」と「差別化ポイント」を明記

## リファレンス

コレクション作成の詳細ライフサイクル（ディレクトリ構造、段階別手順、チェックリスト）は `references/collection-lifecycle.md` を参照。

## 意思決定支援

### ペルソナローテーション

`/collection-ideate` は**1 つのペルソナに絞って `preview.candidate_count` 個の企画候補**を生成する。次回の `/collection-ideate` では次のペルソナに移る。

**今回のターゲットペルソナ判定**:
1. `collections/` 配下の全 `workflow-state.json` から `planning.target_persona` を収集
2. 直近の選択ペルソナの次を今回のターゲットにする
3. 初回 or 不明 → `docs/channel/personas/persona-definition.md` の先頭ペルソナ

**`candidate_count` 候補の差別化軸**:
同一ペルソナ向けに、`differentiation_axes` の掛け合わせを変えてバリエーションを生成する。

### 企画レポート保存

企画候補は必ずコレクションの `20-documentation/plan_proposals.md` に保存すること。

保存後、`workflow-state.json` の `planning.generated = true` に更新する。

## Next Step

企画選択時にタイトルも確定する（`workflow-state.json` の `planning.final_title` に記録）。

企画確定後、**選択した企画のプレビュー画像を `main.png` にコピー**してセッションディレクトリを削除する。`thumbnail_mode` と「画像が生成されたか」によって手順が分岐するため、ケース別に示す。

### parallel モード（デフォルト）

不採用 (`candidate_count` - 1) 枚を `assets/stock/<theme>/` に退避してからプレビューディレクトリを削除する（#364）:

```bash
# 1. 選択した企画のプレビュー画像を main.png としてコピー
cp collections/planning/_plan-previews/<session-dir>/plan-<x>-<slug>.png <collection-path>/10-assets/main.png

# 2. 不採用プレビューを stock 退避（--exclude で採用 1 枚だけ除外）
THEME="<theme-slug>"   # コレクションのテーマ slug
uv run yt-stock-archive \
  collections/planning/_plan-previews/<session-dir>/plan-*.png \
  --theme "$THEME" \
  --source-collection "<collection-path>" \
  --source-role ideate_preview \
  --exclude "plan-<x>-<slug>.png" \
  --meta-json - <<JSON
{
  "provider": "<provider>",
  "model": "<model>",
  "generation_mode": "<mode>",
  "prompt": "<企画 X の最終プロンプト>",
  "reference_images": ["<reference_images.default で使用した paths>"],
  "persona": "<planning.target_persona>"
}
JSON

# 3. 退避後、自セッションのプレビューディレクトリを削除
rm -rf collections/planning/_plan-previews/<session-dir>/
```

parallel モードでは `config/skills/collection-ideate.yaml` の `preview.stock_archive: false` か `config/skills/thumbnail.yaml` の `image_generation.stock.enabled: false` のいずれかで stock 退避を無効化できる（無効化時は CLI 経由で単純削除に戻る）。

### sequential モード時の Next Step

不採用 (`candidate_count` - 1) 案は画像が未生成なので stock 退避は不要。`cp` 1 回 + `rm -rf` だけで済む:

```bash
# 1. 選択した企画のプレビュー画像を main.png としてコピー
cp collections/planning/_plan-previews/<session-dir>/plan-<x>-<slug>.png <collection-path>/10-assets/main.png

# 2. セッションディレクトリ削除
rm -rf collections/planning/_plan-previews/<session-dir>/
```

### コスト拒否 / 生成失敗で main.png が無い場合

4-2 でユーザーがコストを拒否、または 4-4 / 4-5 で全枚生成失敗した場合は `main.png` が未生成のまま Next Step を抜ける。`cp` は実行せず、セッションディレクトリが存在すれば削除する:

```bash
# 採用画像が無いので main.png コピーはスキップ
# セッションディレクトリが残っていれば削除（部分生成のゴミ掃除）
[ -d collections/planning/_plan-previews/<session-dir> ] && rm -rf collections/planning/_plan-previews/<session-dir>/
```

このケースでは下流の `/thumbnail <theme>` が `main.png` 不在を検出し、**Phase 1 から** 本番サムネを新規生成する流れに合流する（下記「企画選択後」参照）。

> **定期クリーンアップ**: 放棄されたセッションのディレクトリが残る場合、7 日以上前のものは手動削除可:
> `find collections/planning/_plan-previews/ -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +`
>
> stock 側の保守は `uv run yt-stock-prune --dry-run` で候補確認 →（必要なら）本実行。

企画選択後:
→ `/thumbnail <theme>` でサムネ仕上げに進む。`main.png` が既に存在する場合は Phase 2 からテキストオーバーレイのみ実行。コスト拒否や生成失敗で `main.png` が無い場合は Phase 1 から本番サムネを新規生成する
→ サムネイル確定後に `/suno <theme>` で SunoAI 音楽プロンプト生成（テーマ確定後に初めて実行）
