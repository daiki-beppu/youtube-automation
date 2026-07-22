# Plan 025: 1Password フォールバックの client_secrets を tempfile 経由から in-memory 渡しに変更する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 37b362ce..HEAD -- src/youtube_automation/utils/secrets.py src/youtube_automation/auth/oauth_handler.py tests/test_secrets.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Status**: DONE
- **Priority**: P2
- **Effort**: M
- **Risk**: MED（OAuth 初回認証フローに触る。既存テストは厚い）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `37b362ce`, 2026-07-21
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/2394

## Why this matters

`config/channel` 側に `auth/client_secrets.json` が無いチャンネルでは、OAuth client secret を 1Password（`op read`）から取得し、**システム temp ディレクトリに平文 JSON として書き出してから** `InstalledAppFlow.from_client_secrets_file()` に渡している。ファイルは `0o600` で作成され `atexit` で削除されるが、`atexit` は SIGKILL・SIGSEGV・電源断では走らないため、異常終了時に `$TMPDIR/client_secrets_*.json` が残留する。`google-auth-oauthlib` には in-memory dict を受け取る `InstalledAppFlow.from_client_config()` が存在するので、tempfile を経由せず secret をディスクに一切書かない実装に置き換えられる。第 5 回セキュリティ監査（2026-07-21）の finding #1。

## Current state

関係ファイルと役割:

- `src/youtube_automation/utils/secrets.py` — シークレット取得ヘルパー。`get_client_secrets_path()`（L112-144）が tempfile を書く当事者。モジュールグローバル `_client_secrets_tempfile`（L109）と `atexit` cleanup（L137-142）を持つ
- `src/youtube_automation/auth/oauth_handler.py` — 唯一の消費者。`resolve_client_secrets_path()`（L112-128）が「実ファイル探索 → 見つからなければ `get_client_secrets_path()` フォールバック」を行い、`YouTubeOAuthHandler.__init__`（L172）が `self.client_secrets_file` に格納。`_validate_client_secrets()`（L252-285）がファイルを読んで JSON 形状検証、`authenticate()`（L334）が `from_client_secrets_file` に渡す
- `tests/test_secrets.py` / `tests/test_oauth_handler_main.py` ほか `tests/test_oauth_*.py` — 既存テスト。構造パターンの手本

`secrets.py:112-144`（現状・要旨）:

```python
def get_client_secrets_path() -> Path:
    global _client_secrets_tempfile
    if _client_secrets_tempfile and _client_secrets_tempfile.exists():
        return _client_secrets_tempfile
    json_content = get_secret("CLIENT_SECRETS_JSON")
    fd, path = tempfile.mkstemp(prefix="client_secrets_", suffix=".json")
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json_content)
    def _cleanup(p: str = path) -> None:
        if os.path.exists(p):
            os.unlink(p)
    atexit.register(_cleanup)
    _client_secrets_tempfile = Path(path)
    return _client_secrets_tempfile
```

`oauth_handler.py:112-128`（現状）:

```python
def resolve_client_secrets_path(channel_dir: Path | None = None) -> Path:
    """実行時 OAuth が使う client_secrets.json の検索順を解決する。"""
    if channel_dir is None:
        from youtube_automation.configuration import channel_dir as _channel_dir
        channel_dir = _channel_dir()
    kind, path = resolve_client_secrets_location(channel_dir)
    if kind in {"file", "invalid-file", "missing-file"}:
        return path
    try:
        from youtube_automation.utils.secrets import get_client_secrets_path
        return get_client_secrets_path()
    except ConfigError:
        return path
```

`oauth_handler.py:172`（`__init__` 内）:

```python
self.client_secrets_file = resolve_client_secrets_path(channel_dir)
```

`oauth_handler.py:273-285`（`_validate_client_secrets` の JSON 形状検証部）:

```python
try:
    data = json.loads(self.client_secrets_file.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError) as e:
    raise ValidationError(f"client_secrets.json 読み込み失敗: {e}") from e
if not isinstance(data, dict):
    raise ValidationError("client_secrets.json は JSON object である必要があります")
installed = data.get("installed")
if not isinstance(installed, dict):
    raise ValidationError("Desktop app の client_secrets.json が必要です: installed セクションがありません")
required_keys = ("client_id", "client_secret", "redirect_uris")
missing = [key for key in required_keys if key not in installed]
if missing:
    raise ValidationError(f"client_secrets.json に必須キー不足: {','.join(missing)}")
```

`oauth_handler.py:334`（`authenticate` 内）:

```python
flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self._scopes)
```

その他の `self.client_secrets_file` 参照（挙動を維持すべき箇所）: L354・L426 の `_redact(...)` 引数、L479 の `paths.extend([auth_handler.client_secrets_file, auth_handler.token_file])`。いずれも「パス表示/redact 用途」なので、フォールバック時も候補パス（`<channel_dir>/auth/client_secrets.json`）を指していれば足りる。

