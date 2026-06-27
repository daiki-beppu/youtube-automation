---
name: channel-setup
description: "Use when /channel-new 後に詳細セットアップをやり直したいとき、または運用中チャンネルの YouTube 側設定（branding / status / localizations）をローカル config と同期したいとき。「設定反映」「チャンネル設定更新」「branding push」「ローカライゼーション同期」「meta.json を YouTube に反映」など既存チャンネルの設定 push/pull、および /channel-direction で方向性を再決定した後の config 再生成に関わる場面で使用すること。初回 branding は /channel-new で開始する"
---

## Overview

本スキルは 2 つのモードを持つ:

1. **詳細セットアップ / 再生成モード** (Step 1〜8): `/channel-new` の初期生成後、または `/channel-direction` で再決定した方向性をもとに、`config/channel/*.json` と skill config を完成させる。
2. **設定 push モード** (Step 9): ローカル `config/channel/meta.json` と `config/localizations.json` を YouTube 側の `brandingSettings` / `status` / `localizations` に反映する。運用中チャンネルの設定変更時に使用。

呼び出し時の文脈から自動判別する。「設定反映」「チャンネル設定更新」「branding push」「ローカライゼーション同期」など push 系の発動キーワードなら **Step 9 へ直行**し、Step 1〜8 はスキップする。

**初回立ち上げの前提**: `/channel-new` を使用する。現在のディレクトリ初期化、TTP benchmark、フルパッケージ config、簡易ペルソナ、初回 branding は `/channel-new` が担当する。

**詳細セットアップ / 再生成の前提**: `/channel-direction` が完了し、`docs/channel/channel-direction.md` が存在すること。

**設定 push モードの前提**: OAuth 認証完了済み (`auth/token.json` が存在) かつ `config/channel/meta.json` の `channel.channel_id` が設定済みであること。

## Instructions

**実行場所**: リポジトリルート（独立リポジトリ）

### Step 1: 方向性ドキュメントの読み込み

`docs/channel/channel-direction.md` を読み、確定した方向性を把握:
- チャンネル名、短縮名、ジャンル、スタイル、コンテキスト
- コアメッセージ、差別化ポイント
- 動画の長さ、投稿頻度、音楽エンジン

### Step 2: 設定内容の提案と承認

#### Step 2.1: 競合 TTP 面のスナップショット取得（必須）

`config/channel/analytics.json::benchmark.channels[0]` が指定されている場合、**Step 2.2 の config 案作成前に必ず**競合チャンネルの TTP 対象面を取得し、生の YouTube レスポンスをそのまま AI のコンテキストに載せる:

```bash
uv run python3 -c "
from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
from youtube_automation.utils.config import load_config
import json

cfg = load_config()
ttp_target = cfg.analytics.benchmark.channels[0]['id']
youtube = YouTubeOAuthHandler().get_youtube_service()
resp = youtube.channels().list(
    part='snippet,brandingSettings,localizations',
    id=ttp_target,
).execute()
print(json.dumps(resp['items'][0], indent=2, ensure_ascii=False))
"
```

取得対象（=「TTP 対象面」チェックリスト、漏らさず全項目を AI のコンテキストに載せる）:

- [ ] `snippet.description` — チャンネル概要欄 base
- [ ] `brandingSettings.channel.description` — branding 説明文（`snippet.description` とほぼ同内容のことが多いが、片方だけ更新される運用もあるので両方取る）
- [ ] `brandingSettings.channel.keywords` — タグセット（数・順序・スペース入りクォート形式 `"my channel"` まで含めて転写）
- [ ] `brandingSettings.channel.country` / `snippet.country`
- [ ] `brandingSettings.channel.defaultLanguage` / `snippet.defaultLanguage`
- [ ] `localizations` 全エントリ（言語別 title / description）
- [ ] 投稿時刻・投稿頻度（`/channel-research` で既に取得済みなら `docs/channel/channel-research.md` を参照）
- [ ] サムネテンプレ・タイトルテンプレ（既存の `/channel-research` 成果物 + 競合 uploads playlist のサンプル）

**「TTP 完全コピー路線」をユーザーが選択している場合の運用ルール**:

- `brandingSettings.channel.description` の章立て構造（welcome 行 + 数段の段落 + 箇条書きセクションなど）と段落順をそのまま転写する
- `keywords` の構成・順序・クォート形式を踏襲し、固有名詞だけを自チャンネル名に置換する
- `localizations` で多言語化されているなら、自分も同じ言語セットを採用候補にする。多言語化していなければ `youtube.json::content_model` の `localization.supported_languages` も同様に絞る選択肢を提示する
- 独自設計の文言は **転写後の差分** として後出しで提案する（先に独自文言を書いてしまうのは TTP 違反）

取得した競合スナップショットは `docs/channel/competitor-branding-snapshot.json` などに保存しておくと、後段の `/channel-setup` 再実行や `/video-description` での再参照が楽になる（必須ではない）。

#### Step 2.2: config 案の生成と承認

