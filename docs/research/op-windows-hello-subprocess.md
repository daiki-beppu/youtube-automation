# Windows Hello 統合と subprocess 経由の 1Password CLI 呼び出しの調査

- 調査日: 2026-09-15
- 対象 ticket: #5153（map: #5151）
- 対象: `subprocess.run(["op", "read", ...])`（`src/youtube_automation/infrastructure/secrets.py`）が Windows の 1Password デスクトップアプリ統合（Windows Hello）で通るかと、その周辺仕様
- 一次資料の範囲: www.1password.dev（旧 developer.1password.com はここへ 301 リダイレクト）、support.1password.com、app-updates.agilebits.com（1Password 公式リリースノート）、releases.1password.com、1password.com。community forum は一次資料として扱わず、リードのみ「未確認事項」に記載する
- 未実施: `op` コマンドの実行（Touch ID プロンプトを避けるため）、Windows / Linux 実機での検証
- 実装形の決定は本 ticket では行わない（仕様化 ticket へ渡す）

## 要約

| # | 問い | 結論 | 確度 |
|---|---|---|---|
| 1 | Windows で Python の `subprocess.run(["op", ...])` から Windows Hello 統合が通るか | **公式に「通る / 通らない」の記載は無い**。公式が明記するのは (a) Windows の対応シェルは PowerShell のみ、(b) Windows では sub-shell で実行したコマンドは別途認可が必要、(c) Windows の session credential は「`op` を起動したプロセスの PID + 開始時刻」で識別される、の 3 点。この 3 点から、Python プロセスが `op` を直接起動する場合、認可は **その Python プロセス（PID）に紐づく** と読める（推論）。Windows Terminal / VS Code 統合ターミナル / cmd の差は **未記載** | 公式記載: 高 / 推論部分: 中 |
| 2 | macOS / Linux の「terminal session」は何で識別されるか | **現在の tty + 開始時刻** に基づく ID（公式明記）。「sub-shell processes in that window」まで認可が及ぶ。**TTY を持たない子プロセス**（Claude Code の Bash など）の扱いは **未記載** | 高 / TTY 無しは未記載 |
| 3 | Windows Hello 統合の最低 CLI / アプリバージョン | CLI 側: biometric unlock は **CLI 2.0.0（2022-03-10）で正式導入**、「biometric unlock requires 1Password 8」。Windows 固有: **CLI 2.31.1（2025-05-28）** が Windows の統合を修復し「最新の 1Password for Windows」を要求、beta 時点の記載は **1Password for Windows 8.10.78+**。アプリ側: 8.10.28 で「Biometrics are no longer required to turn on integration with 1Password CLI」。公式ドキュメント本文には「最低バージョン」の明示は無く、リリースノートからの復元 | 中 |
| 4 | Linux（PolKit）で GUI エージェント無し（SSH セッション）の挙動 | 要件として「**A PolKit authentication agent running**」（アプリ統合に必須）と明記。エージェント無しでどう失敗するかの記述は **未記載**。公式は「非対話 shell の remote 環境では service account または Connect server で認証せよ」と案内 | 要件: 高 / 挙動: 未記載 |
| 5 | Individual プランで service account を作れるか | **プラン別の可否は明文化されていない**が、rate limit ページが「1Password（= Individual）、1Password Families、1Password Teams」の枠を定義し、1password.com の FAQ も「Individual or Family」tier の rate limit に言及。1Password Developer は「every plan including Individual」に含まれると FAQ に記載。作成要件は「Sign up for 1Password」+「adequate account permissions」のみ | 中（間接的な記載のみ） |

## 1. Windows: subprocess から Windows Hello 統合が通るか

### 公式に記載されていること

1. **対応シェルは PowerShell のみ**。Get started の Requirements（Windows タブ）は「1Password subscription / 1Password for Windows / Supported shells: PowerShell」。macOS / Linux は「Bash, Zsh, sh, fish」。
   - https://www.1password.dev/cli/get-started/#step-1-install-1password-cli
2. **sub-shell は別途認可**。Authorization model:
   > Each time you use a 1Password CLI command in a new terminal window or tab, you'll need to authorize your account again:
   > - On macOS and Linux, authorization is confined to a terminal session but extends to sub-shell processes in that window.
   > - On Windows, commands executed in a sub-shell require separate authorization.
   - https://www.1password.dev/cli/app-integration-security/#authorization-model
3. **Windows の session credential は PID ベース**。Technical design > Session credentials（Windows タブ）:
   > The session credential for Windows is an ID that's based on the PID of the process that invokes 1Password CLI, plus the start time. This way every session credential is unique, even after an ID gets reused.
   - https://www.1password.dev/cli/app-integration-security/#session-credentials
