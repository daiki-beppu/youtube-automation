# Part B 監査結果: セキュリティ / シークレット / 権限境界

- **対象**: `.claude/skills/**`, `src/youtube_automation/**`, `auth/`, `infra/terraform/**`, ルート設定
- **担当**: Research Digger Part B（観点 5）
- **取得日**: 2026-05-18
- **作業ディレクトリ**: `/Users/mba/02-yt/takt-worktrees/20260518T0905-372-issue-372-chore-skills-sukiru/`
- **コミット時点**: `git log --all --pretty='%h' | wc -l` = 316 commits
- **方針**: 検出した疑わしい値は **すべて伏字化**。実値は本ファイルに残さない。

---

## エグゼクティブサマリー

| Severity | 件数 | 概要 |
|---|---|---|
| **P0（即時対応必須）** | 0 | なし |
| **P1（高優先・要対応）** | 2 | (a) Terraform `null_resource.deploy` の SSH host key 未検証 / (b) `auth/token.json` のスコープが広く読み取り専用 skill にも write/analytics 権限が乗る |
| **P2（中優先・改善余地）** | 5 | (c) `.gitattributes` 不在 / (d) Terraform local state（remote backend なし） / (e) `channel-new` の token.json コピー導線 / (f) `op read $(...)` 値の shell env 滞留 / (g) `vultr_bandwidth.py` の `URLError` で reason に URL が含まれうる |
| **P3（軽微・参考）** | 3 | (h) bench スクリプトが `os.environ.get` 直読み（意図通り） / (i) `notification.py` 例外文の URL 漏れ余地 / (j) Suno CDN への `curl -L` |

**結論**: シークレット直書きや git 履歴混入は **発見できなかった**。`utils.secrets._SECRET_REFS` を中核とした env → 1Password CLI → ConfigError の解決経路は production code 全体で一貫しており、ログ出力経路の redaction も `oauth_handler._redact()` で網羅されている。残るリスクは **(1) 1 つの token.json が複数 scope を抱える単一障害点設計** と **(2) Terraform ssh provisioner の first-connect MITM 余地** の 2 点に集約される。修正は本 PR スコープ外（観点 5 は監査のみ）。

---

# B-1: シークレット取り扱い

## 5.1 ハードコード検出

検出ルール (= grep 正規表現):

| 種別 | パターン | 検出件数 |
|---|---|---|
| Google API key | `AIza[0-9A-Za-z_-]{35}` | **0** |
| OpenAI key | `sk-[a-zA-Z0-9]{20,}` | **0** |
| GitHub PAT | `ghp_[a-zA-Z0-9]{36}` | **0** |
| Slack token | `xox[baprs]-[0-9a-zA-Z-]+` | **0** |
| Bearer literal | `Bearer\s+[A-Za-z0-9_\-\.]{20,}` | **0** |
| 一般代入 | `(api_key\|password\|secret\|client_secret\|token)\s*[:=]\s*"[^"]{8,}"` | 6（全件 false positive） |

一般代入のヒット 6 件はいずれも **plaintext な値ではなく**、以下のいずれか:

- `src/youtube_automation/auth/oauth_handler.py:39` — `_REDACTED_TOKEN = "<redacted-token>"`（redaction 用プレースホルダ）
- `tests/test_metadata_audit.py:23` — `_ZH_ISSUE_TOKEN = "zh codes"`（テスト用ラベル文字列、credential ではない）
- `tests/test_oauth_handler_exceptions.py:40-41` — 合成された Google 風 access/refresh token サンプル（`ya29.A0AbCdEfGhIjKlMnOpQrStUvWxYz123456` 等、redaction のテスト fixture）
- `tests/test_oauth_handler_main.py:33` — 同上
- `tests/test_secrets.py:27` — `_TEST_SECRET = "CLIENT_SECRETS_JSON"`（_SECRET_REFS の **キー名** 文字列）

**評価**: production code に実値のシークレット直書きは **検出されず**。テスト fixture の合成 token は `_redact()` の挙動を verify するための inert な文字列であり、credential として有効ではない。

