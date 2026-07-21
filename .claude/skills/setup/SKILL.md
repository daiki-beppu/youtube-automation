---
name: setup
description: "Use when ツール導入と GCP / OAuth の API 設定をセットアップ・再診断するとき。「セットアップして」「環境構築」「/setup」「旧 /onboard」で発動。yt-doctor 診断 wizard。新規チャンネルの config・ペルソナ・branding を作る場合は /channel-new を使う"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `*`（共通基盤としてほぼ全スキル）

## Overview

このスキルは **AI が指揮を取るツール・API 設定 wizard** である。automation CLI 導入後は `uv run yt-doctor --apply --json` に診断と安全な `ai-exec` の連続実行を委ね、`apply.stop_reason` が示す human 操作・利用者の決定・コマンド失敗だけを対話的に解決する。

責務は「automation ツールが動き、API 認証とアップロード前提が通る状態」まで。新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding は `/channel-new` が担当する。

利用者は GCP / OAuth に不慣れな前提。**すべてのコマンドの起動・実行・再診断は AI または setup スクリプトが担当する。** 利用者には、ブラウザ上のログイン・アカウント選択・OAuth 同意・秘密情報入力など、認証本人にしか行えない操作だけを `[HUMAN STEP]` として依頼する。

## 前提

本スキルはセットアップの起点であり、前工程スキルの成果物を要求しない。確認するのは以下のみ:

- 実行場所がチャンネル用ディレクトリであること（空フォルダ可。automation CLI の導入から「起動時のチェック」の手順で行う）
- `uv` が利用可能であること。無ければ最初の step（bootstrap カテゴリの `uv` check）でインストールを案内する
- 利用者が Google アカウントを持ち、AI / setup が起動した認証フローに対して、自分のブラウザでログイン・OAuth 同意・Google Auth Platform 設定を行えること（認証本人にしかできない `[HUMAN STEP]` として依頼する）

`config/channel/*.json` の存在は前提にしない（channel カテゴリの check が fail でも `/channel-new` を案内するだけで setup 自体は完了できる）。

### カテゴリ別チェック構成

`yt-doctor` は診断を 5 カテゴリで段階表示する:

| カテゴリ | 内容 |
|---------|------|
| `bootstrap` | ffmpeg / ffprobe / uv / pyproject.toml / automation パッケージ / `yt-skills sync` / 番号付き重複ファイル検知（7 check） |
| `api` | gcloud CLI・GCP プロジェクト・Billing・APIs・ADC・IAM・.env・OAuth 認証・Reporting API ジョブ（12 check） |
| `channel` | config/channel/ のロード可能性・playlists.json の妥当性・playlist 作成 dry-run（3 check: `channel_config` / `playlist_config` / `playlist_create_dry_run`）。fail 時は `/channel-new`（新規開設 / 既存チャンネル取り込み / 再生成モード）を案内するだけ |
| `data` | `/wf-new` の入力モード判定データ + 初期セットアップ事前検査（analytics_report / benchmark_data / ttp_wf_new_readiness / initial_setup_readiness）。minimal mode / benchmark fallback mode は setup のブロッカーにしない。analytics report は最新 `data/analytics_data_*.json` との相対比較に加え、`collection-ideate` の解決済み `freshness_days` を超えた絶対鮮度 stale も検出する。承認済み TTP がある場合だけ `/channel-new`（再生成モード） benchmark 反映完了を確認する |
| `upload` | upload 必須 scope 充足・channel_id 設定済み（1 check） |

### 完了条件

`uv run yt-doctor --apply --json` の `apply.stop_reason` が `completed`（全 check 緑）になり、ツール、API 認証、アップロード前提が揃った状態が完了（報告文面は「完了時」セクションを参照）。例外として `analytics_report` の stale fail だけは後続スキルが自動解消するため setup のブロッカーにせず、`checks` 配列のほかの check がすべて `ok` なら `human_required` で停止しても同じ完了状態として扱う。`data` カテゴリは `/wf-new` の入力モード確認用で、stale analytics report、minimal mode、benchmark fallback mode のいずれも新規チャンネル初回制作を止めない。新規チャンネル作成は次に `/channel-new` を実行する。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API（oauth_token 手順の `uv run yt-oauth` 接続テスト） | 約 1 call | OAuth 認証の実行有無 |
| YouTube Reporting API（`uv run yt-doctor` 診断 + `uv run yt-analytics --reporting-create-job`、無料枠） | 数 call（quota 課金なし） | Reporting job の作成有無 |
| Vertex AI（Gemini / Veo / Lyria） | 0（`gcloud services enable` は API 有効化のみで生成呼び出しなし） | — |

- 上限 / 承認: plain 診断（`uv run yt-doctor --json`）と書き込み系 check（playlist_create_dry_run 等）は読み取り専用 / dry-run で、YouTube 側への変更は発生しない。`yt-doctor --apply` は別であり、ローカルの skill 同期・古い managed skill 削除・`.env` 追記と、GCP の project 選択・Billing 紐付け・API 有効化・ADC quota project・IAM 付与・Reporting job 作成を行い得る。そのため以下の承認 gate を通す。

## 起動時のチェック

空フォルダでは `yt-doctor` がまだ存在しないため、最初にライブ配信予定を確認してから automation CLI を導入する:

