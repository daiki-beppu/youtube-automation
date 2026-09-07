# check id ごとの対応手順

`yt-doctor` が返した `check_id` に対応する節だけを読む。全文を通読する必要はない。
起動時の診断ループ・承認ゲート・`[HUMAN STEP]` の書き方は SKILL.md 本体を正とする。

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

> この `uv add`（および「起動時のチェック」手順 3 の同コマンド）は automation パッケージ導入 **前** に実行するため、リポジトリ参照をパッケージの `UPSTREAM_REPO` 定数から導出できずリテラル固定である。fork 運用者は owner を自 fork に読み替える。パッケージ導入後の `yt-doctor` の `next_action.cmd` は導入済みパッケージの定数から組み立てられる。

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

利用者に既存 project ID を 1 問で確認し、`--project-id <project-id>` を `apply_flags` に保持して再診断する。project 選択はマシン層の設定であり、`--apply` が後続の ADC quota project 設定とともに診断順に行う。

```bash
uv run yt-doctor --apply --json --project-id <project-id>
```

project 自体の作成・変更は GCP 層の責務として上流 `infra/terraform/gcp/` が管理する。既存 project が用意されていなければ上流 README を案内し、上流での apply 完了後に再診断する。

#### `billing_linked` — billing 未紐付け

GCP 層は上流 `infra/terraform/gcp/` が管理する。fail なら `next_action.url` の README に従って上流で plan → apply を行い、完了後に `uv run yt-doctor --json` で再診断する。

#### `apis_enabled` — 必須 API 未有効

GCP 層は上流 `infra/terraform/gcp/` が管理する。fail なら `next_action.url` の README に従って上流で plan → apply を行い、完了後に `uv run yt-doctor --json` で再診断する。

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

GCP 層は上流 `infra/terraform/gcp/` が管理する。fail なら `next_action.url` の README に従って上流で plan → apply を行い、完了後に `uv run yt-doctor --json` で再診断する。

#### `client_secrets` — OAuth クライアント秘密ファイル未配置

**[HUMAN STEP]** としてチャンネルルートで対話 session を起動し、利用者に wizard の入力とブラウザ操作を依頼する:

```bash
bash .claude/skills/setup/references/oauth-client-wizard.sh
```

Console 手順の正本はこの wizard。完了後に `uv run yt-doctor --apply --json <apply_flags>` で再診断し、`client_secrets` が `ok` であることを確認する。失敗なら wizard のエラーに従って再実行する。

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

#### `streaming_vps_state` — Terraform state 管理外の streaming VPS

`VULTR_API_KEY` または `TF_VAR_vultr_api_key` が未設定なら読み取り診断を skip する。warning では自動 import せず、`infra/terraform/streaming/README.md` の「既存 Vultr リソースの import」に従い、表示された instance ID を対応 workspace へ手動 import する。完了後に `uv run yt-doctor --json` を再実行し、同 check が `ok` になることを確認する。

### channel カテゴリ

#### `channel_config` — チャンネル設定未ロード

`yt-doctor` の `next_action.instructions` を確認:

- **`/setup --channel` 案内** (config/channel/ ディレクトリ未存在): 新規チャンネルの場合は `/setup --channel` を実行して設定を作成する。この経路では対象 config が未生成のため「運用設定インタビュー」はスキップし、「運用設定は `/setup --channel` 完了後に `/setup --tool` を再実行して設定できます」と案内する
- **`/setup --import` 案内** (ディレクトリ存在・ロード失敗): 既存チャンネルの config を持ち込む場合は `/setup --import` を実行して設定を修復する

AI は config をここで生成しない。`yt-setup-dirs` で setup 用ディレクトリが作成済みでも `config/channel/*.json` は未生成で正常な中間状態として扱う。`yt-doctor` の `message` に含まれるエラー詳細をそのまま利用者に示し、どちらのルートかを確認してから案内する。

#### `playlist_config` — `config/channel/playlists.json` の妥当性

`config/channel/playlists.json` が未存在（warn）または JSON 不正 / `playlists` 定義不備（fail）の状態。`/setup --regenerate` で `playlists.json` を修復するよう案内する。config 未生成の新規チャンネルでは `/setup --channel` 完了までの正常な中間状態として扱う。

#### `playlist_create_dry_run` — playlist 作成 dry-run

`PlaylistManager.create_all_playlists(dry_run=True)` の事前検査。`playlist_id` 未設定エントリの `title` 欠落や設定ロード失敗を検出する。`yt-doctor` の `next_action.instructions` に従い、`uv run yt-playlist-manager --init --dry-run` の結果と `playlists.json` を確認して修正を案内する。

### data カテゴリ

#### `analytics_report` — `/wf-new` 入力モード状態

検証済み `reports/analysis_*.json` が存在しないこと自体は setup のブロッカーにしない。`yt-doctor` の message に表示される入力モードは、schema検証済み JSON+HTML pair と stale の確認として扱う:

- ファイル名日付が最新の `reports/analysis_*.json` と同日付 `.html` が存在し、`.claude/skills/analytics/references/analysis-json-validator.md` の validator が exit 0 で、stale ではない → analytics mode
- 検証済み `reports/analysis_*.json` が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- 検証済み `reports/analysis_*.json` と `data/benchmark_*.json` がどちらも無い → minimal mode

