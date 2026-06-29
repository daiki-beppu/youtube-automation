---
name: thumbnail
description: "Use when コレクションのサムネイル画像が必要で、CTR最適化されたプロンプト生成 + 画像生成プロバイダー（Gemini / OpenAI / codex）での画像生成を行いたいとき。サムネイル、画像生成、CTR改善、ビジュアル制作、アイキャッチ、main.pngなど、視覚コンテンツの作成に関わる場面で必ず使用すること。Do not use when: SVG・ベクター画像の生成/編集、コード生成、YouTube サムネイル以外の汎用画像生成（これらは本スキルの対象外）"
---

## Overview

コレクション用サムネイルを `config/skills/thumbnail.yaml`（skill-config）に基づいて生成する。
チャンネルごとにスタイル・キャラ・参照画像が異なり、すべて skill-config から動的に読み取る。
画像生成プロバイダー（Gemini / OpenAI / codex）は `image_generation.provider` で切り替え可能。

> imagegen taxonomy 対応: `Use case: product-mockup (YouTube thumbnail variant)`（imagegen の 19 スラグでは product-mockup に相当）。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

`config/skills/thumbnail.yaml` はオプション。`yt-skills sync` で配布される `config.default.yaml` がそのまま使われるため、default 動作で問題なければ作成不要。カスタマイズしたい場合のみ `config.default.yaml` をコピーして `config/skills/thumbnail.yaml` に置き、必要な値だけ上書きする（deep-merge される）。

`config/channel/` が存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- コレクションが確定し、サムネイル制作に着手するとき
- CTR 最適化されたサムネイルが必要なとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | テーマ・活動指定（省略可） | `/thumbnail fiddle playing` |
| 未指定 | デフォルト活動で生成 | `/thumbnail` |

## プロバイダー切り替え

`config/skills/thumbnail.yaml` の `image_generation.provider` で選択する:

| provider | 特徴 | 必要なシークレット |
|---|---|---|
| `gemini` | Gemini Image (Nano Banana 系) | ADC (`GOOGLE_CLOUD_PROJECT` は任意で上書き可) |
| `openai` | OpenAI gpt-image 系（CJK 文字描画が綺麗、16:9/9:16 ネイティブ対応） | `OPENAI_API_KEY` |
| `codex` | `codex-image.sh` 経由で ChatGPT サブスク認証を使う（GCP 課金なし） | `codex login status` が `Logged in using ChatGPT` |

OpenAI provider 使用時は `image_generation.openai.aspect_ratio` を `"16:9"` または `"9:16"` のいずれかに設定（thumbnail スキルは内部で 16:9 固定）。

`config/skills/thumbnail.yaml` の `image_generation.provider` が未設定の場合、デフォルトは `gemini`。channel-config 側で `image_generation.provider` が明示されている場合はそちらが優先される（既存の切り替え挙動は変更しない）。

## 障害時の provider fallback

Gemini API 障害、GCP 課金切れ、ADC 認証不備、quota 超過が疑われる場合は、自動切替せずに provider を明示変更して再実行する。

GCP 課金なしで進める場合:

```yaml
# config/skills/thumbnail.yaml
image_generation:
  provider: codex
```

その後、`yt-generate-image` ではなく codex wrapper を使う:

```bash
bash .claude/skills/thumbnail/references/codex-image.sh \
  "<thumbnail prompt>" \
  <collection-path>/10-assets/main-codex.png \
  <reference-image-1> <reference-image-2>
```

OpenAI API に切り替える場合:

```yaml
image_generation:
  provider: openai
  openai:
    aspect_ratio: "16:9"
```

Gemini / OpenAI の CLI 経路で全 attempt が失敗した場合、`yt-generate-image` はこの fallback 章を案内する。生成物の品質差が出るため、自動で provider を切り替えて上書きすることはしない。

## codex 経由の生成

`image_generation.provider: codex` のチャンネルでは、`yt-generate-image` ではなく `codex-image.sh` を正規の生成経路として使う。`ImageProvider` API 実装は持たないため、`yt-generate-image` に誤配線した場合は明示エラーでこの shell 経路へ誘導される。

