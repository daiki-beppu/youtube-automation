# tool

## Overview

このスキルは **AI が指揮を取るツール・API 設定 wizard** である。automation CLI 導入後は `uv run yt-doctor --apply --json` に診断と安全な `ai-exec` の連続実行を委ね、`apply.stop_reason` が示す human 操作・利用者の決定・コマンド失敗だけを対話的に解決する。

責務は「automation ツールが動き、API 認証とアップロード前提が通る状態」まで。新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding は `/setup --channel` が担当する。

利用者は GCP / OAuth に不慣れな前提。**すべてのコマンドの起動・実行・再診断は AI または setup スクリプトが担当する。** 利用者には、ブラウザ上のログイン・アカウント選択・OAuth 同意・秘密情報入力など、認証本人にしか行えない操作だけを `[HUMAN STEP]` として依頼する。

## 前提

本スキルはセットアップの起点であり、前工程スキルの成果物を要求しない。確認するのは以下のみ:

- 実行場所がチャンネル用ディレクトリであること（空フォルダ可。automation CLI の導入から「起動時のチェック」の手順で行う）
- `uv` が利用可能であること。無ければ最初の step（bootstrap カテゴリの `uv` check）でインストールを案内する
- 利用者が Google アカウントを持ち、AI / setup が起動した認証フローに対して、自分のブラウザでログイン・OAuth 同意・Google Auth Platform 設定を行えること（認証本人にしかできない `[HUMAN STEP]` として依頼する）

`config/channel/*.json` の存在は前提にしない（channel カテゴリの check が fail でも `/setup --channel` を案内するだけで `--tool` 自体は完了できる）。

### カテゴリ別チェック構成

`yt-doctor` は診断を 5 カテゴリで段階表示する:

| カテゴリ | 内容 |
|---------|------|
| `bootstrap` | ffmpeg / ffprobe / uv / pyproject.toml / automation パッケージ / `yt-skills sync` / 番号付き重複ファイル検知（7 check） |
| `api` | gcloud CLI・GCP プロジェクト・Billing・APIs・ADC・IAM・OAuth 認証・Reporting API ジョブ |
| `channel` | config/channel/ のロード可能性・playlists.json の妥当性・playlist 作成 dry-run（3 check: `channel_config` / `playlist_config` / `playlist_create_dry_run`）。fail 時は `/setup --channel` / `--import` / `--regenerate`を案内するだけ |
| `data` | `/wf-new` の入力モード判定データ + 到達可否 + 初期セットアップ事前検査（analytics_report / benchmark_data / ttp_wf_new_readiness / wf_new_readiness / initial_setup_readiness）。`ttp_mode: false` の minimal mode と benchmark fallback mode は setup のブロッカーにしない。analytics report は最新 `data/analytics_data_*.json` との相対比較に加え、`collection-ideate` の解決済み `freshness_days` を超えた絶対鮮度 stale も検出する。承認済み TTP がある場合だけ `/setup --regenerate` benchmark 反映完了を確認し、`ttp_mode: true` の minimal mode は転写元不足として警告する |
| `upload` | upload 必須 scope 充足・channel_id 設定済み（1 check） |

### 完了条件

`uv run yt-doctor --apply --json` の `apply.stop_reason` が `completed`（全 check 緑）になり、ツール、API 認証、アップロード前提が揃った状態が完了（報告文面は「完了時」セクションを参照）。例外として `analytics_report` の stale fail だけは後続スキルが自動解消するため setup のブロッカーにせず、`checks` 配列のほかの check がすべて `ok` なら `human_required` で停止しても同じ完了状態として扱う。`data` カテゴリは `/wf-new` の入力モード確認用で、stale analytics report、`ttp_mode: false` の minimal mode、benchmark fallback mode は新規チャンネル初回制作を止めない。`wf_new_readiness` が `ttp_mode: true` × minimal mode を警告した場合は転写元を準備するまで完了扱いにしない。新規チャンネル作成は次に `/setup --channel` を実行する。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API（oauth_token 手順の `uv run yt-oauth` 接続テスト） | 約 1 call | OAuth 認証の実行有無 |
| YouTube Reporting API（`uv run yt-doctor` 診断 + `uv run yt-analytics --reporting-create-job`、無料枠） | 数 call（quota 課金なし） | Reporting job の作成有無 |
| Vertex AI（Gemini / Veo / Lyria） | 0（`gcloud services enable` は API 有効化のみで生成呼び出しなし） | — |

- 上限 / 承認: plain 診断（`uv run yt-doctor --json`）と書き込み系 check（playlist_create_dry_run 等）は読み取り専用 / dry-run で、YouTube 側への変更は発生しない。`yt-doctor --apply` は別であり、ローカルの skill 同期・古い managed skill 削除と、GCP の project 選択・Billing 紐付け・API 有効化・ADC quota project・IAM 付与・Reporting job 作成を行い得る。そのため以下の承認 gate を通す。

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

project ID が解決済み、または `apply_flags` へ `--project-id` / `--billing-account` を追加・変更するたびに、次回 `--apply` が連続診断で到達し得る変更 plan を承認前に再作成する。`gcloud auth list` で active account を読み取り、正確な project ID、billing account ID（決定済みの場合）、active account と、§Steps に記載した project 選択・Billing 紐付け・API 有効化・ADC quota project・IAM 付与・Reporting job 作成のうち未解決の全コマンドを展開して表示する。