Markdown があるのに同日付 JSON がない、または validator が失敗する場合は fallback せず `/analytics --analyze` 再実行を案内する。

ペアが stale の場合は、`yt-doctor` の message で stale を表示したうえで setup のブロッカーにしない。`apply.stop_reason == "human_required"` かつ `apply.check_id == "analytics_report"` でも `[HUMAN STEP]` として `/analytics --analyze` の実行を利用者へ依頼せず、後続の `/wf-new` 企画工程が同じセッションで自動更新する旨を案内する。`checks` 配列の後続 check を確認し、ほかの未完了 check があればその check の手順へ進む。

自動更新の実行順序、再検証、refresh / API 失敗時の停止・再開条件は `.claude/skills/wf-new/references/freshness-rules.md` を参照する。setup は refresh / API 失敗時の停止・再開条件は上書きしない。`/wf-new` はこの stale 判定を重ねない。

#### `benchmark_data` — ベンチマークデータ状態

benchmark の有無は analytics report の有無より優先しない:

- `yt-doctor`: fresh で検証済みの同日付 `reports/analysis_*.json` / `.html` ペアがある → benchmark の有無に関係なく analytics mode
- validator 成功済みで fresh な JSON+HTML pair がある → benchmark の有無に関係なく analytics mode
- 検証済み analysis JSON が無く、`data/benchmark_*.json` がある → benchmark fallback mode
- 検証済み analysis JSON と `data/benchmark_*.json` がどちらも無い → minimal mode

1 行目は現行 `yt-doctor` の表示上の予備判定であり、最終 Hard Gate ではない。`/wf-new` 企画工程は 2 行目のペア + validator 条件で判定する。

minimal mode / benchmark fallback mode は新規チャンネル初回制作を始めるための許容状態であり、setup の完了を止めない。

#### `ttp_wf_new_readiness` — 承認済み TTP の `/setup --regenerate` benchmark 反映状態

`benchmark.channels` に承認済み TTP 対象がある場合だけ、初回 `/wf-new` 前に `/setup --regenerate` の benchmark 反映が完了しているか確認する。`yt-doctor` の `message` に `/setup --regenerate benchmark 反映未完了` が含まれる場合は、以下を案内する:

- `/setup --regenerate` の benchmark 反映ステップ（Step R3.5）を再実行する
- `data/benchmark_*.json`、`docs/benchmarks/*.md`、`data/thumbnail_compare/benchmark/` の参照画像を揃える
- `config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default` に `data/thumbnail_compare/benchmark/...` の相対パスを転記する
- 完了後に `uv run yt-doctor --apply --json <apply_flags>` を再実行し、`ttp_wf_new_readiness` が ok になることを確認する

同じ check は最終 `persona-definition.json` + `.html` pair についても、schema・digest、`document_type=persona`、非空の人物フィールド、確度とscene参照を検証する。persona 不足は `ttp-seed-confirmation.md` のユーザー承認済み例外では抑制せず、`next_action` の `/channel-strategy --persona` に戻って解消する。

`benchmark.channels` 未設定の場合は minimal mode として扱われるため、setup の完了を止めない。

#### `wf_new_readiness` — `/wf-new` の到達可否

`/wf-new` 企画工程と同じ入力モード判定と `config/skills/collection-ideate.yaml::ttp_mode` の組み合わせを確認する。override ファイルまたは `ttp_mode` が未設定なら、同梱既定どおり `false` として扱う。`analytics mode`、`benchmark fallback mode`、または `ttp_mode: false` の `minimal mode` は、`yt-doctor` の message に表示されたモードのまま `/wf-new` を開始できる。

`ttp_mode: true` × `minimal mode` の warning は、転写元ベンチマークが無く `/wf-new` 企画工程を完了できない状態を示す。`next_action.kind == "human"` の指示を次の順に扱う:

1. 利用者と TTP 対象を決め、`config/channel/analytics.json::benchmark.channels` に保存する
2. AI が `/channel-research --benchmark` を実行して `data/benchmark_*.json` を生成する
3. AI が `uv run yt-doctor --json` を再実行し、`wf_new_readiness` が `ok` になったことを確認する

この check は `/wf-new` の到達可否だけを判定する。`benchmark_data` / `analytics_report` / `ttp_wf_new_readiness` の意味を変更せず、persona 文書の有無も停止条件に加えない。

#### `initial_setup_readiness` — 初期セットアップ事前検査

`config/skills/thumbnail.yaml` / `config/skills/music.yaml::prompt` の空欄・不備（reference_images / composition_rules の未設定、`genre_line` の文字数超過など）と、planning 中コレクションの `descriptions.json` schema / localization / quality / HTML pair 不整合、旧 `descriptions.md` の未移行を warn として一括検出する。`yt-doctor` の `next_action` に従い、開設時の初期転記は `/setup --channel`、開設後の再転記は `/setup --regenerate`、動画説明 pair の再生成・明示 migration は `/video --describe` を案内する。config 未転記の新規チャンネルでは `/setup --channel` 完了までの正常な中間状態として扱う。

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