前提:
- codex CLI 0.131 系以降（旧 stdout プロトコル `generated image <id> <base64>` は 0.131 で削除済み）
- `codex login status` が `Logged in using ChatGPT` を返す
- `jq` が PATH 上にある（`--json` の JSONL 解析に使う）
- ChatGPT サブスクの fair-use 上限は明文化されていないため、大量生成には使わない

直接実行例:

```bash
bash .claude/skills/thumbnail/references/codex-image.sh \
  "a cozy cafe table with steaming coffee, soft morning light" \
  collections/planning/sample/main-codex.png
```

参照画像つきで雰囲気を寄せたい場合は、3 引数目以降に画像パスを追加する。

TTP 参照画像から上位互換サムネを作る場合は、長い個別指定ではなく
`image_generation.codex.default_prompt_template` を使う。参照画像は mood reference
ではなく winning template として扱い、変える要素は `{title}` と品質改善
（mobile readability / face impact / no logos / no watermarks / no broken hands）に限定する。
日本語方針は「TTPを徹底して上位互換の生成」。

既定テンプレート:

```text
TTP this reference thumbnail, then improve it into a stronger original thumbnail.
Keep the winning layout, typography feel, character scale, color mood, texture, and energy.
Make it cleaner, more readable on mobile, stronger face impact, no logos, no watermarks, no broken hands.
Use the title {title}.
```

内部実装の要約:

- wrapper は `codex exec --json --sandbox workspace-write --add-dir <out_dir> --skip-git-repo-check` で起動する
- 受け取った prompt 末尾に `Generate a new image with the image_generation tool. Do not copy any provided reference image; produce a freshly generated PNG. After generation, copy the produced PNG to <out>. Then reply with exactly <out>.` を自動付与する（後述の reference cp failure mode を抑止するため、tool 呼び出しと「reference を copy するな」を明示）
- agent 自身が `~/.codex/generated_images/<thread_id>/ig_*.png` から `<out>` へ `cp` し、最終 `agent_message.text` で `<out>` を返す
- wrapper は事前に `rm -f <out>` で stale artifact を確実に削除してから `codex exec` を起動する
- wrapper は JSONL を `jq` でフィルタし、`tail -n 1` で最後の `agent_message.text` を取得。これを JSON プロトコル契約として `<out>` と完全一致することを検証し（不一致なら非0終了）、その後 `<out>` の存在・サイズと PNG ヘッダ（`89504e470d0a1a0a`）を検証する
- reference 画像を渡したときは、wrapper が事前に各 reference の MD5 を控えておき、最終的に `<out>` の MD5 と一致したら「agent が `image_generation` tool を skip して reference をそのまま cp した」failure mode として非0終了する
- wrapper 側で指定した `<out>` がそのまま最終 path として使えるので、生成後に呼び出し側で path 解決し直す必要はない

運用上の注意:

- **prompt は短く保つ**: 長すぎる prompt は agent が `image_generation` tool 呼び出しを skip して path だけ echo する failure mode に陥る。TTP 参照画像つきでは `image_generation.codex.default_prompt_template` を使い、`{title}` だけを差し替える。失敗したら短縮を最優先で試す
- **reference 画像つきは prompt で「変更点」を明示する**: 「reference を参考に」程度の弱い指示だと agent が `image_generation` tool を skip して reference を `<out>` に cp するだけで終わる failure mode がある。wrapper の自動付与文 + MD5 一致検証で抑止しているが、prompt 側でも reference からの差分（色味の参考 / 構図だけ流用 / 主役を差し替え 等）を明示しておくと安定する
- 失敗時 wrapper は `agent_message (最終)` と codex stderr の末尾 30 行を診断 dump するので、これを見て prompt 短縮 or 参照画像見直しに切り替える

この経路のスコープ:
- `yt-generate-image` の API 呼び出しは使わない
- `ImageProvider` 実装は持たない
- wrapper 自体のリトライなし
- GCP 課金なし。ChatGPT サブスクの fair-use 対象で、`cost_per_image_usd` は通常 `null`
- `cost_tracker` 連携なし。生成回数は shell 実行ログで確認する

## Channel Adaptation

**すべての設定は `config/skills/thumbnail.yaml` から読み取る。**
スキル内にチャンネル固有のハードコードはしない。読み込みは以下のコマンドで確認できる:

```bash
uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('thumbnail'), indent=2, ensure_ascii=False))"
```