> 取得コマンド:
> ```
> Grep -E 'AIza[0-9A-Za-z_-]{35}' --path .
> Grep -E 'sk-[a-zA-Z0-9]{20,}' --path .
> Grep -E 'ghp_[a-zA-Z0-9]{36}' --path .
> Grep -E 'xox[baprs]-[0-9a-zA-Z-]+' --path .
> Grep -iE '(api[_-]?key|password|secret|client_secret|token)\s*[:=]\s*["'\''][^"'\'']{8,}["'\'']' --path .
> ```

---

## 5.2 シークレット参照経路（env → op read → ConfigError）

`src/youtube_automation/utils/secrets.py` の `_SECRET_REFS` 定義:

| シークレット名 | 1Password URI |
|---|---|
| `CLIENT_SECRETS_JSON` | `op://Personal/YouTube_OAuth_Client_Secrets/credential` |
| `OPENAI_API_KEY` | `op://Personal/OpenAI_API_Key/credential` |
| `YOUTUBE_STREAM_KEY` | `op://Personal/YouTube/stream_key` |
| `VULTR_API_KEY` | `op://Personal/Vultr/api_key` |
| `STREAM_WEBHOOK_URL` | `op://Personal/Stream_Notification_Webhook/url` |
| `DISCORD_WEBHOOK_URL` | `op://Personal/YouTube_Stream_Discord_Webhook/url` |

呼び出し側の準拠状況:

| 呼び出し箇所 | 経路 | 評価 |
|---|---|---|
| `src/youtube_automation/utils/image_provider/openai.py:69` | `get_secret("OPENAI_API_KEY")` | ✅ |
| `src/youtube_automation/cli/stream_bandwidth.py:120` | `get_secret("VULTR_API_KEY")` | ✅ |
| `src/youtube_automation/cli/stream_bandwidth.py:151,168` | `get_secret("STREAM_WEBHOOK_URL")` | ✅ |
| `src/youtube_automation/scripts/streaming_archive_check.py:78` | `get_secret("DISCORD_WEBHOOK_URL")` | ✅ |
| `src/youtube_automation/utils/secrets.py:101` | `get_secret("CLIENT_SECRETS_JSON")` → `get_client_secrets_path()` | ✅ |
| `src/youtube_automation/auth/oauth_handler.py:107-115` | `get_client_secrets_path()` フォールバック | ✅ |
| `bench/bench_generate_image.py:61` | `os.environ.get("OPENAI_API_KEY")` のみ（存在チェック） | ⚠️ P3: bench 専用、API 呼び出しは provider 経由なので意図通り |
| `bench/bench_real_apis.py:27` | 同上 | ⚠️ P3: 同上 |

**評価 (5.2)**: production code パス（`src/`）では `get_secret()` 経由が **100% 徹底**。bench スクリプト 2 件は「設定済みか否か」の boolean 判定にしか使っていないため漏洩リスクはない（実 API 呼び出しは `image_provider/openai.py` 経由で再度 `get_secret()` が走る）。

`get_secret()` 実装（`utils/secrets.py:40-79`）の評価:
- 解決順序: `os.environ` → `shutil.which("op")` → `op read` → `ConfigError`
- `lru_cache` でメモ化（同一プロセス内）
- `op read` 失敗 (`CalledProcessError`/`TimeoutExpired`/`FileNotFoundError`) を握りつぶし最終 `ConfigError` に集約 → エラーメッセージに `.env` と 1Password 両ルートを明示
- `_OP_READ_TIMEOUT_SEC = 10` で hang 防止

`get_client_secrets_path()`（`utils/secrets.py:85-116`）:
- `mkstemp` → `chmod 0o600` → `fdopen` の順序 → world-readable な瞬間を経由しない（コメントで明示）
- `atexit.register(_cleanup)` で一時ファイルを掃除（idempotent）

---

## 5.3 .gitignore / 履歴混入

### `.gitignore`（ルート）

検証対象パスのカバレッジ:

| パターン | `.gitignore` 行 | カバー |
|---|---|---|
| `auth/client_secrets.json` | L12 | ✅ |
| `auth/token*.json`（glob、`token_streaming.json` も対象） | L13 | ✅ |
| `.env` | L8 | ✅ |
| `terraform.tfvars` | L33 | ✅ |
| `*.tfstate` / `*.tfstate.*` | L34-35 | ✅ |
| `*.tfplan` | L36 | ✅ |
| `.terraform/` | L37 | ✅ |
| `service-account*.json` | — | ❌ なし（**P2 改善候補**: 慣例的に Google サービスアカウント JSON が手元に落ちうるため glob 追加が望ましい） |

