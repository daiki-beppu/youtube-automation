---
name: wf-new
description: "Use when まだコレクションディレクトリが存在せず、新規コレクション制作を立ち上げたいとき。「新しいコレクション始めたい」「制作開始」「新規ワークフロー」など、企画選択からディレクトリ作成・素材準備までを行う初期化フェーズで使用する。既存コレクションの進行は /wf-next"
---

## Overview

新コレクション開始オーケストレーター。子スキルを順番に呼び、通常は企画選択 + サムネイル承認の2箇所で一時停止する。
Suno チャンネルではプロンプト生成後、`suno-helper` 用の `yt-collection-serve` 起動と疎通確認まで行い、Chrome 拡張でのブラウザ実行だけを user に引き継ぐ。
minimal mode では企画候補生成前にテーマ / ジャンル / 雰囲気の直接入力確認が追加される。
アナリティクス未収集の新チャンネルでも、ベンチマークまたはユーザー直接入力で初回企画を開始する。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**（CLAUDE.md §6 参照）。

## When to Use

| 状況 | 使う？ |
|---|---|
| 制作中コレクションが無い + 新しく始めたい | ✅ 使う |
| 「次なに作る？」とだけ聞かれた（企画候補が未確定） | ❌ 先に `/collection-ideate` で候補を出す（`/wf-new` 内部でも呼ぶが、単独で候補だけ見たいなら直接 `/collection-ideate`）|
| 既存コレクションを次工程へ進めたい | ❌ `/wf-next` を使う |
| 進捗だけ知りたい | ❌ `/wf-status` を使う |

