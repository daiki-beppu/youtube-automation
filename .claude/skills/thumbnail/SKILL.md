---
name: thumbnail
description: "Use when コレクションの YouTube サムネイル（thumbnail.jpg）を CTR 最適化し、textless main.png/jpg を後続生成するとき。「サムネイル」「画像生成」「アイキャッチ」で発動。SVG・汎用画像生成には使わない"
---

## Overview

コレクション用サムネイルを `config/skills/thumbnail.yaml`（skill-config）に基づいて生成する。
チャンネルごとにスタイル・キャラ・参照画像が異なり、すべて skill-config から動的に読み取る。
画像生成プロバイダー（Gemini / OpenAI / codex）は `image_generation.provider` で切り替え可能。

> imagegen taxonomy 対応: `Use case: product-mockup (YouTube thumbnail variant)`（imagegen の 19 スラグでは product-mockup に相当）。

## 設定読み込みゲート

前提確認や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/thumbnail/config.default.yaml`
2. `config/skills/thumbnail.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("thumbnail")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。このスキルが別 skill の skill-config を直接参照する段階では、その skill の `config.default.yaml` と `config/skills/<skill>.yaml` も同じ手順で読む。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

`config/skills/thumbnail.yaml` はオプション。`yt-skills sync` で配布される `config.default.yaml` がそのまま使われるため、default 動作で問題なければ作成不要。カスタマイズしたい場合のみ `config.default.yaml` をコピーして `config/skills/thumbnail.yaml` に置き、必要な値だけ上書きする（deep-merge される）。

`config/channel/` が存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## 完了条件

- `10-assets/thumbnail.jpg`（テキスト付き YouTube サムネ）と `10-assets/main.png`（または `main.jpg`、textless 動画背景）が**別成果物として**それぞれユーザー承認・確定済み
- テキスト付きサムネは承認前に `/thumbnail-compare` の 320px 視認性検証を通過している
- `20-documentation/thumbnail-prompts.md` に textless 背景用・テキスト付き用の両プロンプトを保存済み
- `workflow-state.json` の `thumbnail.approved = true` に更新済み

**読み順**: 標準フローは「ワークフロー > 標準生成順序とファイル契約」から読む。「codex 経由の生成」章は `image_generation.provider: codex` のチャンネルのみ、「フォント安定化」「自動選択」章は該当機能を明示的に使うチャンネルのみ参照すればよい。

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

OpenAI provider 使用時は `image_generation.openai.aspect_ratio` を `"16:9"` または `"9:16"` のいずれかに設定（thumbnail スキルは内部で 16:9 固定）。`image_generation.openai.quality` の既定は `medium`。`high` は 1 枚あたりの単価が数倍高いため、コストを許容できるチャンネルのみ `quality: high` を明示指定する。

`config/skills/thumbnail.yaml` の `image_generation.provider` が未設定の場合、デフォルトは `gemini`。channel-config 側で `image_generation.provider` が明示されている場合はそちらが優先される（既存の切り替え挙動は変更しない）。

## 障害時の provider fallback

Gemini API 障害、GCP 課金切れ、ADC 認証不備、quota 超過が疑われる場合は、自動切替せずに provider を明示変更して再実行する。

GCP 課金なしで進める場合:

```yaml
# config/skills/thumbnail.yaml
image_generation:
  provider: codex
```

その後、`uv run yt-generate-image` ではなく codex wrapper を使う:

```bash
bash .claude/skills/thumbnail/references/codex-image.sh --require-reference \
  "<thumbnail prompt>" \
  <collection-path>/10-assets/thumbnail-codex-v1.png \
  <reference-image-1>
```

OpenAI API に切り替える場合:

```yaml
image_generation:
  provider: openai
  openai:
    aspect_ratio: "16:9"
    # quality 未指定時の既定は medium。high は単価が数倍高いので明示 opt-in のみ
    # quality: high
```

Gemini / OpenAI の CLI 経路で全 attempt が失敗した場合、`uv run yt-generate-image` はこの fallback 章を案内する。生成物の品質差が出るため、自動で provider を切り替えて上書きすることはしない。

## codex 経由の生成

`image_generation.provider: codex` のチャンネルでは、`uv run yt-generate-image` ではなく `codex-image.sh` を正規の生成経路として使う。`ImageProvider` API 実装は持たないため、`uv run yt-generate-image` に誤配線した場合は明示エラーでこの shell 経路へ誘導される。

前提:
- codex CLI 0.131 系以降（旧 stdout プロトコル `generated image <id> <base64>` は 0.131 で削除済み）
- `codex login status` が `Logged in using ChatGPT` を返す
- `jq` が PATH 上にある（`--json` の JSONL 解析に使う）
- wrapper は生成前に最小 `codex exec --json` プローブで codex CLI とサーバー側デフォルトモデルの互換性を確認する。非互換時は生成を試みず、CLI version・検出モデル・アップグレード手順を stderr に出して停止する
- TTP 生成のため、3 引数目以降に参照画像を 1 件以上渡す
- ChatGPT サブスクの fair-use 上限は明文化されていないため、大量生成には使わない

直接実行例:

```bash
bash .claude/skills/thumbnail/references/codex-image.sh --require-reference \
  "TTP this reference thumbnail, then improve it into a stronger original thumbnail for cozy cafe morning coffee. Keep the winning layout and make the title readable on mobile." \
  collections/planning/sample/10-assets/thumbnail-codex-v1.png \
  data/thumbnail_compare/benchmark/<channel>/<reference>.jpg
```

複数候補を作る場合でも、1 回の `codex-image.sh --require-reference` 呼び出しには候補に対応する参照画像 1 枚だけを渡す。TTP 生成では参照画像 0 件で停止する。DistroKid cover などの汎用 codex 生成は `--require-reference` を付けない。

TTP 参照画像から上位互換サムネを作る場合は、長い個別指定ではなく
`image_generation.codex.default_prompt_template` を使う。参照画像は mood reference
ではなく winning template として扱い、変える要素は `{title}` と品質改善
（mobile readability / face impact / no logos / no watermarks / no broken hands）に限定する。
日本語方針は「TTPを徹底してテキスト付き thumbnail を先に確定する」。

codex 経路でも標準ファイル契約は同じ:

1. ベンチマーク参照画像から、テキスト付き候補を `10-assets/thumbnail-codex-v1.png` に生成する。
2. 承認後、PNG 候補を JPEG に変換して `10-assets/thumbnail.jpg` として確定する（例: `sips -s format jpeg 10-assets/thumbnail-codex-v1.png --out 10-assets/thumbnail.jpg`）。`thumbnail.png` のまま確定する場合も、YouTube アップロード用の文字入りサムネであり、動画背景には使わない。
3. 確定した `thumbnail.jpg`（または `thumbnail.png`）を参照画像にして、テキストなし背景候補を `10-assets/main-v1.png` に AI 再生成する。
4. 承認後、`cp 10-assets/main-v1.png 10-assets/main.png` で textless 動画背景として確定する。

既定テンプレート:

```text
TTP this reference thumbnail, then improve it into a stronger original thumbnail.
Keep the winning layout, typography feel, character scale, color mood, texture, and energy.
Make it cleaner, more readable on mobile, stronger face impact, no logos, no watermarks, no broken hands.
Use the title {title}.
```

このテンプレートは `config.default.yaml` の `image_generation.codex.default_prompt_template` と完全一致させる（`tests/test_thumbnail_skill_assets.py` で機械担保）。

**`{title}` の意味論**: `{title}`（`codex-prompt.py` の `title` 引数）に渡すのは**サムネに焼くテキスト（見出し + 短いサブタイトル）だけ**。動画タイトル全文を渡さない — 旧テンプレート運用時に動画タイトル全文がそのまま画像に焼き込まれた事故があり、その再発防止のための契約。

内部実装の要約:

- wrapper は `codex --version` で CLI version を控え、ログイン確認後に `codex exec --json --skip-git-repo-check -- "Reply with exactly codex-model-compat-ok."` の最小プローブを実行する。互換性エラーなら本番生成を呼ばず、`npm install -g @openai/codex@latest` / `brew upgrade codex` / `bun add -g @openai/codex@latest` を案内して非0終了する
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
- 失敗時 wrapper は codex CLI version・デフォルトモデル推定値・`agent_message (最終)`・codex stderr の末尾 30 行を診断 dump するので、これを見て CLI upgrade / prompt 短縮 / 参照画像見直しに切り替える

この経路のスコープ:
- `uv run yt-generate-image` の API 呼び出しは使わない
- `ImageProvider` 実装は持たない
- wrapper 自体のリトライなし
- GCP 課金なし。ChatGPT サブスクの fair-use 対象で、`cost_per_image_usd` は通常 `null`
- `cost_tracker` 連携なし。生成回数は shell 実行ログで確認する

## Channel Adaptation

**すべての設定は `config/skills/thumbnail.yaml` から読み取る。**
スキル内にチャンネル固有のハードコードはしない。作業前に Read tool（Codex では同等のファイル閲覧）で
`.claude/skills/thumbnail/config.default.yaml` とチャンネル側上書きの `config/skills/thumbnail.yaml`
を開き、deep-merge 後の実効値を確認する。

実行前に以下を確認:

1. `image_generation.provider` → 使用するプロバイダー（`gemini` / `openai` / `codex`）
2. `image_generation.gemini.model` → 使用する Gemini モデル
3. `image_generation.gemini.style` → スタイル説明（参照画像ベース）
4. `image_generation.gemini.prompt_prefix` → プロンプト冒頭の固定文（キャラ描写等）
5. `image_generation.gemini.reference_images.default` → 同じベンチマークチャンネル内の参照画像リスト（single_step では必須）
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
| `two_phase` | 従来方式フォールバック。既存参照を選択 → テキスト付き `thumbnail.jpg` 確定 → 承認済み `thumbnail.jpg` から textless `main.png/jpg` 再生成 |

### 参照画像モード（必須）

参照画像を渡して TTP の勝ちパターンを踏襲する方式。`single_step` では参照画像なしの生成は行わない。

```bash
uv run yt-generate-image \
  --ttp-strict-references \
  --prompt "<prompt_prefix を含むプロンプト>" \
  --reference <channel_dir>/<reference_images.default> \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y
```