4. **認可プロンプトには「認可対象のプロセス」が表示される**。
   > The user is shown a prompt containing the 1Password account display name (...) and the process being authorized (for example, iTerm2 or Terminal).
   - https://www.1password.dev/cli/app-integration-security/#security-model
5. **Windows の IPC は named pipe + Authenticode 署名検証**（`op` 実行ファイルの署名をアプリが検証、逆も同様）。呼び出し元シェルの種別を検証するとは書かれていない。
   - https://www.1password.dev/cli/app-integration-security/#how-does-1password-cli-communicate-with-the-1password-app
6. **Windows Hello 無しでは biometrics は使えない**。
   > On Windows, Windows Hello is used to spawn a prompt (...). Without Windows Hello, biometrics cannot be used with 1Password CLI.
   - https://www.1password.dev/cli/app-integration-security/#authorization-prompts
7. **統合の有効化手順**（Windows）: アプリで Windows Hello を有効化 → Settings > Developer > Integrate with 1Password CLI。
   - https://www.1password.dev/cli/app-integration/#step-1-turn-on-the-app-integration
8. **`OP_BIOMETRIC_UNLOCK_ENABLED`** は「アプリ統合を一時的に on / off する」環境変数（`true` / `false`）。PowerShell の設定例も掲載。子プロセスに継承させるかどうか等の説明は無い。
   - https://www.1password.dev/cli/app-integration/#optional-set-the-biometric-unlock-environment-variable
   - https://www.1password.dev/cli/environment-variables/
9. **セッション寿命**: 10 分の無操作で失効、ハードリミット 12 時間、使用のたびに更新。アプリがロックされると全認可が失効。認可失効時に実行中のプロセスはタスクを完了して終了できる。
   - https://www.1password.dev/cli/app-integration-security/#security-model
10. **`op signin` は冪等**で、未認証のときだけプロンプトを出す。`--session token` フラグは「app integration が無効のときに `op signin` が出力する session token」用。
    - https://www.1password.dev/cli/reference/commands/signin/
    - https://www.1password.dev/cli/reference/#global-flags
11. **非対話 shell の案内**: 「For non-interactive shells in local environments, sign in with the 1Password desktop app integration instead. For non-interactive shells in remote environments, authenticate with a service account or a Connect server.」（Sign in manually）。
    - https://www.1password.dev/cli/sign-in-manually/#step-1-add-an-account

### 公式記載から読める含意（推論。実測未了）

- Windows の認可単位は「`op` を起動したプロセス（PID）」なので、**Python が `subprocess.run(["op", ...])` を直接呼ぶ構成では、認可は Python プロセスに紐づく**と読める。同一 Python プロセス内で複数回 `op read` を呼ぶなら初回だけプロンプト（10 分無操作で失効）、Python プロセスを起動し直すたびに再プロンプトになる、と解釈するのが自然。ただし「invokes」が直接の親プロセスを指すのか、プロセスツリーを辿るのかは公式に書かれていない。
- 「PowerShell のみ対応」が「PowerShell 以外から起動した `op` は統合を拒否する」ことを意味するのか、「動作保証・ドキュメントの対象が PowerShell」という意味なのかは **未記載**。IPC の説明（Authenticode 署名検証）には呼び出し元シェルの検査は現れない。
- **PowerShell 経由のラッパ**（`powershell -Command op read ...`）にすると、`op` を起動するプロセスは毎回新しい PowerShell（新 PID）になるため、PID ベース識別の記載どおりなら**毎回別認可**になりうる。「sub-shell は別途認可」の記載はこの構成に不利に働く可能性がある。
- **`OP_BIOMETRIC_UNLOCK_ENABLED=false`** で統合を切っても、代替となる手動 sign-in は「アプリ統合を有効にしたままでは `op account add` できない」（Sign in manually の記載）、かつ「any process running under the current user can, on some platforms, potentially access your 1Password account」と公式が非推奨にしている。
- **Windows Terminal / VS Code 統合ターミナル / cmd の差**は公式に **未記載**。session credential が PID ベースである以上、ターミナルエミュレータの種類ではなく「`op` を起動したプロセス」で決まると読めるが、実測未了。
- **Windows はキャッシュ非対応**（`--cache` は「Caching is not available on Windows」）。呼び出し回数が macOS より API リクエストに直結する。
  - https://www.1password.dev/cli/reference/#global-flags

## 2. macOS / Linux の「terminal session」の識別子

### 公式に記載されていること