`channel-research.md` の分析データと **Step 2.1 で取得した競合スナップショット** を参照しながら、方向性に基づいて config 内容を Claude が生成し提案する。
生成ルールは **`references/config-generation-rules.md`** を参照（tags / descriptions / title / suno の書き方、および TTP 路線時の競合転写ルール）。
雛形は `references/config-template/*.json`（責務別 4 ファイル: meta / content / youtube / analytics）。

#### Step 2.3: TTP self-check（ユーザー承認前）

「TTP できているか」を Claude が自己レビューし、ユーザー承認前に以下を提示する:

- [ ] `descriptions.opening` / `descriptions.sub_opening` の段落構造が競合の `brandingSettings.channel.description` と対応しているか
- [ ] `tags.base` の語彙・件数・クォート形式が `brandingSettings.channel.keywords` と整合しているか
- [ ] `localization.supported_languages` が競合 `localizations` のエントリ言語と整合しているか（TTP 路線なら同じ、独自路線なら明示的に diff を説明）
- [ ] 独自要素を入れている場合、どこを転写しどこを差別化したか 1 行ずつ説明できるか

self-check が pass したら提案をユーザーに見せ、承認 or 修正指示を受ける。

### Step 3: config/channel/*.json の完成

`/channel-new` が作成した初期 config を完全版に拡張。`references/config-template/` の各ファイルを
`config/channel/` 配下に配置し、全フィールドを埋める。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。
`benchmark.channels` は `/channel-new` で既に設定済み（`config/channel/analytics.json`）。

**channel-direction.md からの転記（必須・空のまま終了しないこと、issue #567）**:

| `channel-direction.md` の決定 | 書き込み先 |
|---|---|
| 動画の長さ（分）| `config/channel/audio.json::audio.target_duration_min` / `target_duration_max` |
| テーマ → アクティビティ・シーンの対応表 | `config/channel/content.json::title.theme_scenes`（TTP 形式・推奨）または `title.theme_activities`（レガシー） |
| 投稿頻度 | `config/schedule_config.json`（Step 5） |
| 音楽エンジン | `config/channel/youtube.json::music_engine`（`suno` / `lyria`） |
| ジャンル / スタイル / コンテキスト | `config/channel/content.json::genre.{primary,style,context}` |

`title.theme_scenes` を空で残すと `yt-populate-scene-phrases` が `--en` 手動指定を要求する。
チャンネル方向性が決まっているのに空で抜けるのは禁止（Fail Fast 原則違反）。

### Step 3.5: config/skills/*.yaml への転記（音楽方向性・サムネ TTP）

`docs/channel/channel-direction.md` の「ジャンル & スタイル」「ビジュアルアイデンティティ」決定は
**必ず** `config/skills/<skill>.yaml` に転記する。空のまま残ると下流 skill が
チャンネル方向性を AI に手書きさせる素地になる（issue #567 根本原因）。

雛形は `references/config-template/skills/<skill>.yaml`。channel-direction.md の決定を
プレースホルダ（`{{...}}`）に埋めてから `config/skills/` 配下にコピーする。

| 対象 skill | 雛形 | 書き込む内容 |
|---|---|---|
| suno（`music_engine: suno` のとき）| `references/config-template/skills/suno.yaml` | `workspace_name` / `genre_line`（ジャンル＋スタイル決定の直訳）/ `exclude_styles` |
| thumbnail | `references/config-template/skills/thumbnail.yaml` | `image_generation.gemini.brand_background` / `composition_rules.*` / `reference_images.default`（TTP サムネ）/ `diff_prompt_template` |
| lyria（`music_engine: lyria` のとき）| `.claude/skills/lyria/config.default.yaml` を参照 | プロンプト系・尺・track 戦略 |

**TTP 参照画像の自動 download**: `config/channel/analytics.json::benchmark.channels` が
設定済みなら `uv run yt-benchmark` で `docs/benchmarks/*.md` と `data/thumbnail_compare/benchmark/`
に各競合の代表サムネが download される。それを `image_generation.gemini.reference_images.default`
に列挙する（`path_base: channel_dir` で channel_dir からの相対パス）。
手動 download は **しない**（issue #567）。

**fail-fast 動作**: `/thumbnail` `/suno` `/lyria` 等の下流 skill は、関連 config が空のまま
呼ばれた場合「`/channel-setup` 未完了」を案内して停止する責務を持つ（CLAUDE.md
Fail Fast 原則）。`channel-setup` 側で空欄を残さないことで、この案内が
発火しない状態を担保する。

### Step 4: 残りディレクトリの作成

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。

### Step 5: 残りファイル生成