**参照画像の選択ロジック**:
- `reference_images.default` には同じベンチマークチャンネル内の別サムネイル画像を並べる
- `--max-attempts N` のときは N 枚以上のユニーク参照画像が必要。不足・重複・同一参照の再利用はエラー
- `--reference-index N` を指定した場合のみ単一参照固定になり、attempt 数は 1 に固定される
- `path_base: "channel_dir"` の場合、パスはプロジェクトルートからの相対パス
- `--reference` 使用時は `composition_prefix` が自動スキップされる（generate_image.py 修正済み）

## プロンプト構築

プロンプト構築の原則（prompt_prefix / fixed_character / composition_rules の組み立て）は `references/prompting.md`、TTP の短い差分プロンプト例は `references/sample-prompts.md` を参照する。

> 将来検討（issue #654）: imagegen の 14 項目 Shared prompt schema 形式と既存 skill-config の bridge ヘルパが `references/prompt-schema.md` および `youtube_automation.utils.image_provider.prompt_schema` に試験導入されている。実本番フローからは未接続。設計判断は `docs/skill-design/ADR-001-thumbnail-prompt-schema.md`。

## ワークフロー

### 標準生成順序とファイル契約

`/thumbnail` の標準手順は、**テキストなし動画背景 → テキスト付き YouTube サムネ**の順に進める。

1. ベンチマーク先サムネを参照画像にして、構図・色温度・主役スケール・背景テクスチャだけを踏襲したテキストなし動画背景候補を生成する。
2. 背景候補を `open` と `uv run yt-thumbnail-check` で確認し、ユーザー承認後に `10-assets/main.png` または `10-assets/main.jpg` として確定する。
3. 承認済み `main.png/jpg` を参照画像にして、YouTube 用のテキスト付きサムネ候補を生成する。
4. `/thumbnail-compare` で 320px 視認性検証後にユーザー承認し、テキスト付き最終サムネを `10-assets/thumbnail.jpg` として確定する。
5. `config/skills/loop-video.yaml::enabled: true` のチャンネルでは、テキストなし `main.png/jpg` を `/loop-video` に渡して `loop.mp4` を生成する。
6. `config/skills/loop-video.yaml::enabled: false` のチャンネルでは Veo を実行せず、テキストなし `main.png/jpg` を静止画背景として `/videoup` に渡す。

`thumbnail.jpg` はアップロード用の文字入りサムネイル、`main.png/jpg` は動画背景・loop-video 入力用の文字なし素材として扱う。両者を同一画像で代用しない。

### Single-Step / TTP モード（`generation_mode: "single_step"`、デフォルト・推奨）

ベンチマーク模倣（**TTP**: trace / imitate）の標準実装。テキスト付きベンチマーク参照画像（背景テクスチャ・オブジェクト配置・主役スケールを含む）を参照にして、**背景として維持する要素と除去する文字要素だけ**をプロンプトで指示する。1 回目の生成では、YouTube 用の文字をまだ載せず、動画にも使う textless 背景候補を作る。TTP 参照のテキストレイアウトは、後段の文字入りサムネ生成時に視認性・情報量の参考として扱う。

**重要**: 参照画像と同じ要素（レイアウト、固定オブジェクト、テキスト配置）はプロンプトに含めない。差分のみを指示することで、参照画像のクオリティを維持しつつ変更が正しく反映される。コピーではなくバリエーションを作るのがゴール。

