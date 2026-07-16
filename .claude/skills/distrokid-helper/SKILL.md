---
name: distrokid-helper
description: "Use when コレクションの楽曲を DistroKid 配信用に準備し、distrokid-helper Chrome 拡張へ渡すローカルサーバーを起動したいとき（30-distrokid 生成 / disc 分割 / metadata.md / ジャケット 3000×3000 新規生成 / uv run yt-collection-serve 起動）。『DistroKid 準備』『配信準備』『アルバム化』『distrokid-helper』で発動。DistroKid Web への転記・アップロード操作そのものは Chrome 拡張側の責務"
---

## Overview

コレクションの楽曲（`02-Individual-music/*.mp3`）を DistroKid 配信向けに整備し、`30-distrokid/` 以下に成果物一式を生成します。

- **spec.json** — 分割計画・メタデータの機械可読 JSON。**`uv run yt-collection-serve` が直接読む SSOT**（#941）。`build` が canonical パス `30-distrokid/spec.json` へ atomic write する。LLM がタイトルユニーク化・アルバム名決定を担当
- **disc 分割 + mp3 コピー** — 1 アルバム 35 曲上限を考慮して均等分割し、各 disc ディレクトリへ mp3 をコピー
- **metadata.md** — DistroKid Web フォーム転記用の人間向けドキュメント（各 disc に生成）。`serve` の読み取り優先は spec.json であり、metadata.md は拡張が使えないときの手動フォールバック用
- **README.md** — アップロード手順書（`30-distrokid/README.md`）
- **cover_art_3000.jpg** — 新規 AI 生成した 3000×3000 JPEG ジャケット
- **uv run yt-collection-serve 起動** — `distrokid-helper` Chrome 拡張が読む `/distrokid/collections` と `/collections/<id>/distrokid/<disc>/release.json` を localhost で配信

CLI 仕様の詳細は `references/distrokid_prepare.py`（実体: `src/youtube_automation/scripts/distrokid_prepare.py`）を参照。`distrokid.json` に含まれうる PII（songwriter の本名）の取り扱いと `.gitignore` 運用は `references/pii-gitignore.md` を参照。

## 前提

以下の 1〜3 を確認し、満たさなければ案内して停止する。4 は停止条件ではなく、未設定時に 2 択の分岐を提示する:

1. 対象コレクションの `02-Individual-music/*.mp3` が 1 件以上存在すること。無ければ前工程（`/suno-helper` → `/masterup`、または `/lyria`）を案内して停止する
2. `config/channel/distrokid.json` の `distrokid.enabled` が `true` で、`distrokid.profile.artist` が配信アーティスト名になっていること。`false` / 未設定のチャンネルでは本スキルを使わず、設定方法はユーザーに確認する
3. ジャケット生成に使用する `config/skills/thumbnail.yaml` が存在すること（`provider` / `brand_background` / `style_lock_clause` を参照する）。無ければ `/thumbnail` の設定整備を案内する
4. `config/channel/distrokid.json` の `distrokid.profile.songwriter`（作曲者の本名。`{ "first": "...", "last": "..." }` の nested 構造、`middle` は任意）が設定されているか確認する。schema 上は任意のため未設定でも停止しないが、未設定のまま進めると Chrome 拡張のフォーム一括入力で songwriter（本名）欄だけが空になり、DistroKid Web で曲ごとの手入力が必要になる。未設定の場合は **plan / build（ステップ 1 / 4）に進む前に** AskUserQuestion で以下の 2 択を提示し、選択に従う:
   - **設定して進める** — `config/channel/distrokid.json` に `profile.songwriter` を追記してから続行する。songwriter は PII（本名）のため、**追記する前に必ず `references/pii-gitignore.md` を Read し**、記入例とあわせてリポジトリの公開範囲・`.gitignore` 運用を確認する
   - **手入力を了承して進める** — 未設定のまま続行し、DistroKid Web フォームで songwriter 欄を曲ごとに手入力することを了承する

DistroKid Web への転記・アップロードは Chrome 拡張（`/ext-install` で導入する distrokid-helper）の責務であり、本スキルの前提には含まない。

## When to Use

- Suno / Lyria で生成した楽曲を Spotify / Apple Music 等へ配信したいとき
- YouTube の BGM コレクションをアルバムとしてリリースしたいとき
- 既存の `02-Individual-music/*.mp3` が 1 枚に収まらず disc 分割が必要なとき

## Quick Reference

