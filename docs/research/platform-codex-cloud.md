# Codex Cloud の適性調査（実行基盤選定の入力）

Issue: #3297（親: #3293「ADR: 実行基盤の選定」の入力）
調査日: 2026-08-07
一次情報の範囲: OpenAI 公式のみ（developers.openai.com / learn.chatgpt.com / help.openai.com / github.com/openai）。
`developers.openai.com/codex/*` は現在 `learn.chatgpt.com/docs/*` へ 308 リダイレクトされるため、出典 URL は
実際に取得した learn.chatgpt.com 側で記す（同一ドキュメントの正規パス）。公式情報で確認できなかった項目は
「不明（一次情報なし）」と明示する。

## 結論（要約）

- **AI 工程（企画・生成・PR ベースの作業）にはネイティブ適性が高い**。cloud chat はエージェント実行が前提で、
  AGENTS.md・並列実行・PR 作成・GitHub/Slack/Linear からの delegate が公式機能として揃う。
- **メディア工程（ffmpeg・9.7GB 級中間物）には現状判断材料が決定的に不足**。ディスク容量・CPU 性能・
  1 タスクの実行時間上限がいずれも非公表で、成果物の搬出経路も Git（diff / PR / branch push）以外は
  文書化されていない。
- **スケジュール実行に致命的な穴がある**。Scheduled tasks はローカル（desktop app・マシン常時起動が必要）か
  Web（ローカルフォルダ・リポジトリ環境なし）の 2 形態のみで、「Codex Cloud タスクを定期起動する」経路は
  公式ドキュメントに存在しない。既存 automation-schedule の codex-automation backend が想定する
  「マシンレス定期制作ラン」は Codex Cloud 単体では組めない。
- **secret 管理が本プロジェクトの認証設計と衝突する**。secrets は setup script のみで agent phase 開始前に
  除去される仕様のため、YouTube OAuth token を agent phase で使うには環境変数（平文相当）に置くしかない。
  1Password 連携の記載はない。
- ベンダーロックイン度は低い（AGENTS.md / bash setup script / 公開 Dockerfile）。ロックインの本体は
  「ChatGPT プラン契約」で、cloud は API キーでは使えない。

---

## 共通評価軸

### 1. 料金体系

**事実**

- Codex は ChatGPT プラン（Free / Go 含む）に含まれ、cloud chats は Plus / Pro / Business / Enterprise で
  利用可。**API キー認証では cloud 系機能（cloud chats・GitHub code review・Slack 等)は使えない**。
  出典: https://learn.chatgpt.com/docs/pricing.md（プラン別 feature matrix、API Key カード「No cloud-based features」）
- 課金は API トークン使用量に連動したクレジット制。「Usage is calculated in credits per million input
  tokens, cached input tokens, and output tokens」。レートカード（credits / 1M tokens）:
  GPT-5.6 Sol 125 / 12.5 / 750、Terra 50 / 5 / 300、Luna 5 / 0.5 / 30。「GPT-5.6 usage averages 5-40
  credits per message」。出典: 同上
- **ローカルメッセージと cloud chats は同一の 5 時間窓を共有**し、「Additional weekly limits may apply」。
  Plus のローカルメッセージ目安は Sol 10-100 / Terra 25-200 / Luna 250-2,000（5 時間あたり）、Pro は
  その 5x / 20x、Business は Plus と同等（per-seat）。出典: 同上
- 現行 pricing ページの使用回数表では **Cloud chats 列が全モデル「Not available」表記**で、cloud chat の
  公表回数レンジは読み取れない（後述の通り cloud はモデル固定のため、モデル別表に載らないとみられる）。
  出典: 同上
- 上限到達時: 進行中ターンは fair-use の範囲で完走でき、Plus / Pro はクレジット追加購入で継続可能。
  出典: https://learn.chatgpt.com/docs/pricing.md、https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- Business プランは「Larger virtual machines to run cloud chats faster」を明記。出典: https://learn.chatgpt.com/docs/pricing.md