1. 利用者に「このチャンネルで近いうちにライブ配信または 24/7 配信を予定していますか？」と 1 問だけ確認する
   - 予定なしの場合: 追加案内はせず、次の手順へ進む
   - 予定ありの場合: YouTube のライブ配信有効化はリクエストから最大 24 時間かかるため、今すぐ有効化しておくよう注意喚起し、以下を **[HUMAN STEP]** として案内する。ただし、この有効化完了は `/setup` のブロッカーにせず、案内後は次の手順へ進む

```
> [HUMAN STEP]
> YouTube のライブ配信有効化は、リクエストから最大 24 時間かかる場合があります。
> 近いうちにライブ配信または 24/7 配信を行う予定があるため、今すぐ有効化リクエストだけ済ませてください。
>
> 手順:
>   1. https://studio.youtube.com を開く
>   2. 右上の「作成」から「ライブ配信開始」を選ぶ
>   3. 画面の案内に従ってライブ配信の有効化をリクエストする
>
> 有効化完了は待たずに、/setup wizard はこのまま続行します。
```

2. `uv` が無ければ `uv` step の公式コマンドを AI が実行する
3. `pyproject.toml` が無ければ `uv init` を Bash で実行する
4. `pyproject.toml` に `youtube-channels-automation` 依存が無ければ `uv add git+https://github.com/daiki-beppu/youtube-automation.git` を Bash で実行する
5. `uv run yt-skills sync --asset skills --force` / `uv run yt-skills sync --asset claude-md` / `uv run yt-skills sync --asset auth-template` を Bash で実行する
6. `uv run yt-setup-dirs` を Bash で実行し、OAuth クライアント JSON の配置先 `auth/` など setup に必要な最小ディレクトリを作成する
7. 初回のみ `uv run yt-doctor --json` を読み取り preflight として実行し、`checks[].next_action` から現時点の変更対象・コマンドを表示する。project ID がすでに解決できる場合は、後述の「GCP 変更 plan の承認」に従って連続実行で新たに到達し得る変更も全件表示する。`skills_synced` が prune を求める場合は、実在する managed legacy skill の削除対象パスを 1 件ずつ列挙する。その上で AskUserQuestion により「表示した変更を実行」/「中止」の明示 2 択を提示し、「GCP 変更は外部反映され、prune は列挙したファイルを削除する」と警告する。承認されなければここで停止する
8. 承認後、収集済み決定 flag を保持する `apply_flags` を空で初期化し、`uv run yt-doctor --apply --json <apply_flags>` を 1 回実行して JSON の `apply.stop_reason` を読む。初回は flag 無しの `uv run yt-doctor --apply --json` となる
9. `completed`: 冒頭の「完了条件」を確認し、「運用設定インタビュー」後に「完了時」を報告する
10. `human_required`: `apply.check_id` の §Steps を参照する。`apply.next_action.reason == "authentication"` なら `apply.next_action.cmd` を AI が対話 session で起動してから、ブラウザ認証だけを `[HUMAN STEP]` として依頼する。その他は対応する `[HUMAN STEP]` を 1 つだけ依頼して停止する。認証コマンドまたは人間操作の完了後、必要な後処理と現在の `apply_flags` をすべて付けた手順 8 の再診断は AI が行う。`analytics_report` stale の例外は「完了条件」に従う
11. `decision_required`: `apply.check_id` が `gcp_project` なら project ID、`billing_linked` なら billing account ID を利用者に 1 問で確認する。値を `apply_flags` へ仮追加または同名 flag の値を仮置換し、後述の「GCP 変更 plan の承認」で、その flag により新たに実行可能になる全コマンドと正確な project / account を再表示する。AskUserQuestion の「表示した GCP 変更を実行」/「中止」の 2 択で承認された後だけ flag を確定して再実行する。以後 `completed` まで全 flag を毎回付け、値を変更するたびに plan を再表示・再承認する。project と billing が両方決定済みなら `uv run yt-doctor --apply --json --project-id <project-id> --billing-account <billing-id>` となる
12. `command_failed`: `apply.check_id` / `apply.cmd` / `apply.stderr` を利用者に示し、AI が §Steps に沿って原因を診断・解消してから、現在の `apply_flags` をすべて付けて手順 8 を再実行する。認証・承認入力以外のコマンドを利用者へ委ねない

`--apply` は `ai-exec` を診断順に連続実行し、各コマンド後に再診断する。AI は `apply.executed` を実行済み履歴として読み、§Steps に残る同じ `ai-exec` コマンドを重複実行してはならない。`stop_reason` が上記 4 値以外、または JSON が読めない場合は安全側に停止し、CLI 出力を示す。

### GCP 変更 plan の承認

project ID が解決済み、または `apply_flags` へ `--project-id` / `--billing-account` を追加・変更するたびに、次回 `--apply` が連続診断で到達し得る変更 plan を承認前に再作成する。`gcloud auth list` で active account を読み取り、正確な project ID、billing account ID（決定済みの場合）、active account と、§Steps に記載した project 選択・Billing 紐付け・API 有効化・ADC quota project・IAM 付与・`.env` 追記・Reporting job 作成のうち未解決の全コマンドを展開して表示する。

