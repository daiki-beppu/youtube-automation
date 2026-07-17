# 環境 parity 調査

- 取得日: 2026-07-17（Asia/Tokyo）
- 対象: `/Users/mba/02-yt/00-automation`
- 調査方式: tracked 設定、lockfile、CI workflow、TAKT runtime 設定、認証実装、operator skill の読み取りと、秘密値を表示しない非破壊コマンド
- 制約: `git add` / `git commit` / `git push`、依存 install、Nix devShell 入場、外部認証、実 Chrome 操作は未実施

## 調査項目ごとの結果と詳細

### 1. ローカル、TAKT、CI の比較

| 項目 | 通常ローカルの正規入口 | 現 TAKT step の観測 | Linux CI | Windows CI | parity 判定 |
|---|---|---|---|---|---|
| checkout | worktree + `.envrc` または `.lefthook/setup-worktree.sh` | repository root の `main`、ambient shell | fresh checkout、`ubuntu-latest` | fresh checkout、`windows-latest` | TAKT cwd と通常開発規約が不一致 |
| Python | Nix `python311` = 3.11.15 | ambient 3.14.6、`.venv` 3.11.15 | Nix 3.11.15 | `setup-python` の `3.11`（patch 浮動） | `uv run` は概ね一致、ambient は不一致 |
| uv | Nix 0.11.3 | ambient 0.11.26 | Nix 0.11.3 | `setup-uv@v6`（exact 版未固定） | 不一致 |
| Python deps | `uv.lock` + `.venv` | lock check OK、`.venv` 存在 | `uv sync` | `uv sync` | CI は `--frozen` なし |
| Ruff / pytest / xdist | lock: 0.15.8 / 9.0.2 / 3.8.0 | 同左 | 同左 | pytest 9.0.2、cost tracker のみ | Windows coverage は限定的 |
| FFmpeg | Nix 8.0.1 | ambient 8.1.2 | Nix 8.0.1 | job に無し | ambient 直呼びは不一致 |
| lefthook | Nix 2.1.1、install 必須 | ambient 2.1.1、TAKT worker は install skip | hook 自体は実行せず個別 gate を CI 化 | 無し | 意図的非対称 |
| Node / pnpm | extensions shell 24.14.0 / 11.12.0 | ambient 25.4.0 / 10.32.1 | extensions shell 24.14.0 / 11.12.0 | 無し | ambient 直呼びは不一致 |
| Playwright | 初回 Chromium install が必要 | install 状態は worktree ごとに不定 | CI 中に `--with-deps chromium` | 無し | 初回不足が workflow 中に判明 |
| auth | system `op`、ADC、OAuth files、Chrome login | CLI は存在するが認証状態は未確認 | 通常 test は実 auth を使わない | 同左 | CI green は実認証を証明しない |

一次資料:

- `/Users/mba/02-yt/00-automation/flake.nix`
- `/Users/mba/02-yt/00-automation/flake.lock`
- `/Users/mba/02-yt/00-automation/.envrc`
- `/Users/mba/02-yt/00-automation/.takt/config.yaml`
- `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh`
- `/Users/mba/02-yt/00-automation/.github/workflows/ci.yml`
- `/Users/mba/02-yt/00-automation/.github/workflows/extensions.yml`
- `/Users/mba/02-yt/00-automation/docs/development.md`
- `/Users/mba/02-yt/00-automation/docs/takt-operations.md`

### 2. 生のバージョン・lock 出力

現 TAKT shell の出力:

```text
git version 2.54.0
nix (Determinate Nix 3.17.0) 2.33.3
direnv 2.37.1
uv 0.11.26 (aarch64-apple-darwin)
Python 3.14.6
lefthook 2.1.1
ffmpeg 8.1.2
node v25.4.0
pnpm 10.32.1
takt 0.51.0
gh 2.96.0
op 2.33.0
```

Nix lock を評価した値:

```text
python311=3.11.15
uv=0.11.3
ffmpeg=8.0.1
lefthook=2.1.1
nodejs_24=24.14.0
pnpm=11.12.0  # flake.nix の固定 tarball
```

Python lock / `.venv`:

