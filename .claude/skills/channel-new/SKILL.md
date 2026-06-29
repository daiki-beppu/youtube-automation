---
name: channel-new
description: "Use when 新しい YouTube チャンネル用の独立リポジトリを現在のディレクトリで初期化したいとき。「チャンネル追加」「新チャンネル」「チャンネル開設」「チャンネルセットアップ」「新しいチャンネル作りたい」「TTP 対象を集める」など、新規チャンネルの TTP 対象確認、config 生成、簡易ペルソナ、branding 初回反映まで end-to-end で進める場面で必ず使用すること。"
---

## Overview

新チャンネル開設を `/setup`（onboard）後の 1 スキルで完結させるエントリポイント。
現在の作業ディレクトリをそのまま channel repo として使い、TTP 対象の確認と TTP に必要な情報収集、フルパッケージ config 生成、簡易ペルソナ、YouTube branding 初回反映まで進める。

**標準フロー**:
```
/setup        → GCP / OAuth / ADC / automation パッケージ準備
/channel-new  → TTP hearing + seed confirmation + config + persona + branding ← このスキル
/wf-new       → 初回コレクション制作
```

`/channel-research`、`/channel-direction`、`/channel-setup` は廃止しない。
追加の競合探索、本格ベンチマーク収集、詳細分析、方向性の再検討、運用中の設定 push / pull が必要なときに追加で使う。

## TTP 原則

`/channel-new` の主目的は、競合チャンネルを **seed** ではなく **TTP 対象** として収集し、転写する型を明文化すること。
ユーザーには「どんなチャンネルにしたいか」より先に「どのチャンネルの何を TTP したいか」を聞く。

TTP メモは最低限、以下の観点を含める:

- タイトル構造
- サムネ構図
- 投稿頻度
- 動画尺
- ジャンル / 音楽スタイル
- branding description / keywords の段落構造と語彙

## Instructions

**実行場所**: `/setup` 完了後の channel repo ルート。テンプレートから clone しない。今いるディレクトリを初期化する。

### Step 1: TTP ヒアリング

ユーザーに以下を質問し、各チャンネルごとに「何を転写するか」の関係性メモを必須で残す。

- **TTP したいチャンネル**: URL / handle / channel ID を 1 件以上
- **転写したい要素**: タイトル構造 / サムネ構図 / 投稿頻度 / 尺 / ジャンル / branding のどれか
- **仮チャンネル名と SHORT**: `meta.json::channel.name` / `channel.short` に入れる
- **初期ジャンル情報**: `genre.primary` / `genre.style` / `genre.context`
- **動画尺の初期値（分）**: `audio.target_duration_min` / `target_duration_max`
- **音楽エンジン**: `music_engine` に入れる `suno` / `lyria` のどちらか
- **branding 方針**: TTP 対象の description / keywords / localizations をどの程度転写するか

このヒアリング結果は `yt-channel-init` の CLI 引数と、後続の seed fetch / TTP 対象反映に使う。
ヒアリング後は `docs/channel/ttp-seed-confirmation.md` を作成し、TTP したいチャンネル URL / handle / channel ID、転写したい要素、関係性メモを保存する。

### Step 2: 現在のディレクトリを repo 初期化

`.git` がなければ現在のディレクトリで初期化する。テンプレートリポジトリは使わない。

```bash
git init
gh repo create <repo-name> --private --source . --remote origin
```

`gh` 未認証やリポジトリ作成を今行わない判断になった場合も、ローカル初期化と config 生成は止めない。
ただし remote 作成を保留したことは作業メモに明記する。

### Step 3: setup 完了確認

`/channel-new` は **`/setup` 完了済み** を前提に進める。`/setup` が automation パッケージ導入、`yt-skills sync`、GCP プロジェクト作成、API 有効化、ADC、OAuth クライアント ID 配置、OAuth token 生成までを担当する。

AI は以下を実行して状態を確認する:

```bash
uv run yt-doctor --json
```

以下の check が `ok` でない場合は、ここで `/setup` を案内して停止する。認証とツール導入が完了するまで Step 4 以降へ進まない。

- `ffmpeg`
- `ffprobe`
- `uv`
- `uv_project`
- `automation_package`
- `skills_synced`
- `gcloud`
- `gcloud_account`
- `gcp_project`
- `billing_linked`
- `apis_enabled`
- `adc`
- `adc_quota_project`
- `iam_aiplatform_user`
- `env_file`
- `client_secrets`
- `oauth_token`

Step 4 の config 生成で解消するため、以下の config 未生成由来の fail は許容する:

- `channel_config`: `config/channel/ ディレクトリが存在しない (新規チャンネル)`
- `upload_ready`: `config/channel/meta.json が存在しない`
- `upload_ready`: `channel.channel_id が未設定`