実行前に以下を確認:

1. `image_generation.provider` → 使用するプロバイダー（`gemini` / `openai` / `codex`）
2. `image_generation.gemini.model` → 使用する Gemini モデル
3. `image_generation.gemini.style` → スタイル説明（参照画像ベース or プロンプトベース）
4. `image_generation.gemini.prompt_prefix` → プロンプト冒頭の固定文（キャラ描写等）
5. `image_generation.gemini.reference_images` → 参照画像の定義（あれば参照画像モード）
6. `image_generation.gemini.fixed_character` → 固定キャラの設定（あればキャラ固定モード）
7. `image_generation.gemini.composition_rules` → 構図・環境のルール
8. `image_generation.gemini.thumbnail_text` → テキストオーバーレイの設定
9. `image_generation.gemini.generation_mode` → 生成モード（後述）
10. `image_generation.gemini.brand_background` → チャンネル統一背景色（single_step / diff_from_reference で使用）
11. `image_generation.gemini.color_themes` → テーマ別カラーパレット（single_step モードで差し替え）

## 生成モード判定

`image_generation.gemini.generation_mode` を確認:

| モード | 説明 |
|---|---|
| `single_step`（**デフォルト**・TTP 推奨）| テキスト付き参照画像から差分のみ指示し、YouTube 用のテキスト付きサムネ候補を 1 ステップで生成。ベンチマーク模倣（TTP）の標準実装 |
| `diff_from_reference` | 既存キャラ画像を参照に差分指示 |
| `two_phase` | 従来の 2 フェーズ（背景 → テキストオーバーレイ）|

### 参照画像モード（`reference_images` が定義されている場合）

参照画像を渡してスタイルを維持する方式。

```bash
uv run yt-generate-image \
  --prompt "<prompt_prefix を含むプロンプト>" \
  --reference <channel_dir>/<reference_images.default> \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y
```

**参照画像の選択ロジック**:
- `reference_images` のキーからシーンに最適なものを選択
- `path_base: "channel_dir"` の場合、パスはチャンネルディレクトリからの相対パス
- `--reference` 使用時は `composition_prefix` が自動スキップされる（generate_image.py 修正済み）

### プロンプトベースモード（`reference_images` が未定義の場合）

参照画像なしでプロンプトのみで生成する方式（フォールバック）。

```bash
uv run yt-generate-image \
  --prompt "<完全なプロンプト>" \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y
```

`composition_prefix` が自動付加される。

## プロンプト構築

プロンプト構築の原則（prompt_prefix / fixed_character / composition_rules の組み立て）は `references/prompting.md`、参照画像モード・プロンプトベースモードの具体的なプロンプトテンプレート例は `references/sample-prompts.md` を参照する。

> 将来検討（issue #654）: imagegen の 14 項目 Shared prompt schema 形式と既存 skill-config の bridge ヘルパが `references/prompt-schema.md` および `youtube_automation.utils.image_provider.prompt_schema` に試験導入されている。実本番フローからは未接続。設計判断は `docs/skill-design/ADR-001-thumbnail-prompt-schema.md`。

## ワークフロー

### 標準生成順序とファイル契約

`/thumbnail` の標準手順は、**テキスト付き YouTube サムネ → テキストなし動画背景**の順に進める。

1. ベンチマーク先サムネを参照画像にして、YouTube 用のテキスト付きサムネ候補を生成する。
2. 承認したテキスト付き画像を参照画像にして、文字・ロゴ・タイポグラフィを除去したテキストなし版を AI で再生成する。
3. テキスト付き最終サムネは `10-assets/thumbnail.jpg`、テキストなし動画背景は `10-assets/main.png` または `10-assets/main.jpg` として確定する。
4. `config/skills/loop-video.yaml::enabled: true` のチャンネルでは、テキストなし `main.png/jpg` を `/loop-video` に渡して `loop.mp4` を生成する。
5. `config/skills/loop-video.yaml::enabled: false` のチャンネルでは Veo を実行せず、テキストなし `main.png/jpg` を静止画背景として `/videoup` に渡す。

`thumbnail.jpg` はアップロード用の文字入りサムネイル、`main.png/jpg` は動画背景・loop-video 入力用の文字なし素材として扱う。両者を同一画像で代用しない。