| サブコマンド | 説明 |
|---|---|
| `uv run yt-distrokid-prepare plan <collection> [--discs N] [--max-per-disc 35] [--output PATH]` | MP3 を列挙して均等分割し draft spec.json を出力。重複素タイトルには `needs_unique: true` が付く |
| `uv run yt-distrokid-prepare build --spec <spec.json> <collection> [--force] [--release-date YYYY-MM-DD]` | spec 検証 → mp3 分割コピー → ffprobe 尺計測 → metadata.md + README.md 生成 |
| `uv run yt-distrokid-prepare cover --input <image> <collection> [--force] [--crop]` | 新規 AI 生成した 1:1 画像を 3000×3000 JPEG（`30-distrokid/cover_art_3000.jpg`）に最終化 |
| `uv run yt-distrokid-prepare verify <collection>` | cover サイズ / タイトルユニーク / ≤35 曲 を最終検証（release_date 未設定は warning） |
| `uv run yt-collection-serve <collections-root> --distrokid-capture-root <channel-root> --allow-extension distrokid-helper --port 7874` | distrokid-helper 拡張向けに DistroKid dir mode サーバーを起動し、配信済み記録の POST も有効化 |

## Instructions

### 前提チェック

作業開始前に、冒頭「## 前提」の 1〜3（停止条件）を満たしていることを確認する。満たさない場合はステップ 1 に進まない。あわせて 4 の `profile.songwriter` を確認し、未設定ならステップ 1 に進む前に「設定するか、フォームで手入力することを了承するか」の 2 択（詳細は「## 前提」の 4）を提示して選択を得る。

---

### ステップ 1: plan 実行 → spec.json 確認

```bash
uv run yt-distrokid-prepare plan <collection>
# disc 数を明示したい場合:
uv run yt-distrokid-prepare plan <collection> --discs 2
# 上限を変えたい場合:
uv run yt-distrokid-prepare plan <collection> --max-per-disc 30
```

出力された `<collection>/30-distrokid/spec.json` を Read で開き、全 disc・全トラックを把握する。

---

### ステップ 2: タイトルユニーク化（LLM の担当）

spec.json の `"needs_unique": true` が付いたトラックに **em-dash サフィックス**でバリエーションを付与する。

**ルール:**
- 同一素タイトル群の **1 件目は無印のまま**でよい
- 2 件目以降に `— Reprise` / `— Dusk` / `— Late Set` / `— Late Night` 等を付与する
- コレクション横断（disc1 + disc2 + ...）でタイトルが一意になること（`build` が機械検証する）
- ユニーク化後は `needs_unique` フィールドを spec から除去、または `false` に書き換えてよい

**実例（soulful-grooves Coding Focus Collection より抜粋。無印の 1 件目は一部省略）:**

| 素タイトル（重複 4 件） | ユニーク化後 |
|---|---|
| Easy Release（1件目） | Easy Release |
| Easy Release（2件目） | Easy Release — Reprise |
| Slip Right Through（2件目） | Slip Right Through — Reprise |
| Slip Right Through（3件目） | Slip Right Through — Dusk |
| Dust In The Light（4件目） | Dust In The Light — Late Set |

単一 disc / 複数 disc の完全な spec 例は `references/spec-example.json` を参照。

---

### ステップ 3: アルバム名・slug 決定（LLM の担当）

コレクションのテーマ・雰囲気から `album_title` と `slug` の案を考え、**AskUserQuestion でユーザーに確認**してから spec.json を更新する。

推奨形式:
- **単一 disc（35 曲以下）**: `album_title` は `<Theme>`（例: `Dark Techno`）、`slug` は `<theme-kebab-case>`（例: `dark-techno`）。disc 接尾辞 / Vol 表記を付けない
- **複数 disc（35 曲超）**: `album_title` は `<Theme> Vol.{N}`（例: `Coding Focus Vol.1`）、`slug` は `disc{N}-<theme-kebab-case>-vol{N}`（例: `disc1-coding-focus-vol1`）

ユーザー確認後、spec.json の各 disc の `album_title` と `slug` を編集する。

---

### ステップ 4: build 実行

**リリース日が決まっている場合は最初から `--release-date` を付けて 1 回で完結させる**（後から日付だけ更新するために `build --force` を再実行するよりも効率的）:

```bash
# リリース日が決まっている場合（推奨）
uv run yt-distrokid-prepare build \
  --spec <collection>/30-distrokid/spec.json \
  --release-date 2026-06-20 \
  <collection>

# リリース日未定の場合（後でリリース日確認 → verify 前に build --force）
uv run yt-distrokid-prepare build \
  --spec <collection>/30-distrokid/spec.json \
  <collection>
```