`upload_ready` が `auth/token.json が存在しない`、`upload 必須 scope 不足`、`token.json 読み込み失敗` で fail している場合は `/setup` を案内して停止する。その他の fail / warn / unknown が残る場合は、表示された `next_action` に従って解消してから進む。

seed fetch は YouTube Data API 認証に依存するため、既存チャンネルの token コピーで代替しない。

### Step 4: フルパッケージ config / ディレクトリ生成

`yt-channel-init` で `config/channel/*.json` と正準ディレクトリ構造を一括生成する:

```bash
uv run yt-channel-init \
  --short "<SHORT>" \
  --name "<仮チャンネル名>" \
  --genre "<genre.primary>" \
  --style "<genre.style>" \
  --context "<genre.context>" \
  --core-message "<core message>" \
  --target-duration-min "<min minutes>" \
  --target-duration-max "<max minutes>" \
  --music-engine "<suno|lyria>" \
  --branding-description "<TTP 構造を転写した説明文>" \
  --channel-keyword "<keyword 1>" \
  --channel-keyword "<keyword 2>"
```

TTP 対象がこの時点で channel ID まで分かっている場合も、Step 4 では `benchmark.channels` へ書き込まない。
候補 URL / handle / channel ID と関係性メモだけを残し、Step 5 の実データ確認とユーザー承認後に反映する。

生成対象:

- `config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json`
- `config/localizations.json`
- `config/schedule_config.json`（`upload_settings` を含む）
- `config/skills/{suno,thumbnail}.yaml`
- `.env`
- `.gitignore`
- `auth/client_secrets.template.json`
- `auth/`, `collections/`, `data/`, `docs/channel/personas/`, `docs/benchmarks/`, `research/`

冪等性: 既存ファイルは `--force` がない限り上書きしない。差分がある場合は unified diff を確認してから `--force` を判断する。

### Step 5: TTP seed fetch と承認済み対象反映

Step 1 の TTP チャンネルを YouTube Data API で実データ化する。

```bash
uv run yt-channel-seed "https://www.youtube.com/@example" \
  --target . \
  --no-write-benchmark \
  --json
```

表示されたチャンネル名、登録者数、動画数、直近タイトルをユーザーに提示し、TTP 対象として確定するか確認する。
承認前に `benchmark.channels` へ書き込まない。承認されたチャンネルだけ relationship メモ付きで `config/channel/analytics.json::benchmark.channels` に反映する。

```bash
uv run yt-channel-seed "https://www.youtube.com/@example" \
  --target . \
  --relationship "title-structure: ..., thumbnail-composition: ..., posting-cadence: ..."
```

`yt-channel-seed --no-write-benchmark --json` の出力は seed 確認用であり、`description` / `keywords` / `localizations` / `brandingSettings` は含まない。
seed 確認後、`docs/channel/ttp-seed-confirmation.md` を更新して以下を保存する:

- source URL / handle / channel ID
- `yt-channel-seed --no-write-benchmark --json` の要約（チャンネル名、登録者数、動画数、uploads playlist ID、直近タイトル）
- ユーザーの承認 / 不採用判断
- 承認済み対象だけの relationship メモ
- `config/channel/analytics.json::benchmark.channels` に反映した id / slug / name / relationship
- 後続 `/discover-competitors` / `/benchmark` / `/viewer-voice` / `/channel-research` が必要かどうか

承認済み TTP 対象について、branding 転写に必要な情報は別途取得して保存する:

```bash
uv run python3 - <<'PY'
from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
import json
from pathlib import Path

approved_channel_ids = ["UC..."]  # Step 5 で承認された TTP 対象だけ
youtube = YouTubeOAuthHandler().get_youtube_service()
items = []
for channel_id in approved_channel_ids:
    resp = youtube.channels().list(
        part="snippet,brandingSettings,localizations",
        id=channel_id,
    ).execute()
    items.extend(resp.get("items", []))

out = Path("docs/channel/competitor-branding-snapshot.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False), encoding="utf-8")
PY
```

`docs/channel/competitor-branding-snapshot.json` は以下を含む TTP branding snapshot として扱う:

- `snippet.description`
- `brandingSettings.channel.description`
- `brandingSettings.channel.keywords`
- `brandingSettings.channel.country` / `snippet.country`
- `brandingSettings.channel.defaultLanguage` / `snippet.defaultLanguage`
- `localizations` 全エントリ

TTP するうえで必要な実データメモは、`docs/channel/ttp-seed-confirmation.md` と `docs/channel/competitor-branding-snapshot.json` を正とする:

- チャンネル名 / handle / channel ID
- 登録者数、動画数、直近タイトルから見える型
- タイトル構造、サムネ構図、投稿頻度、動画尺
- description / keywords / localizations の転写方針（branding snapshot 由来）
- `config/channel/analytics.json::benchmark.channels` に入れた relationship

### Step 6: 追加調査は後続スキルへ委譲

`/channel-new` の標準フローでは、TTP 対象以外の競合発掘や本格ベンチマーク収集を実行しない。
以下は必要になった時点で、ユーザーに目的を確認してから後続スキルとして実行する:

- 追加の競合候補を広げたい → `/discover-competitors`
- 承認済み TTP 対象の動画データやサムネイルを本格収集したい → `/benchmark`
- コメントを含めて視聴者インサイトを見たい → `/viewer-voice`
- 収集済みデータから方向性を深掘りしたい → `/channel-research`

### Step 7: 簡易ペルソナ導出

新チャンネルには `/viewer-voice` や `/benchmark` の結果がまだない場合があるため、ここでは軽量版だけ作る。

入力:

- `config/channel/analytics.json::benchmark.channels`
- `docs/channel/ttp-seed-confirmation.md`
- `docs/channel/competitor-branding-snapshot.json`

出力:

```text
docs/channel/personas/channel-new-persona.md
```

内容:

- 第一ペルソナ 1 名
- 補助ペルソナ 1-2 名
- 利用シーン
- 検索語彙 / コメント語彙
- タイトル、タグ、概要欄、サムネへの反映方針

本格的な見直しは公開後に `/audience-persona` で実行する。

### Step 8: branding 初回反映

Step 5 で保存した `docs/channel/competitor-branding-snapshot.json` の TTP 対象 `brandingSettings` を参照して、ローカル config の `youtube_channel` と `config/localizations.json` を確認する。

確認観点:

- description の段落構造
- keywords の件数、順序、クォート形式
- country / default_language
- localizations の言語セット

まず認証済みチャンネルの ID を `config/channel/meta.json::channel.channel_id` に保存し、取り違え防止の照合を有効にする。
この操作は local branding を上書きしない。

```bash
uv run yt-channel-settings pull --channel-id-only --apply
uv run yt-channel-settings diff
uv run yt-channel-settings push
uv run yt-channel-settings push --apply
```

`push` dry-run の内容をユーザーに見せ、`meta.json::channel.channel_id` が認証済みチャンネル ID と一致していることを確認してから `--apply` する。

### Step 9: wf-new 接続前チェック

`/wf-new` へ進む前に、初回で止まりやすい前提を確認する。

| 前提 | 初回 fallback |
|---|---|
| Analytics データがまだ無い | #1272 で wf-new 側対応予定。初回は TTP メモと seed fetch 結果を企画根拠として使う |
| `config/skills/thumbnail.yaml` の reference_images が空 | TTP サムネの手動選定メモを `notes` に残す。本格収集が必要なら `/benchmark` で `yt-benchmark-collect --keep-thumbnails` を実行する |
| `config/skills/suno.yaml` が placeholder のまま | Step 1 のジャンル情報を `genre_line` に反映してから進む |
| `auth/token.json` が無い | `/setup` を再実行し、OAuth を完了してから YouTube API 操作に戻る |

最後に案内する:

```text
チャンネル初期化が完了しました。次は /wf-new で初回コレクション制作に進めます。
```

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| `/setup` 未完了 | `auth/token.json` 不在、ADC 未設定、API 403 | `/setup` を先に完了する |
| `gh` CLI 不在/未認証 | `command not found: gh` / `gh auth` エラー | `gh` を install し `gh auth login` を実行。remote 作成だけ保留して config 生成は継続可 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota リセットを待つか、対象チャンネル数を絞る |
| seed が誤チャンネル | `yt-channel-seed --no-write-benchmark --json` の表示が想定と違う | ユーザー確認で不採用にし、承認後の書き込みコマンドを実行しない |
| branding push 失敗 | `yt-channel-settings push --apply` が 400/403 | dry-run 差分、OAuth scope、`meta.json::channel.channel_id` を確認する |

## Cross References

- `/setup` → 前提: automation ツール導入 + GCP / OAuth / ADC 準備
- `/discover-competitors` → TTP 対象外の追加競合発掘
- `/benchmark` → 承認済み TTP 対象の本格ベンチマーク収集
- `/viewer-voice` → コメント収集と視聴者インサイト分析
- `/audience-persona` → 公開後の本格ペルソナ見直し
- `/channel-research` → 収集済みデータの詳細分析
- `/channel-direction` → 方向性の再検討
- `/channel-setup` → 運用中の設定 push / pull と詳細セットアップ
- `/wf-new` → 初回コレクション制作