### Single-Step / TTP モード（`generation_mode: "single_step"`、デフォルト・推奨）

ベンチマーク模倣（**TTP**: trace / imitate）の標準実装。テキスト付きベンチマーク参照画像（テキストレイアウト・背景テクスチャ・オブジェクト配置を含む）を参照にして、**変更点だけ**をプロンプトで指示する。1 回目の生成では、YouTube 用のテキスト付きサムネ候補を作る。

**重要**: 参照画像と同じ要素（レイアウト、固定オブジェクト、テキスト配置）はプロンプトに含めない。差分のみを指示することで、参照画像のクオリティを維持しつつ変更が正しく反映される。コピーではなくバリエーションを作るのがゴール。

**IP / 版権セーフティ (#569)**: TTP は参照画像のレイアウト・テクスチャ・オブジェクト配置を強く転写するため、ベンチマーク側に焼き込まれた**署名（サイン）・透かし・ロゴ・チャンネルバッジ・著作権表記等の識別マークがそのまま再現される事故が起きやすい**。プロンプト構築時は必ず標準除外 clause `no signature, no autograph, no watermark, no logo, no brand mark, clean corners` を含めること（config: `image_generation.gemini.single_step.ip_safety_clause`）。**参照元の識別マークはコピーしない — 版権 / IP リスクを生むため**、たとえ参照画像のスタイルガイドとして優秀でもサインや筆記体の署名は転写対象から外す。

#### プリフライト

`generation_mode: "single_step"` で `--reference` を指定せずに `yt-generate-image` を起動するとエラー中断する。次の対処が必要:

1. **skill-config に `reference_images.default` が未設定** → `config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.default` にベンチマークサムネのパス（文字列 1 件 or list 複数件）を設定
2. **設定はあるが CLI 引数に展開していない** → `--reference <path>` で渡す。list なら `--reference A --reference B --reference C` のように複数指定

#### 参照画像（複数 + ローテーション）

`reference_images.default` は文字列 1 件 / list 複数件の両方を受け付ける。list 指定時は同一ベンチマークチャンネル内の複数サムネ候補を並べておくことで、attempt 毎にローテーションして雰囲気が出る組合せを探れる。

| CLI 引数 | 用途 |
|---|---|
| `--max-attempts N` | 試行回数。各 attempt で参照を切替、出力は `-vN` で別保存 |
| `--no-rotate` | 切替を無効化（先頭固定） |
| `--reference-index N` | 特定の参照のみ使用（ローテーション無効、attempt=1） |

config 側のデフォルトは `image_generation.gemini.single_step.{max_attempts, rotate}` で設定可能。

#### プロンプト構築

1. `image_generation.gemini.color_themes` からテーマのカラー設定を取得
2. `image_generation.gemini.diff_prompt_template` のプレースホルダーを置換してプロンプト構築:
   - `{background}`: カラーテーマの背景色（未指定時は `image_generation.gemini.brand_background` を使用）
   - `{candle}`, `{cocktail_description}` などオブジェクト系プレースホルダ: `ideate.objects` や `color_themes` 配下の値
   - `{title_line1}`, `{title_line2}`: コレクションタイトル
3. 共通ガイダンス clause（`single_step.variation_clause` / `style_lock_clause` / `text_strip_clause` / `anatomy_clause` / `ip_safety_clause`）をチャンネル側 `diff_prompt_template` で必要に応じて挿入。**キャラ + 手が写る構図では `${anatomy_clause}` を必ず展開する**（#570、Gemini は楽器持ち・指を伸ばすポーズで指の融合・本数異常を起こしやすい）。**`ip_safety_clause` (#569) は TTP モードで常時挿入必須** — チャンネル側で `diff_prompt_template` を組み立てる際に `${ip_safety_clause}` を必ず展開し、参照元の署名・透かし・ロゴが焼き込まれないようにする。空文字に上書きしての無効化は版権 / IP リスクを生むため非推奨

#### 生成コマンド

`reference_images.default` と stock (#364 PR-B) を Python ワンライナーで合成し、`--reference` 引数を組み立てる。stock 採用ログは stderr の `[INFO] stock 採用: ...` で確認できる。

```bash
THEME="<theme-slug>"   # 例: tavern / library / jazz-bar

REFS=$(uv run python3 -c "
from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.image_provider.composition import normalize_reference_default
from youtube_automation.utils.stock import resolve_stock_refs

cfg = load_skill_config('thumbnail').get('image_generation', {}).get('gemini', {})
ref_cfg = cfg.get('reference_images', {}) if isinstance(cfg, dict) else {}
ch = channel_dir()
defaults = [str(ch / p) for p in normalize_reference_default(ref_cfg.get('default'))]
stock = [str(p) for p in resolve_stock_refs(ch, stock_refs_config=ref_cfg.get('stock', {}), theme='$THEME')]
for p in defaults + stock:
    print(p)
")

REF_ARGS=()
while IFS= read -r p; do
  [ -n "$p" ] && REF_ARGS+=(--reference "$p")
done <<< "$REFS"

uv run yt-generate-image "${REF_ARGS[@]}" \
  --max-attempts 3 \
  --prompt "<diff_prompt_template を置換したプロンプト>" \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y
```

stock 合成を一時的に止めたいときは `config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.stock.enabled: false` を上書きする（default のみで生成される）。

4. `open` でプレビュー → `/thumbnail-compare` で 320px 視認性検証 → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`
5. 承認済み `thumbnail.jpg` を参照画像にして、テキストなし動画背景を AI 再生成:

```bash
COLLECTION_PATH="<collection-path>"
TEXTLESS_PROMPT="$(cat <<'PROMPT'
<textless background regeneration prompt>
PROMPT
)"

uv run yt-generate-image \
  --reference "${COLLECTION_PATH}/10-assets/thumbnail.jpg" \
  --prompt "$TEXTLESS_PROMPT" \
  --output "${COLLECTION_PATH}/10-assets/main-v1.jpg" -y
```

テキストなし再生成プロンプトでは、参照画像の構図・主役スケール・光・色温度・背景テクスチャは維持し、タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名だけを除去する。新しいテキストを追加しないことを明示する。

6. `open` でプレビュー → ユーザー承認 → `cp main-v1.jpg main.png`（PNG が不要な運用では `main.jpg` でも可）
7. `20-documentation/thumbnail-prompts.md` に、テキスト付き生成プロンプトとテキストなし再生成プロンプトの両方を保存する

#### 運用上の注意

- **リトライ前提**: 画像生成プロバイダーは同一プロンプトでも瞬発的にエラーを返す。各 attempt 内で内蔵リトライ最大 2 回が走る
- **テキスト継承**: 参照画像内のキャッチコピー・ジャンルタグ・フォントはデフォルトで継承される。変えたい部分だけ明示指示
- **テキストなし版の作成**: `main.png/jpg` は `thumbnail.jpg` から文字だけを取り除いた動画背景素材として再生成する。文字入り `thumbnail.jpg` をそのまま動画背景や `/loop-video` 入力にしない
- **コスト**: 事前見積もりは `config/skills/thumbnail.yaml` の `image_generation.<provider>.cost_per_image_usd` を指定したときのみ CLI 表示に出る。未指定なら「不明」と表示され、実コストは GCP Cloud Console > Billing で確認する（`max_attempts × 1 リクエスト` ＋ 各 attempt で内蔵リトライ最大 2 回）

#### 失敗時の対処

雰囲気が出ない場合、ChatGPT 等の外部ツールで手動生成して `main.png` にコピーする運用は廃止。ツール内で完結する代替策:

1. `--reference-index N` で特定のベンチマーク参照に固定して試す
2. `reference_images.default` の list を見直し、別のベンチマーク候補を追加
3. `diff_prompt_template` の差分指示を見直し（特に `variation_clause` / `style_lock_clause` のオン/オフ）

差分プロンプトの具体例は skill-config の `image_generation.gemini.diff_prompt_template` を参照し、チャンネル固有のオブジェクト・カラーを埋める。実装事例として `daiki-beppu/rjn` の `config/skills/thumbnail.yaml` が参考になる（jazzgak チャンネルの 5 サムネを `color_themes.<theme>.reference_image` で多軸切替）。

#### TTP プリフライト・チェックリスト

コレクション着手時は、本章上部のプロンプト構築や生成コマンドへ進む**前**に必ずここを通す。1 項目でも欠けると TTP モードの再現性が落ちる。

- [ ] `reference_images.default` が設定済みで、直近の高再生ベンチマークサムネを指している
  ```bash
  uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('thumbnail').get('image_generation', {}).get('gemini', {}).get('reference_images', {}).get('default'), ensure_ascii=False, indent=2))"
  ```
- [ ] `image_generation.gemini.generation_mode` が `generation_mode: "single_step"` になっている。`two_phase` / `diff_from_reference` を使うなら理由を明示する
- [ ] `diff_prompt_template` に参照と重複する要素（レイアウト・固定オブジェクト・テキスト配置・既知の色味）を書いていない。差分のみを記述する
- [ ] `diff_prompt_template` に `${ip_safety_clause}` 相当の除外句（`no signature, no autograph, no watermark, no logo, no brand mark, clean corners`）を含めている (#569)。参照元ベンチマークサムネに署名・サイン・透かし・チャンネルロゴ等の識別マークがある場合は特に必須
- [ ] stock 合成（#364）の扱いを確認し、`image_generation.gemini.reference_images.stock.enabled` が意図どおりになっている
- [ ] サムネ承認**前**に `/thumbnail-compare` を実行し、320px 縮小時の文字可読性・コントラスト・主役認識を検証する段取りになっている
- [ ] 承認済み `thumbnail.jpg` からテキストなし `main.png/jpg` を AI 再生成する段取りになっている
- [ ] `20-documentation/thumbnail-prompts.md` にテキスト付き生成プロンプトとテキストなし再生成プロンプトの両方を保存する段取りになっている

チェック通過後に本章上部の手順へ戻って `/thumbnail` を進める。CLI エラーで止まったときは、このチェックリストではなく本章上部の `#### プリフライト` を参照する。