`/wf-new` は `workflow-state.json` を **新規作成し自動更新する**。ユーザーが手で編集してはいけない（[扱い基準](../../../docs/workflow-cheatsheet.md#workflow-statejson-の扱い)）。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

`/wf-new` は「順番にスキルを呼ぶ」ための薄いオーケストレーターである。各工程の詳細ロジックは子スキルへ寄せ、ここでは呼び出し順、停止点、成果物確認、`workflow-state.json` 更新だけを持つ。

データ収集は `/analytics-collect`（`yt-analytics` のラッパー）が担当するため、workflow からは呼び出さない。必要に応じてユーザー側で cron / launchd に登録する運用。テーマは企画の結果で決定されるため、最初に手入力しない。

### 呼び出しルール

- **順次実行**: 子スキルは必ず上から順に呼ぶ。並列 Agent は使わない
- **責務分離**: 子スキルの内部手順を `/wf-new` で再実装しない。必要な前提チェックだけを行い、失敗時は子スキルの障害時ガイダンスへ誘導する
- **停止点**: user 入力で止めるのは原則として (1) 企画選択 (2) サムネイル承認。minimal mode のみ、企画前にテーマ / ジャンル / 雰囲気の直接入力確認を追加する
- **状態更新**: 各ステップ完了時に `workflow-state.json` の該当 `assets` と `updated_at` を更新する。手で編集させない
- **再開性**: 途中失敗時は完了済み成果物を再生成せず、未完了ステップから再開できるように次に呼ぶ skill / CLI を明示する

### 実行シーケンス

| 順番 | 呼び出し先 | `/wf-new` の責務 | 主な成果物 |
|---|---|---|---|
| 1 | `/collection-ideate` | 入力モード判定を渡し、候補表示後に企画選択で停止 | 選択企画、プレビュー画像 |
| 2 | `yt-init-collection` | 選択企画から collection dir と初期 state を作る | `workflow-state.json` |
| 3 | `yt-populate-scene-phrases` | 多言語チャンネルの scene phrases を初期化 | `scene_phrases` |
| 4 | `/thumbnail` | テキスト付き `thumbnail.jpg` とテキストなし `main.png/jpg` を別成果物として確定する | `10-assets/thumbnail.jpg`, `10-assets/main.png` |
| 5 | `/suno` または `/lyria` | 音楽エンジンに応じてプロンプト生成 skill を呼ぶ | `suno-prompts.json` または Lyria 設計 |
| 6 | user 承認 | サムネイル承認で停止し、承認後に進める | `assets.thumbnail = true` |
| 7 | `/loop-video` または静止背景運用 | `loop-video.enabled=true` なら承認済み textless `main.png/jpg` から loop video を生成。`enabled=false` なら Veo を呼ばず textless `main.png/jpg` を静止背景として使う | `10-assets/loop.mp4` または textless `10-assets/main.png/jpg` |
| 8 | `yt-collection-serve`（Suno のみ） | suno-helper 用 server 起動と疎通確認まで行う | `http://<channel>.localhost:<PORT>` |

`/suno-helper` の Chrome 操作と `/wf-next` は自動実行しない。`/wf-new` は Suno 用 server 起動までで user に引き継ぐ。

### Phase 1: 企画（自動実行 + 入力モードに応じた一時停止）

```
Step 1（企画）を自動実行中...
```

1. **入力モード判定** — `/collection-ideate` を呼ぶ前に以下を確認し、同じ条件を `/collection-ideate` に引き継ぐ

| モード | 判定条件 | `/collection-ideate` の入力 |
|---|---|---|
| analytics mode | `reports/analysis_*.md` が存在し、stale ではない | 日次収集データ + ベンチマーク + config |
| benchmark fallback mode | `reports/analysis_*.md` が存在せず、`data/benchmark_*.json` が存在する | ベンチマークデータ + config |
| minimal mode | `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない | ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config |

`reports/analysis_*.md` が存在するが stale の場合は fallback せず、`/analytics-analyze` 再実行を案内して中断する。古い分析と別入力の混在を避けるため。

2. **Skill ツールで `/collection-ideate` を実行** — 入力モードに応じて企画候補をプレビューサムネイル付きで生成
   - analytics mode: 日次収集データ + ベンチマークを基に分析 + ペルソナ別候補を生成
   - benchmark fallback mode: 自チャンネル分析をスキップし、ベンチマークデータ + config から初回候補を生成
   - minimal mode: テーマ / ジャンル / 雰囲気をユーザーに確認し、その直接入力 + config から初回候補を生成

`/collection-ideate` の出力が表示された後、**ユーザーに企画選択のみ求める**:
- 選択肢: 提示された候補のいずれか
- **トラック数・音楽エンジンは確認しない**（`config/channel/*.json` の設定に従う）
- **ここでフローが一時停止し、ユーザーの入力を待つ**

**エラーハンドリング:**
- analytics mode で `/collection-ideate` がエラー → エラー内容を表示して中断。分析データの確認を案内
- benchmark fallback mode / minimal mode で `/collection-ideate` がエラー → エラー内容を表示して中断。入力モードと不足データを明示して再入力または `/benchmark` を案内

### Phase 2: 選択後の順次オーケストレーション

ユーザーが企画を選択したら、以下を上から順に実行する。途中で失敗したら、失敗したステップの次アクションを表示して停止する。

#### 2a. コレクション初期化（ディレクトリ + workflow-state.json）

`/collection-ideate` の選択結果を入力にして、コレクションディレクトリと workflow-state.json を自動生成する:

```bash
uv run yt-init-collection "<Collection Name>" "<theme-slug>" --track-count <N> --selected-plan <A-E> --music-engine <suno|lyria>
```

- `<Collection Name>`: 企画で決定したコレクション表示名
- `<theme-slug>`: ハイフン区切りのテーマスラッグ（例: `brigid-hearth`）
- `--track-count`: 確認済みトラック数（デフォルト 12）
- `--selected-plan`: 選択された企画（A〜E）
- `--music-engine`: 音楽エンジン（`suno` / `lyria`）。**省略時は `config/channel/youtube.json` の `music_engine` が使われる**。コレクション単位で上書きしたいときのみ明示する

スクリプトが以下を自動実行:
- `collections/planning/YYYYMMDD-<short>-<theme>-collection/` ディレクトリ作成
- サブディレクトリ（10-assets, 20-documentation）作成
- `workflow-state.json` 初期化（stage=planning, phase=planning-approved）

出力されたパスを後続ステップで使用する。フルスキーマは `references/schema.md` を参照。

#### 2b. scene_phrases 初期化

次に、多言語タイトル生成で必須となる `workflow-state.json.scene_phrases` を投入する:

まず Agent ツールでサブエージェントを起動し、`en` 以外の `supported_languages` 全件に対する翻訳 JSON object だけを生成させる。CLI 内部から Gemini / Claude CLI を呼ばない。

```bash
uv run yt-populate-scene-phrases <collection-dir-name> \
  --translations-file /tmp/scene-phrases.json
```

- `<collection-dir-name>`: 2a で作成された `YYYYMMDD-<short>-<theme>-collection` のディレクトリ名
- 英語フレーズは `config/channel/content.json` の `title.theme_scenes[<theme>].scene` から自動解決される。翻訳文は Agent ツールで生成し、`--translations-json` または `--translations-file` で渡す
- **`supported_languages` が 1 言語以下のチャンネルでは CLI 側で自動スキップ**されるため、条件分岐は不要（そのまま呼んで構わない）
- 既に `scene_phrases` が存在する場合もスキップ（`--overwrite` で上書き可能）
- `theme_scenes[<theme>]` が未定義の場合は `--en "<custom phrase>"` で英語フレーズを明示指定する。詳細は `references/scene_phrases.md` 参照

**エラーハンドリング:**
- `theme_scenes` 未定義 + `--en` 未指定 → エラー終了。`config/channel/content.json` の `title.theme_scenes` に該当 theme を追加するか、`--en` を渡して再実行
- 翻訳 JSON 未指定 / 言語欠落 → エラーに表示されるプロンプトで Agent に JSON を再生成させる（メタデータ生成前に `/wf-next` から再実行可能）

#### 2b. ドキュメント保存

Phase 1 の成果物を `20-documentation/` に保存:
- 企画候補一覧と選択結果

#### 2c. サムネイル確定 + 音楽素材生成

このステップはサムネイル系 skill と音楽系 skill を順番に呼ぶ。音楽素材生成はサムネイルのローカル成果物が揃ってから実行する。

1. **企画成果物を collection に固定**:
   - 選択した企画のプレビュー画像は企画参照として保存する。`10-assets/main.png` にはコピーしない
   - Phase 1 の企画候補一覧と選択結果を `20-documentation/` に保存
   - プレビューディレクトリの自セッション分を削除

2. **サムネイル skill を順番に処理**:
   - `single_step` モードまたは `image_generation.provider: codex` の場合でも `/thumbnail <theme>` を Skill ツールで実行する。`/thumbnail` 側で、ベンチマーク参照からテキスト付き `10-assets/thumbnail.jpg` を生成し、承認済み `thumbnail.jpg` からテキストなし `10-assets/main.png` または `main.jpg` を AI 再生成する
   - `two_phase` / `diff_from_reference` など、それ以外のモードでも `/thumbnail <theme>` を Skill ツールで実行し、同じく `thumbnail.jpg` と textless `main.png/jpg` を別成果物として確定する
   - `thumbnail.jpg` と `main.png/jpg` を同一画像で代用しない。`main.png` を `thumbnail.jpg` にコピーする旧運用は禁止
   - QA が NG の場合は `/collection-ideate` または `/thumbnail` の該当生成ステップへ戻し、`/wf-new` は停止する

3. **音楽 skill を順番に処理**:
   - Suno: `/suno <theme>` を Skill ツールで実行する。`/suno` 呼び出し前提条件チェック（`config/skills/suno.yaml::genre_line` または `data/video_analysis/<slug>/*.json`）を満たさない場合は `/suno` を起動せず、`uv run yt-video-analyze --source benchmark --channel <slug> --top 5` を案内して停止する。AI が `genre_line` を手書きで埋めて続行することは禁止
   - Lyria: `/lyria <theme>` を Skill ツールで実行する（この時点ではプロンプト設計まで。Lyria 3 API 呼び出しは `/wf-next`）
   - 成功したら `assets.music_prompts = true` に更新する

音楽素材生成に失敗した場合はエラーを報告し、次に手動で呼ぶべき `/suno` または `/lyria` コマンドを表示して停止する。

#### 2d. サムネイル承認

このステップは user 承認ゲートであり、子スキルは呼ばない。

1. サムネイルをプレビューで開く:
   ```bash
   open <collection-path>/10-assets/thumbnail.jpg
   ```

2. AskUserQuestion でサムネイルの承認を求める:
   ```
   question: "サムネイルを承認しますか？"
   options:
     - 承認する → assets.thumbnail = true に更新 → ループ動画生成へ
     - 再生成 → `/collection-ideate` のプレビュー段階で調整済みのため、diff_prompt を修正して `generate_image.py` で再生成
     - 中断 → ここで一旦停止（後で `/wf-next` で再開可能）
   ```

承認されたら `assets.thumbnail = true` に更新し、ループ動画設定確認へ進む。再生成または中断の場合は停止する。

#### 2e. ループ動画生成

サムネイル承認後、`config/skills/loop-video.yaml::enabled` を確認する。

- `enabled: false` の場合: `/loop-video` は呼ばず、textless `main.png/jpg` の静止画背景運用として続行する。`assets.loop_video = false` を維持し、`phase = "prepared"` に更新する
- `enabled` 未指定 or `true` の場合: `/loop-video` を Skill ツールで実行する（テキストなし `main.png/jpg` → `loop.mp4`）
  - 成功: `assets.loop_video = true` に更新
  - 失敗: `assets.loop_video = "failed"` を記録して続行（`/wf-next` で再試行可能）
  - いずれの場合も `phase = "prepared"` に更新する

#### 2f. Suno helper server 起動（Suno のみ）

`/suno` が生成した `20-documentation/suno-prompts.json` を Chrome 拡張へ配信するため、`yt-collection-serve` を **dir mode + 拡張 origin lock** で起動する。これは `/wf-new` の責務に含める。Suno UI での連続生成、playlist 追加、ZIP 一括 DL は引き続き `/suno-helper` の user 操作に委ねる。

1. **拡張 ID を確認**:
   - 既知であればそれを使う
   - 不明であれば user に `chrome://extensions` → suno-helper → 詳細 → ID を確認してもらい、`<EXTENSION_ID>` として受け取る
   - ID が得られない場合はサーバー起動をスキップし、下記コマンドを完了ガイダンスに出して停止しない

2. **port を決める**:
   - 既定は `7873`
   - 既に `7873` が使われている場合、同じ `Origin: chrome-extension://<EXTENSION_ID>` で下記の疎通確認 3 点が通るなら既存サーバーを再利用する
   - 既存サーバーが別用途または疎通確認に失敗する場合は `7874`, `7875`... の空き port を選ぶ

3. **バックグラウンド起動**:

   ```bash
   EXTENSION_ID="<EXTENSION_ID>"
   PORT=7873
   mkdir -p .tmp/logs
   nohup uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
     --allow-origin "chrome-extension://${EXTENSION_ID}" \
     --port "${PORT}" \
     > ".tmp/logs/yt-collection-serve-${PORT}.log" 2>&1 &
   ```

   - 必ず `"$CHANNEL_DIR/collections/planning"` を渡す（dir mode）。collection 単体パスや `suno-prompts.json` 直指定は playlist phase がスキップされるため使わない
   - `--allow-origin` は必須。未指定だと `GET /auth/token` と `POST /collections/<id>/downloaded` が 403 になる

4. **起動後の疎通確認（3 点すべて必須）**:

   ```bash
   curl -s "http://<channel>.localhost:${PORT}/collections" | python3 -m json.tool | head -20
   curl -s -H "Origin: chrome-extension://${EXTENSION_ID}" \
     "http://<channel>.localhost:${PORT}/auth/token" | python3 -m json.tool
   ```

   - `/collections` が JSON array を返す
   - 対象 collection が `"status": "ready"` と `"pattern_count"` を持つ
   - `/auth/token` が `{ "token": "..." }` を返す

5. **失敗時**:
   - サーバー起動または疎通確認に失敗しても `phase = "prepared"` は維持し、`/wf-new` は完了扱いにする
   - 失敗内容、log path、再実行コマンドを完了ガイダンスに出す
   - user は後で `/suno-helper` の Step 1 から起動し直せる

#### 2g. 完了ガイダンス

```
`/wf-new` 完了！

コレクション: <collection_name>
テーマ: <theme>
トラック数: <track_count>
音楽エンジン: <suno|lyria>
ディレクトリ: collections/planning/YYYYMMDD-<short>-<theme>-collection/
現在のフェーズ: prepared
ループ動画: ✅ 生成済み / ⚠️ 失敗（`/wf-next` で再試行可能）
Suno-helper server: ✅ http://<channel>.localhost:<PORT> 起動済み / ⚠️ 未起動（Suno の場合のみ）
```

音楽エンジンに応じた次ステップ案内:
- **Suno**: 「suno-helper server は `http://<channel>.localhost:<PORT>` で起動済みです。Chrome で Suno Custom Mode を開き、suno-helper popup のローカル配信元からこのチャンネルを選び、対象 collection を選んで連続実行してください。全件完了で playlist 一括追加 + ZIP 一括 DL まで自動。完了後に `/wf-next` を実行（plain Suno UI への手動投入は非推奨）」
- **Lyria**: 「`/wf-next` を実行すると Lyria 3 API が呼ばれ、コレクション尺に応じてセグメントが生成されます → ミキシング+マスタリング後に再度 `/wf-next`」

**重要**: `/wf-new` が自動で行うのは Suno 用ローカル server の起動と疎通確認まで。`/suno-helper` のブラウザ実行（Chrome + Suno ログイン + 拡張ロード + 連続実行開始）と `/wf-next` の次フェーズ進行は user に委ねる。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| GCP ADC 未取得/失効 | `ConfigError` / ADC 認証エラー | `gcloud auth application-default login`（必要なら `set-quota-project`）を再実行 |
| Vertex AI rate | HTTP 429 | 時間を置いて再実行。並列実行を避け順次処理する |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud（Vertex AI）のステータスを確認し、時間を置いて再実行 |
| 委譲先 skill の失敗 | 子 skill がエラー終了 | 各子 skill の「障害時ガイダンス」を参照して個別に対処 |

## Cross References

- 企画生成: `/collection-ideate` スキル
  - analytics mode: `reports/analysis_*.md` + ベンチマーク + config を使用
  - benchmark fallback mode: `data/benchmark_*.json` + config のみで初回企画を生成
  - minimal mode: ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config のみで初回企画を生成
- サムネイル生成: `/thumbnail` スキル
- ループ動画生成: `/loop-video` スキル
- 音楽プロンプト生成: `/suno` スキル
- Suno UI への連続注入 + playlist 一括追加: `/suno-helper` スキル
- 音楽プロンプト設計 + Lyria 3 API 呼び出し: `/lyria` スキル
- 後続ステップ管理: `/wf-next`
- 進捗確認: `/wf-status`