```text
$ uv lock --check
Resolved 65 packages in 26ms
exit=0

$ .venv/bin/python --version
Python 3.11.15
$ .venv/bin/python -m pytest --version
pytest 9.0.2
$ .venv/bin/ruff --version
ruff 0.15.8
```

主要 locked package は `google-api-python-client 2.193.0`、`google-auth-httplib2 0.3.0`、`google-auth-oauthlib 1.3.0`、`google-genai 1.69.0`、`openai 2.33.0`、`pandas 3.0.1`、`Pillow 12.3.0`、`pytest-xdist 3.8.0`。出典は `/Users/mba/02-yt/00-automation/uv.lock`。

Nix inputs:

```text
nixpkgs rev=456e8a9468b9d46bd8c9524425026c00745bc4d2
flake-utils rev=11707dc2f618dd54ca8739b309ec4fc024de578b
```

拡張は両 `package.json` が `packageManager: pnpm@11.12.0`、lockfileVersion 9.0。主要値は Playwright 1.60.0、TypeScript 5.9.3、Vitest 4.1.8、WXT 0.20.26、Oxlint 1.73.0。出典:

- `/Users/mba/02-yt/00-automation/extensions/suno-helper/package.json`
- `/Users/mba/02-yt/00-automation/extensions/suno-helper/pnpm-lock.yaml`
- `/Users/mba/02-yt/00-automation/extensions/distrokid-helper/package.json`
- `/Users/mba/02-yt/00-automation/extensions/distrokid-helper/pnpm-lock.yaml`

### 3. CI、lint、型検査、test、build の生コマンド

Python CI (`/Users/mba/02-yt/00-automation/.github/workflows/ci.yml`):

```text
nix develop --command uv sync
nix develop --command uv run ruff check .
nix develop --command uv run ruff format --check .
nix develop --command uv run pytest -n auto

# Windows only
uv sync
uv run pytest tests/test_cost_tracker.py -q
```

追加 gate は CHANGELOG、ADR 番号重複、Any/any 新規追加検査。Python の mypy/pyright 等の型検査と wheel/sdist build job は存在しない。

Extensions CI (`/Users/mba/02-yt/00-automation/.github/workflows/extensions.yml`):

```text
nix develop .#extensions --command pnpm install --frozen-lockfile
nix develop .#extensions --command pnpm run audit
nix develop .#extensions --command pnpm lint
nix develop .#extensions --command pnpm format:check
nix develop .#extensions --command pnpm compile
nix develop .#extensions --command pnpm test
nix develop .#extensions --command pnpm build
nix develop .#extensions --command pnpm exec playwright install --with-deps chromium
nix develop .#extensions --command xvfb-run -a pnpm test:e2e
```

`compile` は `wxt prepare && tsc --noEmit`。build 後に生成 manifest の permissions / host permissions を inline Node script で検証する。

リリース build (`/Users/mba/02-yt/00-automation/.github/workflows/release-extensions.yml`):

```text
bash .claude/skills/automation-release/references/verify-extensions.sh suno-helper
bash .claude/skills/automation-release/references/verify-extensions.sh distrokid-helper
```

通常 CI は `cachix/install-nix-action@v30`、release は `DeterminateSystems/nix-installer-action@main` で入口が異なる。Python build backend は `/Users/mba/02-yt/00-automation/pyproject.toml` の `hatchling.build` だが、`hatchling` は version 未指定で `uv.lock` にも無く、`.venv` への import は `ModuleNotFoundError` だった。isolated build 時に初めて取得・失敗し得る。

### 4. Nix、direnv、lefthook、worktree 初期化

通常経路:

```text
.envrc (nix-direnv 3.1.1 bootstrap + use flake)
  または bash .lefthook/setup-worktree.sh <command>
    -> direnv allow/exec
    -> 失敗時 nix develop fallback
      -> shellHook
        -> .lefthook/install.sh
        -> uv sync --quiet
```

`install.sh` は lefthook install を最大3回、0.2秒間隔で retryし、通常環境では fail-closed。一方 `flake.nix` の `uv sync --quiet` は失敗を warning にして shell 入場を継続する。このため「devShell 入場成功」は依存同期成功を意味しない。