### Two-Phase モード（従来方式・フォールバック）

#### Phase 1: 背景候補生成（main.png）

**main.png が既に存在する場合は Phase 1 をスキップして Phase 2 へ進む。**
（`/collection-ideate` で本番品質のプレビューが生成され、選択後にコピーされている）

main.png が存在しない場合のみ:
1. テーマに合わせてプロンプトを構築（`references/prompting.md` の原則と `references/sample-prompts.md` のテンプレートを参照）
2. 参照画像モードなら `reference_images` から適切な画像を選択
3. 生成: `yt-generate-image --reference <参照画像> --prompt <プロンプト> --output 10-assets/main-v1.jpg -y`
4. `open` でプレビュー → ユーザー承認 → `cp main-v1.jpg main.png`

#### Phase 2: テキストオーバーレイ（thumbnail.jpg）

1. `image_generation.gemini.thumbnail_text` からテキスト設定を取得
2. テキストオーバーレイプロンプトを構築:

**`thumbnail_text.text_overlay_prompt` が定義されている場合（推奨）:**
テンプレート内の `{title_line1}`, `{title_line2}`, `{channel_name}` をコレクションのタイトルとチャンネル名で置換して使用。

**未定義の場合（フォールバック）:** `references/sample-prompts.md` の「Two-Phase モードのテキストオーバーレイ・フォールバックプロンプト」を使用する。

