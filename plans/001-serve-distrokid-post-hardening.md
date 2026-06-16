# Plan 001: POST /distrokid/releases の入力検証と POST body サイズ上限を追加する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat fa296fe..HEAD -- src/youtube_automation/scripts/collection_serve.py tests/test_distrokid_collections_endpoint.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `fa296fe`, 2026-06-12
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/953

## Why this matters

`yt-collection-serve` の `POST /distrokid/releases` は、distrokid-helper Chrome 拡張がフォーム自動入力完了後に「この disc は配信済み」と記録するためのエンドポイントで、`<channel_root>/config/distrokid-releases.json` に書き込まれる。現状 2 つの弱点がある:

1. **collection_id / disc の実在チェックがない** — 非空文字列であれば何でも書き込まれる。CORS 許可済み origin（distrokid.com 上の悪意ページ、または同一マシン上の任意の Chrome 拡張 — CORS は `chrome-extension://` scheme を全許可）から偽の「配信済み」キーを注入でき、拡張の popup ドロップダウンから未配信 disc が消える（運用事故: その disc が配信されないまま放置される）。
2. **POST body の Content-Length に上限がない** — `self.rfile.read(length)` が無制限で、巨大な Content-Length を申告するローカルクライアントがメモリを枯渇させられる。`/suno/playlists` も同じ穴を持つ。

サーバーは `localhost` bind の個人用ツールであり脅威は限定的だが、両修正とも数行で済みリスクがほぼゼロのため対処する価値がある。

## Current state

- `src/youtube_automation/scripts/collection_serve.py` — stdlib `ThreadingHTTPServer` ベースの配信サーバー。`create_server()`（line 431）がクロージャでハンドラを生成する。
- `tests/test_distrokid_collections_endpoint.py` — `/distrokid/*` エンドポイントのユニットテスト。POST のテストは line 719 以降。

`create_server()` のシグネチャ（`collection_serve.py:431-455`）。POST ハンドラのクロージャから `collections_root`（dir mode のコレクションルート、単一 mode では `None`）と `capture_root` が見える:

```python
def create_server(
    port: int,
    allow_origin: str | None,
    *,
    prompts_path: Path | None,
    collection_dir: Path | None,
    distrokid: Distrokid | None,
    collections_root: Path | None = None,
    distrokid_source: str | None = None,
    playlist_capture: tuple[Path, str] | None = None,
) -> ThreadingHTTPServer:
    ...
    dir_mode = collections_root is not None
    distrokid_enabled = distrokid is not None and distrokid.enabled
    capture_root, capture_prefix = playlist_capture if playlist_capture is not None else (None, None)
```

POST ハンドラの該当部（`collection_serve.py:496-559`、抜粋）。**両ルートとも `Content-Length` を無制限に read している**（line 509-510 と 537-538）。`/distrokid/releases` は非空チェックのみ（line 547-554）:

```python
        def do_POST(self) -> None:  # noqa: N802
            origin = self._allowed_origin()

            # POST /suno/playlists: capture 有効時のみ（#893 要件5）。
            if self.path == SUNO_PLAYLISTS_ROUTE:
                ...
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                ...

            # POST /distrokid/releases: capture 有効時のみ（#934）。
            if self.path == _DISTROKID_RELEASES_ROUTE:
                ...
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_error(400, "Bad Request")
                    return
                if not isinstance(payload, dict):
                    self.send_error(400, "Bad Request")
                    return
                coll_id = payload.get("collection_id")
                disc = payload.get("disc")
                album_title = payload.get("album_title")
                if not coll_id or not disc or not album_title:
                    # 必須フィールド欠落は 400（#934）。
                    self.send_error(400, "Bad Request")
                    return
                write_distrokid_release(capture_root, coll_id, disc, album_title)
```

検証に使える既存関数（同ファイル内）:

- `find_collection_dirs(root: Path) -> list[Path]`（line 354）— `root` 直下の `*-collection` ディレクトリを列挙。
- `find_distrokid_discs(collection_dir: Path) -> list[str]`（line 202）— `<collection_dir>/30-distrokid/<disc>/` のうち mp3 を含む disc 名を列挙。

リポジトリ規約:

- エラーは `send_error(400, "Bad Request")` のスタイルを踏襲（既存 POST ハンドラに合わせる。`_send_json_error` は GET の ConfigError 用 #944）。
- 例外は `utils/exceptions.py` のドメイン例外を使い、生 `Exception` を catch しない。ここでは新規例外は不要。
- テストは Given/When/Then docstring の日本語スタイル（下記 Test plan の exemplar 参照）。
- **`src/youtube_automation/` を変更するため `CHANGELOG.md` の `[Unreleased]` への追記が必須**（pre-push の changelog ゲートと CI が落ちる）。

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| 対象テスト | `uv run pytest tests/test_distrokid_collections_endpoint.py -q` | all pass |
| 全ユニット | `uv run pytest tests/ -q --ignore=tests/integration` | all pass |
| Lint | `uv run ruff check src/youtube_automation/scripts/collection_serve.py tests/test_distrokid_collections_endpoint.py` | exit 0 |
| Format | `uv run ruff format --check src/youtube_automation/scripts/collection_serve.py tests/test_distrokid_collections_endpoint.py` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/youtube_automation/scripts/collection_serve.py`
- `tests/test_distrokid_collections_endpoint.py`
- `CHANGELOG.md`（`[Unreleased]` への追記）

**Out of scope** (do NOT touch, even though they look related):

- `extensions/distrokid-helper/**` — 拡張側は正しい値しか送らないので変更不要。
- `write_distrokid_release()` 自体のロック追加（TOCTOU race）— 単一オペレーター運用で実発生確率がほぼゼロと判断し、意図的に見送り（plans/README.md の rejected 欄参照）。
- `is_origin_allowed()` の CORS 仕様変更 — 別判断（unpacked 拡張は ID がマシンごとに変わるため pin は運用コストが高い）。

## Git workflow

- このリポジトリは **worktree 必須**。main 作業ツリーで直接編集しない:
  `git -C /Users/mba/02-yt/automation pull --ff-only && git -C /Users/mba/02-yt/automation worktree add .worktrees/serve-post-hardening -b fix/serve-distrokid-post-hardening` し、その worktree 内で作業する。
- Commit 規約: 日本語 Conventional Commits。例: `fix(collection-serve): POST /distrokid/releases に実在検証と body サイズ上限を追加`
- push / PR 作成はオペレーターの指示があるまで行わない。

## Steps

### Step 1: POST body サイズ上限を追加する

`collection_serve.py` のモジュールレベル定数群（`_DISTROKID_RELEASES_ROUTE = "/distrokid/releases"` がある line 79 付近）に追加:

```python
# POST body の上限バイト数。両 POST ルートとも小さな JSON しか受けないため 1 MiB で十分。
_MAX_POST_BODY_BYTES = 1024 * 1024
```

`do_POST` 内の **2 箇所**（`/suno/playlists` と `/distrokid/releases`）で、`length = int(...)` の直後・`self.rfile.read` の前にガードを挿入:

```python
                if length > _MAX_POST_BODY_BYTES:
                    self.send_error(413, "Payload Too Large")
                    return
```

**Verify**: `uv run pytest tests/test_distrokid_collections_endpoint.py -q` → 既存テストが全て pass（回帰なし）

### Step 2: collection_id / disc の実在検証を追加する

`/distrokid/releases` ハンドラ内、非空チェック（`if not coll_id or not disc or not album_title:`）の直後・`write_distrokid_release(...)` の前に挿入:

```python
                # dir mode では実在する collection/disc のみ記録を受け付ける（偽の配信済み注入を防ぐ）。
                # 単一ファイル mode（collections_root=None）は従来挙動を維持する。
                if collections_root is not None:
                    coll_dir = collections_root / coll_id
                    if coll_dir not in find_collection_dirs(collections_root) or disc not in find_distrokid_discs(coll_dir):
                        self.send_error(400, "Bad Request")
                        return
```

注意: `find_collection_dirs` / `find_distrokid_discs` は同一モジュール内のトップレベル関数なので import 追加は不要。`coll_id` に `../` 等が含まれる場合も `coll_dir not in find_collection_dirs(...)` の比較で弾かれる（列挙結果は `root.iterdir()` 由来のため）。

**Verify**: `uv run pytest tests/test_distrokid_collections_endpoint.py -q` → 既存テストが全て pass（既存テストは実在する collection/disc を使っているため壊れないはず。壊れたら STOP 条件参照）

### Step 3: 新規テストを追加する

Test plan の節を参照して `tests/test_distrokid_collections_endpoint.py` の `# POST /distrokid/releases` セクション（line 719 以降）にテストを追加する。

**Verify**: `uv run pytest tests/test_distrokid_collections_endpoint.py -q` → 全 pass（新規 4 件を含む）

### Step 4: CHANGELOG 追記と最終確認

`CHANGELOG.md` の `[Unreleased]` セクションに既存エントリの体裁に合わせて追記する（例: `### Fixed` 配下に「`POST /distrokid/releases` に collection/disc の実在検証と POST body 1 MiB 上限を追加」）。

**Verify**: `uv run ruff check src/youtube_automation/scripts/collection_serve.py tests/test_distrokid_collections_endpoint.py && uv run ruff format --check src/youtube_automation/scripts/collection_serve.py tests/test_distrokid_collections_endpoint.py` → exit 0

## Test plan

`tests/test_distrokid_collections_endpoint.py` に追加。構造は既存の `test_post_distrokid_releases_writes_file_and_returns_recorded`（line 731、Given/When/Then docstring + `_make_collection` + `serve_dir_dk` fixture + `_post` ヘルパ + `_EXTENSION_ORIGIN` ヘッダ）をそのまま踏襲する:

1. `test_post_distrokid_releases_unknown_collection_returns_400` — 実在しない `collection_id` を POST → `urllib.error.HTTPError` code 400、かつ `distrokid-releases.json` が作られない（または該当キーが無い）。
2. `test_post_distrokid_releases_unknown_disc_returns_400` — 実在 collection + 実在しない `disc` → 400。
3. `test_post_distrokid_releases_oversized_body_returns_413` — `_post` に `1024 * 1024 + 1` バイトの bytes body（例: `b"x" * (1024 * 1024 + 1)`）を渡す → HTTPError code 413。
4. `test_post_suno_playlists_oversized_body_returns_413` — `/suno/playlists` ルートにも同様の 413 テスト（既存の suno playlists テストがあるファイルが別なら、このファイルではなくそちらに置く。`grep -rn "suno/playlists" tests/` で確認すること）。

**Verification**: `uv run pytest tests/ -q --ignore=tests/integration` → 全 pass

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `uv run pytest tests/ -q --ignore=tests/integration` exits 0; 上記 4 テストが存在し pass する
- [ ] `uv run ruff check` / `uv run ruff format --check`（変更ファイル対象）exits 0
- [ ] `grep -n "_MAX_POST_BODY_BYTES" src/youtube_automation/scripts/collection_serve.py` が定数定義 + 2 箇所の使用（計 3 行以上）を返す
- [ ] `CHANGELOG.md` の `[Unreleased]` に本変更のエントリがある
- [ ] `git status` で in-scope 外のファイルが変更されていない
- [ ] `plans/README.md` の status 行を更新済み

## STOP conditions

Stop and report back (do not improvise) if:

- "Current state" の抜粋と実コードが一致しない（`do_POST` の構造が変わっている等）。
- Step 2 の後で**既存**テストが落ちる — 既存テストが実在しない collection/disc で POST 成功を期待している場合、検証仕様自体の再検討が必要。
- 単一ファイル mode で拡張が POST /distrokid/releases を使う経路が見つかった場合（`extensions/distrokid-helper` を grep して `recordDistrokidRelease` 呼び出し元が dir mode 以外にもある場合）— 検証の gating 方針に影響する。
- 検証コマンドが 2 回の修正試行後も失敗する。

## Maintenance notes

- 将来 `30-distrokid/` 以外の disc レイアウトが追加される場合、`find_distrokid_discs` の仕様変更がこの検証にも波及する。
- レビューで見るべき点: 413 ガードが **read の前**にあること（読んでから弾くのでは意味がない）、検証が dir mode のみに gating されていること。
- 見送った follow-up: `write_distrokid_release` のファイルロック（TOCTOU）、CORS の拡張 ID pin。理由は Scope 欄と plans/README.md 参照。
