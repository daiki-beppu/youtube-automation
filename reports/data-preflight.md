# 実装前 preflight 設計調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象: `/Users/mba/02-yt/00-automation`
- 前提データ: `/Users/mba/02-yt/00-automation/reports/data-environment-parity.md`
- 性格: 設計案のみ。コード、workflow、CI、設定は変更していない。

## 調査項目ごとの結果と詳細

### 1. preflight の目的と実行位置

実装stepの最初、tracked fileを変更する前に一度実行する。実装後の lint/test/build とは分離する。

```text
TAKT worker作成
  -> runtime.prepare
  -> environment-parity-preflight（本設計）
       -> READY: implementへ
       -> RETRYABLE_ENV: bounded retry / 待機
       -> REPAIR_REQUIRED: 修復案を保存して停止
       -> AUTH_OR_USER_ACTION: user-owned sessionへhandoff
       -> POLICY_BLOCK: 権限拡張なしで停止
  -> implement
  -> local validation
  -> Supervisor quality review
  -> workflow成功後 commit/push/PR/CI
```

重要な比較規則:

- **base/controlでも同じ失敗**: environment / baseline infrastructure。Supervisor REJECTにしない。
- **baseは成功しheadだけ失敗**: change-induced regression。Supervisor品質REJECT対象。
- **外部状態で結果が変わる**（network、rate、expired auth、port、profile attach）: environment/external classification。
- **tracked config自体が壊れて全環境で再現**: task scope内で変更したなら品質defect、着手前からならbaseline blockerとして別issue候補。

根拠:

- `/Users/mba/02-yt/00-automation/.takt/config.yaml`
- `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh`
- `/Users/mba/02-yt/00-automation/docs/development.md`
- `/Users/mba/02-yt/00-automation/reports/data-workflow-transitions.md`

### 2. exit 分類契約

単一exit codeだけで詳細を失わないよう、stdoutは秘密を含まないJSON 1件、stderrはsanitize済み人間向け要約とする。

```json
{
  "schema_version": 1,
  "status": "blocked",
  "classification": "ENV_DEPENDENCY_SYNC",
  "exit_code": 22,
  "retryable": true,
  "owner": "environment",
  "check_id": "python.uv_sync_frozen",
  "repair": "network/cacheを確認し同一commandを再実行",
  "evidence": {"command": "<sanitized>", "exit": 1}
}
```

| exit | classification | 意味 | retry | Supervisorへ |
|---:|---|---|---|---|
| 0 | `READY` | 全必須検査OK | 不要 | 実装後のみ進む |
| 20 | `ENV_TOOL_MISSING` | nix/direnv/uv/git等が無い | 修復後可 | 渡さない |
| 21 | `ENV_VERSION_MISMATCH` | Nix/lock契約外のtoolを使用 | 正規入口へ切替後可 | 渡さない |
| 22 | `ENV_DEPENDENCY_SYNC` | lock/sync/cache/network失敗 | transientのみ最大2回 | 渡さない |
| 23 | `ENV_WORKTREE_INIT` | runtime dir、direnv、Nix eval、permission | 修復後可 | 渡さない |
| 24 | `ENV_GIT_IDENTITY` | author/committer identity不在 | config bridge後可 | 渡さない |
| 25 | `ENV_EXTERNAL_TRANSIENT` | DNS、HTTP 429/5xx、service outage | backoff付き可 | 渡さない |
| 30 | `AUTH_MISSING` | OAuth/ADC/op/gh credential不在・失効 | user再認証後可 | 渡さない |
| 31 | `USER_ACTION_REQUIRED` | login/CAPTCHA/consent/payment/legal確認 | 自動retry不可 | 渡さない |
| 32 | `BROWSER_SESSION_CONFLICT` | DevTools/debugger/profile/port競合 | session修復後可 | 渡さない |
| 40 | `BASELINE_CONFIG_INVALID` | 着手前のtracked config/lock破損 | 自動retry不可 | blocker、品質REJECTにしない |
| 41 | `POLICY_OR_PERMISSION_BLOCK` | sandbox権限、許可外external mutation | authority取得まで不可 | 渡さない |
| 50 | `CHANGE_REGRESSION` | base成功/head失敗 | code修正後 | 品質REJECT対象 |
| 70 | `PREFLIGHT_INTERNAL_ERROR` | classifier自身のbug/schema破損 | 1回のみ再実行 | infrastructure failure |
| 130 | `USER_INTERRUPT` | SIGINT/user cancel | user指示まで不可 | REJECTにしない |