3. 生成: `yt-generate-image --reference 10-assets/main.png --prompt <テキスト指示> --output 10-assets/thumbnail-v1.jpg -y`
4. `open` でプレビュー → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`

## 品質チェック

生成直後の自動セルフチェック（#489）:

```bash
uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.jpg --json
```

`yt-thumbnail-check` は Gemini Vision で `collection-ideate.yaml` の `objects.fixed` と
`self_check.no_logo_guard` から YES/NO チェックリストを組み立て、画像に対する合否を
JSON で返す（終了コード 0=合格 / 1=不合格）。手作業チェックの前段スクリーニングとして、
TTP 構図逸脱（wet_runway 不在・矩形ロゴ混入・テキスト burned-in 等）を機械的に検出する。

Phase 1 生成後:
- [ ] `image_generation.gemini.style` に記載されたスタイルが維持されているか
- [ ] `composition_rules.environment` の制約を満たしているか
- [ ] `fixed_character` の外見が維持されているか（ある場合）
- [ ] キャラの顔が見えているか（`fixed_character.face` の指示通り）
- [ ] キャラサイズが `composition_rules.character_size` を満たしているか
- [ ] テキストが入っていないか
- [ ] **解剖学チェック（手・指）**: キャラが写っている場合、手・指が解剖学的に正しいか（各手 5 本指・指の分離が明瞭・指の融合や本数異常・溶融が無い・プロポーションが破綻していない）。**特に楽器持ちキャラ・指を伸ばす/握るポーズでは Gemini が破綻しやすい**ため必ず Read ツールで等倍プレビューを開いて目視確認する。NG なら `anatomy_clause` を強調 / 再生成 / プロバイダー切り替え（codex は人体破綻に強い傾向）で対応する（#570）

Phase 2 生成後:
- [ ] 背景が変わっていないか
- [ ] タイトルテキストが `composition_rules.text_lines` の制約内か
- [ ] `thumbnail_text.channel_name` が表示されているか

> **Note (#570)**: キャラ + 手が写る構図では、`image_generation.gemini.single_step.anatomy_clause` をプロンプト末尾に `${anatomy_clause}` として展開しておくと、Gemini の手・指破綻（指の融合・本数異常・溶融）の発生率を下げられる。`/collection-ideate` の single_step プレビューを最終 thumbnail に流用する場合（`/wf-new` Phase 2c）も、承認前に最低限の QA（手・指 / 文字 / 署名）を必ず通すこと。

## 視認性検証と整合性監査の役割分担

`/thumbnail-compare` と `/alignment-check` は並走で使うが、見る対象とタイミングが異なる。

| スキル | 役割 | スコープ | 主指標 | 実行タイミング |
|---|---|---|---|---|
| `/thumbnail-compare` | 視認性検証 | 単体サムネ × ベンチマーク | 320px 縮小可読性・コントラスト・キャラ認識 | サムネ承認**前**（TTP プリフライトでも確認） |
| `/alignment-check` | 整合性監査 | コレクション全体（音楽 × サムネ × タイトル） | ムード / ビジュアル / タイトル訴求の一致 | 公開**後**、または方向性見直し時 |

1. `/thumbnail` で候補生成後、承認前に `/thumbnail-compare` を実行して視認性検証を通す。
2. 承認・公開後、または方向性見直し時に `/alignment-check` でコレクション全体の整合性監査を行う。
3. `/alignment-check` で不整合が出たコレクションは `/thumbnail` で再生成し、再度 `/thumbnail-compare` で 320px 視認性を確認する。

## プロンプト保存

プロンプトは `20-documentation/thumbnail-prompts.md` に保存:

```markdown
# Thumbnail Prompts - <コレクション名>