`--force` は spec 記載の disc dir のみを再生成する（`cover_art_3000.jpg` は不可触）。**`spec.json` は `--force` の有無に関わらず build が毎回書き直す**（canonical パスへの atomic write）。既存 disc dir がある場合は `--force` なしでは停止する。

---

### ステップ 5: ジャケット新規生成（LLM の担当）

**既存の textless 動画背景 / 参考ビジュアル（`10-assets/main.png`）の流用禁止。**
DistroKid の配信ジャケットは 1:1 正方形、テキスト・ロゴなしの新規 AI 生成画像でなければならない。

#### プロンプト組み立て

`config/skills/thumbnail.yaml` から以下を読み取る:
- `image_generation.gemini.brand_background` — チャンネル統一の背景テクスチャ・色味
- `image_generation.gemini.single_step.style_lock_clause` — スタイル固定 clause

プロンプトに **必ず以下を含める**（テキスト完全排除宣言）:
```
square album cover, NO text, NO typography, NO logo, NO letters, NO watermark, NO signature
```

コレクションのテーマ・ムードに合わせてビジュアル要素を加える（例: coding focus → 静寂・集中・柔らかい光）。

#### provider 分岐

`config/skills/thumbnail.yaml` の `image_generation.provider` を確認:

**provider が `gemini` または `openai` の場合:**

```bash
uv run yt-generate-image \
  --prompt "square album cover, NO text, NO typography, NO logo, NO letters, <brand_background>, <theme description>, painterly style, 1:1 aspect ratio" \
  --output <collection>/30-distrokid/cover-src.png \
  --aspect-ratio 1:1 \
  --size 2K \
  -y
```

**provider が `codex` の場合:**

```bash
bash .claude/skills/thumbnail/references/codex-image.sh \
  "square album cover art for an instrumental <theme> album, strictly square 1:1 composition, <brand_background>, <style_lock_clause のエッセンス>, NO text, NO letters, NO watermark, NO logo, NO signature, clean painterly illustration" \
  <collection>/30-distrokid/cover-src.png
```

codex は aspect 引数を持たないため **prompt で正方形を明示する**こと。非正方形になった場合は次ステップで `--crop` を使う。

#### 生成画像の確認と承認

生成した画像をユーザーに提示（Read ツールで画像ファイルを開く）し、**承認を得てから** `cover` コマンドへ進む。

---

### ステップ 6: cover 最終化

承認後、`cover` コマンドで 3000×3000 JPEG に最終化する:

```bash
# 正方形の場合
uv run yt-distrokid-prepare cover \
  --input <collection>/30-distrokid/cover-src.png \
  <collection>

# 非正方形（codex で生成した場合など）→ 中央クロップ
uv run yt-distrokid-prepare cover \
  --input <collection>/30-distrokid/cover-src.png \
  --crop \
  <collection>

# 上書き確認
uv run yt-distrokid-prepare cover \
  --input <collection>/30-distrokid/cover-src.png \
  --force \
  <collection>
```

---

### ステップ 7: リリース日確認

DistroKid の推奨は **申請から 4 営業日以上先**。

リリース日が未定の場合、**申請日（本日）から 4 営業日後の最短日**をデフォルト案として算出して提示する。営業日は**土日を除外**して数える（祝日は考慮しない）。例: 申請日が 2026-06-19（金）なら 4 営業日後の最短日は 2026-06-25（木）。AskUserQuestion でデフォルト案を提示し、ユーザーが確定した日付で `build --release-date --force` を実行して更新する:

```bash
uv run yt-distrokid-prepare build \
  --spec <collection>/30-distrokid/spec.json \
  --release-date YYYY-MM-DD \
  --force \
  <collection>
```

**ステップ 4 の時点でリリース日が決まっていれば最初から `--release-date` を付けておくと二度手間を避けられる**（ステップ 4 の注記を参照）。

---

### ステップ 8: verify 最終チェック

```bash
uv run yt-distrokid-prepare verify <collection>
```

verify は以下を error として検証する（1 件でもあれば exit 1）:
- cover_art_3000.jpg が 3000×3000 JPEG であること
- 全 disc でタイトルがコレクション横断でユニークであること
- 各 disc が 35 曲以下であること

release_date（`workflow-state.json` の `planning.publish_target_at`）未設定は error ではなく **warning** として表示される。

verify のサマリーをユーザーに提示して完了を確認する。

---

### ステップ 9: distrokid-helper サーバー起動

verify が green になったら、DistroKid Web 操作へ進む前に `uv run yt-collection-serve` を **DistroKid dir mode** で起動する。これは本スキルの責務に含める。

