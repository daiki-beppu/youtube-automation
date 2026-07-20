# 再生成モード（Step R1〜R8: 方向性検討後の詳細セットアップ / config 再生成）

`/channel-new` 再生成モードの手順詳細。SKILL.md の「モード判別」で本モードと判定された場合に、このファイルの手順どおりに実行する。
本ファイル内の `references/...` は `.claude/skills/channel-new/references/...`（本ファイルと同じディレクトリ配下）を指す。

新規開設モードの初期生成後、または方向性検討モードで再決定した方向性をもとに、`config/channel/*.json` と skill config を完成させる。

**実行場所**: リポジトリルート（独立リポジトリ）

**前提**:

- 新規開設モードが完了していること（TTP 対象確認 / seed fetch / 承認済み benchmark.channels 反映 / config / persona / branding の初期生成は新規開設モードが担当する）
- 方向性検討モードが完了し、`docs/channel/channel-direction.md` が存在すること

## Step R1: 方向性ドキュメントの読み込み

`docs/channel/channel-direction.md` を読み、確定した方向性を把握:
- チャンネル名、短縮名、ジャンル、スタイル、コンテキスト
- コアメッセージ、差別化ポイント
- 動画の長さ、投稿頻度、音楽エンジン

## Step R2: 設定内容の提案と承認

### Step R2.1: 競合 TTP 面のスナップショット取得（必須）

`config/channel/analytics.json::benchmark.channels` に承認済み TTP 対象が指定されている場合、**Step R2.2 の config 案作成前に必ず**競合チャンネルの TTP 対象面を全件取得し、snapshot を AI のコンテキストに載せる。取得は `references/fetch_branding_snapshot.py` に一本化する（新規開設モード Step 5 と同じスクリプト）。1 回のコマンドで承認済み `benchmark.channels` 全件の `id` を `--channel-id` として繰り返し指定する:

```bash
uv run python .claude/skills/channel-new/references/fetch_branding_snapshot.py \
  --channel-id "<benchmark.channels[0].id>" \
  --channel-id "<benchmark.channels[1].id>" \
  --output docs/channel/competitor-branding-snapshot.json
```

承認済み TTP 対象が 1 件だけなら `--channel-id` は 1 つでよい。複数ある場合に先頭 1 件だけで済ませない。

取得対象（=「TTP 対象面」チェックリスト、漏らさず全項目を AI のコンテキストに載せる）:

- [ ] `snippet.description` — チャンネル概要欄 base
- [ ] `brandingSettings.channel.description` — branding 説明文（`snippet.description` とほぼ同内容のことが多いが、片方だけ更新される運用もあるので両方取る）
- [ ] `brandingSettings.channel.keywords` — タグセット（数・順序・スペース入りクォート形式 `"my channel"` まで含めて転写）
- [ ] `brandingSettings.channel.country` / `snippet.country`
- [ ] `brandingSettings.channel.defaultLanguage` / `snippet.defaultLanguage`
- [ ] `localizations` 全エントリ（言語別 title / description）
- [ ] 投稿時刻・投稿頻度（分析モードで既に取得済みなら `docs/channel-research.md` を参照）
- [ ] サムネテンプレ・タイトルテンプレ（既存の分析モード成果物 + 競合 uploads playlist のサンプル）

**「TTP 完全コピー路線」をユーザーが選択している場合の運用ルール**:

- `brandingSettings.channel.description` の章立て構造（welcome 行 + 数段の段落 + 箇条書きセクションなど）と段落順をそのまま転写する
- `keywords` の構成・順序・クォート形式を踏襲し、固有名詞だけを自チャンネル名に置換する
- `localizations` で多言語化されているなら、その言語セットを追加・削除せず踏襲する。多言語化していなければローカライズ先を `en` のみにする
- 独自設計の文言は **転写後の差分** として後出しで提案する（先に独自文言を書いてしまうのは TTP 違反）

保存された `docs/channel/competitor-branding-snapshot.json` は、再生成モードの再実行や `/video-description` での再参照にそのまま使える。

### Step R2.2: config 案の生成と承認

`docs/channel-research.md` の分析データと **Step R2.1 で取得した競合スナップショット** を参照しながら、方向性に基づいて config 内容を Claude が生成し提案する。
生成ルールは **`references/config-generation-rules.md`** を参照（tags / descriptions / title / suno の書き方、および TTP 路線時の競合転写ルール）。
雛形は `references/config-template/*.json`（責務別 5 ファイル: meta / content / youtube / analytics / audio）。

### Step R2.3: TTP self-check（ユーザー承認前）