*プロバイダー: {image_generation.provider}*
*スタイル: {image_generation.gemini.style}*
*モデル: {image_generation.gemini.model}*
*参照画像: <使用した参照画像>*

## Text-Included Thumbnail Prompt (thumbnail.jpg)

\```
<ベンチマーク参照画像からテキスト付きサムネを生成したプロンプト>
\```

## Textless Background Regeneration Prompt (main.png/main.jpg)

\```
<承認済み thumbnail.jpg からテキストなし背景を再生成したプロンプト>
\```
```

## ファイル命名ルール（上書き禁止）

| ファイル | 用途 |
|---------|------|
| `thumbnail.jpg` | YouTube アップロード用のテキスト付き最終サムネ |
| `thumbnail-v{N}.jpg` | テキスト付き候補 |
| `main.png` / `main.jpg` | 動画背景・`/loop-video` 入力用のテキストなし最終画像 |
| `main-v{N}.jpg` | テキストなし背景候補 |
| `loop.mp4` | `loop-video` 有効チャンネルだけで生成する動画背景。無効チャンネルでは作らない |

### クリーンアップ（承認後に必ず実行・stock 退避）

不採用候補は `<channel_dir>/assets/stock/<theme>/` に隣接メタデータ付きで退避する（#364）。

```bash
THEME="<theme-slug>"   # 例: tavern / library / jazz-bar
uv run yt-stock-archive \
  10-assets/main-v*.jpg 10-assets/thumbnail-v*.jpg \
  --theme "$THEME" \
  --source-collection "$(pwd)" \
  --source-role thumbnail_candidate \
  --meta-json - <<JSON
{
  "provider": "<provider>",
  "model": "<model>",
  "generation_mode": "<mode>",
  "prompt": "<最終生成プロンプト>",
  "reference_images": ["<参照画像 1>", "<参照画像 2>"]
}
JSON
```