- **cloud chats のモデルは変更不可**（「Currently, you can't change the default model for Codex cloud
  chats.」）。モデルカタログ上、Codex cloud 対応（cloud=true）は最上位の GPT-5.6 Sol のみ。
  出典: https://learn.chatgpt.com/docs/models.md

**本プロジェクトへの含意**

- cloud 実行は常にフラッグシップ単価（Sol 相当）で消費され、安価モデルへ逃がす選択肢がない。
  週次〜日次の制作ランでは、ローカルの Claude / takt 運用と同じ 5 時間窓・週次上限を cloud が食い合う。
- 消費はトークン連動で事前予測が難しく、「1 ラン=定額」の見積りが立たない。クレジット追加購入で
  頭打ちは回避できるが、従量が青天井になり得る。

### 2. 実行時間上限（1 タスクの最長実行時間）

**事実**

- **不明（一次情報なし）**。cloud docs・pricing・help center のいずれにも 1 タスクの wall-clock 上限の
  記載がない。
- 関連事実: コンテナ状態のキャッシュ保持は最大 12 時間（タスク実行時間の上限ではない）。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- 関連事実: 公式ブログは GPT-5.3-Codex が約 25 時間連続で作業した事例を紹介（実行環境が cloud か
  local かの明記なし）。出典: https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
- 関連事実: 使用上限に達しても進行中ターンは fair-use 範囲で継続できる。
  出典: https://learn.chatgpt.com/docs/pricing.md

**本プロジェクトへの含意**

- 2 時間尺エンコードのような長時間バッチを 1 タスクに載せられる保証がない。上限が非公表である以上、
  「途中で切られたときに再開できる」設計（チェックポイント + 冪等）を前提にしない限り採用判断ができない。

### 3. 一時ディスク容量と IO（9.7GB 級の中間物）

**事実**

- **不明（一次情報なし）**。コンテナのディスク容量・IO 性能はどの公式ドキュメントにも記載がない。
  cloud-environment ドキュメントは CPU / RAM / ディスクのスペックを一切示していない。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- 関連事実: Business 以上は「Larger virtual machines」とのみ記載（数値なし）。
  出典: https://learn.chatgpt.com/docs/pricing.md

**本プロジェクトへの含意**

- 9.7GB の中間物を扱えるかは実測しないと分からない。評価を進めるなら「実環境で `df` / `dd` を叩く
  検証タスクを 1 本流す」のが唯一の確認手段（ドキュメントからは回答不能）。

### 4. R2 との転送（ネットワークアクセス制約）

**事実**

- **agent phase のインターネットアクセスは既定で OFF**。「By default, Codex blocks internet access
  during the agent phase. Setup scripts still run with internet access」。環境ごとに On にでき、
  ドメイン allowlist（None / Common dependencies プリセット約 70 ドメイン / All）と許可 HTTP メソッドで
  制限できる。メソッド制限を有効にすると GET / HEAD / OPTIONS 以外（POST / PUT / PATCH / DELETE 等)が
  ブロックされる。出典: https://learn.chatgpt.com/docs/cloud/internet-access.md
- **全 outbound は HTTP/HTTPS プロキシ経由**。「Environments run behind an HTTP/HTTPS network proxy for
  security and abuse prevention purposes. All outbound internet traffic passes through this proxy.」
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- OpenAI 自身が、agent のネット許可はプロンプトインジェクション経由の code / secret 流出リスクを
  高めると明示的に警告している。出典: https://learn.chatgpt.com/docs/cloud/internet-access.md

**本プロジェクトへの含意**

- R2 への転送は「On + R2 エンドポイント（`*.r2.cloudflarestorage.com` またはカスタムドメイン）を
  allowlist + PUT/POST を許可」という構成なら仕様上ブロックされない（S3 API は HTTPS なのでプロキシ
  越しに通る余地がある）。ただし公式に文書化された成果物経路ではなく、大容量転送の帯域・安定性は不明。