retryは同一入力の再実行で意味があるものだけに限定する。missing binary、version mismatch、auth missing、baseline invalidを無条件retryしてtokenと時間を消費しない。

### 3. 実装前の検査表

| check id | 検査 | 対象ファイル/状態 | 成功条件 | failure class | retry | 修復案 |
|---|---|---|---|---|---|---|
| `repo.checkout` | Git checkoutとbranch/worktree識別 | `.git`, `CLAUDE.md` | worktree内、root解決可 | 23 | 修復後 | 正しいTAKT worktreeを再作成 |
| `repo.dirty_scope` | 既存変更を記録 | `git status --porcelain=v2` | 情報取得可。dirty自体は失敗でない | 23 | 可 | permission/lock修復。index状態を成果物欠落扱いしない |
| `runtime.paths` | TAKT runtime dirsがworktree内 | `.takt/config.yaml`, runtime env | XDG/TMPDIRが許可root内 | 23/41 | 修復後 | runtime.prepare再実行、sandbox policy確認 |
| `tool.nix` | Nix存在・flake eval | `flake.nix`, `flake.lock` | eval成功、locked rev一致 | 20/22/40 | 条件付 | cache/network修復。lock破損はbaseline blocker |
| `tool.entrypoint` | ambientでなく正規shell使用 | resolved PATH/version | Python 3.11、Node24、pnpm11.12 | 21 | 可 | setup wrapper / extensions shellへ切替 |
| `python.lock` | lock整合 | `pyproject.toml`, `uv.lock` | `uv lock --check` exit0 | 22/40 | 条件付 | lock driftならtask scopeを確認し明示更新 |
| `python.sync` | dependency可用性 | `.venv`, uv cache | explicit frozen/check sync成功 | 22 | 最大2 | network/cache確認、再sync |
| `python.smoke` | import/entrypoint | installed package | `import youtube_automation` と CLI help成功 | 22/40 | 条件付 | sync、package config修復 |
| `extension.lock` | pnpm契約 | 各package/lock/workspace | packageManager 11.12、frozen install可 | 21/22/40 | 条件付 | extensions shell、lock修復 |
| `playwright.browser` | Chromium bundle | Playwright cache | executable存在/軽量launch | 22 | 最大2 | `playwright install --with-deps chromium` |
| `hooks.policy` | 通常installかTAKT skip明示 | `lefthook.yml`, runtime flag | normal=check-install0、TAKT=explicit skip | 23/40 | 修復後 | wrapper再生成。TAKTではCI委譲を記録 |
| `git.identity` | postExecution前提 | effective Git config | author/committer ident exit0 | 24 | 修復後 | identityのみ安全にbridge。global config全体は継承しない |
| `ci.command_map` | local/CI command対応 | `.github/workflows/*.yml` | 変更scopeに必要なcommand列挙 | 40 | 不可 | workflow/config更新を別候補化 |
| `secret.presence` | 値を読まずprovider有無 | env key名、ignored files、`op`可用性 | 必要工程のproviderが1つ以上 | 30 | user後 | env/file/opのいずれかを設定 |
| `adc.status` | access token stdout破棄で認証probe | ADC/gcloud | command exit0、project解決 | 30 | user後 | login + quota project |
| `oauth.files` | path/type/mode/JSON shape | channel `auth/` | regular file、parse可、秘密非表示 | 30 | user後 | `yt-doctor` + browser consent |
| `chrome.profile` | profile/preferences/extension候補 | Chrome user data | exact ID 1件 | 32 | 修復後 | Chromeでload、重複解消、manual origin |
| `chrome.login` | target site UI状態 | user-owned Chrome tab | login済、required tab/UI有 | 31 | user後 | userがlogin/CAPTCHA/確認を完了 |
| `port.available` | 7872/7873/7874等 | listening sockets/registry | collisionなし、再利用対象はhealth OK | 32 | 可 | port分離、stale serverのみ停止 |
| `external.cli` | task別CLI | gcloud/op/gh/terraform/ffmpeg/ffprobe/jq/curl/ssh | 必要binaryとminimum version | 20/21 | 修復後 | Nix/system install、正規PATH |