表示後、「これらは project `<project-id>` の外部 GCP 状態を変更する」と警告し、AskUserQuestion で「表示した GCP 変更を実行」/「中止」の 2 択を提示する。承認されるまで flag 付き `--apply` を実行しない。値の追加・変更は前回の承認を無効にし、必ず plan を再表示して承認を取り直す。

`/setup` は `uv run yt-setup-dirs` で `auth/`, `branding/`, `collections/`, `data/`, `docs/channel/personas/`, `docs/benchmarks/`, `research/` を冪等に作成する。`/setup` では `config/channel/*.json` を生成しない。新規チャンネルの config、TTP メモ、ペルソナ、branding は引き続き `/channel-new` の責務。

## 認証コマンドと人間操作の責務

以下の認証コマンドも、利用者へ実行を依頼してはならない。AI が PTY 付きの対話 session、または setup スクリプトの inherited stdio で起動し、プロセスを維持する:

- `gcloud auth login`
- `gcloud auth application-default login`
- `uv run yt-oauth`

人間は開いたブラウザでログイン・アカウント選択・OAuth 同意だけを行う。認可コード、password、token、client secret をチャットへ貼らせない。YouTube OAuth は AI が `uv run yt-oauth` を background session で起動し、stdout の同意 URL を利用者へ中継する。PKCE の `code_verifier` を保持するため、AI は認証開始時と同じプロセスを完了まで維持し、別プロセスでコマンドを再実行しない。認証プロセスが exit 0 になったら AI が `yt-doctor --apply` を再実行する。exit 非 0 なら stderr を確認して再試行条件を案内する。

**Google Auth Platform の Branding / Audience / Clients 設定と client secret の Download JSON** (Google Cloud Console GUI 操作) は gcloud / Terraform に該当 API が存在しないため、これも `[HUMAN STEP]` で依頼する。ダウンロード後の `client_secrets.json` 配置と再診断は AI が `yt-doctor --fix-client-secrets` で行う。

## [HUMAN STEP] の書き方

利用者に認証操作を依頼するときは、先に AI が認証コマンドを対話 session で起動し、必ず以下の形式でブラウザ操作だけを依頼する:

```
> [HUMAN STEP]
> 認証コマンドは setup が起動済みです。開いたブラウザで Google ログインと同意を完了してください。
> password・認可コード・token はチャットへ貼らないでください。
```

認証プロセスの終了を session で待ち、待機中は 60 秒以内の間隔で進捗を伝える。exit 0 後は該当 step の後処理と、現在の `apply_flags` をすべて付けた `uv run yt-doctor --apply --json <apply_flags>` を AI が実行して新しい `apply.stop_reason` を確認する（`client_secrets` は `yt-doctor --fix-client-secrets` を先に実行する）。認証以外のコマンドも利用者へ実行依頼せず、AI / setup が実行する。

例外: 「起動時のチェック」のライブ配信有効化リクエスト案内は、リードタイム確保のための早期注意喚起である。`[HUMAN STEP]` 書式で案内するが、完了待ちはせず wizard を通常どおり続行する。

## Steps (check id ごとの対応手順)

各 step は `yt-doctor` の check id にマップする。AI は `apply.check_id` の値を見て該当 step に飛ぶ。`--apply` 導入後、`ai-exec` と明記した個別コマンドは `command_failed` の原因確認用であり、通常ループでは `--apply` が自動実行する。automation 導入前の `uv_project` / `automation_package` と認証コマンドは AI が直接実行する。`[HUMAN STEP]` はブラウザ認証・GUI 操作・利用者の決定だけを指し、コマンド実行を含めない。

### bootstrap カテゴリ

#### `ffmpeg` / `ffprobe` — 動画生成ツール未インストール

`yt-doctor` の `next_action.instructions` から OS に合う手順を選び、AI がインストールコマンドを実行する。macOS なら以下を実行する:

```bash
brew install ffmpeg
```

#### `uv` — uv 未インストール

利用者の OS に合わせ、https://docs.astral.sh/uv/getting-started/installation/ の公式コマンドを AI が実行する。認証情報や管理者承認が求められた場合だけ、その入力を `[HUMAN STEP]` として依頼する。

#### `uv_project` — `pyproject.toml` 未作成

AI が以下を直接実行:

```bash
uv init
```

#### `automation_package` — automation パッケージ未導入

AI が以下を直接実行:

```bash
uv add git+https://github.com/daiki-beppu/youtube-automation.git
```

> この `uv add`（および「起動時のチェック」手順 3 の同コマンド）は automation パッケージ導入 **前** に実行するため、リポジトリ参照をパッケージの `UPSTREAM_REPO` 定数から導出できずリテラル固定である。fork 運用者は owner を自 fork に読み替える（upstream `.claude/CLAUDE.template.md` の「fork 運用者向け」節を参照）。パッケージ導入後の `yt-doctor` の `next_action.cmd` は導入済みパッケージの定数から組み立てられる。

#### `skills_synced` — スキル未展開

`apply.next_action.kind == "human"` でもコマンドは利用者へ依頼しない。`reason == "authentication"` なら `cmd` を AI が起動し、人間にはブラウザ認証だけを依頼する。それ以外は `apply.next_action.instructions` から GUI 操作・判断だけを **[HUMAN STEP]** として依頼し、必要なコマンドは AI が実行する。`ai-exec` の sync / prune は「起動時のチェック」手順 7 で実行対象と削除パスを示し、利用者が実行を承認した場合だけ `--apply` が自動実行する。