```bash
# CHANNEL_DIR がチャンネルルートを指している場合
uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" --distrokid-capture-root "$CHANNEL_DIR" --allow-extension distrokid-helper --port 7874

# CHANNEL_DIR が未設定、またはチャンネル外の CWD から起動する場合
CHANNEL_DIR=/path/to/channel uv run yt-collection-serve /path/to/channel/collections/planning --distrokid-capture-root /path/to/channel --allow-extension distrokid-helper --port 7874
```

起動後、以下を確認する:

```bash
curl -s http://localhost:7874/distrokid/collections | python3 -m json.tool | head -40
```

`yt-collection-serve collections/planning --port 49152` の稼働情報は固定 registry `http://localhost:7872/.well-known/yt-collection-serve` から動的検出する。popup の selector を開くと候補更新が始まり、更新完了後に選択肢が開く。既定の `http://youtube-automation.localhost:7873` は常に表示される。候補履歴は保存しない。

確認ポイント:

1. JSON array が返ること
2. 対象 collection と `30-distrokid/<disc>` が一覧に含まれること
3. サーバー出力に `distrokid dir mode enabled` が表示されること
4. サーバー出力に `distrokid releases enabled` が表示されること
5. サーバー出力に `detected extension: distrokid-helper -> <id> (chrome-extension://<id>)` が表示されること

`--distrokid-capture-root` は distrokid-helper の配信済み記録 `POST /distrokid/releases` に必要。DistroKid dir mode では必ずチャンネルルートを指定する。`--allow-extension distrokid-helper` は Chrome の profile preferences から unpacked 拡張 ID を検出し、DistroKid page origin からの write POST を許可しない exact origin lock として使う。検出 0 件・複数 ID 競合・Preferences 読み取り不可・Preferences JSON parse failure で失敗する場合のみ、エラーに表示された候補を確認して `--allow-origin chrome-extension://<EXTENSION_ID>` を手動指定する。

ユーザーには distrokid-helper popup の **ローカル配信元** selector から動的検出された配信元を選ぶよう案内する。コレクション一覧と選択 disc の release.json が自動取得される。Chrome 拡張 **distrokid-helper** を使った DistroKid Web フォームへの転記・アップロード操作そのものは本スキルの範囲外。

---

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| ffprobe 不在 | `command not found: ffprobe` または `FileNotFoundError: ffprobe` | `nix develop` で devShell に入るか `brew install ffmpeg` を実行してから再試行 |
| codex 生成が非正方形 | `cover-src.png` が正方形でない | `cover --crop` を付けて中央クロップ処理を行う |
| disc が 35 曲超になる | build 時に ValidationError | `plan --discs N` で disc 数を増やして spec を作り直す。`--max-per-disc` を小さくする方法でも可 |
| 既存 30-distrokid がある | build 時に「disc dir already exists」エラー | `build --force` で spec 記載の disc だけ再生成される。`cover_art_3000.jpg` は `--force` でも上書きされない（cover は `cover --force` で別途上書き）。`spec.json` は build が毎回上書きする（`--force` 有無問わず） |
| `distrokid.enabled` が false | ConfigError または plan 実行時エラー | `config/channel/distrokid.json` の `distrokid.enabled` を `true` に設定してからリトライ |
| タイトル重複エラー | build 時に「duplicate title across discs」エラー | spec.json を開き `needs_unique: true` のトラックに em-dash サフィックスを付与して再度 build |
| `/distrokid/collections` が 404 | single file mode で起動している、または collections root が違う | `<collection>` ではなく `<channel>/collections/planning` を渡して `uv run yt-collection-serve` を起動し直す |
| `distrokid dir mode enabled` が出ない | `config/channel/distrokid.json` が読めない、または `enabled=false` | `CHANNEL_DIR` がチャンネルルートを指していることと `distrokid.enabled` を確認してからサーバーを再起動 |
| `distrokid releases` が disabled または POST が 404 | `--distrokid-capture-root` が未指定、またはチャンネルルート以外を指している | `--distrokid-capture-root "$CHANNEL_DIR"` または `--distrokid-capture-root /path/to/channel` を付けて再起動 |

---

## Handoff to Chrome Extension

サーバー起動と疎通確認が完了したら:

1. distrokid-helper popup の **ローカル配信元** selector を開き、候補更新後に表示された対象を選択する
2. Chrome 拡張 **distrokid-helper** を使って `30-distrokid/README.md` の手順に従い DistroKid Web フォームへ転記・アップロードを行う

DistroKid 申請後の DSP リンク（Spotify / Apple Music）到着は通常 1〜2 週間かかる。