`config/skills/thumbnail.yaml` の `image_generation.stock.enabled: false` に設定するとこの CLI は退避せず単純削除（従来挙動）に戻る。

### `workflow-state.json` 更新

画像確認・承認後、`thumbnail.approved = true` を更新する。

## stock 退避と再利用

不採用画像は `<channel_dir>/assets/stock/<theme-slug>/` に画像本体 + 隣接 `<image>.meta.json` で退避される（schema_version=1）。メタには prompt / provider / model / generation_mode / source_collection / reference_images / generated_at / rejected_at を保存し、将来別コレクションの参照画像として再利用できる。

stock の操作 CLI:

| CLI | 用途 |
|---|---|
| `yt-stock-list [--theme T] [--source-role R] [--limit N] [--format table\|json]` | stock 一覧（新しい順） |
| `yt-stock-preview [--theme T] [--limit N]` | macOS `open` でプレビュー起動 |
| `yt-stock-prune [--retention-days N] [--max-per-theme N] [--dry-run]` | 古い画像 / 上限超過分を削除（config 既定値あり） |

`config/skills/thumbnail.yaml` の `image_generation.stock`:

```yaml
image_generation:
  stock:
    enabled: true          # false で退避を無効化（unlink のみ）
    retention_days: 90     # yt-stock-prune の保持日数
    max_per_theme: 50      # yt-stock-prune の上限
```

### stock 再利用（参照画像プールへの自動合成）

PR-B (#364): 上記「生成コマンド」の Python ワンライナーで `resolve_stock_refs()` を呼び、stock 画像を `reference_images.default` の末尾に合成して `--reference` に展開する。`composition.select_reference` の attempt ローテーション対象になるため、`--max-attempts N` を増やすほど stock 由来のバリエーションが反映される。

- **デフォルト動作**: `enabled: true` (opt-out) で `source_role="thumbnail_candidate"` のみ採用、`theme_match="exact"` で同テーマのみ。stock が 0 件なら default のみで生成（`fallback_when_empty: true`）。
- **採用ログ**: 1 枚採用ごとに stderr へ `[INFO] stock 採用: <path> (theme=<t>, role=thumbnail_candidate)` を出力。監査時は stderr を grep。
- **無効化**: `config/skills/thumbnail.yaml` で `image_generation.gemini.reference_images.stock.enabled: false` を上書き。
- **チューニング**: `max_count` / `shuffle` / `theme_match: "any"` / `source_role: null` (role フィルタなし) などをチャンネル側で調整。

```yaml
image_generation:
  gemini:
    reference_images:
      stock:
        enabled: true
        max_count: 3
        theme_match: "exact"     # "any" で全テーマ横断
        source_role: "thumbnail_candidate"
        shuffle: true
        seed: null
        fallback_when_empty: true
```

## 長時間処理の取り扱い

`yt-generate-image` は Gemini / OpenAI への API 同期呼び出しで **10〜30 秒** ブロックする。`--max-attempts N` でローテーション生成する場合は `N × 10〜30 秒` かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
uv run yt-generate-image \
  --reference <ref> --prompt "<prompt>" \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y \
  > /tmp/thumbnail-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ サムネイル画像を生成中（推定 N × 10〜30 秒）。完了まで他の質問にもお答えできます。
> ログ: /tmp/thumbnail-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "thumbnail" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "thumbnail"` + `cmux notify --title "thumbnail 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（生成された `thumbnail-vN.jpg` のパス、attempt 回数、内部リトライ有無）をユーザーへ返す。プロバイダーが瞬発エラーを返した場合はそのエラー行を抜き出して報告する。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| GCP ADC 未取得/失効 | `ConfigError` / ADC 認証エラー | `gcloud auth application-default login`（必要なら `set-quota-project`）を再実行 |
| Vertex AI rate | HTTP 429 | 時間を置いて再実行。並列実行を避け順次処理する |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud（Vertex AI）のステータスを確認し、時間を置いて再実行 |
| 画像 provider 障害 | 片方の provider のエラー | `image_generation.provider` を `gemini` ↔ `openai` で切り替える |

## Next Step

サムネイル確定後:
→ `/suno <theme>` で音楽プロンプト生成