初回展開や同梱 skill 不足時は以下を実行する:

```bash
uv run yt-skills sync --asset skills --force
uv run yt-skills sync --asset claude-md
uv run yt-skills sync --asset auth-template
uv run yt-setup-dirs
```

旧 `/onboard` 等の managed legacy skill が残存している場合は、通常の `--force` sync では削除されない。plain 診断後に実在する削除対象を列挙し、「削除した managed skill は復元されない」と警告した上で AskUserQuestion の「prune を実行」/「中止」の 2 択で承認を取る。承認されるまで `--apply` を実行しない。承認後の `--apply` が以下の prune を実行する:

```bash
uv run yt-skills sync --asset skills --force --prune --yes
```

`.agents/skills` が `.claude/skills` を指す symlink になっていない warning の場合は、実体と既存パスを確認し、変更対象を表示して承認を得た後に AI が symlink を作成する。完了後は AI が `uv run yt-doctor --apply --json <apply_flags>` を再実行する。

#### `numbered_duplicates` — 番号付き重複ファイル検出

iCloud Drive 等のクラウド同期コンフリクトで `.venv/bin/` や `.claude/skills/` に `<名前> 2` 形式の重複ファイルが生成されたケース。`yt-doctor` の `apply.next_action.instructions` を参照するが、すぐに削除しない。検出した実在パスを 1 件ずつ列挙し、「削除後は元の重複ファイルを復元できない」と警告し、AskUserQuestion で「列挙した対象を削除」/「中止」の 2 択を提示する。承認されるまで削除しない。`.venv` 全体の再作成が必要な場合も、対象の絶対パスと再作成コマンド `uv sync` を示し、同じ 2 択で別途承認を取った後だけ、その `.venv` を削除して `uv sync` で再作成する。

### api カテゴリ

#### `gcloud` — gcloud CLI 未インストール

macOS なら AI が以下を実行する:

```bash
brew install --cask google-cloud-sdk
```

その他 OS は https://cloud.google.com/sdk/docs/install の公式手順を確認し、AI が該当コマンドを実行する。管理者認証だけを利用者へ依頼する。

#### `gcloud_account` — gcloud 未ログイン

AI が PTY 付き対話 session で次を起動する:

```bash
gcloud auth login
```

プロセスを維持したまま、利用者にはブラウザ認証だけを **[HUMAN STEP]** で依頼する:

```
> [HUMAN STEP]
> 認証コマンドは setup が起動済みです。開いたブラウザで Google ログインと同意を完了してください。
> password・認可コード・token はチャットへ貼らないでください。
```

#### `gcp_project` — GCP プロジェクト未確定

利用者に既存流用か新規作成か聞く:

- 既存流用: project ID を聞く（`.env` への `GOOGLE_CLOUD_PROJECT` 書き込みは不要。project_id は ADC quota project から自動解決される）
- 新規作成: チャンネル情報から推奨 project ID と表示名を生成し、利用者に提示して承認またはカスタム入力を求める

新規作成時の推奨値:

- チャンネル名: `config/channel/meta.json` の `channel.name` が存在すればそれを使う。未設定の場合は `<channel_dir>` のベースネームを title case 化して使う (例: `lofi-beats` -> `Lofi Beats`)
- project ID: `yt-{channel-slug}`。`channel-slug` はチャンネル名を kebab-case 化し、英小文字・数字・ハイフン以外をハイフンに置換、連続ハイフンを 1 個に畳み、先頭末尾のハイフンを削る
- project ID は GCP 制約に合わせて 6-30 文字、英小文字開始、末尾は英小文字か数字（ハイフン終端は不可）に収める。`yt-{channel-slug}` が 30 文字を超える場合は次の 3 段で truncate する:
  1. `yt-` prefix は必ず保持し、超過分は `channel-slug` の末尾から削って全体を 30 文字以内にする（prefix 側からは削らない）
  2. 切り詰め後の末尾がハイフンになった場合は、そのハイフンも追加で削る（例: `yt-midnight-drive-time-lounge-a`（31 文字）を先頭 30 文字で単純に切ると `yt-midnight-drive-time-lounge-`（30 文字、末尾ハイフンで GCP 制約違反）になるため、ハイフンを削って `yt-midnight-drive-time-lounge`（29 文字）にする）
  3. 上記処理後に 6 文字未満になる・空になる・truncate で意味が読み取れなくなる場合は自動生成をやめ、カスタム入力を求める
- project 表示名 (`--name`): `{チャンネル名} YouTube` (例: `Lo-Fi Beats YouTube`)

利用者には「推奨 project ID は `<suggested-project-id>`、表示名は `<channel-name> YouTube`。この ID で作成してよいか、またはカスタム project ID を入力してください」と確認する。project ID はグローバルユニークなので、作成失敗時は別 ID を聞いてリトライする。

新規作成を選んだ場合は、決定した project ID と表示名を示し、「Google Cloud に外部 resource を作成し、作成後も resource は残る」と警告する。AskUserQuestion で「project を作成」/「中止」の明示 2 択を提示し、作成が承認されるまで次のコマンドを実行しない:

```bash
gcloud projects create <project-id> --name="<channel-name> YouTube"
```

新規作成の成功後、または既存 project ID が決まった後は、手動で `gcloud config set` を実行しない。必ず先に「GCP 変更 plan の承認」へ戻る。この project ID で新たに実行可能になる全変更を再表示する。AskUserQuestion で実行が承認された後だけ次を実行し、中止ならここで停止する。project 選択と後続の ADC quota project 設定は `--apply` が診断順に行う。

```bash
uv run yt-doctor --apply --json --project-id <project-id>
```

#### `billing_linked` — billing 未紐付け

AI が利用可能な account を取得し、利用者に決定を依頼する:

1. `gcloud beta billing accounts list --format=json` で利用可能 billing account を取得
2. `open: true` のものだけを表で利用者に提示し、どれを使うか選ばせる
3. 選択された ID を `apply_flags` へ仮追加し、必ず先に「GCP 変更 plan の承認」へ戻る。project / billing account と新たに実行可能になる全変更を再表示し、AskUserQuestion で実行が承認された後だけ次を再実行する。中止ならここで停止する:

```bash
uv run yt-doctor --apply --json --project-id <project-id> --billing-account <billing-id>
```

billing account が 1 つも無い利用者には、Console URL (`https://console.cloud.google.com/billing`) を提示して billing account 自体の作成を依頼。

#### `apis_enabled` — 必須 API 未有効

`--apply` が以下を自動実行:

```bash
gcloud services enable youtube.googleapis.com youtubeanalytics.googleapis.com youtubereporting.googleapis.com aiplatform.googleapis.com generativelanguage.googleapis.com --project=<project-id>
```

billing 未紐付けで失敗する場合は `billing_linked` に戻る。

#### `adc` — Application Default Credentials 未設定

AI が PTY 付き対話 session で次を起動する:

```bash
gcloud auth application-default login
```

プロセスを維持したまま、利用者にはブラウザ認証だけを **[HUMAN STEP]** で依頼する:

```
> [HUMAN STEP]
> ADC 認証コマンドは setup が起動済みです。開いたブラウザで Google ログインと同意を完了してください。
> password・認可コード・token はチャットへ貼らないでください。
```

#### `adc_quota_project` — ADC quota project 不一致

`--apply` が以下を自動実行:

```bash
gcloud auth application-default set-quota-project <project-id>
```

#### `iam_aiplatform_user` — Vertex AI 権限未付与

`--apply` が以下を自動実行 (active アカウントは `gcloud auth list` で取得):

```bash
gcloud projects add-iam-policy-binding <project-id> \
  --member=user:<active-account> \
  --role=roles/aiplatform.user \
  --condition=None \
  --quiet
```

#### `env_file` — `.env` 未生成または不足キー