秘密検査では値、token、account email、vault URIの展開結果をreportへ書かない。`print-access-token`、`op read` 等はstdout/stderrを破棄し、exitとsanitized categoryのみ保存する。

### 4. task scope別プロファイル

全taskへ全外部認証を要求すると過剰blockになるため、変更pathとissue capabilityからprofileを選ぶ。

| profile | 常時検査に追加 | 適用例 |
|---|---|---|
| `python-core` | Python lock/sync/smoke、Ruff/Pytest command map | `src/`, Python tests |
| `python-package` | isolated wheel/sdist build、artifact content inspection | `pyproject.toml`, force-include, release |
| `extensions` | Node/pnpm frozen、compile/unit/build/Playwright | `extensions/` |
| `oauth-youtube` | client/token provider、user consent capability | upload/analytics/comments |
| `vertex-ai` | gcloud/ADC/project/location | Lyria/image/Veo |
| `chrome-suno` | Suno extension/profile/login/port/debugger | suno-helper operator |
| `chrome-distrokid` | DistroKid extension/profile/login/port | distrokid helper |
| `streaming` | Terraform/op/ADC/state/ffprobe/secrets presence | infra streaming |
| `github-release` | gh auth、Git identity、tag/release policy | release workflow |

### 5. Supervisor品質REJECTとの境界

Supervisorへ渡すのは「同じ宣言済み環境でbase/controlが通り、head/changeだけが破壊した」という証拠だけ。

| 事象 | workflow結果 | 理由 |
|---|---|---|
| Nix download/DNS/429/5xx | `ENV_EXTERNAL_TRANSIENT` | code品質でない |
| binary/cache/browser未install | `ENV_TOOL_MISSING` / `ENV_DEPENDENCY_SYNC` | workflow開始前不足 |
| OAuth/ADC/op/Chrome login/CAPTCHA | `AUTH_MISSING` / `USER_ACTION_REQUIRED` | user/session ownership |
| sandboxがprofile/Homeを読めない | `POLICY_OR_PERMISSION_BLOCK` | authority境界 |
| baseとheadの両方でtest失敗 | `BASELINE_CONFIG_INVALID` または既知baseline | change defectと未確定 |
| base成功、headでlint/test/build失敗 | `CHANGE_REGRESSION` | Supervisor REJECT対象 |
| headが必要version/lock契約を壊した | `CHANGE_REGRESSION` | tracked change起因 |
| implementationがauth tokenを漏洩 | 即時quality/security REJECT | changeそのものの欠陥 |

現 TAKT 0.51.0 は `ABORT` をtask recordで十分細分類せず、環境障害と永久失敗を同じ failedへ潰し得る。根拠は `/Users/mba/02-yt/00-automation/reports/data-workflow-transitions.md`。preflight JSONはSupervisor自然言語判定へ渡す前にengine/task layerで保存し、`classification`, `retryable`, `owner`, `check_id` を失わないこと。

また workflow内Supervisorが「PR/CI green」を合格条件にしてはいけない。commit/push/PR/CIはworkflow成功後のpostExecutionで初めて到達可能であり、循環待ちになる。Supervisorはlocal readinessまで、CIはpostExecution gateとする。

### 6. 認証済み共有Chrome sessionの実行境界

1. CI Playwrightはmock site + isolated Chromium profileだけを検証する。実Suno/DistroKid loginの受入証拠にしない。
2. 実操作は利用者がすでにログインしたuser-owned Chrome profile上でのみ行う。profile directoryのcopy、token/cookie抽出、別browserへの移植はしない。
3. agentはlogin、CAPTCHA、consent、payment/token consumption、legal/PII確認で停止し、`USER_ACTION_REQUIRED` を返す。
4. Chromeを強制終了しない。共有tab/sessionを勝手に再起動しない。
5. Suno helperの`chrome.debugger` attach中はDevTools MCP/別debuggerを併用しない。競合は `BROWSER_SESSION_CONFLICT`。
6. unpacked extension IDが0件/複数ならprofileを推測せず、候補を秘密化してuser確認またはmanual exact originへhandoffする。
7. localhost serverはhealth確認後に既存を再利用し、port ownerが不明ならkillしない。新portへ分離する。

出典:

- `/Users/mba/02-yt/00-automation/.claude/skills/suno-helper/SKILL.md`
- `/Users/mba/02-yt/00-automation/.claude/skills/distrokid-helper/SKILL.md`
- `/Users/mba/02-yt/00-automation/src/youtube_automation/utils/chrome_extensions.py`
- `/Users/mba/02-yt/00-automation/extensions/suno-helper/playwright.config.ts`
- `/Users/mba/02-yt/00-automation/extensions/distrokid-helper/playwright.config.ts`

### 7. 変更候補、受入条件、テスト、rollback（未実装）

#### 候補A: repository preflight CLI

- 対象候補: `src/youtube_automation/cli/`、`src/youtube_automation/cli_entrypoints.py`、`pyproject.toml`
- 受入条件: profile別check、上記exit/JSON schema、secret redaction、60秒未満のdefault profile、read-only default。
- unit: fake PATH/env/subprocessで全classification、timeout、redaction、retryable matrix。
- integration: temp worktree、broken lock、missing tool、isolated XDG、fake Chrome Preferences。
- failure再現: ambient pnpm10、Git identity exit128、複数extension ID、ADC command nonzero。
- test command: `bash .lefthook/setup-worktree.sh uv run pytest tests/test_preflight.py tests/integration/test_preflight.py -n auto`
- rollback: entry pointとmoduleをrevert。既存CLI挙動へ影響させない独立追加にする。

#### 候補B: TAKT workflow先頭preflight step

- 対象候補: project/global workflow YAML、TAKT task result schema/engine。
- 受入条件: implement前に実行、environment/authはSupervisorへ到達しない、structured failureがtask recordに残る、retry上限を守る。
- unit: exit code→transition table、unknown schema→70、SIGINT→130。
- integration: `preflight -> implement`、retryable2回後成功、user-action即停止、base/head比較。
- failure再現: `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1` とidentity無しを注入。
- test command: TAKT upstreamのworkflow engine/test suite + `takt workflow doctor <workflow>`。
- rollback: workflowからpreflight edgeを外す。schema追加はoptional/後方互換にする。

#### 候補C: Python CIをfrozen + package build化

- 対象候補: `.github/workflows/ci.yml`、`pyproject.toml`、必要ならbuild dependency lock方針。
- 受入条件: lock driftでfail、wheel/sdist両方build、force-included skills/docs/auth templateのartifact検査、source tree無差分。
- unit: artifact member listをfixture期待値と比較。
- integration: `uv sync --frozen`、isolated build、wheel install後`yt-skills list` smoke。
- failure再現: pyprojectだけdependency変更、force-include path欠落、Hatchling非互換。
- test command候補: `nix develop --command uv sync --frozen`; `nix develop --command uv build`; temp venvへwheel installしてsmoke。
- rollback: build jobをremoveし現CIへ戻す。lockfileは変更前を復元。

#### 候補D: devShell dependency sync fail-closed

- 対象候補: `flake.nix::shellHook`、`.lefthook/setup-worktree.sh`。
- 受入条件: explicit setupではsync failure nonzero、対話shellの扱いを明示、TAKT skip-lefthookとは独立。
- unit: source contractで`uv sync` failureを握り潰さないこと。
- integration: fake uv exit1、direnv fallback、Nix route。
- failure再現: offline/invalid lockでshell入場。
- test command: `bash .lefthook/setup-worktree.sh sh -c 'uv lock --check && uv sync --frozen'` と既存 `tests/test_lefthook_installation_contract.py`。
- rollback: soft-warning shellHookへ戻し、preflight側のexplicit syncだけ維持。

#### 候補E: Git identityの限定bridge

- 対象候補: `.takt/runtime-prepare.sh` またはTAKT core runtime environment。
- 受入条件: isolated XDGでもauthor/committer ident exit0、credential/helper/signing/filter設定は持ち込まない、値をlogしない。
- unit: identity present/missing、malformed、global config isolation。
- integration: temp repoでhooks無効のdummy commit（専用fixtureのみ）、実worktreeではcommitしない。
- failure再現: current observed `git var GIT_AUTHOR_IDENT` exit128。
- test command: dedicated runtime tests + `git var GIT_AUTHOR_IDENT >/dev/null` / committer counterpart。
- rollback: bridge env/configを削除。auto-commit前に明示blockへ戻す。

#### 候補F: Chrome/auth capability probe