- 非 HTTP(S) プロトコル（rsync / ssh 等）は使えない前提で設計する必要がある。
- R2 credential を agent phase に渡す手段が環境変数しかない（軸 7 参照）ため、ネット許可 +
  平文 credential の組み合わせは OpenAI 自身が警告する exfil リスク構成そのものになる。

### 5. CPU 性能と ffmpeg 適性

**事実**

- ベースは `universal` イメージ（ubuntu:24.04）。参照実装 openai/codex-universal の Dockerfile に
  **ffmpeg は含まれていない**（build-essential / git / rsync 等はあり）。
  出典: https://github.com/openai/codex-universal（README / Dockerfile）
- setup script で追加パッケージのインストールは可能で、setup phase は常時インターネットあり
  （`apt-get install ffmpeg` は技術的に可能）。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- CPU コア数・クロック・エンコード性能に関する公式数値は**不明（一次情報なし）**。
  Business の「Larger virtual machines」以外に手掛かりなし。出典: https://learn.chatgpt.com/docs/pricing.md

**本プロジェクトへの含意**

- ffmpeg 導入自体は setup script 1 行で解決する。問題は性能で、軽量レジーム（静止画ループ 2 時間尺で
  1〜2 分）が cloud VM で何分かかるか予測材料がゼロ。重量レジーム（エフェクト・スペクトラム）は
  実行時間上限（軸 2）・ディスク（軸 3）と併せて三重に未知数であり、実測なしに載せる判断はできない。

### 6. スケジュール実行

**事実**

- Scheduled tasks（旧 automations、`/codex/automations` → 現ドキュメント名「Scheduled tasks」）は
  2 形態のみ:
  - **desktop app**: ローカルプロジェクト or ローカル worktree で実行。「Keep the computer on and the
    app running when a scheduled task needs local files.」（マシンとアプリの常時稼働が必要）
  - **web**: 「Web tasks can use uploaded context and connected tools, but they can't work directly in
    a folder on your computer.」ローカルフォルダも worktree も保持しない。
  出典: https://learn.chatgpt.com/docs/automations.md
- **Scheduled task から Codex Cloud 環境（GitHub リポジトリ接続のクラウドコンテナ）を定期起動する経路は
  文書化されていない** → 不明（一次情報なし）。
- cloud chat の起動手段として文書化されているのは: Web UI（chatgpt.com/codex）、GitHub の `@codex`
  メンション、Linear、Slack、Codex CLI（「Start and review work from the web or Codex CLI」）。
  いずれも人間または外部イベント起点で、時刻起点のトリガはない。
  出典: https://learn.chatgpt.com/docs/cloud.md、https://learn.chatgpt.com/docs/third-party/github.md
- 代替の自動化経路として **Codex GitHub Action**（`openai/codex-action@v1`）があるが、これは GitHub
  Actions ランナー上で `codex exec` を動かすもので（API キー課金・ChatGPT プラン枠外）、Codex Cloud の
  実行環境ではない。出典: https://learn.chatgpt.com/docs/github-action.md
- Business / Enterprise の **Codex access tokens** も「trusted non-interactive **local** workflows
  (Codex CLI / app-server)」用で、cloud タスク起動用ではない。
  出典: https://learn.chatgpt.com/docs/enterprise/access-tokens.md
- scheduled task が `gpt-5.4` / `gpt-5.4-mini` を使う場合、2026-08-31 のモデル退役前に
  `gpt-5.6-terra` / `gpt-5.6-luna` へ更新が必要。出典: https://learn.chatgpt.com/docs/automations.md

**本プロジェクトへの含意**