`.env` が未生成の場合は `--apply` が以下の既定値を既存値を保持して書き込む。不足キーのみの場合は `apply.next_action` の案内に従う:

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION=us-central1
```

`us-central1` はデフォルト。利用者が別リージョンを希望すれば差し替える。`GOOGLE_CLOUD_PROJECT` は ADC quota project から自動解決されるため通常は書き込み不要（明示したい場合のみ任意 override として追加）。

#### `client_secrets` — OAuth クライアント秘密ファイル未配置

**[HUMAN STEP]** で依頼 (`yt-doctor` の `next_action.url` をそのまま使う):

HUMAN STEP を出す前に、`gcp_project` と同じルールでチャンネル名を解決し、以下の推奨名をメッセージに含める:

- Google Auth Platform > Branding のアプリ名: `{チャンネル名} YouTube Automation` (例: `Lo-Fi Beats YouTube Automation`)
- OAuth クライアント ID 名: `{チャンネル名} Desktop Client` (例: `Lo-Fi Beats Desktop Client`)

```
> [HUMAN STEP]
> OAuth クライアント ID は Google Cloud Console でしか作成できません。
>
> 以下の URL を開いてください:
>   https://console.cloud.google.com/apis/credentials?project=<project-id>
>
> 推奨入力値:
>   - Google Auth Platform > Branding のアプリ名: <channel-name> YouTube Automation
>   - OAuth クライアント ID 名: <channel-name> Desktop Client
>
> 手順:
>   1. 左メニューで「Google Auth Platform」を開く
>   2. 「Branding」でアプリ名に上記の推奨アプリ名を入力し、ユーザーサポートメールと
>      デベロッパー連絡先には自分の Google アカウントを入れて保存
>   3. 「Audience」で User type は「External」、Publishing status は「Testing」のまま、
>      「Test users」に OAuth 認証でログインする Google アカウントを追加
>      （未追加だと初回認証が 403 access_denied で止まります）
>   4. 「Clients」→「Create client」で Application type「Desktop app」を選び、
>      名前には上記の推奨 OAuth クライアント ID 名を入力
>   5. 作成した client を開き、「Client secrets」→「Add secret」で新しい secret を発行
>   6. 「Download JSON」を押して Downloads に保存
>
> 完了したら "done" と返してください。
```

利用者が "done" と返したら、AI が次を順に Bash で実行する:

```bash
uv run yt-doctor --fix-client-secrets
uv run yt-doctor --apply --json <apply_flags>
```

`client_secrets` が `ok` になるか確認する。fix または再診断が失敗した場合はエラー詳細を見せてリトライする。

#### `oauth_token` — OAuth トークン未取得

`--apply` はブラウザ認証を無人実行しない。AI が background session で次を起動する:

```bash
uv run yt-oauth
```

stdout に表示された同意 URL を利用者へ中継し、プロセスを維持したまま、ブラウザ認証だけを **[HUMAN STEP]** として依頼する:

```
> [HUMAN STEP]
> OAuth 認証コマンドは setup が起動済みです。開いたブラウザで対象アカウントを選び、同意を完了してください。
> password・認可コード・token はチャットへ貼らないでください。
```

初回はブラウザが開いて認証が走る。完了すると `<channel_dir>/auth/token.json` が生成される。AI は background process の exit 0 を待ち、`uv run yt-doctor --apply --json <apply_flags>` を再実行して検証する。

#### `reporting_job` — Reporting API ジョブ未作成

`--apply` が以下を自動実行する:

```bash
uv run yt-analytics --reporting-create-job
```

コマンドは冪等で、既存ジョブがあれば再利用する。成功後は `--apply` が再診断して次の check へ進む。

### channel カテゴリ

#### `channel_config` — チャンネル設定未ロード

`yt-doctor` の `next_action.instructions` を確認:

- **`/channel-new` 案内** (config/channel/ ディレクトリ未存在): 新規チャンネルの場合は `/channel-new` を実行して設定を作成する。この経路では対象 config が未生成のため「運用設定インタビュー」はスキップし、「運用設定は `/channel-new` 完了後に `/setup` を再実行して設定できます」と案内する
- **`/channel-new` 取り込みモード案内** (ディレクトリ存在・ロード失敗): 既存チャンネルの config を持ち込む場合は `/channel-new`（既存チャンネル取り込みモード）を実行して設定を修復する

AI は config をここで生成しない。`yt-setup-dirs` で setup 用ディレクトリが作成済みでも `config/channel/*.json` は未生成で正常な中間状態として扱う。`yt-doctor` の `message` に含まれるエラー詳細をそのまま利用者に示し、どちらのルートかを確認してから案内する。

#### `playlist_config` — `config/channel/playlists.json` の妥当性

`config/channel/playlists.json` が未存在（warn）または JSON 不正 / `playlists` 定義不備（fail）の状態。`/channel-new`（再生成モード）で `playlists.json` を作成・修正するよう案内するだけで、setup 側では生成しない。config 未生成の新規チャンネルでは `/channel-new` 完了までの正常な中間状態として扱う。

#### `playlist_create_dry_run` — playlist 作成 dry-run

`PlaylistManager.create_all_playlists(dry_run=True)` の事前検査。`playlist_id` 未設定エントリの `title` 欠落や設定ロード失敗を検出する。`yt-doctor` の `next_action.instructions` に従い、`uv run yt-playlist-manager --init --dry-run` の結果と `playlists.json` を確認して修正を案内する。

### data カテゴリ

#### `analytics_report` — `/wf-new` 入力モード状態

`reports/analysis_*.md` が存在しないこと自体は setup のブロッカーにしない。`yt-doctor` の message に表示される入力モードは、Markdown の有無と stale の**予備確認**として扱う。`yt-doctor` は同日付 JSON の存在や analysis JSON validator の成否を確認しないため、analytics mode の最終判定には使わない:

- ファイル名日付が最新の `reports/analysis_*.md` と同日付の `.json` が存在し、`.claude/skills/analytics-analyze/references/analysis-json-validator.md` の validator が exit 0 で、stale ではない → analytics mode
- `reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode

Markdown があるのに同日付 JSON がない、または validator が失敗する場合は fallback せず `/analytics-analyze` 再実行を案内する。

ペアが stale の場合は、`yt-doctor` の message で stale を表示したうえで setup のブロッカーにしない。`apply.stop_reason == "human_required"` かつ `apply.check_id == "analytics_report"` でも `[HUMAN STEP]` として `/analytics-analyze` の実行を利用者へ依頼せず、後続の `/collection-ideate` が同じセッションで自動更新する旨を案内する。`checks` 配列の後続 check を確認し、ほかの未完了 check があればその check の手順へ進む。

自動更新の実行順序、再検証、refresh / API 失敗時の停止・再開条件は `.claude/skills/collection-ideate/references/freshness-rules.md` を参照する。setup は refresh / API 失敗時の停止・再開条件は上書きしない。`/wf-new` はこの stale 判定を重ねない。

#### `benchmark_data` — ベンチマークデータ状態

benchmark の有無は analytics report の有無より優先しない:

- `yt-doctor` の予備判定: fresh `reports/analysis_*.md` がある → benchmark の有無に関係なく analytics mode
- validator 成功済みで fresh な同日付 `reports/analysis_*.md` / `.json` ペアがある → benchmark の有無に関係なく analytics mode
- `reports/analysis_*.md` が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも無い → minimal mode

1 行目は現行 `yt-doctor` の表示上の予備判定であり、最終 Hard Gate ではない。`/wf-new` と `/collection-ideate` は 2 行目のペア + validator 条件で判定する。

minimal mode / benchmark fallback mode は新規チャンネル初回制作を始めるための許容状態であり、setup の完了を止めない。

#### `ttp_wf_new_readiness` — 承認済み TTP の `/channel-new` benchmark 反映状態

`benchmark.channels` に承認済み TTP 対象がある場合だけ、初回 `/wf-new` 前に `/channel-new`（再生成モード）の benchmark 反映が完了しているか確認する。`yt-doctor` の `message` に `/channel-new benchmark 反映未完了` が含まれる場合は、以下を案内する:

- `/channel-new`（再生成モード）の benchmark 反映ステップ（Step R3.5）を再実行する
- `data/benchmark_*.json`、`docs/benchmarks/*.md`、`data/thumbnail_compare/benchmark/` の参照画像を揃える
- `config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default` に `data/thumbnail_compare/benchmark/...` の相対パスを転記する
- 完了後に `uv run yt-doctor --apply --json <apply_flags>` を再実行し、`ttp_wf_new_readiness` が ok になることを確認する

`benchmark.channels` 未設定の場合は minimal mode として扱われるため、setup の完了を止めない。

#### `initial_setup_readiness` — 初期セットアップ事前検査

`config/skills/thumbnail.yaml` / `config/skills/suno.yaml` の空欄・不備（reference_images / composition_rules の未設定、`genre_line` の文字数超過など）と、planning 中コレクションの `descriptions.md` parse 失敗を warn として一括検出する。`yt-doctor` の `next_action` に従い、skill config の転記は `/channel-new`（再生成モード）、descriptions.md の再生成は `/video-description` を案内する。config 未転記の新規チャンネルでは `/channel-new` 完了までの正常な中間状態として扱う。

### upload カテゴリ

#### `upload_ready` — アップロード可能状態未達

`yt-doctor` の `message` / `data` / `next_action` をひとまとめの診断契約として読み、以下の順で分岐する。`data.reason` がある場合は、散文の `message` より優先して判定する。

##### YouTube チャンネル未作成

`data.reason == "channel_not_found"` の場合だけ、認証済みアカウントに YouTube チャンネルがまだないと判定する。以下を **[HUMAN STEP]** として案内し、作成完了まで後続へ進まない。

```
> [HUMAN STEP]
> 認証済みの Google アカウントに YouTube チャンネルがまだありません。
> YouTube Studio (https://studio.youtube.com) を開き、このアカウントでチャンネルを作成してください。
> 作成完了後に "done" と返してください。
```

"done" の後に `uv run yt-doctor --apply --json <apply_flags>` を再実行する。

##### remote channel ID のローカル反映

`data.remote_channel_id` が取得済みで、`message` が `channel.channel_id が未設定` を示す場合は、ID を手書きせず既存入口を案内する。利用者の合意後に AI が以下を実行し、`meta.json` のみに channel ID を反映する。

```bash
uv run yt-channel-settings pull --channel-id-only --apply
uv run yt-doctor --apply --json <apply_flags>
```

##### local / remote ID 不一致

`data.reason == "channel_id_mismatch"` の場合は `data.local_channel_id` と `data.remote_channel_id` を並べて示し、**自動上書きしない**。どちらが意図したチャンネルかを利用者に確認し、次の 2 択から選んでもらう。

- remote ID 側が正しい: まず `uv run yt-channel-settings pull --channel-id-only` で dry-run を表示する。利用者が反映を承認した場合だけ `uv run yt-channel-settings pull --channel-id-only --apply` を実行する
- local ID 側が正しい: 削除対象を表示して承認を得た後、AI が `<channel_dir>/auth/token.json` を削除して `uv run yt-oauth` を background session で起動し、stdout の同意 URL を中継する。利用者には意図した Google アカウントでのブラウザ認証だけを **[HUMAN STEP]** として依頼する

選択した対処の完了後に `uv run yt-doctor --apply --json <apply_flags>` を再実行し、ID 一致を確認する。

##### quota / auth / network 失敗

`data.reason == "api_error"` の場合は、理由にかかわらずチャンネル未作成として扱わない。doctor の `next_action.instructions` に従って次の対処を案内する。

- quota / 5xx: quota リセットまたはサービス復旧を待つ
- auth: 削除対象を表示して承認を得た後、AI が `<channel_dir>/auth/token.json` を削除して `uv run yt-oauth` を background session で起動し、stdout の同意 URL を中継する。利用者には意図したアカウントでのブラウザ認証だけを **[HUMAN STEP]** として依頼する
- network / その他一時失敗: ネットワーク接続と Google API の稼働状況を確認する

再試行条件が整った後だけ `uv run yt-doctor --apply --json <apply_flags>` を再実行する。

##### ローカル前提の不備

scope 不足の場合は、削除対象を表示して承認を得た後、AI が `<channel_dir>/auth/token.json` を削除し、`uv run yt-oauth` を background session で起動して stdout の同意 URL を中継する。利用者には **[HUMAN STEP]** でブラウザ同意だけを依頼する:

```
> [HUMAN STEP]
> OAuth token に upload 必須 scope が不足しています。再認証コマンドは setup が起動済みです。
> ブラウザの OAuth 同意画面で youtube / youtube.force-ssl scope を含むアカウントを選択してください。
> password・認可コード・token はチャットへ貼らないでください。
```

remote ID がまだ取得できていない channel_id 未設定は、AI が `uv run yt-channel-status` を起動して ID を取得し、上の「remote channel ID のローカル反映」に戻る。再認証が必要なら先に `uv run yt-oauth` の background flow を完了する。手書きで `meta.json` を更新しない。

## 運用設定インタビュー

冒頭の「完了条件」に従い、条件を満たした後、完了報告の**直前**に実行する。`/setup` の再診断時も同じ手順で現在の運用設定を確認する。

### 実行条件と共通ルール

1. `config/channel/` が存在せず `channel_config` の未生成経路に入った場合は、インタビューを実行しない。`channel_config` の手順どおり「運用設定は `/channel-new` 完了後に `/setup` を再実行して設定できます」と案内する。`/setup` は config を生成しない。
2. `config/channel/` がロード可能なら、`config/channel/workflow.json` は任意であり、未存在でもインタビューを実行する。下表の workflow 6 行は、`workflow.json` またはその入れ子のキーが未設定なら表の default を現在値として扱う。回答が現在値と異なる場合は、必要な入れ子を含む `workflow.json` を作成または更新する。
3. 下表の各行について、質問する直前に config を読んで現在値を取得する。現在値を利用者に質問してはならない。loop-video はまず `.claude/skills/loop-video/config.default.yaml` を読み、`config/skills/loop-video.yaml` が存在する場合はそれも読んで、`youtube_automation.utils.skill_config.load_skill_config("loop-video")` と同じ deep-merge（default の上に override）で `enabled` の現在値を解決する。override に `enabled` が無い場合も default の値を現在値とする。
4. 質問は必ず 1 問ずつ表示し、回答を待ってから次の行へ進む。各質問には現在値と、現在値を維持する推奨回答を添える。複数の質問をまとめて表示してはならない。
5. 回答が現在値と同じならファイルを編集しない。異なる場合だけ、その行の config を Edit で更新する。既存 `config/skills/loop-video.yaml` を更新するときは `enabled` だけを変更し、ほかの override キーを保持する。

| 順番 | config | キー | default | 質問と推奨回答 |
| --- | --- | --- | --- | --- |
| 1 | `config/channel/workflow.json` | `workflow.wf_next.skip_audio_approval` | `true` | 「音源承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 2 | `config/channel/workflow.json` | `workflow.wf_next.skip_upload_approval` | `true` | 「アップロード承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 3 | `config/channel/workflow.json` | `workflow.wf_next.skip_manual_mastering` | `false` | 「手動マスタリング検出をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持（既存のマスタリングフローを変えないため）」 |
| 4 | `config/channel/workflow.json` | `workflow.post-publish.skip_approvals.community-post` | `true` | 「コミュニティ投稿前の承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 5 | `config/channel/workflow.json` | `workflow.post-publish.skip_approvals.pinned-comment` | `true` | 「固定コメント前の承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 6 | `config/channel/workflow.json` | `workflow.post-publish.skip_approvals.metadata-audit` | `true` | 「メタデータ監査前の承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 7 | `config/skills/loop-video.yaml` | `enabled` | `true` | 「ループ動画生成を有効にしますか？ 現在値: `<current>`。Veo API の利用には課金が発生します。推奨: 現在値を維持（既存の Veo 利用方針を変えないため）」 |

`workflow.wf_next.skip_*_approval` と `workflow.post-publish.skip_approvals.*` はすべて `true = 承認省略`。`workflow.wf_next.skip_manual_mastering` を `true` にすると、最終マスター候補がなくても raw master を最終音源として採用する。

`config/skills/loop-video.yaml` が存在しない場合は、解決した現在値と異なる回答のときだけ、回答値を `enabled` に持つ override ファイルを新規作成する。現在値のままなら override ファイルを作成してはならない。

## 完了時

冒頭の「完了条件」に従い、条件を満たして「運用設定インタビュー」を終えたら:

```
✓ setup 完了。
  - automation ツールと同期済みスキルが利用できます
  - GCP / OAuth / ADC の API 認証が通ります
  - 動画アップロードに必要な OAuth scope と channel_id が揃っています
  新規チャンネルを作る場合は、次に /channel-new を実行してください。
```

を表示して終了。

## 関連スキル

- `/channel-new`: 新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding (`channel_config` fail・新規チャンネルの場合)
- `/channel-new`（既存チャンネル取り込みモード）: 既存チャンネル設定の取り込み (`channel_config` fail・既存 config ありの場合)
- `/channel-status`: OAuth token 生成とチャンネル ID 確認
- `/wf-new`: config 作成後の新規コレクション制作開始

## 上級者向け: terraform ルート

複数チャンネルを横断管理したい / 別 PC へ引っ越したい / GCP 側の drift を検出したい場合は `infra/terraform/gcp/` の README を参照。tfstate で構成管理できる代わりに `terraform.tfvars` 編集の 1 ステップが増える。

AI が tfvars を Write して `.claude/skills/channel-new/references/gcp-terraform-apply.sh --auto-approve` を Bash で叩けば自動化可能。Google Auth Platform の Branding / Audience Test users / Clients 設定と `client_secrets.json` 配置は両ルート共通。