表示後、「これらは project `<project-id>` の外部 GCP 状態を変更する」と警告し、AskUserQuestion で「表示した GCP 変更を実行」/「中止」の 2 択を提示する。承認されるまで flag 付き `--apply` を実行しない。値の追加・変更は前回の承認を無効にし、必ず plan を再表示して承認を取り直す。

`/setup` は `uv run yt-setup-dirs` で `auth/`, `branding/`, `collections/`, `data/`, `docs/channel/personas/`, `docs/benchmarks/`, `research/` を冪等に作成する。`/setup --tool` では `config/channel/*.json` を生成しない。新規チャンネルの config、TTP メモ、ペルソナ、branding は `/setup --channel` の責務。

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

`yt-doctor` が FAILED / WARNING を返したら、その `check_id` に対応する節を
[references/check-runbook.md](check-runbook.md) から読む。全 check の手順を先読みしない。

収録している check id: `ffmpeg` / `uv` / `uv_project` / `automation_package` / `skills_synced` /
`numbered_duplicates` / `gcloud` / `gcloud_account` / `gcp_project` / `billing_linked` / `apis_enabled` /
`adc` / `adc_quota_project` / `iam_aiplatform_user` / `client_secrets` / `oauth_token` / `reporting_job` ほか。

## 運用設定インタビュー

冒頭の「完了条件」に従い、条件を満たした後、完了報告の**直前**に実行する。`/setup` の再診断時も同じ手順で現在の運用設定を確認する。

### 実行条件と共通ルール

1. `config/channel/` が存在せず `channel_config` の未生成経路に入った場合は、インタビューを実行しない。`channel_config` の手順どおり「運用設定は `/setup --channel` 完了後に `/setup --tool` を再実行して設定できます」と案内する。`--tool` は config を生成しない。
2. `config/channel/` がロード可能なら、`config/channel/workflow.json` は任意であり、未存在でもインタビューを実行する。下表の workflow 6 行は、`workflow.json` またはその入れ子のキーが未設定なら表の default を現在値として扱う。回答が現在値と異なる場合は、必要な入れ子を含む `workflow.json` を作成または更新する。
3. 下表の各行について、質問する直前に config を読んで現在値を取得する。現在値を利用者に質問してはならない。loop-video はまず `.claude/skills/thumbnail/config.default.yaml::loop` を読み、`config/skills/loop-video.yaml` が存在する場合はそれも読んで、`youtube_automation.configuration.skills.load_skill_config("loop-video")` と同じ deep-merge（default の上に override）で `enabled` の現在値を解決する。override に `enabled` が無い場合も default の値を現在値とする。
4. 質問は必ず 1 問ずつ表示し、回答を待ってから次の行へ進む。各質問には現在値と、現在値を維持する推奨回答を添える。複数の質問をまとめて表示してはならない。
5. 回答が現在値と同じならファイルを編集しない。異なる場合だけ、その行の config を Edit で更新する。既存 `config/skills/loop-video.yaml` を更新するときは `enabled` だけを変更し、ほかの override キーを保持する。

| 順番 | config | キー | default | 質問と推奨回答 |
| --- | --- | --- | --- | --- |
| 1 | `config/channel/workflow.json` | `workflow.wf_next.skip_audio_approval` | `true` | 「音源承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 2 | `config/channel/workflow.json` | `workflow.wf_next.skip_upload_approval` | `true` | 「アップロード承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 3 | `config/channel/workflow.json` | `workflow.wf_next.skip_manual_mastering` | `false` | 「手動マスタリング検出をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持（既存のマスタリングフローを変えないため）」 |
| 4 | `config/channel/workflow.json` | `workflow.post_publish.skip_approvals.community-post` | `true` | 「コミュニティ投稿前の承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 5 | `config/channel/workflow.json` | `workflow.post_publish.skip_approvals.pinned-comment` | `true` | 「固定コメント前の承認をスキップしますか？ 現在値: `<current>`。推奨: 現在値を維持」 |
| 6 | `config/skills/loop-video.yaml` | `enabled` | `true` | 「ループ動画生成を有効にしますか？ 現在値: `<current>`。Veo API の利用には課金が発生します。推奨: 現在値を維持（既存の Veo 利用方針を変えないため）」 |

`workflow.wf_next.skip_*_approval` と `workflow.post_publish.skip_approvals.*` はすべて `true = 承認省略`。非推奨の `metadata-audit` 承認キーは新規生成しない。`workflow.wf_next.skip_manual_mastering` を `true` にすると、最終マスター候補がなくても raw master を最終音源として採用する。

`config/skills/loop-video.yaml` が存在しない場合は、解決した現在値と異なる回答のときだけ、回答値を `enabled` に持つ override ファイルを新規作成する。現在値のままなら override ファイルを作成してはならない。

## 完了時

冒頭の「完了条件」に従い、条件を満たして「運用設定インタビュー」を終えたら:

```
✓ setup 完了。
  - automation ツールと同期済みスキルが利用できます
  - GCP / OAuth / ADC の API 認証が通ります
  - 動画アップロードに必要な OAuth scope と channel_id が揃っています
  新規チャンネルを作る場合は、次に /setup --channel を実行してください。
```

を表示して終了。

## 関連スキル

- `/setup --channel`: 新規チャンネルの TTP 対象確認、config 生成、ペルソナ、branding (`channel_config` fail・新規チャンネルの場合)
- `/setup --import` : 既存チャンネル設定の取り込み (`channel_config` fail・既存 config ありの場合)
- `/analytics --status`: OAuth token 生成とチャンネル ID 確認
- `/wf-new`: config 作成後の新規コレクション制作開始