- 既存 automation-schedule の codex-automation backend（ChatGPT desktop/web の Scheduled を使う設計）は、
  desktop 経路ではマシン常時稼働が前提になり「クラウド実行基盤」の要件を満たさない。web 経路は
  リポジトリ環境を持てない。**「マシンレスの定期制作ラン」を Codex Cloud 単体で組む公式経路は現存しない**。
- 回避策は GitHub Actions cron + `@codex` メンション（PR/issue コメント経由で cloud chat を起動）の
  ような間接トリガだが、これは公式にサポートされたパターンとして文書化されていない。

### 7. secret 管理

**事実**

- 環境変数と secrets は別物:
  - 環境変数は「set for the full duration of the chat」（setup + agent phase の全期間有効）
  - **secrets は追加の暗号化層付きで保存され「only available to setup scripts. For security reasons,
    secrets are removed before the agent phase starts.」**（agent phase 開始前に除去）
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- setup script は agent と別 bash セッションで、`export` は agent phase に持ち越されない。永続化するには
  `~/.bashrc` へ書くか環境設定で定義する（ドキュメント明記）。出典: 同上
- setup script / maintenance script / 環境変数 / secrets のいずれかを変更するとコンテナキャッシュが
  無効化される。Business / Enterprise ではキャッシュが環境の全ユーザーで共有される。出典: 同上
- **1Password 連携: 不明（一次情報なし）**。公式ドキュメントに op CLI / 1Password への言及はない。

**本プロジェクトへの含意**

- 本プロジェクトの secret 解決順（`os.environ` → `op read` → `ConfigError`）のうち `op read` 経路は
  cloud の agent phase では成立しない（ネット既定 OFF + secret は agent phase に存在しない + op の
  service account token 自体の置き場がない）。
- YouTube OAuth token のような agent phase で必要な credential は、(a) 環境変数として置く
  （agent から見えて cloud 設定 UI に残る・変更のたびにキャッシュ無効化）か、(b) refresh token を
  secret に置き setup script で access token を発行して `~/.bashrc` に書き出す、の二択。
  (b) は仕様に沿った運用だが、agent phase 中の再 refresh は不可（軸 4 のネット制限に加え
  refresh token が agent phase に存在しない）ため、長時間タスクでは token 失効に対処できない。

### 8. 環境定義の可搬性

**事実**

- 実行イメージは `universal` 固定。**カスタムベースイメージの持ち込みは文書化されていない**。
  カスタマイズ手段は (a) Set package versions（`CODEX_ENV_*` による Python / Node 等のバージョン pin）、
  (b) bash の setup script / maintenance script、(c) 環境変数・secrets、(d) AGENTS.md。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md
- 参照実装 `ghcr.io/openai/codex-universal` はローカルで pull して検証可能だが「This is not an identical
  environment」と明記。出典: https://github.com/openai/codex-universal
- 自動セットアップは npm / yarn / pnpm / pip / pipenv / poetry を認識（uv は setup script での明示
  インストールが必要。universal image 側には uv が同梱される: codex-universal README の Python 追加
  パッケージに `uv` あり）。出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md、https://github.com/openai/codex-universal

**本プロジェクトへの含意**

- 本リポジトリは devShell（`nix develop`）必須の規約だが、universal image に Nix はない。setup script で
  Nix を導入することは技術的には可能でも、コンテナ作成（キャッシュ 12h 失効）のたびに flake 評価 +
  `uv sync` を回すことになり、起動コストが重い。cloud 用には「Nix を捨てて uv 直行」の別系統
  setup script を書く必要がある。
- 既存の `.codex/environments/environment.toml` は Codex **desktop** の worktree 環境用
  （`$CODEX_WORKTREE_PATH` / `nix develop` 前提）で、cloud 環境設定（chatgpt.com/codex/settings/environments）
  とは別物。そのまま流用はできない。

### 9. AI エージェント実行適性

**事実**