回帰テストあり: `tests/test_gitignore_auth_tokens.py`（issue #158）が `auth/token*.json` glob の必須性 + 後方互換 + 旧 exact 形式撤去を保証。

`.claude/skills/channel-setup/references/terraform-gcp/.gitignore` も独立に存在し、wheel に同梱される展開先で `terraform.tfstate*` / `terraform.tfvars` / `*.auto.tfvars` を ignore。

### `.gitattributes`

`/Users/mba/02-yt/takt-worktrees/.../.gitattributes` は **存在しない**（`ls -la .gitattributes` で `No such file or directory`）。`export-ignore` / `filter` 系の防御層は無し。**P2 改善候補**: archive 生成時に `auth/` を含めない / `linguist-vendored` 等の用途で 1 ファイル作る余地あり。

### `git ls-files` で誤って tracked されているか

```
git ls-files | grep -E '(token\.json|client_secrets\.json|\.env$|\.tfstate|service-account)'
git ls-files | grep -E 'tfvars$'
```

両コマンドとも **0 件**。tracked の secret 含有ファイルは存在しない。`.env.example`, `auth/client_secrets_template.json`, `auth/SETUP.md`, `*.tfvars.example` のテンプレートのみ tracked。

### 過去コミット履歴

```
git log --all --full-history -- 'auth/client_secrets.json' 'auth/token.json' 'auth/token_streaming.json'  # → 0 件
git log --all --full-history -- '.env' '.env.local'                                                       # → 0 件
git log --all --full-history -- 'infra/terraform/streaming/terraform.tfvars'                              # → 0 件
```

**評価 (5.3)**: 316 コミットの履歴を通じて、上記 sensitive ファイルが **一度も commit されていない**。

---

## 5.4 ログ・stdout 出力リスク

### Python 側（`src/`）

`(print|logger\.(info|debug|warning|error|exception)).*(token|secret|api_key|password|credential|refresh|bearer)` ヒット件数 = **4 件**、全件 `_redact()` 経由 or path-only:

| 場所 | 内容 | 評価 |
|---|---|---|
| `src/youtube_automation/auth/oauth_handler.py:172` | `logger.warning("既存トークン読み込み失敗: %s", _redact(str(e), self.token_file))` | ✅ redact 経由 |
| `src/youtube_automation/auth/oauth_handler.py:186` | `logger.warning("token refresh 失敗: %s", _redact(str(e)))` | ✅ |
| `src/youtube_automation/auth/oauth_handler.py:200` | `logger.error("OAuth 2.0 認証失敗: %s", _redact(str(e), self.client_secrets_file))` | ✅ |
| `src/youtube_automation/auth/oauth_handler.py:221` | `print(f"💾 認証トークン保存完了: {self.token_file}")` | ✅ パス（**値ではない**） |

`_redact()`（`oauth_handler.py:43-60`）の対象パターン:
- `ya29\.[\w\-]+`（Google access token）
- `1//[\w\-]+`（Google refresh token）
- `[\w\-]{20,}\.[\w\-]{20,}\.[\w\-]{20,}`（JWT 3 セグメント）
- `(?i)\b(?:refresh_token|access_token|client_secret|id_token)=[^\s&]+`
- 引数で渡された Path / str を `os.fspath` で `<redacted-path>` 置換
- OSError 形式 `: '<abs path>'` の絶対パスを除去

回帰テスト: `tests/test_oauth_handler_exceptions.py` / `tests/test_oauth_handler_main.py` が合成 token を含む例外メッセージで redaction を verify。

### CLI stdout（stream key）

`src/youtube_automation/scripts/fetch_stream_key.py:186-202` (`_emit_stdout`):

```python
if os.environ.get("GITHUB_ACTIONS") == "true":
    print(f"::add-mask::{value}")    # GHA log masking
if sys.stdout.isatty():
    print("WARNING: stream_key を TTY に出力します。pipe で受けてください。", file=sys.stderr)
    sys.exit(2)                      # TTY 拒否
print(value)                          # pipe 経由のみ
```

`::add-mask::` でログマスキング、TTY 出力を fail-fast で拒否。`write_op_secret()` も argv に値を載せず stdin 経由（`utils/secrets.py:143-147`、Issue #151）。

### Shell スクリプト