「TTP できているか」を Claude が自己レビューし、ユーザー承認前に以下を提示する:

- [ ] `descriptions.opening` / `descriptions.sub_opening` の段落構造が競合の `brandingSettings.channel.description` と対応しているか
- [ ] `tags.base` の語彙・件数・クォート形式が `brandingSettings.channel.keywords` と整合しているか
- [ ] `config/localizations.json::supported_languages` が 3 分岐ルールに一致しているか（TTP 多言語なら競合と完全一致、TTP 非多言語なら `en` のみ、非 TTP なら単一言語・ローカライズなし）
- [ ] 独自要素を入れている場合、どこを転写しどこを差別化したか 1 行ずつ説明できるか

self-check が pass したら提案をユーザーに見せ、承認 or 修正指示を受ける。

## Step R3: config/channel/*.json の完成

新規開設モードが作成した初期 config を完全版に拡張。`references/config-template/` の各ファイルを
`config/channel/` 配下に配置し、全フィールドを埋める。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。
`benchmark.channels` は新規開設モードで承認済み TTP 対象だけが設定済み（`config/channel/analytics.json`）。

**channel-direction.md からの転記（必須・空のまま終了しないこと、issue #567）**:

| `channel-direction.md` の決定 | 書き込み先 |
|---|---|
| 動画の長さ（分）| `config/channel/audio.json::audio.target_duration_min` / `target_duration_max` |
| テーマ → アクティビティ・シーンの対応表 | `config/channel/content.json::title.theme_scenes`（TTP 形式・推奨）または `title.theme_activities`（レガシー） |
| 投稿頻度 | `config/schedule_config.json`（Step R5） |
| 音楽エンジン | `config/channel/youtube.json::music_engine`（`suno` / `lyria`） |
| アップロード metadata | `config/channel/youtube.json::youtube.{category_id,privacy_status}` |
| ジャンル / スタイル / コンテキスト | `config/channel/content.json::genre.{primary,style,context}` |

`title.theme_scenes` を空で残すと `yt-populate-scene-phrases` が `--en` 手動指定を要求する。
チャンネル方向性が決まっているのに空で抜けるのは禁止（Fail Fast 原則違反）。

## Step R3.5: config/skills/*.yaml への転記（音楽方向性・サムネ TTP）

`docs/channel/channel-direction.md` の「ジャンル & スタイル」「ビジュアルアイデンティティ」決定は
**必ず** `config/skills/<skill>.yaml` に転記する。空のまま残ると下流 skill が
チャンネル方向性を AI に手書きさせる素地になる（issue #567 根本原因）。

雛形は `references/config-template/skills/<skill>.yaml`。channel-direction.md の決定を
プレースホルダ（`{{...}}`）に埋めてから `config/skills/` 配下にコピーする。

| 対象 skill | 雛形 | 書き込む内容 |
|---|---|---|
| suno（`music_engine: suno` のとき）| `references/config-template/skills/suno.yaml` | `workspace_name` / `genre_line`（ジャンル＋スタイル決定の直訳）/ `exclude_styles` |
| thumbnail | `references/config-template/skills/thumbnail.yaml` | `image_generation.provider`（GCP 課金なしなら `codex` を優先案内）/ `image_generation.gemini.brand_background` / `composition_rules.*` / `reference_images.default`（TTP サムネ）/ `reference_images.channel_branding`（snapshot / icon・banner reference / output path）/ `diff_prompt_template` |
| lyria（`music_engine: lyria` のとき）| `.claude/skills/lyria/config.default.yaml` を参照 | プロンプト系・尺・track 戦略 |

新規チャンネルで GCP 課金を避けたい利用者には、thumbnail provider として `codex` を先に案内する。
`codex` は ChatGPT サブスク認証を使うため GCP 課金は発生しないが、`codex login status` が
`Logged in using ChatGPT` を返すことが前提。Gemini を選ぶ場合は ADC / GCP 課金が必要。

**TTP 参照画像の自動 download**: `config/channel/analytics.json::benchmark.channels` が
設定済みなら `/benchmark` skill（CLI は `yt-benchmark-collect`）で
`docs/benchmarks/*.md` と `data/thumbnail_compare/benchmark/`
に各競合の代表サムネが download される。それを `image_generation.gemini.reference_images.default`
に列挙する（`path_base: channel_dir` でプロジェクトルートからの相対パス）。
手動 download は **しない**（issue #567）。