| ファイル | 生成方法 |
|---------|---------|
| `config/channel/audio.json` | `references/config-template/audio.json` をコピー。`target_duration_min` は channel-direction.md の「動画の長さ」を必ず転記する（空のまま終了しない、issue #567）|
| `config/schedule_config.json` | `references/schedule-template.json` をコピー。投稿頻度を方向性に合わせて調整 |
| `config/upload_settings.json` | `references/upload-settings-template.json` をコピー |
| `config/localizations.json` | `references/localizations-template.json` をコピーし、ジャンル情報を反映した具体的な文言に調整。`supported_languages` は `["ja", "en", "de"]` を必ず含める（広告単価が高い 3 言語、issue #272）。低 CPM 言語は原則追加しない。多言語展開しないチャンネルは省略可（`load_config().localizations.supported_languages` は `youtube.api.language` へフォールバック）。`config/localizations.json` が唯一の Canonical ソース |
| `.claude/CLAUDE.md` | `references/claude-md-template.md` の `{{CHANNEL_NAME}}` / `{{DIR_NAME}}` を置換 |

### Step 6: GCP / Vertex AI ブートストラップ

**`/onboard` を実行してください**。GCP プロジェクト作成・API 有効化・IAM 付与・`.env` 書き出し・OAuth クライアント ID 作成までを AI 主導の wizard で進める。

事前に `yt-doctor --json` を叩き、`checks[]` のうち `category == "api"` の全 check が `ok` なら `/onboard` は完了済みのため本 step を skip して **Step 7 へ進む**（`channel` / `data` / `upload` カテゴリは config 生成後フェーズで満たす）。

旧: bootstrap.sh / terraform を手動で叩く手順は `references/gcp-bootstrap.md` に残してあるが、通常ルートは `/onboard` に統一する。

### Step 7: 検証

JSON 構文検証・config ロードテスト・channel_id 自動取得コマンドは **`references/verification.md`** を参照。
検証後、生成された全ファイルを一覧で確認する。

### Step 8: 次ステップ案内

1. **YouTube チャンネル作成**（まだの場合）→ `config/channel/meta.json` の `channel.youtube_handle`、`channel.url`、`channel.channel_id` を更新
2. **OAuth 認証と channel_id 取得**: 手順は `references/verification.md`（「OAuth 認証」「channel_id の自動取得」）を参照
3. **ブランディング素材**: 生成手順は `references/verification.md`（「ブランディング素材生成」）を参照
4. **YouTube 側に設定を反映**: 初回反映は `/channel-new` で実施済み。再反映や運用中の更新は Step 9（設定 push モード）を参照
5. **初回コレクション制作**: `/wf-new` を実行

### Step 9: 設定 push モード（運用中チャンネルの設定同期）

ローカル `config/channel/meta.json` の `youtube_channel` セクション（description / keywords / country / default_language / unsubscribed_trailer / made_for_kids）と `config/localizations.json` を YouTube チャンネルに反映、もしくは YouTube 側から取り込む。新規セットアップ後はもちろん、運用中に設定を変更したときの **設定反映フェーズ** としても本セクションが入口。

**運用フロー（push 方向: local → YouTube）**:

1. `uv run yt-channel-settings diff` で意図しないずれがないか確認（読み取り専用）
2. `uv run yt-channel-settings push` の dry-run 出力をレビュー（API 呼び出しなし）
3. 問題なければ `uv run yt-channel-settings push --apply` で実反映

**逆方向（pull: YouTube → local）が必要な場合**:

```bash
uv run yt-channel-settings pull               # dry-run: 取り込み内容のプレビュー
uv run yt-channel-settings pull --apply       # 実反映: meta.json と localizations.json を書き換え
```

YouTube 側で手動編集した設定をローカルに取り込みたいときに使う。`--apply` 後は git diff で変更内容を必ず確認すること。

**API 制約と運用上の注意**:

- `--apply` 実行時は `brandingSettings` / `localizations` / `status` を **別々の `channels().update()` 呼び出し** として個別に発火する。YouTube Data API は `brandingSettings` を他の part と同時送信すると `branding_settings cannot be used with other parts` で 400 エラーを返すため (#230)。この分割は CLI 側で自動対応済みで、運用者が意識する必要はない。
- `localizations` セクションを **完全に空** にして送信すると `Required` 400 エラーになる。`config/localizations.json` の `supported_languages` を全削除して全ローカライゼーションを消したい場合は、少なくとも `default_language` の 1 件はエントリを残して push すること（送信しなかったロケールは YouTube 側で自動削除される）。
- `--no-localizations` を付けると localizations 関連の比較・送信をスキップする（branding と status だけを反映したいときに使う）。
- 認可スコープは `youtube.force-ssl` が必要。`auth/token.json` が古い OAuth scope のままだと 403 になるので、その場合は `auth/token.json` を削除して再認証する。

## Cross References

- `/channel-new` → 初回セットアップ: TTP benchmark / config / persona / branding
- `/channel-direction` → 再検討フェーズ: 方向性決定
- `references/` → テンプレートファイル（同スキルディレクトリ内）
- `/wf-new` → チャンネル完成後の最初のアクション
- `yt-channel-settings` CLI (`src/youtube_automation/scripts/channel_settings_cli.py`) — Step 9（設定 push モード）の実装本体