`echo.*\$.*(TOKEN|SECRET|KEY|PASS|WEBHOOK)` パターン → **0 件**。

`.claude/skills/streaming/references/notify.sh:23-27` は `source` を使わない限定パーサで `/etc/youtube-stream-healthcheck.env` を読む（コメントで「env ファイル改ざん時の任意コード実行を防ぐ」と明示）。`notify.sh:34-40` は webhook URL が `https://(discord\.com|discordapp\.com)/api/webhooks/` でなければ exit 0（SSRF 防御、Issue #166/#174）。

`.claude/skills/streaming/references/run-ffmpeg.sh:25`:
```bash
exec /usr/bin/ffmpeg -re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"
```
`exec` を使い shell を残さないことで `systemctl show` / 親プロセス cmdline から RTMP URL（= stream_key を含む）を隠す（Issue #160）。systemd `DynamicUser=yes`（#159）で `/proc/<pid>/cmdline` は ffmpeg プロセスのみ閲覧可。

**評価 (5.4)**: ログ / stdout 経路は **全件 redaction or 値ではなくパス**。`fetch_stream_key.py` / `notify.sh` / `run-ffmpeg.sh` は二重三重の防御（GHA mask、TTY 拒否、whitelist、exec）が施されている。

---

# B-2: 権限境界

## 5.5 OAuth スコープ最小化

`src/youtube_automation/auth/oauth_handler.py:69-74`:

```python
SCOPES = [
    "https://www.googleapis.com/auth/youtube",                          # 全権限（read+write）
    "https://www.googleapis.com/auth/youtube.force-ssl",                # SSL 必須化
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",   # Reporting API v1 (#84)
]
```

### スコープと skill 利用パターンの突合せ

| skill | 必要スコープ（実利用） | デフォルト `SCOPES` が過剰か |
|---|---|---|
| `video-upload` | `youtube` (write) + `youtube.force-ssl` | ✅ 過剰なし |
| `comments-reply` | `youtube.force-ssl` (write/comments.insert) | ✅ 過剰なし（doc に明記、L18） |
| `playlist` | `youtube` (write/playlists.insert/playlistItems.delete) | ✅ 過剰なし |
| `channel-setup`（branding push） | `youtube.force-ssl` (write) | ✅ 過剰なし |
| `analytics-collect` | `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | ⚠️ **不要に `youtube` (write) を含む** |
| `benchmark` | `youtube` の read のみ（再生回数等） | ⚠️ **不要に write を含む** |
| `discover-competitors` | YouTube Data API read | ⚠️ **同上** |
| `viewer-voice` | YouTube Data API read | ⚠️ **同上** |
| `metadata-audit` | YouTube Data API read | ⚠️ **同上** |
| `channel-status` | YouTube Data API read | ⚠️ **同上** |

### 例外: stream key 取得は **正しく分離**

`src/youtube_automation/scripts/fetch_stream_key.py:99-109`:

```python
def get_streaming_credentials(force_reauth: bool = False):
    token_path = channel_dir() / "auth" / _STREAMING_TOKEN_FILENAME       # token_streaming.json
    handler = YouTubeOAuthHandler(scopes=[_STREAMING_SCOPE], token_path=token_path)
    return handler.authenticate(force_reauth=force_reauth)