- Technical design > Session credentials:
  > The session credential for macOS is an ID that's based on the current tty, plus the start time.
  > The session credential for Linux is an ID that's based on the current tty, plus the start time.
  - https://www.1password.dev/cli/app-integration-security/#session-credentials
- 目的は「granted authorization を単一のターミナルに限定する」こと。別ウィンドウで別アカウントを使うには再承認が要る。
- 「authorization is confined to a terminal session but extends to sub-shell processes in that window」（同 Authorization model）。
- macOS の IPC は NSXPCConnection（1Password Browser Helper が relay）、Linux は Unix socket + `onepassword-cli` グループの set-gid ビットで `op` の真正性を検証。
  - https://www.1password.dev/cli/app-integration-security/#how-does-1password-cli-communicate-with-the-1password-app

### 未記載・推論

- 識別子は **TTY**（親 PID ではない）。同じ TTY に属する sub-shell が同じ認可を共有するのはこの設計の帰結。
- **TTY を持たない子プロセス**（Claude Code の Bash ツール、cron、`subprocess.run` を stdin/stdout をパイプにして呼ぶ場合など）で「current tty」が何になるか、認可が親のターミナルに紐づくのか、独立したセッションとして毎回プロンプトになるのかは **公式に未記載**。
- CLI 2.5.1（2022-06-22）のリリースノートに「Using biometric unlock on macOS should no longer return the error "connecting to desktop app: determining parent process of" in some rare cases. {2544}」とあり、macOS 実装が親プロセスの特定も行っていることが示唆されるが、これは session credential の説明とは別のもの（アプリ側プロンプトの「認可対象プロセス名」の特定と読める）で、識別子が親 PID だとは言えない。
  - https://app-updates.agilebits.com/product_history/CLI2 （2.5.1 の Fixed 節）
- Sign in manually ページの「For non-interactive shells in local environments, sign in with the 1Password desktop app integration instead」は、非対話 shell でもアプリ統合が使える前提を示すが、TTY 無しでの認可の共有単位は説明していない。

## 3. Windows Hello 統合の最低 CLI / アプリバージョン

公式ドキュメント本文（Get started / App integration）には「最低バージョン」の数値は無く、「1Password for Windows」「Make sure you're using the latest version of the 1Password desktop app」とだけある。数値はリリースノートからの復元:

| 出典 | 内容 |
|---|---|
| CLI 2.0.0-beta.11（2022-01-26） | 「This release introduces Biometric Unlock; If you have the latest nightly build of the 1Password 8 installed, you can now use it to sign in to the CLI using biometrics.」 |
| CLI 2.0.0-beta.14（2022-03-04） | 「`op account add` help text now notes that biometric unlock requires 1Password 8. {2099}」「Biometric unlock now can now be manually enabled or disabled by setting OP_BIOMETRIC_UNLOCK respectively "true" or "false". {2035}」（当時の変数名は `OP_BIOMETRIC_UNLOCK`。現行ドキュメントは `OP_BIOMETRIC_UNLOCK_ENABLED`） |
| CLI 2.0.0（2022-03-10） | 「Biometric Unlock can now be used instead of typing your account password on the command line. {1943}」 |
| CLI 2.7.0-beta.03（2022-08-10） | 「fixes a bug (...) in which Windows and Linux users could not use biometric authentication to sign in.」 |
| CLI 2.31.1-beta.01（2025-05-21） | 「This release fixes the 1Password CLI integration with the desktop application on Windows operating systems. To use the desktop app integration, you must be on 1Password for Windows nightly or beta (8.10.78+).」 |
| CLI 2.31.1（2025-05-28） | 「This release fixes the 1Password CLI integration with the desktop application on Windows. To use the desktop app integration, download the latest version of 1Password for Windows.」「The 1Password app integration with 1Password CLI now works again on Windows. {4325}」 |
| 1Password for Windows 8.10.18 | 「We've redesigned the authorization prompts for the 1Password command-line tool.」 |
| 1Password for Windows 8.10.28 | 「Biometrics are no longer required to turn on integration with 1Password CLI.」 |
| 1Password for Windows 8.10.35 | 「We've addressed an issue in how 1Password for Windows validates incoming connections from browsers and the 1Password CLI. Credits to Secfault Security.」 |
| 1Password for Windows 8.12.2 | 「We've added a new developer setting to enable SDK integrations, so you can authenticate SDKs with authorization prompts from the 1Password desktop app.」（CLI ではなく SDK 向け） |
| 1Password for Windows 8.12.36 | 「We've fixed an issue where system authentication prompts, like for 1Password CLI or the SSH agent, wouldn't always display if all of your 1Password accounts were unlocked.」 |