- cloud chat はエージェント実行がネイティブ: コンテナ作成 → repo checkout → setup → 「The agent runs
  terminal commands in a loop. It edits code, runs checks, and tries to validate its work. If your repo
  includes `AGENTS.md`, the agent uses it to find project-specific lint and test commands.」→ diff 提示・
  PR 作成・follow-up。並列タスク実行が主要ユースケースとして設計されている。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md、https://learn.chatgpt.com/docs/cloud.md
- GitHub / Linear / Slack から delegate 可能。PR コメントの `@codex <指示>` で PR を文脈にした cloud
  chat が起動し、「can push a fix back to the branch when it has permission to do so」。
  出典: https://learn.chatgpt.com/docs/third-party/github.md
- モデルは固定（変更不可・カタログ上 cloud=true は GPT-5.6 Sol のみ）。
  出典: https://learn.chatgpt.com/docs/models.md

**本プロジェクトへの含意**

- AI 工程（企画・プロンプト生成・コード変更・PR ベースの制作準備）には適性が高い。AGENTS.md 資産が
  そのまま効く。
- 一方でメディア工程は軸 2 / 3 / 5 の三重の不確定に加え、成果物搬出が Git 系に閉じている（固有論点 a）。
  この非対称性は「AI 工程とメディア工程を分離し、メディア工程は別基盤に置く」設計を支持する
  具体的材料になる。

### 10. ベンダーロックイン度

**事実**

- 可搬資産: AGENTS.md（エージェント横断の事実上の共通慣行）、setup script（素の bash）、
  universal image（公開 Dockerfile でローカル再現可）。
  出典: https://learn.chatgpt.com/docs/environments/cloud-environment.md、https://github.com/openai/codex-universal
- 非可搬要素: 環境定義（env vars / secrets / allowlist）は ChatGPT 設定 UI 内にあり、cloud chats は
  ChatGPT アカウント / プランに紐付く。**API キーでは cloud を使えない**ため、cloud 利用は ChatGPT
  プラン契約と不可分。出典: https://learn.chatgpt.com/docs/pricing.md

**本プロジェクトへの含意**

- 撤退コストは低い。成果物は Git 経由で残り、setup script と AGENTS.md は他基盤（GitHub Actions、
  他社エージェント実行環境）へほぼそのまま持ち出せる。ロックインの実体は「ChatGPT プランの契約と
  usage 枠」であり、コード資産ではない。

---

## この基盤に固有の論点

### a. git push / PR 作成以外の成果物搬出手段

- 公式に文書化された搬出経路は (1) diff の提示、(2) PR 作成、(3) GitHub 統合経由での branch への
  push back、の Git 系のみ。コンテナからのファイルダウンロードや artifact ストレージのような搬出機構は
  cloud ドキュメントに存在しない。
  出典: https://learn.chatgpt.com/docs/cloud.md、https://learn.chatgpt.com/docs/third-party/github.md
- R2 への直接 push は、agent internet access を On にして R2 ドメインを allowlist し PUT/POST を許可すれば
  仕様上はブロックされない（軸 4）。ただし文書化されたパターンではなく、credential は環境変数経由に
  ならざるを得ず（軸 7）、9.7GB 級のプロキシ経由転送の実用性は不明（一次情報なし）。
- 含意: 動画バイナリを Git に載せる運用は非現実的なので、**メディア成果物の搬出はこの基盤の
  文書化された機能の外側**にある。

### b. 有効期限つき credential（YouTube OAuth token）の扱い

- secrets が agent phase 前に除去される仕様（軸 7）により、有効期限つき token の正攻法は
  「setup script で secret（refresh token）から短命 access token を発行し `~/.bashrc` に書く」構成。
  agent phase 中の再 refresh は既定構成では不可能（ネット OFF + refresh token 不在）。
- YouTube API を agent phase から叩くには internet access On + `googleapis.com` 等の allowlist +
  POST 許可が必須（既定 OFF のままでは API 呼び出し自体ができない）。