- 対象候補: preflight profile、`utils/chrome_extensions.py`、operator skills。
- 受入条件: secret/cookie非読出し、profile 0/1/Nを分類、login/CAPTCHAをuser action化、mock E2Eと実session証拠を分離。
- unit: unreadable/invalid/duplicate Preferences、manual exact origin、port collision。
- integration: disposable Chrome profile + unpacked test extension。実accountは自動test対象外。
- failure再現: duplicate extension IDs、debugger attach conflict、stale port registry。
- test command: Python chrome-extension tests + `nix develop .#extensions --command pnpm -C extensions/suno-helper test:e2e`。
- rollback: probeをadvisoryへ戻し、既存manual fallbackを維持。

#### 候補G: Actions/toolchain pin統一

- 対象候補: `.github/workflows/*.yml`、`flake.lock`。
- 受入条件: normal/releaseが同じNix入口、Actionsをcommit SHAで固定、Windows uv/Python patchを記録、更新手順を文書化。
- unit: workflow YAML contract test。
- integration: PR CI + release dry build（release作成なし）。
- failure再現: installer action差替、floating image/tool versionのsnapshot差分。
- test command: repositoryのworkflow contract tests、Actions上の全job。
- rollback:直前のaction refへ戻す。Nix lockは独立revert可能にする。

### 8. preflight自身のテスト戦略

| 層 | 必須ケース | 外部変更 |
|---|---|---|
| pure unit | classifier、schema、redaction、retry matrix、profile selection | なし |
| subprocess unit | missing/version/timeout/exit mapping | fake binaryのみ |
| temp integration | temp Git repo/worktree、isolated XDG、lock drift | `/tmp`のみ |
| Nix integration | locked versions、default/extensions shell | cache read/downloadあり |
| CI integration | Linux/Windows、frozen sync、package build、mock E2E | CI artifactのみ |
| operator acceptance | authenticated Chrome login/CAPTCHA/handoff | user-owned session、明示実行 |

fail再現testは必ず「base/control」と「head/candidate」を同じenvironment fingerprintで比較する。fingerprintはOS/arch、flake rev、Python/uv、Node/pnpm、CI image label、profile種別を含めるが、user名、email、token、absolute Chrome profile pathは含めない。

## 主要な発見のサマリー

1. preflightは品質testの前段に独立配置し、environment/auth/user-actionをstructured classificationで終端させる必要がある。
2. exit codeだけでなく`classification/retryable/owner/check_id/repair`を永続化しないとTAKTの固定abort reasonで情報が失われる。
3. base/control比較が、環境障害をSupervisor REJECTへ誤送しない最も強い境界になる。
4. shared Chrome、OAuth、ADC、CAPTCHAはuser-owned capabilityであり、CI mock E2Eの延長として扱えない。
5. 最優先変更候補は明示frozen sync、Python package build、Git identity preflight、workflow engineのfailure metadata保持。

## 注意点・リスク

- preflightが重すぎると全workflowの開始costを増やす。常時profileは軽量、Playwright/build/authはscope別に遅延選択する。
- auth probeのstdout/stderr保存は秘密漏洩リスク。command文字列にもsecret値を展開しない。
- automatic repairがlock、credentials、Chrome profile、Terraform stateを書き換える設計にしてはいけない。preflight defaultはread-only。
- network failureのretryはbounded + jitter。認証不足やversion mismatchは即時repair-required。
- user shared ChromeをCI/headless browserへコピーするとsession窃取・破損リスクがある。
- TAKT hook skipを単純撤去するとsandbox書込み失敗が再発する。CI委譲を維持したまま明示validationを足す。

## 調査できなかった項目と理由

- TAKT upstreamに本classification schemaを入れた場合の実run: 未実装のため。
- GitHub Actionsの実runner fingerprintとretry挙動: workflowを起動していないため。
- 実authenticated Chrome acceptance: user sessionが必要。
- ADC/op/OAuth expiryごとの実stderr taxonomy:秘密・外部認証を呼ばなかったため。
- isolated Python buildの実失敗パターン: artifact生成とnetwork取得を避けたため。

## 推奨／結論

最小導入順は、(1) read-only preflight CLIとJSON schema、(2) TAKT implement前stepとfailure metadata保持、(3) frozen Python sync + package build CI、(4) task別Chrome/auth profileである。Supervisorは`CHANGE_REGRESSION`だけを品質REJECTにし、それ以外はownerとretryabilityを保持したenvironment/auth/user-action終端へ分離する。これによりworkflow開始後に初めて判明する不足を前倒しし、環境復旧で直る失敗にreview/fixループを消費しない。