TAKT worker は `/Users/mba/02-yt/00-automation/.takt/runtime-prepare.sh` から次を受け取る。

```text
XDG_DATA_HOME=${TAKT_RUNTIME_ROOT}/data
YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1
```

TAKT core はさらに runtime-local `TMPDIR` / `XDG_CACHE_HOME` / `XDG_CONFIG_HOME` / `XDG_STATE_HOME` と `CI=true` を使う。hook install skip は sandbox の共有 hooks / direnv allow store 書込み失敗を避ける意図的例外で、CHANGELOG 等は CI に委譲される。詳細は `/Users/mba/02-yt/00-automation/reports/data-git-hooks-worktree.md`。

現 checkout で `lefthook check-install` は exit 0。ただし Git identity は次のとおりで、workflow 完了後の auto-commit 前に初めて失敗し得る。

```text
$ git var GIT_AUTHOR_IDENT
exit=128
$ XDG_CONFIG_HOME=<isolated> git var GIT_AUTHOR_IDENT
exit=128
```

### 5. 環境変数と秘密情報の境界

| 種別 | key / source | 解決・用途 | CI での実証 |
|---|---|---|---|
| channel | `CHANNEL_DIR` | 下流 channel root。tests は一時 fixture に差替え | 実 channel は未実証 |
| OAuth client | `CLIENT_SECRETS_DIR`, `CLIENT_SECRETS_JSON`, `auth/client_secrets.json` | file候補後、env → `op read` fallback | 未実証 |
| OAuth token | `auth/token*.json` | user OAuth flow後の token | 未実証 |
| API secrets | `OPENAI_API_KEY`, `YOUTUBE_STREAM_KEY`, `VULTR_API_KEY`, `STREAM_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL` | env → 1Password URI | 未実証 |
| secret opt-out | `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` | tests で外部 `op` を止める | 実 auth の反証にもならない |
| Google AI | `GOOGLE_CLOUD_PROJECT` 任意、ADC quota project fallback | Vertex AI / Lyria / image | 未実証 |
| location | `GOOGLE_CLOUD_LOCATION` | 一部 Google AI 経路 | 通常 test のみ |
| CI diff | `BASE_SHA`, `HEAD_SHA`, `PRE_PUSH_DIFF_BASE`, `FALLOW_AUDIT_BASE`, `PR_LABELS` | CI gate comparison | CI only |
| TAKT | `TAKT_RUNTIME_ROOT`, runtime XDG, `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK` | sandbox 分離 | TAKT only |

秘密値の実装上の単一ソースは `/Users/mba/02-yt/00-automation/src/youtube_automation/utils/secrets.py`。取得順は environment → `op read`（10秒 timeout）→ `ConfigError`。Nix shell は `op` を同梱せず system install を期待する。一方 `/Users/mba/02-yt/00-automation/README.md` には Nix shell が `op` を提供するように読める記述があり、`flake.nix` の実装と不一致。

`.gitignore` は `.env`、`auth/client_secrets.json`、`auth/token*.json`、Terraform secret/state 系を除外する。`reports/data-environment-parity.md` と `reports/data-preflight.md` は ignore 対象外であることを `git check-ignore -v` で確認した。

### 6. 外部 CLI と認証済み profile / ユーザー操作

| 工程 | 必須条件 | agent / CI が可能な範囲 | 人間・共有 session 境界 |
|---|---|---|---|
| Google OAuth / ADC | `gcloud`, browser login, quota project | CLI存在、非秘密の診断 | `gcloud auth login`、ADC login、Google Auth Platform UI、client JSON download は user step |
| 1Password | system `op`, signed-in account | binary存在・secret名の静的確認 | signin / biometric / vault access は user/session owner |
| YouTube OAuth | client JSON + browser consent + token file | path/permission/JSON shape check | consent UI・再認証は user step |
| Suno helper | 実 Chrome profile、unpacked extension、Suno login、Advanced tab | localhost server、overlay観測、mock E2E | login、CAPTCHA、payment/token confirmation は user step |
| DistroKid helper | 実 Chrome profile、extension、DistroKid login | payload/server/extension unit-E2E | upload、account/payment/legal/PII confirmation は user step |
| Terraform streaming | Terraform >=1.5、ADC、`op` secrets、state backend | fmt/validate/plan（credentials有時） | apply/destroy、課金、公開インフラ変更は別承認境界 |
| GitHub | `gh` auth / `GH_TOKEN` | local read、CI token scope内操作 | push/PR/release は workflow後段の外部変更 |