**IP / 版権セーフティ (#569)**: TTP は参照画像のレイアウト・テクスチャ・オブジェクト配置を強く転写するため、ベンチマーク側に焼き込まれた**署名（サイン）・透かし・ロゴ・チャンネルバッジ・著作権表記等の識別マークがそのまま再現される事故が起きやすい**。プロンプト構築時は必ず標準除外 clause `no signature, no autograph, no watermark, no logo, no brand mark, clean corners` を含めること（config: `image_generation.gemini.single_step.ip_safety_clause`）。**参照元の識別マークはコピーしない — 版権 / IP リスクを生むため**、たとえ参照画像のスタイルガイドとして優秀でもサインや筆記体の署名は転写対象から外す。

#### プリフライト

`generation_mode: "single_step"` で `--reference` を指定せずに `uv run yt-generate-image` を起動するとエラー中断する。次の対処が必要:

1. **skill-config に `reference_images.default` が未設定** → `config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.default` にベンチマークサムネのパス（文字列 1 件 or list 複数件）を設定
2. **設定はあるが CLI 引数に展開していない** → `--reference <path>` で渡す。list なら `--reference A --reference B --reference C` のように複数指定
3. **`--max-attempts N` に参照画像が足りない** → 同じベンチマークチャンネル内の別サムネイル画像を N 枚以上に増やす。ローテーションで同じ参照へ戻す運用はしない

#### 参照画像（複数 + ローテーション）

`reference_images.default` は同じベンチマークチャンネル内の複数サムネ候補を list で指定する。`--max-attempts N` で N 候補を出す場合、各 attempt は別参照画像 1 枚を使う。参照画像が N 枚未満、同じ画像の重複、`--no-rotate` による先頭固定はいずれもエラーになる。

別チャンネル由来の参照画像や stock 画像を混ぜる場合は、TTP 参照プールとは別スコープとして扱う。混在させるなら `config/skills/thumbnail.yaml` 側で明示し、生成ログの `benchmark_channel=` と `thumbnail-prompts.md` の attempt 別参照欄で追跡できるようにする。

| CLI 引数 | 用途 |
|---|---|
| `--max-attempts N` | 試行回数。各 attempt で別参照を 1 枚ずつ割当、出力は `-vN` で別保存 |
| `--no-rotate` | single_step の複数候補では使用不可（同一参照再利用になるためエラー） |
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

`reference_images.default` から `--reference` 引数を組み立てる。default では同じベンチマークチャンネル内の別サムネイル画像のみを使う。
`config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.default` を Read tool で確認し、
各パス（`CHANNEL_DIR` 相対）を絶対パスに解決して `--reference` を列挙する:

```bash
uv run yt-generate-image \
  --reference <CHANNEL_DIR>/<default[0]> \
  --reference <CHANNEL_DIR>/<default[1]> \
  --ttp-strict-references \
  --max-attempts 3 \
  --prompt "<diff_prompt_template を置換したプロンプト>" \
  --output <collection-path>/10-assets/main-v1.png -y
```

stock 画像を別スコープとして混ぜたい場合だけ、`config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.stock.enabled: true` を明示し、採用ログ stderr の `[INFO] stock 採用: ...` を保存する。stock を混ぜると「同じベンチマークチャンネルの別サムネ」ではなくなるため、生成後の `thumbnail-prompts.md` に attempt ごとの参照元を必ず記録する。

4. `open` でプレビュー → `uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json` → ユーザー承認 → `cp main-v1.png main.png`（JPEG で確定する運用では `main-v1.jpg` → `main.jpg` に揃える。拡張子を偽装しない）
5. 承認済み `main.png/jpg` を参照画像にして、テキスト付き YouTube サムネを AI 生成:

```bash
COLLECTION_PATH="<collection-path>"
THUMBNAIL_PROMPT="$(cat <<'PROMPT'
<text-included thumbnail prompt>
PROMPT
)"

uv run yt-generate-image \
  --reference "${COLLECTION_PATH}/10-assets/main.png" \
  --prompt "$THUMBNAIL_PROMPT" \
  --output "${COLLECTION_PATH}/10-assets/thumbnail-v1.jpg" -y
```

テキスト付き生成プロンプトでは、承認済み背景の構図・主役スケール・光・色温度・背景テクスチャを維持し、`thumbnail_text` のタイトル・チャンネル名だけを追加する。背景を描き直さないこと、文字以外の新しい主役やロゴを追加しないことを明示する。

6. `open` でプレビュー → `/thumbnail-compare` で 320px 視認性検証 → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`
7. `20-documentation/thumbnail-prompts.md` に、テキストなし背景生成プロンプトとテキスト付き生成プロンプトの両方を保存する

#### 運用上の注意

- **リトライ前提**: 画像生成プロバイダーは同一プロンプトでも瞬発的にエラーを返す。各 attempt 内で内蔵リトライ最大 2 回が走る
- **テキスト除去**: 初回の textless 背景生成では、参照サムネ内のキャッチコピー・ジャンルタグ・フォントが焼き込まれやすい。`text_strip_clause` / `Remove all text` を明示し、文字情報は第2段のテキスト付きサムネ生成だけで扱う
- **テキストなし版の先行確定**: `main.png/jpg` は文字入り生成より先に承認する動画背景素材。文字入り `thumbnail.jpg` をそのまま動画背景や `/loop-video` 入力にしない
- **コスト**: 事前見積もりは `config/skills/thumbnail.yaml` の `image_generation.<provider>.cost_per_image_usd` を指定したときのみ CLI 表示に出る。未指定なら「不明」と表示され、実コストは GCP Cloud Console > Billing で確認する（`max_attempts × 1 リクエスト` ＋ 各 attempt で内蔵リトライ最大 2 回）

#### 失敗時の対処

雰囲気が出ない場合、ChatGPT 等の外部ツールで手動生成して `main.png` にコピーする運用は廃止。ツール内で完結する代替策:

1. `--reference-index N` で特定のベンチマーク参照に固定して試す
2. `reference_images.default` の list を見直し、別のベンチマーク候補を追加
3. `diff_prompt_template` の差分指示を見直し（特に `variation_clause` / `style_lock_clause` のオン/オフ）

差分プロンプトの具体例は skill-config の `image_generation.gemini.diff_prompt_template` を参照し、チャンネル固有のオブジェクト・カラーを埋める。

> **参考（オペレーター向け・実行時は無視してよい）**: `daiki-beppu/rjn` の `config/skills/thumbnail.yaml` が参考になる（jazzgak チャンネルの 5 サムネを `color_themes.<theme>.reference_image` で多軸切替）。private リポジトリのため下流リポジトリの実行者はアクセスできない。取得を試みないこと。

#### TTP プリフライト・チェックリスト

コレクション着手時は、本章上部のプロンプト構築や生成コマンドへ進む**前**に必ずここを通す。1 項目でも欠けると TTP モードの再現性が落ちる。

- [ ] `reference_images.default` が設定済みで、同じベンチマークチャンネル内の別サムネイル画像を `--max-attempts` 以上の枚数だけ指している（`config/skills/thumbnail.yaml` の `image_generation.gemini.reference_images.default` を Read tool で確認する）
- [ ] `image_generation.gemini.generation_mode` が `generation_mode: "single_step"` になっている。`two_phase` / `diff_from_reference` を使うなら理由を明示する
- [ ] 同じ参照画像の重複、参照不足、`--no-rotate` による複数候補生成になっていない
- [ ] `diff_prompt_template` に参照と重複する要素（レイアウト・固定オブジェクト・テキスト配置・既知の色味）を書いていない。差分のみを記述する
- [ ] `diff_prompt_template` に `${ip_safety_clause}` 相当の除外句（`no signature, no autograph, no watermark, no logo, no brand mark, clean corners`）を含めている (#569)。参照元ベンチマークサムネに署名・サイン・透かし・チャンネルロゴ等の識別マークがある場合は特に必須
- [ ] stock 合成（#364）の扱いを確認し、`image_generation.gemini.reference_images.stock.enabled` が意図どおりになっている
- [ ] ベンチマーク参照から textless `main-v1.png/jpg` を先に生成し、構図・色温度・背景テクスチャをユーザー承認する段取りになっている
- [ ] 承認済み `main.png/jpg` を参照してテキスト付き `thumbnail-v1.jpg/png` を生成する段取りになっている
- [ ] サムネ承認**前**に `/thumbnail-compare` を実行し、320px 縮小時の文字可読性・コントラスト・主役認識を検証する段取りになっている
- [ ] `20-documentation/thumbnail-prompts.md` にテキストなし背景生成プロンプトとテキスト付き生成プロンプトの両方を保存する段取りになっている

チェック通過後に本章上部の手順へ戻って `/thumbnail` を進める。CLI エラーで止まったときは、このチェックリストではなく本章上部の `#### プリフライト` を参照する。

### Two-Phase モード（従来方式・フォールバック）

Two-Phase は旧チャンネル向けのフォールバック。使う場合も、textless 背景を先に承認し、最終契約は `thumbnail.jpg`（テキスト付き YouTube サムネ）と `main.png/jpg`（テキストなし動画背景）を別成果物として確定する。

#### Phase 1: 既存参照の選択（新規生成しない）

既存 `main.png/jpg`、`planning-preview.png`、または `reference_images` は、Phase 2 のテキスト付き候補生成の参照素材としてだけ使う。ここでは `yt-generate-image` を実行せず、textless 動画背景として承認・確定もしない。最終 `main.png/jpg` は Phase 3 で承認済み `thumbnail.jpg` から AI 再生成する。

参照素材を選ぶ場合:
1. テーマに合う既存 `main.png/jpg`、`planning-preview.png`、または `reference_images` から 1 枚以上を選択する
2. `open` でプレビューし、Phase 2 のテキスト付き候補生成の参照に使えるかだけ確認する
3. 参照素材を `main.png/jpg` へコピーしない。`main.png/jpg` は Phase 3 でだけ確定する

#### Phase 2: テキストオーバーレイ（thumbnail.jpg）

1. `image_generation.gemini.thumbnail_text` からテキスト設定を取得
2. テキストオーバーレイプロンプトを構築:

**`thumbnail_text.text_overlay_prompt` が定義されている場合（推奨）:**
テンプレート内の `{title_line1}`, `{title_line2}`, `{channel_name}` をコレクションのタイトルとチャンネル名で置換して使用。

**未定義の場合（フォールバック）:** `references/sample-prompts.md` の「Two-Phase モードのテキストオーバーレイ・フォールバックプロンプト」を使用する。

3. 生成: `uv run yt-generate-image --reference <既存参照画像> --prompt <テキスト指示> --output 10-assets/thumbnail-v1.jpg -y`
4. `open` でプレビュー → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`

#### Phase 3: 承認済み thumbnail から textless main を再生成

1. 承認済み `thumbnail.jpg` を参照して textless `main-v1.png` を AI 再生成する。
2. `open` でプレビュー → ユーザー承認 → `cp main-v1.png main.png` で動画背景を確定する（JPEG で確定する運用では `main-v1.jpg` → `main.jpg` に揃える）。

## フォント安定化（#1332）

「サムネの文字フォントが毎回バラバラになる」問題への対処。フォントの扱いは 2 経路あり、要求水準で使い分ける。

| 経路 | 仕組み | フォント再現性 |
|---|---|---|
| **AI プロンプト経路**（既定） | 第2段のテキスト付きサムネ生成プロンプトで書体の雰囲気を指示（`thumbnail_text.font` / `single_step.typography_clause`） | **保証されない**。AI 画像生成はフォント名を厳密に再現できず、同じ指示でも生成ごとに書体が揺れる |
| **決定的合成経路**（`yt-thumbnail-text`） | textless 背景に実フォントファイル（.ttf/.otf/.ttc）を Pillow で描画 | **完全に安定**。同一の背景・テキスト・設定なら常に同一出力 |

### AI プロンプト経路でのフォント指示

- **single_step（TTP）**: 初回 `diff_prompt_template` は textless `main-v1.png/jpg` 背景生成専用のため、`${typography_clause}` やタイトル文字の描画指示を入れない。書体の一貫性を高めたい場合は、承認済み `main.png/jpg` から作る第2段のテキスト付き thumbnail prompt に `single_step.typography_clause` を展開し、`{font_description}` を `thumbnail_text.font.copy` の値で置換する
- **two_phase**: Phase 2 のオーバーレイプロンプトで `thumbnail_text.font.copy` / `font.genre_tag` の記述が使われる

いずれも改善であって保証ではない。「同一チャンネルで常に同じフォント」が必要なら決定的合成経路を使う。

### 決定的合成経路（yt-thumbnail-text）

`config/skills/thumbnail.yaml` にフォントファイルを設定する:

```yaml
image_generation:
  gemini:
    thumbnail_text:
      overlay:
        font:
          title: "assets/fonts/NotoSansJP-Bold.ttf"   # channel_dir 相対 or 絶対パス
```

フォントファイルは Google Fonts 等から入手し `<channel_dir>/assets/fonts/` に置く運用を推奨（フォントのライセンス条項を確認すること）。サイズ・色・縁取り・配置は `overlay.title` / `overlay.channel_name` / `overlay.layout` で調整する（デフォルト値は `config.default.yaml` 参照）。

`yt-thumbnail-text` は標準 `/thumbnail` フローから自動分岐しない。フォントの完全固定が必要なコレクションで、運用者がこの経路を明示的に選んだときだけ実行する。

生成手順（フォント固定が必要な場合の明示実行）:

この経路も標準契約に従い、最初にテキスト付き `thumbnail-v*.jpg` を生成・承認して `thumbnail.jpg` を確定する。その後、承認済み `thumbnail.jpg` から textless `main-v*.png/jpg` を AI 再生成し、必要な場合だけ実フォントでテキスト付きサムネを再合成する。

1. 標準 Single-Step または Two-Phase でテキスト付き候補を生成し、`thumbnail.jpg` を承認・確定する。
2. 承認済み `thumbnail.jpg` を参照画像にして、textless 背景候補 `main-v1.png` を AI 再生成する。
3. textless 背景候補を承認し、`cp main-v1.png main.png` で動画背景を確定する。
4. フォント固定版の再合成が必要な場合、実フォントでテキスト付き候補を合成する:

```bash
uv run yt-thumbnail-text \
  --background <collection-path>/10-assets/main.png \
  --title "<Title Line 1>" --title "<Title Line 2>" \
  --channel-name "<channel_name>" \
  --output <collection-path>/10-assets/thumbnail-v1.jpg
```

5. `open` でプレビュー → `/thumbnail-compare` で 320px 視認性検証 → 承認 → `cp thumbnail-v1.jpg thumbnail.jpg`

決定的合成はフォント安定化だけを担う。textless `main.png/jpg` を先に最終化してから `thumbnail.jpg` を作る旧順序には戻さず、承認済み `thumbnail.jpg` から textless 版を AI 再生成する工程は維持する。

### フォント指定に失敗した場合

`yt-thumbnail-text` は失敗理由と代替手順を明示して終了コード 1 で停止する:

- **`image_generation.gemini.thumbnail_text.overlay.font.title` 未設定** → `config/skills/thumbnail.yaml` に .ttf/.otf/.ttc のパスを設定する
- **フォントファイルが存在しない** → パスを確認（相対パスは channel_dir 起点）。フォントを `<channel_dir>/assets/fonts/` に配置し直す
- **ファイルが壊れている・フォントとして読めない** → 別のフォントファイルを用意する

決定的合成を使わない判断をした場合は、AI プロンプト経路（上記 `typography_clause` / two_phase の `thumbnail_text.font`）へフォールバックする。その場合フォントの厳密な再現は保証されないことをユーザーに伝えること。

## 自動選択（auto-selection・opt-in）

TTP 参照画像が固定されているチャンネルでは、候補生成後のユーザー承認を省略し、`uv run yt-thumbnail-auto-select` で `10-assets/thumbnail.jpg` を自動確定できる（#1370）。`auto_selection.enabled` が false / 未設定のチャンネルでは何も変わらず、従来の手動承認フローを使う。

有効化（チャンネル側 `config/skills/thumbnail.yaml`）:

```yaml
image_generation:
  auto_selection:
    enabled: true          # opt-in。false / 未設定なら従来の手動承認フロー
    min_width: 1280        # 候補の最小解像度
    min_height: 720
    aspect_tolerance: 0.01 # 16:9 判定の許容誤差
```

実行手順（`auto_selection.enabled: true` のチャンネルのみ。無効チャンネルで実行すると終了コード 2 の明示エラー）:

1. 候補生成後、dry-run で採点とランキングを確認する:

```bash
uv run yt-thumbnail-auto-select <collection-path> --dry-run
```

2. 問題なければ apply で確定する（`--json` で選択理由を構造化出力できる）:

```bash
uv run yt-thumbnail-auto-select <collection-path> --apply
```

選択ロジック（deterministic・学習なし）:

- `image_generation.gemini.reference_images.default` の各参照画像から特徴量（brightness / contrast / saturation / dominant_hue / colorfulness）を抽出して centroid を作る
- `10-assets/` の候補（`thumbnail-v*.jpg` / `thumbnail-v*.png` / `thumbnail-codex-v*.png`）を採点し、16:9・最小解像度を満たす候補のうち centroid に最も近いもの（distance 最小）を選ぶ
- apply 時は選択候補を `thumbnail.jpg` にコピー（PNG 候補は JPEG 変換）し、`workflow-state.json` があれば `thumbnail_auto_selection` キーに選択候補・distance・ランキング・実行時刻を記録する

失敗時は silent fallback しない（終了コード 1 / 2 の明示エラー）:

- 候補なし / 参照画像なし / 適格候補なし（全候補が 16:9 逸脱・解像度不足）
- 確定済み `thumbnail.jpg` / `thumbnail.png` が既に存在（上書きは `--force` の明示が必要）
- `auto_selection.enabled` が false のまま実行

自動確定後も `/thumbnail-compare` の 320px 視認性検証と下記の品質チェックリストは通すこと。textless `main.png` 再生成以降の後工程は従来どおり。

## 品質チェック

textless 背景候補の自動セルフチェック（#489）:

```bash
uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json
```

`uv run yt-thumbnail-check` は `main-v1.png` / `main-v1.jpg` のような **テキストなし背景候補**を対象にする。Gemini Vision で `collection-ideate.yaml` の `objects.fixed` と
`self_check.no_logo_guard` から YES/NO チェックリストを組み立て、画像に対する合否を
JSON で返す（終了コード 0=合格 / 1=不合格）。手作業チェックの前段スクリーニングとして、
TTP 構図逸脱（wet_runway 不在・矩形ロゴ混入・テキスト burned-in 等）を機械的に検出する。

textless main 候補生成後（`main-v1.png` / `main-v1.jpg`）:
- [ ] ベンチマーク参照の構図・主役スケール・光・色温度・背景テクスチャが textless 背景として維持されているか
- [ ] タイトル文字、字幕、ロゴ、透かし、タイポグラフィ、チャンネル名が残っていないか
- [ ] 新しい文字や記号が追加されていないか
- [ ] `uv run yt-thumbnail-check <collection-path>/10-assets/main-v1.png --json` を通したか（JPEG 候補なら `main-v1.jpg` を指定）
- [ ] `/loop-video` 入力や `/videoup` 静止背景として使える textless 背景になっているか

テキスト付き thumbnail 候補生成後（`thumbnail-v1.jpg` / `thumbnail-codex-v1.png`）:
- [ ] 承認済み `main.png/jpg` の構図・主役スケール・光・色温度・背景テクスチャが維持されているか
- [ ] `/thumbnail-compare` で 320px 縮小時のタイトル可読性・コントラスト・主役認識を確認したか
- [ ] タイトルテキストが `composition_rules.text_lines` の制約内か
- [ ] `thumbnail_text.channel_name` が表示されているか
- [ ] 参照元の署名・サイン・透かし・ロゴ・ブランドマークが焼き込まれていないか
- [ ] `image_generation.gemini.style` に記載されたスタイルが維持されているか
- [ ] `composition_rules.environment` の制約を満たしているか
- [ ] `fixed_character` の外見が維持されているか（ある場合）
- [ ] キャラの顔が見えているか（`fixed_character.face` の指示通り）
- [ ] キャラサイズが `composition_rules.character_size` を満たしているか
- [ ] **解剖学チェック（手・指）**: キャラが写っている場合、手・指が解剖学的に正しいか（各手 5 本指・指の分離が明瞭・指の融合や本数異常・溶融が無い・プロポーションが破綻していない）。**特に楽器持ちキャラ・指を伸ばす/握るポーズでは Gemini が破綻しやすい**ため必ず Read ツールで等倍プレビューを開いて目視確認する。NG なら `anatomy_clause` を強調 / 再生成 / プロバイダー切り替え（codex は人体破綻に強い傾向）で対応する（#570）

> **Note (#570)**: キャラ + 手が写る構図では、`image_generation.gemini.single_step.anatomy_clause` をプロンプト末尾に `${anatomy_clause}` として展開しておくと、Gemini の手・指破綻（指の融合・本数異常・溶融）の発生率を下げられる。`/collection-ideate` の single_step プレビューは企画参照素材であり最終 thumbnail には流用しないが、参照素材として採用する前にも最低限の QA（手・指 / 署名 / ロゴ）を通すこと。

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

## Reference Assignments

| attempt | output | reference_image | benchmark_channel |
|---:|---|---|---|
| 1 | `10-assets/main-v1.png` | `<参照画像 1>` | `<benchmark_channel>` |
| 2 | `10-assets/main-v2.png` | `<参照画像 2>` | `<benchmark_channel>` |
| 3 | `10-assets/main-v3.png` | `<参照画像 3>` | `<benchmark_channel>` |

## Textless Background Prompt (main.png/main.jpg)

\```
<ベンチマーク参照画像からテキストなし背景を生成したプロンプト>
\```

## Text-Included Thumbnail Prompt (thumbnail.jpg)

\```
<承認済み main.png/jpg からテキスト付きサムネを生成したプロンプト>
\```
```

## ファイル命名ルール（上書き禁止）

| ファイル | 用途 |
|---------|------|
| `thumbnail.jpg` | YouTube アップロード用のテキスト付き最終サムネ |
| `thumbnail-v{N}.jpg` / `thumbnail-v{N}.png` / `thumbnail-codex-v{N}.png` | テキスト付き候補 |
| `main.png` / `main.jpg` | 動画背景・`/loop-video` 入力用のテキストなし最終画像 |
| `main-v{N}.png` / `main-v{N}.jpg` | テキストなし背景候補 |
| `loop.mp4` | `loop-video` 有効チャンネルだけで生成する動画背景。無効チャンネルでは作らない |

### クリーンアップ（承認後に必ず実行・stock 退避）

不採用候補は `<channel_dir>/assets/stock/<theme>/` に隣接メタデータ付きで退避する（#364）。

```bash
THEME="<theme-slug>"   # 例: tavern / library / jazz-bar
uv run yt-stock-archive \
  10-assets/main-v*.png 10-assets/main-v*.jpg \
  10-assets/thumbnail-v*.jpg 10-assets/thumbnail-v*.png 10-assets/thumbnail-codex-v*.png \
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

`yt-thumbnail-auto-select --apply` で確定した場合は、選択候補・distance・ランキング・実行時刻が `thumbnail_auto_selection` キーに監査ログとして自動記録される（#1370）。

## stock 退避と再利用

不採用画像は `<channel_dir>/assets/stock/<theme-slug>/` に画像本体 + 隣接 `<image>.meta.json` で退避される（schema_version=1）。メタには prompt / provider / model / generation_mode / source_collection / reference_images / generated_at / rejected_at を保存し、将来別コレクションの参照画像として再利用できる。

stock の操作 CLI:

| CLI | 用途 |
|---|---|
| `uv run yt-stock-list [--theme T] [--source-role R] [--limit N] [--format table\|json]` | stock 一覧（新しい順） |
| `uv run yt-stock-preview [--theme T] [--limit N]` | macOS `open` でプレビュー起動 |
| `uv run yt-stock-prune [--retention-days N] [--max-per-theme N] [--dry-run]` | 古い画像 / 上限超過分を削除（config 既定値あり） |

`config/skills/thumbnail.yaml` の `image_generation.stock`:

```yaml
image_generation:
  stock:
    enabled: true          # false で退避を無効化（unlink のみ）
    retention_days: 90     # uv run yt-stock-prune の保持日数
    max_per_theme: 50      # uv run yt-stock-prune の上限
```

### stock 再利用（参照画像プールへの自動合成）

PR-B (#364): stock 画像は `reference_images.default` とは別スコープの参照プールとして扱う。TTP single_step の標準フローでは同じベンチマークチャンネル内の別サムネだけを使い、`--ttp-strict-references` では stock 混在を拒否するため、stock 合成は default OFF。必要なチャンネルだけ `enabled: true` を明示し、TTP strict ではない汎用参照生成に限って `resolve_stock_refs()` の結果を `--reference` に追加する。

- **デフォルト動作**: `enabled: false` で stock は混ぜない。
- **有効化**: `config/skills/thumbnail.yaml` で `image_generation.gemini.reference_images.stock.enabled: true` を明示する。TTP strict 候補生成では使わない。
- **採用ログ**: 1 枚採用ごとに stderr へ `[INFO] stock 採用: <path> (theme=<t>, role=thumbnail_candidate)` を出力。監査時は stderr を grep。
- **チューニング**: `max_count` / `shuffle` / `theme_match: "any"` / `source_role: null` (role フィルタなし) などをチャンネル側で調整。

```yaml
image_generation:
  gemini:
    reference_images:
      stock:
        enabled: false
        max_count: 3
        theme_match: "exact"     # "any" で全テーマ横断
        source_role: "thumbnail_candidate"
        shuffle: true
        seed: null
        fallback_when_empty: true
```

## 長時間処理の取り扱い

`uv run yt-generate-image` は Gemini / OpenAI への API 同期呼び出しで **10〜30 秒** ブロックする。`--max-attempts N` でローテーション生成する場合は `N × 10〜30 秒` かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例:

```bash
uv run yt-generate-image \
  --ttp-strict-references \
  --reference <ref> --prompt "<prompt>" \
  --output <collection-path>/10-assets/main-v1.png -y \
  > /tmp/thumbnail-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ サムネイル画像を生成中（推定 N × 10〜30 秒）。完了まで他の質問にもお答えできます。
> ログ: /tmp/thumbnail-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "thumbnail" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "thumbnail"` + `cmux notify --title "thumbnail 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（生成された `main-vN.png` のパス、attempt 回数、内部リトライ有無）をユーザーへ返す。プロバイダーが瞬発エラーを返した場合はそのエラー行を抜き出して報告する。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| GCP ADC 未取得/失効 | `ConfigError` / ADC 認証エラー | `gcloud auth application-default login`（必要なら `set-quota-project`）を再実行 |
| Vertex AI rate | HTTP 429 | 時間を置いて再実行。並列実行を避け順次処理する |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud（Vertex AI）のステータスを確認し、時間を置いて再実行 |
| 画像 provider 障害 | 片方の provider のエラー | `image_generation.provider` を `gemini` ↔ `openai` で切り替える |

## Next Step

サムネイル確定後:
→ Suno チャンネル: `/suno <theme>` で音楽プロンプト生成
→ Lyria チャンネル: `/lyria <theme>` でマスター音源生成（`/suno` 系工程は不要）