リポジトリ規約: fully-qualified import（`from youtube_automation.xxx import ...`）、ドメイン例外（`ConfigError` / `ValidationError` / `AuthError`、`utils/exceptions.py`）、docstring とコメントは日本語。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `uv run pytest tests/test_secrets.py tests/test_oauth_handler_main.py tests/test_oauth_handler_exceptions.py tests/test_oauth_worktree_fallback.py -q` | all pass |
| 全体テスト（高速レーン） | `uv run pytest -q -m "not slow and not repo_contract" -n auto` | all pass |
| Lint | `uv run ruff check src tests` | exit 0 |
| 残存参照確認 | `rg -n "get_client_secrets_path" src tests` | 移行後は 0 件（Step 4 完了時） |

## Scope

**In scope**（変更してよいファイル）:
- `src/youtube_automation/utils/secrets.py`
- `src/youtube_automation/auth/oauth_handler.py`
- `tests/test_secrets.py`
- `tests/test_oauth_handler_main.py`（必要な範囲で）
- `CHANGELOG.md`（`[Unreleased]` 追記 — src 変更のため必須ゲート）
- `plans/README.md`（status 更新）

**Out of scope**（触らない）:
- `src/youtube_automation/cli/doctor.py` — `_client_secrets_file_for_accounts` は実ファイル探索専用で tempfile 経路に依存しない
- `resolve_client_secrets_location()` / `client_secrets_file_candidates()`（oauth_handler.py L68-109）の探索順序・分類 — 変更禁止（doctor / onboarding が契約として依存、`tests/test_oauth_onboarding_contract.py` が監視）
- `write_op_secret()` / `get_secret()` 本体のシグネチャ

## Git workflow

- リポジトリ規約: 作業は必ず worktree（`$REPO_ROOT/.worktrees/<slug>/`）上で行う。main へ直接コミットしない
- Branch 例: `advisor/025-client-secrets-in-memory`
- Commit: 日本語 Conventional Commits（例: `fix(auth): client_secrets の 1Password フォールバックを in-memory 化する`）
- push / PR はオペレーターの指示があるまで行わない

## Steps

### Step 1: `secrets.py` に `get_client_secrets_config()` を追加

`get_secret("CLIENT_SECRETS_JSON")` の戻り値を `json.loads` して dict で返す関数を追加する:

```python
def get_client_secrets_config() -> dict:
    """client_secrets の JSON 内容を in-memory dict で取得する。

    tempfile を経由しないため、異常終了時にも secret がディスクに残らない。

    Raises:
        ConfigError: 取得できない、または JSON として解釈できない場合
    """
    raw = get_secret("CLIENT_SECRETS_JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"CLIENT_SECRETS_JSON を JSON として解釈できません: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError("CLIENT_SECRETS_JSON は JSON object である必要があります")
    return data
```

エラーメッセージに secret の値そのものを含めないこと（`{e}` は位置情報のみで値を含まないので可）。

**Verify**: `uv run pytest tests/test_secrets.py -q` → 既存 all pass（新関数はまだ未テストでよい）

### Step 2: `oauth_handler.py` をフォールバック時 in-memory 化

1. `resolve_client_secrets_path()` の tempfile フォールバック分岐（L123-128）を「候補パスをそのまま返す」に変更するのではなく、**新しい解決関数を追加**する:

```python
def resolve_client_secrets_source(channel_dir: Path | None = None) -> tuple[Path, dict | None]:
    """client_secrets の (表示用パス, in-memory config) を解決する。

    実ファイルがあれば (そのパス, None)。無ければ 1Password フォールバックを試み、
    成功時は (候補パス, dict)、失敗時は (候補パス, None) を返す。
    """
```

実装は現行 `resolve_client_secrets_path` のロジックを流用し、`kind == "secret-fallback"` のとき `get_client_secrets_config()` を試す（`ConfigError` は握って `(path, None)`）。

2. `__init__`（L172）を差し替え:

```python
self.client_secrets_file, self._client_secrets_config = resolve_client_secrets_source(channel_dir)
```

3. `_validate_client_secrets()`（L252-285）: JSON 形状検証部（L277-285 の dict / installed / required_keys チェック）をモジュールレベル関数 `_validate_client_secrets_data(data: dict) -> None` に抽出し、冒頭に分岐を追加:

```python
if self._client_secrets_config is not None:
    _validate_client_secrets_data(self._client_secrets_config)
    return
```

ファイル経路（既存の exists / is_file / read_text チェック）は現行どおり残し、抽出した `_validate_client_secrets_data` を呼ぶ形にする。エラーメッセージ文言は変更しない（onboarding contract テストが文言に依存する可能性がある）。

4. `authenticate()`（L334）を分岐:

```python
if self._client_secrets_config is not None:
    flow = InstalledAppFlow.from_client_config(self._client_secrets_config, self._scopes)
else:
    flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_file), self._scopes)
```

5. 旧 `resolve_client_secrets_path()` は他 callsite が無ければ削除、あれば `resolve_client_secrets_source()[0]` を返す thin wrapper として残す（`rg -n "resolve_client_secrets_path" src tests` で確認して判断）。

**Verify**: `uv run pytest tests/test_oauth_handler_main.py tests/test_oauth_handler_exceptions.py tests/test_oauth_onboarding_contract.py -q` → all pass

### Step 3: `secrets.py` から tempfile 機構を削除

`get_client_secrets_path()`・`_client_secrets_tempfile`・`atexit` cleanup（L109-144）と、不要になった `import atexit` / `import tempfile` を削除する。先に `rg -n "get_client_secrets_path" src tests` で参照ゼロ（tests 内の直接テストは Step 4 で書き換え）を確認すること。

**Verify**: `rg -n "get_client_secrets_path|_client_secrets_tempfile" src` → 0 件。`uv run ruff check src` → exit 0

### Step 4: テスト更新・追加

`tests/test_secrets.py` の既存構造（`monkeypatch.setenv` + `reset_cache`）に倣い:

- `get_client_secrets_config`: (a) env `CLIENT_SECRETS_JSON` に有効 JSON → dict が返る、(b) 不正 JSON → `ConfigError`、(c) JSON だが object でない（例 `"[]"`）→ `ConfigError`
- `get_client_secrets_path` の旧テストは削除または config 版に書き換え
- `tests/test_oauth_handler_main.py` に倣い、フォールバック経路のハンドラで: (d) `_validate_client_secrets()` が in-memory dict を検証し tempfile を作らない（`tmp_path` を `TMPDIR` に向けて `client_secrets_*` グロブが空であることを assert）、(e) `authenticate()` が `from_client_config` を呼ぶ（`InstalledAppFlow` を monkeypatch して呼び分けを assert）

**Verify**: `uv run pytest tests/test_secrets.py tests/test_oauth_handler_main.py -q` → all pass（新規 5 ケース以上を含む）

### Step 5: CHANGELOG 追記と最終確認

`CHANGELOG.md` の `[Unreleased]` に Security 項目として追記（例: 「1Password フォールバック時の client_secrets を tempfile 経由から in-memory 渡しに変更し、異常終了時のディスク残留を解消」）。

**Verify**: `uv run pytest -q -m "not slow and not repo_contract" -n auto` → all pass / `uv run ruff check src tests` → exit 0

## Test plan

上記 Step 4 の (a)〜(e)。構造パターンは `tests/test_secrets.py`（env + reset_cache）と `tests/test_oauth_handler_main.py`（ハンドラ初期化のフィクスチャ）に従う。`tests/conftest.py` が `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向け、`YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` が既定有効な点に注意（テストは env 経由で secret を注入する）。

## Done criteria

- [ ] `rg -n "get_client_secrets_path|mkstemp" src/youtube_automation/utils/secrets.py` → 0 件
- [ ] `rg -n "from_client_config" src/youtube_automation/auth/oauth_handler.py` → 1 件以上
- [ ] `uv run pytest tests/test_secrets.py tests/test_oauth_handler_main.py tests/test_oauth_handler_exceptions.py tests/test_oauth_onboarding_contract.py tests/test_oauth_worktree_fallback.py -q` → all pass
- [ ] `uv run pytest -q -m "not slow and not repo_contract" -n auto` → all pass
- [ ] `uv run ruff check src tests` → exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記あり
- [ ] in-scope 外のファイルに変更なし（`git status`）
- [ ] `plans/README.md` の status 更新

## STOP conditions

- "Current state" の抜粋と実コードが一致しない（drift）
- `resolve_client_secrets_path` の callsite が oauth_handler 以外に 3 箇所以上見つかった（設計判断が必要 — wrapper 維持で済むか advisor に確認）
- `tests/test_oauth_onboarding_contract.py` がエラーメッセージ文言の変更で fail した（文言を戻しても解消しない場合）
- `InstalledAppFlow.from_client_config` がインストール済み `google-auth-oauthlib` に存在しない（バージョン確認の上報告）

## Maintenance notes

- 今後 `client_secrets` の新しい消費者を追加する場合は、パスではなく `resolve_client_secrets_source()` を使い、tempfile 復活させないこと
- レビュー観点: フォールバック時のエラーメッセージ UX（「client_secrets.json が見つかりません」ガイド文）が従来どおり出ること
- 見送った follow-up: 実ファイル経路（`auth/client_secrets.json`）自体の in-memory 化は不要（ユーザー自身が置いた永続ファイルであり脅威モデルが異なる）