**benchmark 反映完了の検証**: Step R3.5 の最後に `uv run yt-doctor --json` を実行し、
`ttp_wf_new_readiness` が `ok` になることを確認する。`warn` の場合は
`/channel-new benchmark 反映未完了` として、`data/benchmark_*.json`、
`docs/benchmarks/*.md`、`data/thumbnail_compare/benchmark/`、および
`config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default` と
`config/skills/thumbnail.yaml::image_generation.gemini.reference_images.channel_branding` の欠落を解消してから次へ進む。

**fail-fast 動作**: `/thumbnail` `/suno` `/lyria` 等の下流 skill は、関連 config が空のまま
呼ばれた場合「`/channel-new`（再生成モード）未完了」を案内して停止する責務を持つ（CLAUDE.md
Fail Fast 原則）。再生成モード側で空欄を残さないことで、この案内が
発火しない状態を担保する。

## Step R4: 残りディレクトリの作成

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。

## Step R5: 残りファイル生成

| ファイル | 生成方法 |
|---------|---------|
| `config/channel/audio.json` | `references/config-template/audio.json` をコピー。`target_duration_min` は channel-direction.md の「動画の長さ」を必ず転記する（空のまま終了しない、issue #567）|
| `config/schedule_config.json` | `references/schedule-template.json` をコピー。投稿頻度と `upload_settings` を方向性に合わせて調整する |
| `config/localizations.json` | `references/localizations-template.json`（既定 `["ja", "en"]`）を起点に、次の 3 分岐へ必ず調整する: TTP かつ競合が多言語なら競合 `localizations` の言語セットを追加・削除せず踏襲、TTP かつ競合が非多言語なら `en` のみ、非 TTP なら単一言語・ローカライズなしとしてファイル省略可。省略時は `load_config().localizations.supported_languages` が `youtube.api.language` へフォールバックする。ジャンル情報を反映した具体的な文言に調整し、`languages.<lang>.title_template` のプレースホルダは **`{scene_phrase}` / `{activities}` / `{scene_emoji}` のみ使用可**（アップローダー許可リスト、issue #1471）。`{style}` / `{theme}` / `{axis_label}` 等の content.json 用キーは使わない。違反は `uv run yt-doctor --json` の `channel_config` check が検出する。`config/localizations.json` が唯一の Canonical ソース |
| `.claude/CLAUDE.md` | `references/claude-md-template.md` の `{{CHANNEL_NAME}}` / `{{DIR_NAME}}` を置換 |

## Step R6: GCP / Vertex AI ブートストラップ

**`/setup` を実行してください**。GCP プロジェクト作成・API 有効化・IAM 付与・`.env` 書き出しを AI 主導で進め、Google Auth Platform の Branding / Audience Test users / Clients 設定と `client_secrets.json` 配置を `[HUMAN STEP]` として案内する。

事前に `uv run yt-doctor --json` を叩き、`checks[]` のうち `category == "api"` の全 check が `ok` なら `/setup` は完了済みのため本 step を skip して **Step R7 へ進む**（`channel` / `upload` カテゴリは config 生成後フェーズで満たす）。

旧: bootstrap.sh / terraform を手動で叩く手順は `references/gcp-bootstrap.md` に残してあるが、通常ルートは `/setup` に統一する。

## Step R7: 検証

JSON 構文検証・config ロードテスト・channel_id 自動取得コマンドは **`references/verification.md`** を参照。
検証後、生成された全ファイルを一覧で確認する。

## Step R8: 次ステップ案内

1. **YouTube チャンネル作成**（まだの場合）→ `config/channel/meta.json` の `channel.youtube_handle`、`channel.url`、`channel.channel_id` を更新
2. **OAuth 認証と channel_id 取得**: 手順は `references/verification.md`（「OAuth 認証」「channel_id の自動取得」）を参照
3. **ブランディング素材**: 生成手順は `references/verification.md`（「ブランディング素材生成」）を参照
4. **YouTube 側に設定を反映**: 初回反映は新規開設モード Step 8 で実施済み。再反映や運用中の更新は設定 push モードを参照
5. **任意のパイロット検証**: 色味・構図・ムード・テンポを先に確認したい場合は、仮コレクションで `/thumbnail` → `/thumbnail-compare`、および `music_engine` が `suno` なら `/suno` → `/suno-helper`、`lyria` なら `/lyria` を実行し、OK/NG を判断する。NG なら `config/skills/thumbnail.yaml` / `config/skills/suno.yaml` / `config/skills/lyria.yaml` を調整して再試作する。OK なら仮コレクションを削除するか、既存 `collections/planning/` として `/wf-next` で継続する
6. **初回コレクション制作**: パイロットを省略する、またはパイロット OK 後に新規本制作を始める場合は `/wf-new` を実行