```

`_STREAMING_SCOPE = "https://www.googleapis.com/auth/youtube"` 単独 + 専用 token ファイル `token_streaming.json` で **scope 分離が実装されている**。コメントで「`youtube.readonly` だと streamName がマスクされる」と理由も明示。

### 評価 (5.5) — **P1**

`auth/token.json` 1 本に **broad scope（read+write+analytics）が同居** している。Read-only skill が credential を握ったまま動くため、token.json 漏洩時の blast radius は「全 skill 分の権限」=「動画削除・差し替え・収益情報閲覧」まで及ぶ。

**推奨**:
- `token.json`（write 用、upload/comments/playlist）と `token_readonly.json`（analytics + read 用）に分離
- streaming の `token_streaming.json` パターン（issue #135）を analytics 系にも横展開
- 既存 skill で scope を上書きする方法（`YouTubeOAuthHandler(scopes=[...], token_path=...)`）はすでに用意されているので、CLI 側を変えるだけで適用可能

---

## 5.6 削除系操作の確認ステップ

| skill | 破壊的操作 | dry-run | ユーザー確認 | ロールバック |
|---|---|---|---|---|
| `live-clean` | `rm -f` で master.mp3 / master-mix.wav / *-Master.mp4 / 個別 mp3 等を削除 | ✅ Step 3 で必ずドライラン表示（SKILL.md:62-82） | ✅ `AskUserQuestion でユーザーに確認を取る。承認されるまで絶対に削除を実行しない` (L84) | ⚠️ なし（YouTube 上の動画 / Suno からの再取得に依存）。SKILL.md L42-50 に「再生成可能性」マトリクスあり |
| `playlist` (`--clean-deleted`) | `playlistItems().delete()` (`scripts/playlist_manager.py:385`) | ✅ `--dry-run` フラグあり（SKILL.md:77-78） | ⚠️ 明示的な確認プロンプトはなし。`--dry-run` → 目視 → 本番の 2 段階運用を skill 側が文書化 (L54) | ❌ なし（削除した playlistItem の URL は YouTube が再発行しない） |
| `playlist` (`--init`) | `playlistItems().insert()`（destructive ではないが二重追加余地） | ✅ `--init --dry-run` | ⚠️ プロンプトなし | — |
| `streaming` (`§5 片付け`) | `terraform destroy`（VPS 完全消去） | ⚠️ `terraform plan` で確認可だが手動 | ⚠️ `terraform destroy` の対話 `yes` 入力のみ。SKILL.md L120-127 が「長期休止する場合は必ず destroy」と促す | ✅ §1 再構築で `5〜10 分` で復旧（state ファイルが残っていれば差分のみ） |
| `streaming` (動画差し替え) | `swap_video.sh` → `null_resource.deploy` の re-run（11h サイクル中なら数秒の中断） | ✅ `terraform plan` を必ず先に実行（swap_video.sh:113） | ✅ デフォルトは対話 `apply`、`--auto-approve` は明示 opt-in（swap_video.sh:115-120） | ✅ 旧動画は VPS に上書きされるが、ローカルファイルは残る |
| `channel-direction` | `rm -rf .venv && uv sync`（再構築用、`.claude/skills/channel-direction/SKILL.md:141`） | ❌ | ❌ | ✅ `uv sync` で再生成可能 |
| `collection-ideate` | `rm -rf collections/planning/_plan-previews/<session-dir>/`（SKILL.md:323） | ❌ | ❌ | ❌ session preview のみで再生成可能 |
| `lyria/references/worktree_sync.sh:116` | `rm -rf "01-master/preview"` | ✅ `$DRY_RUN` フラグあり (L113-115) | ❌ | ❌ preview は intermediate なので再生成可能 |

### 評価 (5.6)

| skill | 評価 |
|---|---|
| `live-clean` | ✅ 模範的：AskUserQuestion + dry-run + 削除前リスト + `rm -rf` 禁止条項（L104）まで明示 |
| `playlist` | ⚠️ `--dry-run` はあるが対話確認なし。文書のみで「2 段階運用を徹底する」と要請（L54） |
| `streaming destroy` | ⚠️ Terraform 標準の `yes` 入力のみ。`terraform destroy` を AskUserQuestion でラップしていない |
| `swap_video.sh` | ✅ 対話デフォルト、`--auto-approve` opt-in、SSH agent 検証も fail-fast |
| `channel-direction` の `rm -rf .venv` | ⚠️ doc 内のコマンド例として羅列されているのみ、ガードなし。`.venv` 範囲なので blast radius は限定的 |

`branch-clean` skill は本リポジトリ `.claude/skills/` 配下に **存在しない**（dotfiles 由来のグローバル skill。本リポジトリでは管理対象外）。

---

## 5.7 git 履歴へのシークレット混入

```
git log --all --full-history -- 'auth/' '.env' 'config/channel/' 'infra/terraform/streaming/terraform.tfvars'
```

| 対象 | コミット履歴 |
|---|---|
| `auth/client_secrets.json` | **0 件** |
| `auth/token.json` / `auth/token_streaming.json` | **0 件** |
| `.env` / `.env.local` | **0 件** |
| `infra/terraform/streaming/terraform.tfvars` | **0 件** |
| `*.tfstate` 系 | **0 件** |

316 コミットを `--all --full-history` で走査して、上記 sensitive ファイルが **一度も含まれていない**。`auth/SETUP.md`, `auth/client_secrets_template.json`, `*.tfvars.example`, `.env.example` のみが tracked。

**評価 (5.7)**: 履歴汚染なし。

---

## 5.8 Terraform state / tfvars

### Streaming モジュール (`infra/terraform/streaming/`)

| ファイル | 状態 |
|---|---|
| `main.tf` | tracked（resource 定義） |
| `variables.tf` | tracked、`sensitive = true` 付き（vultr_api_key / stream_key / discord_webhook_url） |
| `terraform.tfvars.example` | tracked、コメントで「secret はここに書かず TF_VAR_* 経由」を明示 |
| `terraform.tfvars` | **gitignore 済み**（`.gitignore:33`） |
| `terraform.tfstate` / `*.tfstate.*` | **gitignore 済み**（`.gitignore:34-35`） |
| `*.tfplan` | gitignore 済み（`.gitignore:36`） |

`variables.tf` で `sensitive = true` 宣言された変数:
- `vultr_api_key` (L1-5)
- `stream_key` (L36-40)
- `discord_webhook_url` (L42-46)

`main.tf:39-53` の `null_resource.deploy.triggers` で `sensitive` 値を `triggers` map に格納する際 `nonsensitive(sha256(...))` でラップ（Terraform 1.5+ の sensitive 派生伝播対応、コメントで明示）。これにより:
- `stream_key` / `discord_webhook_url` の実値は **tfstate に sensitive として平文保存される**（Terraform の sensitive は **暗号化ではない**、出力時のマスキングのみ）
- triggers の SHA256 ハッシュも tfstate に残るが、不可逆

### Remote backend

```
Grep -n 'backend\s+"' --path .  → 0 件
```

`infra/terraform/streaming/versions.tf` / `infra/terraform/gcp/versions.tf` のいずれにも `backend "s3"` / `backend "gcs"` / `backend "remote"` の宣言なし。**state は完全に local**。

**含意 (P2)**:
- `terraform.tfstate` がローカル disk に作られ、`stream_key` / `discord_webhook_url` が平文で含まれる
- 個人ノート PC が紛失 / バックアップが流出すると tfstate から secret が抜ける
- `.gitignore` でコミットは防がれているが、**ローカル file system 上の rest 状態は protected されていない**

**推奨**: `gcs` / `s3` remote backend + customer-managed encryption key への移行。ただし個人運用では local + FileVault などで十分という判断もあり得る（コストとリスクのバランス）。

### GCP モジュール (`infra/terraform/gcp/`, `.claude/skills/channel-setup/references/terraform-gcp/`)

両モジュールも remote backend 設定なし。`auth/SETUP.md:145` で「`infra/terraform/gcp/terraform.tfvars`: **絶対に公開しない**（gitignore 済み）」と明示。

---

## 5.9 1Password CLI 前提とフォールバック

### `get_secret()` 失敗時のエラーメッセージ

`src/youtube_automation/utils/secrets.py:75-79`:

```python
raise ConfigError(
    f"{name} を取得できませんでした。\n"
    f"  → .env に {name}=... を設定するか、\n"
    f"  → 1Password の {op_ref} に登録してください"
)
```

両ルート（`.env` / 1Password）が明示され、op_ref には実際の URI 文字列が入る。ユーザーが対処可能。

### `op` 未インストール時の挙動

`secrets.py:60-73`:

```python
if shutil.which("op"):
    try:
        result = subprocess.run(["op", "read", op_ref], ...)
        ...
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
```

`op` PATH 上に無ければ `shutil.which` が False で skip → 最終 ConfigError。`op` あって失敗（auth 未済、URI 不在）も握りつぶし → 最終 ConfigError。**op の有無に依存しない**（`.env` で代替可能）。

### `write_op_secret()` のフォールバック

`secrets.py:135-141`:

```python
op_path = shutil.which("op")
if not op_path:
    raise ConfigError(
        "1Password CLI (op) が見つかりません。\n"
        "  → https://developer.1password.com/docs/cli/get-started/ からインストールするか、\n"
        "  → 既にインストール済みなら PATH を確認してください"
    )