Suno の operator contract は `/Users/mba/02-yt/00-automation/.claude/skills/suno-helper/SKILL.md`。ログイン画面、明示 CAPTCHA、account/payment/token 確認で停止し、Chrome を強制終了しない。DevTools/別 debugger は拡張の `chrome.debugger` attach と競合し得る。DistroKid の境界は `/Users/mba/02-yt/00-automation/.claude/skills/distrokid-helper/SKILL.md`。

Chrome extension origin 検出は `/Users/mba/02-yt/00-automation/src/youtube_automation/utils/chrome_extensions.py` が macOS の `~/Library/Application Support/Google/Chrome` 配下の全 profileから `Secure Preferences`、次に `Preferences` を読む。0件、複数ID、read/parse失敗は手動 `--allow-origin chrome-extension://<ID>` fallback。TAKT sandbox/CI の一時 profile は、利用者の認証済み共有 profile の代替ではない。

## 主要な発見のサマリー

1. `uv run` は `.venv` の Python 3.11/locked deps を使うが、TAKT の ambient Python、uv、FFmpeg、Node、pnpm は Nix/CI 契約外である。
2. fresh worktree では `.direnv`、`.venv`、`node_modules`、Playwright Chromium が無く、初回 network/install failure が実装開始後に出る。
3. devShell shellHook の dependency sync は soft-fail。明示 `uv sync` / lock check を実装前に別実行しないと不足を抱えたまま進む。
4. CI は Python lock frozen、Python package build、Python型検査、実認証、実Chrome profileを検証しない。
5. TAKT の hook skip は設計どおりだが、CI到達前の品質保証と workflow後の Git identity が別途必要。
6. shared/authenticated Chrome session は mock Playwright E2E と責務が異なり、Supervisor のコード品質 REJECT 条件に混ぜられない。

## 注意点・リスク

- `ubuntu-latest` / `windows-latest`、Actions major tag、release の `@main` は浮動する。
- `uv sync` に `--frozen` がなく、CIで lock drift を fail-closed にできていない。
- Python package build が無いため、未固定 Hatchling、force-include、sdist/wheel欠落は release 時まで潜伏し得る。
- Playwright `--with-deps` は network/OS package権限に依存し、実Chrome loginの準備完了とは無関係。
- `ffprobe` 不在を soft skip する Terraform preflight は、動画品質未検査のまま planを通す。
- profile Preferences の候補重複や unreadable は環境障害であり、実装 defect と即断できない。
- 認証確認コマンドの stdout を保存すると token、account、email、project情報が漏れ得る。preflight は stdoutを破棄し、分類だけを保存する必要がある。

## 調査できなかった項目と理由

- CI runner image の当日実体バージョン: workflowを新規実行していないため未取得。
- `op` signin、vault item、ADC access token、OAuth token の有効性: 秘密値・外部認証へのアクセスを避けた。
- 実 Suno / DistroKid login、CAPTCHA、拡張 attach: 利用者の共有Chrome profile操作が必要。
- fresh TAKT worktree の初回 Nix/direnv/Playwright所要時間とnetwork failure: install/writeを伴うため未再現。
- Python wheel/sdist の実 build: build dependency downloadと成果物生成を伴い、本stepは調査のみのため未実施。
- Terraform plan/backend/provider auth: state/backend/credentialと外部APIアクセスが必要。

## 推奨／結論

正規コマンド入口を Python は `bash .lefthook/setup-worktree.sh uv ...`、extensions は `nix develop .#extensions --command pnpm ...` に固定し、ambient toolを禁止する。workflow開始直後に lock、explicit sync、tool version、Git identity、必要な auth/session capability を検査し、環境・認証不足は Supervisor品質判定へ渡さず structured preflight failure として停止または保留する。CI には frozen Python sync と Python package build を追加する候補価値が高い。