- https://app-updates.agilebits.com/product_history/CLI2
- https://releases.1password.com/windows/8.10/ （1Password for Windows のリリースノート一覧。上記のアプリ版数は同ページの見出しから取得。リリース日は版数見出しと分離して表示されるため本表では省略）

現実的な下限は **CLI 2.31.1 以上 + 2025-05 時点で最新の 1Password for Windows（beta 表記では 8.10.78+）** と読めるが、「最低」として公式が宣言した値ではない。CLI の最新安定版は 2.39.0（2026-08-14）。

## 4. Linux（PolKit）で GUI エージェント無し（SSH セッション）の挙動

### 公式に記載されていること

- アプリ統合の要件（Linux）: 「1Password for Linux*」「PolKit*」「A PolKit authentication agent running*」。アスタリスクの注記は「Required to integrate 1Password CLI with the 1Password app.」
  - https://www.1password.dev/cli/get-started/#step-1-install-1password-cli
  - https://www.1password.dev/cli/app-integration/#requirements
- 認可プロンプト: 「On Linux, PolKit is used to spawn a prompt that includes an authentication challenge for the user (commonly fingerprint or the user's OS password).」
  - https://www.1password.dev/cli/app-integration-security/#authorization-prompts
- アプリのシステム認証は polkit + PAM に委譲。polkit action は `/usr/share/polkit-1/actions/com.1password.1Password.policy`、PAM 設定は `/etc/pam.d/polkit-1` または `/etc/pam.conf`。
  - https://support.1password.com/system-authentication-linux-security/
- 非対話 shell の remote 環境は service account / Connect server を使うよう案内（Sign in manually）。Get started も「We recommend using service accounts for shared building, automated access, and headless server authentication.」
  - https://www.1password.dev/cli/sign-in-manually/#step-1-add-an-account
  - https://www.1password.dev/cli/get-started/#step-2-turn-on-the-1password-desktop-app-integration

### 未記載

- PolKit 認証エージェントが無いセッション（SSH ログイン、GUI セッション外）で `op` がどのエラーで失敗するか、フォールバック（アカウントパスワード入力等）があるかは **公式ドキュメントに記載無し**。
- SSH 先に GUI セッションが並行して存在する場合にプロンプトがそちらへ出るかどうかも未記載。

## 5. Individual プランでの service account 作成可否

### 公式に記載されていること

- 作成要件は「Sign up for 1Password.」「Have adequate account permissions to create service accounts.」のみで、プラン制限の記載は無い。「If you don't see the option to create service accounts, ask your administrator」。
  - https://www.1password.dev/service-accounts/get-started/#requirements
- 「Included with 1Password subscription: Yes」（Secrets Automation の比較表）。
  - https://www.1password.dev/secrets-automation/#comparison
- Rate limit はアカウント種別ごとに定義され、**「1Password, 1Password Families, and 1Password Teams」**の枠がある（hourly: Read 1,000 / Write 100 per token。daily: 「1Password and 1Password Families」は Read/Write 1,000 per 1Password account、Teams は 5,000、Business は 50,000）。ここでの「1Password」は Families / Teams / Business と並置されており、Individual を指すと読める。
  - https://www.1password.dev/service-accounts/rate-limits/
- 1password.com Developer ページ FAQ: 「Yes, 1Password Developer is part of every plan including Individual, Family, Teams, Business, and Enterprise.」「1Password Service Accounts of hourly and daily rate limits that vary by tier (Individual or Family, Teams, and Business).」
  - https://1password.com/developer-security
- Personal pricing の Individual の比較表に「1Password Developer（SSH workflows, Git commit signing, and CLI & SDKs）」が含まれる。service account の語は無い。
  - https://1password.com/pricing/personal
- Manage service accounts の「Manage who can create service accounts」は Teams / Business の権限管理だけを扱う（Individual / Families の記述は無い）。
  - https://www.1password.dev/service-accounts/manage-service-accounts/#manage-who-can-create-service-accounts
- service account の制約: built-in Personal / Private / Employee vault と default Shared vault にはアクセス権を付与できない。CLI 2.18.0 以上が必要。権限・vault は作成後に変更不可。
  - https://www.1password.dev/service-accounts/get-started/#limitations

### 判定

「Individual プランで service account を作成できる」と直接明言した一次資料は **無い**。ただし rate limit 表と 1password.com FAQ が Individual（「1Password」/「Individual」tier）向けの枠を定義しているため、間接的には利用可能と読める。確定は実アカウントでの作成ウィザード（https://start.1password.com/developer-tools/infrastructure-secrets/serviceaccount/）の表示で行う必要がある（本調査では未実施）。
なお Individual アカウントの既定 vault は Private であり、service account は Private vault にアクセスできないため、**専用 vault を新設してシークレットを移す前提**になる。

## 根拠 URL 一覧

| 内容 | URL |
|---|---|
| アプリ統合の手順・要件・`OP_BIOMETRIC_UNLOCK_ENABLED`・トラブルシュート | https://www.1password.dev/cli/app-integration/ |
| セキュリティモデル・認可モデル・session credential・IPC・プロンプト | https://www.1password.dev/cli/app-integration-security/ |
| Get started（対応シェル、要件のアスタリスク注記、service account 推奨） | https://www.1password.dev/cli/get-started/ |
| 環境変数一覧 | https://www.1password.dev/cli/environment-variables/ |
| CLI リファレンス（global flags: `--session`, `--cache`） | https://www.1password.dev/cli/reference/ |
| `op signin` | https://www.1password.dev/cli/reference/commands/signin/ |
| 手動 sign-in（非対話 shell の案内、既知リスク） | https://www.1password.dev/cli/sign-in-manually/ |
| CLI リリースノート（2.0.0 / 2.5.1 / 2.7.0-beta.03 / 2.31.1） | https://app-updates.agilebits.com/product_history/CLI2 |
| 1Password for Windows 8.10.x リリースノート（8.10.28 の CLI 統合変更） | https://releases.1password.com/windows/8.10/ |
| Windows Hello の設定（アプリ側） | https://support.1password.com/windows-hello/ |
| Windows Hello のセキュリティ | https://support.1password.com/windows-hello-security/ |
| Linux システム認証の設定 | https://support.1password.com/system-authentication-linux/ |
| Linux システム認証のセキュリティ（polkit / PAM） | https://support.1password.com/system-authentication-linux-security/ |
| Service account 概要 | https://www.1password.dev/service-accounts/ |
| Service account Get started（要件・制約） | https://www.1password.dev/service-accounts/get-started/ |
| Service account の管理（作成権限） | https://www.1password.dev/service-accounts/manage-service-accounts/ |
| Service account の rate limit（アカウント種別） | https://www.1password.dev/service-accounts/rate-limits/ |
| CLI で service account を使う | https://www.1password.dev/service-accounts/use-with-1password-cli/ |
| Secrets Automation 比較表 | https://www.1password.dev/secrets-automation/ |
| 1Password Developer FAQ（プラン包含・tier 別 rate limit） | https://1password.com/developer-security |
| Personal pricing（Individual に 1Password Developer が含まれる） | https://1password.com/pricing/personal |

## 未確認事項

1. **Windows で Python 直接起動の `op` が統合を通るか**（公式は未記載。「PowerShell のみ対応」が拒否を意味するのか保証範囲を意味するのか不明）。実機検証が必要。
2. **Windows の「PID of the process that invokes 1Password CLI」が直接の親か、プロセスツリーのどこかか**。同一 Python プロセスからの連続呼び出しで認可が共有されるかは実測未了。
3. **Windows Terminal / VS Code 統合ターミナル / cmd / PowerShell 7 と Windows PowerShell 5.1 の差**（公式未記載）。
4. **macOS / Linux で TTY を持たない子プロセス**（Claude Code の Bash、cron、パイプ接続の `subprocess`）における認可の共有単位（公式未記載）。
5. **Linux で PolKit 認証エージェント無し（SSH セッション）のときの具体的エラーとフォールバック**（公式未記載）。
6. **Windows Hello 統合の「最低」バージョンの公式宣言**（無し。リリースノートからの復元値のみ）。1Password for Windows の 8.10.78 以降で CLI 統合に関する追加変更が無いかは 8.10 系ページしか確認しておらず、8.11 / 8.12 系の個別ノートは未走査。
7. **Individual プランでの service account 作成の直接的な明文**（無し。rate limit 表と FAQ の間接記載のみ）。実アカウントのウィザード表示で確定する必要がある。
8. **`OP_BIOMETRIC_UNLOCK_ENABLED=false` 時の Windows での挙動**（手動 sign-in にフォールバックするか、`op account add` が必要か）。手動 sign-in は公式が非推奨。
9. community forum に関連スレッドがある（例: 「CLI Integration Requires Windows Hello」「Windows CLI session」「Is it possible for 1Password CLI running on WSL to connect with 1Password hosted on Windows?」「How do I use the SSH agent in headless Linux?」など、いずれも https://www.1password.community/ 配下）。一次資料ではないため本調査の根拠にはしていない。WSL から Windows 側アプリへの接続は公式ドキュメントに記載が無い。