- 含意: 「トークン失効までに終わる長さのタスク」しか安全に組めず、実行時間上限が不明（軸 2）なことと
  併せて、アップロード工程を cloud に置く設計は成立が危うい。

### c. リポジトリ既存の Codex 統合資産との整合

- `AGENTS.md`: cloud でもそのまま有効（cloud の agent が AGENTS.md を参照する仕様。軸 9）。
  最も再利用価値が高い資産。
- `.codex/environments/environment.toml`: Codex **desktop** worktree 用（`$CODEX_WORKTREE_PATH` /
  `nix develop` / ブランチ自動作成）。cloud の環境設定は chatgpt.com 側 UI で別管理であり、この
  ファイルは cloud には効かない。
- `.worktreeinclude`: Codex デスクトップの worktree チャット用の仕組みで、本リポジトリには現状
  未設置。cloud は毎回 fresh clone + setup script のため `.worktreeinclude` に相当する概念がなく、
  gitignore 済み設定ファイル（`.env` / `auth/token.json` 等）は env vars / secrets / setup script で
  再構成する必要がある。
- automation-schedule の `codex-automation` backend: ChatGPT の Scheduled tasks を使う設計だが、
  軸 6 の通り Scheduled tasks から cloud 環境への定期起動経路は文書化されておらず、desktop 経路は
  マシン常時稼働が前提。**この backend は「ローカル併用の自動化」としては整合するが、
  「クラウド実行基盤」の代替にはならない**。

---

## 出典一覧（すべて 2026-08-07 取得）

| 出典 | URL |
|---|---|
| Codex cloud（概要・起動手段・搬出） | https://learn.chatgpt.com/docs/cloud （= developers.openai.com/codex/cloud） |
| Cloud environments（setup / secrets / cache / proxy） | https://learn.chatgpt.com/docs/environments/cloud-environment |
| Agent internet access（既定 OFF / allowlist / メソッド制限） | https://learn.chatgpt.com/docs/cloud/internet-access |
| Pricing（プラン・credits・5h 窓・feature matrix） | https://learn.chatgpt.com/docs/pricing |
| Models（cloud 対応モデル・cloud はモデル変更不可） | https://learn.chatgpt.com/docs/models |
| Scheduled tasks（desktop/web の制約・モデル退役） | https://learn.chatgpt.com/docs/automations |
| GitHub 統合（@codex delegate / branch push back） | https://learn.chatgpt.com/docs/third-party/github |
| Codex GitHub Action（GH ランナーでの codex exec） | https://learn.chatgpt.com/docs/github-action |
| Access tokens（Business/Enterprise の local 自動化用） | https://learn.chatgpt.com/docs/enterprise/access-tokens |
| Workspace model availability（cloud のモデル境界） | https://learn.chatgpt.com/docs/enterprise/workspace-model-availability |
| codex-universal（Dockerfile: ubuntu 24.04・ffmpeg 非同梱） | https://github.com/openai/codex-universal |
| Using Codex with your ChatGPT plan（プラン・データ管理） | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan |
| Run long horizon tasks with Codex（25 時間連続実行の事例） | https://developers.openai.com/blog/run-long-horizon-tasks-with-codex |

### 「不明（一次情報なし）」の項目一覧

- 1 タスクの最長実行時間（wall-clock 上限）
- コンテナの一時ディスク容量・IO 性能
- CPU コア数・RAM・エンコード性能（Business の「Larger virtual machines」以外に記載なし）
- cloud chat の公表使用回数レンジ（pricing 表では全モデル「Not available」表記）
- Scheduled tasks から Codex Cloud タスクを定期起動できるか
- 1Password（op CLI）連携
- カスタムベースイメージの持ち込み可否（文書化なし = 現状不可とみるのが妥当）
- 9.7GB 級ファイルのプロキシ経由転送の実用性