```

インストール URL も含めた親切なメッセージ。`edit` 失敗時は `create` に自動フォールバック（既存 item 不在ケース対応、L149-189）。

### Skill 側の `op read` 利用

`.claude/skills/streaming/SKILL.md:50-52, 123`:

```bash
export TF_VAR_vultr_api_key=$(op read 'op://Personal/Vultr/api_key')
export TF_VAR_stream_key=$(op read 'op://Personal/YouTube/stream_key')
export TF_VAR_discord_webhook_url=$(op read 'op://Personal/YouTube_Stream_Discord_Webhook/url')
```

これは Python の `get_secret()` を経由せず **直接 `op read`** を呼ぶ。理由は Terraform の `TF_VAR_*` env 経路に乗せるため。

**懸念 (P2)**:
- `op read` 失敗時のエラー文言は op CLI 標準（英語、cryptic）。`get_secret()` の親切メッセージは適用されない
- `export VAR=$(op read ...)` でシェル env に滞留 → `env` 出力で見える / 子プロセスへ継承される
- shell session 終了まで env から secret が消えない（`unset TF_VAR_stream_key` の呼びかけが skill にない）

**推奨**: skill ドキュメントに `unset TF_VAR_*` の cleanup を追記する、または `direnv` / `op run --` ラッパーを案内する。

---

# 追加で発見した周辺事項

## (a) Terraform `null_resource.deploy` の SSH host key 検証なし — **P1**

`infra/terraform/streaming/main.tf:55-60`:

```hcl
connection {
    type  = "ssh"
    host  = vultr_instance.this.main_ip
    user  = "root"
    agent = true
}
```

`host_key = ...` / `target_platform` の指定なし。Terraform ssh provisioner の **デフォルト挙動は host key 検証なし**（StrictHostKeyChecking 相当が無効）。

含意:
- Vultr が VPS に割り当てる public IP に対して、初回 SSH 接続時に MITM された場合、検知できない
- 11 GB の動画 SCP + `cron.d` / `healthcheck.sh` / `notify.sh` / `run-ffmpeg.sh` の **すべて** が攻撃者経路を通る可能性
- cloud-init は `ssh_pwauth: false` で password 認証は無効化しているが、host key 検証なしのため経路自体は確保される

実害確率は限定的（Vultr ネットワーク内の MITM、または DNS / BGP hijack が必要）だが、IaC のベストプラクティスとしては:
- `vultr_instance` 作成後、cloud-init の最初の段階で host key を Vultr API（あれば）または instance log から取得し、`connection { host_key = ... }` に埋める
- または provisioner を捨て、cloud-init で全配置を完結させる

**推奨**: `data.vultr_instance_user_data` 等で startup-script から host key を取り出し、二段階 apply で host_key を pin する。これは別 issue 化を推奨。

## (b) `channel-new` Step 3 の token.json コピー — **P2**

`.claude/skills/channel-new/SKILL.md:62-82`:

```bash
ls -d ../*/auth/token.json 2>/dev/null
# ユーザーに候補を選ばせる
cp <選択されたパス> auth/token.json
```

「リサーチ用ショートカット」として、既存チャンネルの `token.json` を新リポジトリへコピーして再利用する。

懸念:
- コピーされた token は **元チャンネルの全 scope（write + analytics）** を保持
- 新リポジトリでベンチマーク収集（read のみ）に使う前提だが、書き込み API も呼べる
- Step 3 末尾に「ベンチマーク収集完了後にコピーを破棄」のような guidance がない
- 複数チャンネル間で同一 OAuth client で発行された token が混在する可能性

**推奨**: SKILL.md に「リサーチ完了後 `rm auth/token.json` で削除し、本番セットアップ時に再認証」のステップを追記。または read-only scope の専用 token をコピー対象にする。

## (c) `notification.py:62-63` の例外メッセージ — **P3**

```python
except (urllib.error.URLError, TimeoutError) as e:
    raise NotificationError(f"webhook POST failed: {e}") from e
```

`urllib.error.URLError(e)` の `__str__` に URL が含まれる実装パスはまれ（通常は reason のみ）だが、HTTPError 派生では URL が `e.url` 経由で含まれることがある。webhook URL は secret なので、エラーログに混入する余地が小さく残る。

`vultr_bandwidth.py:44-45` の `YouTubeAPIError(f"Vultr bandwidth API request failed: {e}")` も同様。Vultr URL に instance_id は入るが API key は header のみで URL には載らない。

**推奨**: 例外フォーマット時に `str(e)` を `_redact()` に通すヘルパーを `utils/secrets.py` に追加し、horizontal に適用。

## (d) `masterup` skill の `curl -L` パターン — **P3**

`.claude/skills/masterup/SKILL.md:88-89`:

```bash
curl -L -o "02-Individual-music/{filename}.mp3" "https://cdn1.suno.ai/{song_id}.mp3"
```

`{song_id}` はユーザーが WebFetch で取得した自分の playlist の Song ID。HTTPS なので path 改ざんはない。`-L` でリダイレクトを許す → CDN が悪意ある redirect chain を返すと別ホストにアクセスする可能性。Suno CDN を信頼する前提なら問題ないが、`--max-redirs 3` を付けると保守的。

## (e) Bench スクリプトの `os.environ.get(... )` 直読み — **P3（意図通り）**

`bench/bench_generate_image.py:61`, `bench/bench_real_apis.py:27` は `OPENAI_API_KEY` を `os.environ.get` で boolean 存在チェックするのみ。実際の API 呼び出しは `image_provider/openai.py` 経由で `get_secret()` がもう一度走るため、1Password fallback も効く。

bench の目的（CI で skip するか判定）に照らせば意図通り。ただし `OPENAI_API_KEY` が `.env` にも env にも無く 1Password だけにある場合、bench は SKIP になる。これは bench の設計上の制約。

---

# 既知リスク仮説（plan の H7）の検証

| ID | 仮説 | 検証結果 |
|---|---|---|
| **H7** | `auth/token.json` を skill が直接読む箇所が残存 | ✅ **検証済み（否定）**: Grep `open\([^)]*token\.json` / `Path\([^)]*token\.json` / `json\.load.*token` ヒット 0 件。token.json への直接アクセスは `YouTubeOAuthHandler` に閉じている |

---

# 調査不可項目

| 項目 | 理由 |
|---|---|
| `auth/client_secrets.json` の実体の有無 / 内容 | ポリシー上 read 禁止。存在チェックのみ可だが、本 worktree には `auth/SETUP.md` と `auth/client_secrets_template.json` のみが置かれており実体は存在しない |
| ローカル `terraform.tfstate` の中身（実 stream_key を含むか） | gitignore 済みで本 worktree に存在しない（`infra/terraform/streaming/.terraform/` 不在）。production 環境でのみ生成される |
| 1Password vault の実際の保護状態（MFA、shared / personal の境界） | リポジトリ外の運用設定。コードからは検証不可 |
| Vultr 側ファイアウォール / API token のアクセス制限 | Vultr UI 設定。リポジトリ外 |

---

# 推奨アクション（優先度順）

| # | 優先度 | 推奨アクション |
|---|---|---|
| 1 | **P1** | `auth/token.json` の scope 分離（read-only token / write token）。`fetch_stream_key.py` の `token_streaming.json` パターンを横展開 |
| 2 | **P1** | Terraform `null_resource.deploy.connection` に `host_key` pin を導入（または cloud-init 単独配置に切替） |
| 3 | P2 | `.gitignore` に `service-account*.json` を追加 |
| 4 | P2 | Terraform remote backend 検討（gcs / s3 + CMEK） |
| 5 | P2 | `channel-new` Step 3 末尾に token.json cleanup ステップを追記 |
| 6 | P2 | `streaming` skill に `unset TF_VAR_*` の post-cleanup ガイダンスを追記 |
| 7 | P3 | `_redact()` を horizontal helper として utils へ昇格し `NotificationError` / `YouTubeAPIError` の format に適用 |
| 8 | P3 | `masterup` の `curl -L` に `--max-redirs 3` を追加 |

---

# 結論

- **シークレット直書き / git 履歴混入 / ログ漏洩はゼロ件**。`utils.secrets._SECRET_REFS` と `_redact()` の二層防御は production code 全体で一貫している。
- 残るリスクは **scope 設計**（token.json 1 本に broad scope 同居）と **Terraform first-connect 検証**（host key 未 pin）の 2 点に集約。いずれも単発の修正で改善可能。
- 既知仮説 H7（token.json を直接読む skill）は **否定**。
- P0 は **0 件**。P1 が 2 件、P2 が 5 件、P3 が 3 件。

監査スコープ上、本 PR では修正は行わない（観点 5 は監査のみ）。analyze / supervise step で fix リストを編成する際の根拠資料として本ファイルを参照すること。
