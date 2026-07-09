# Plan 020: アップロード経路の堅牢化 — tracking 書き込みのアトミック化・QuotaExhaustedError の非終端化・サムネ temp リーク解消

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 5394c378..HEAD -- src/youtube_automation/agents/_tracking_io.py src/youtube_automation/agents/_complete_collection_executor.py src/youtube_automation/agents/short_uploader.py src/youtube_automation/agents/_collection_uploader_constants.py src/youtube_automation/utils/upload_core.py`
> 差分が出た in-scope ファイルは「Current state」の抜粋と実コードを突き合わせ、
> 不一致なら STOP condition として扱う。

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5394c378`, 2026-07-09

## Why this matters

このリポジトリの存在理由である「無人アップロード」経路に、独立した 3 つの堅牢性欠陥がある。(1) `upload_tracking.json` が非アトミック書き込みで、アップロード中のクラッシュで truncate されると次回実行が「tracking なし」と誤認して video_id / resume session URI を喪失し再アップロード走行する。(2) `upload_core` が明示的に「リトライ可能」として raise する `QuotaExhaustedError`（retry_after_seconds 付き）が、agents 側の生 `except Exception` に吸われてコレクション恒久失敗（`status="failed"`）として記録され、オペレーターは「時間をおいて再実行すれば直る」というシグナルを失う。(3) サムネイル圧縮が全品質で失敗した場合、temp ファイルをリークした上で 2MB 超の元ファイルをそのまま API に投げて確実に失敗する。3 件とも同一サブシステム（agents + upload_core）の S 級修正なので 1 プランにまとめる。

## Current state

対象ファイルと役割:

- `src/youtube_automation/agents/_tracking_io.py` — tracking / workflow-state JSON I/O の mixin（CollectionUploader に合成される）
- `src/youtube_automation/agents/_complete_collection_executor.py` — Complete Collection アップロードの実行 mixin
- `src/youtube_automation/agents/short_uploader.py` — ショート 1 本のアップロード agent（1 実行 = 1 本）
- `src/youtube_automation/agents/_collection_uploader_constants.py` — action 文字列定数
- `src/youtube_automation/utils/upload_core.py` — resumable upload / サムネ設定の共通エンジン

### (1) 非アトミック書き込み + 破損の無言 None（_tracking_io.py:31-51）

```python
    def _load_tracking(self, collection_path: Path) -> dict | None:
        """tracking ファイル読み込み"""
        tracking_file = self._get_tracking_path(collection_path)
        if not tracking_file.exists():
            return None

        try:
            with open(tracking_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_tracking(self, collection_path: Path, tracking: dict):
        """tracking 保存"""
        tracking_file = self._get_tracking_path(collection_path)
        tracking_file.parent.mkdir(exist_ok=True)
        try:
            with open(tracking_file, "w", encoding="utf-8") as f:
                json.dump(tracking, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"⚠️  追跡ファイル保存エラー: {e}")
```

リポジトリ既存のアトミック書き込み規約（これに合わせる）— `src/youtube_automation/utils/comments/history.py:65-71`:

```python
    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        # 途中断絶時の履歴破損を防ぐため tmp に書いてから rename で差し替える
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, self._path)
```

### (2) QuotaExhaustedError が終端 failed に潰される

raise 側 — `src/youtube_automation/utils/upload_core.py:204-208`（429 リトライ枯渇時）:

```python
                elif status_code == 429:
                    raise QuotaExhaustedError(
                        f"YouTube API の quota 超過/レート制限。時間をおいて再実行してください: {e}",
                        retry_after_seconds=retry_after,
                    ) from e
```

例外クラス — `src/youtube_automation/utils/exceptions.py:45-54`。`retry_after_seconds: float | None` 属性を持ち、docstring に「時間をおいて再実行することで resume 可能であることを呼び出し側に明示する」とある。**呼び出し側がその契約を無視しているのが本バグ**。

握りつぶし箇所 1 — `src/youtube_automation/agents/_complete_collection_executor.py:110-118`:

```python
        except Exception as e:
            # 例外パスでも callback が書いた disk 状態を尊重するため再ロード
            current = self._load_tracking(collection_path) or tracking
            cc_current = current.setdefault("complete_collection", {})
            cc_current["status"] = "failed"
            cc_current["error"] = str(e)
            self._save_tracking(collection_path, current)
            logger.error(f"❌ Complete Collection エラー: {e}")
            return {"action": "complete_collection_failed", "details": {"error": str(e)}}
```

握りつぶし箇所 2 — `src/youtube_automation/agents/short_uploader.py:308-319`:

```python
        try:
            video_id = self.uploader.upload_video(
                str(video_path),
                metadata,
                thumbnail_path,
                resume_session_uri=resume_session_uri,
                on_session_uri_changed=_on_session_uri_changed,
                on_upload_complete=_on_upload_complete,
            )
        except Exception as e:
            logger.error(f"❌ upload_video 失敗: {e}")
            return {"action": ACTION_FAILED, "details": {"error": str(e)}}
```

action 文字列の消費側は 1 箇所のみ（確認済み）: `short_uploader.py:515` の `if result["action"] == ACTION_FAILED: sys.exit(1)`。Complete Collection 側の action 文字列を閉集合として分岐する消費側は存在しない。

定数ファイル — `_collection_uploader_constants.py:8-9` に `ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED` / `ACTION_COMPLETE_COLLECTION_UPLOADED` があり、`__all__` にも列挙されている。

### (3) サムネ temp リーク — `src/youtube_automation/utils/upload_core.py:256-284`

```python
        tmp_fd = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_fd.close()
        compressed = Path(tmp_fd.name)
        failed_qualities: set[int] = set()

        while (quality := strategy.next_quality(failed_qualities)) is not None:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(thumbnail_path), "-qscale:v", str(quality), str(compressed)],
                capture_output=True,
            )
            if compressed.exists() and compressed.stat().st_size <= max_bytes:
                ...
                return compressed
            failed_qualities.add(quality)

        logger.warning(f"サムネイル圧縮後も {compressed.stat().st_size / 1024:.0f}KB — 上限超過")
        return thumbnail_path
```

全品質失敗時（および ffmpeg が一度も出力しなかった場合）、`compressed` は unlink されない。呼び出し側 `set_thumbnail`（同ファイル :245-246）は「返り値 ≠ 入力パス」のときだけ unlink するため、元パスが返るこの経路では temp が残る。さらに `compressed.stat()` は ffmpeg が一度も書けなかった場合 `FileNotFoundError` を起こす。

### 適用される規約

- エラーハンドリング: `utils/exceptions.py` のドメイン例外を使う。生 `Exception` / `KeyError` を catch しない（CLAUDE.md）。既存の広い catch を**狭める方向のみ**変更し、挙動互換を保つ。
- `src/youtube_automation/` を触るため `CHANGELOG.md` の `[Unreleased]` 追記が必須（lefthook pre-push + CI ゲート）。
- import は fully-qualified（`from youtube_automation.xxx import ...`）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `uv run pytest tests/test_collection_uploader.py tests/test_short_uploader.py tests/integration/test_upload_core.py -q` | all pass |
| 全テスト | `uv run pytest -q` | all pass（約 5,000 件） |
| Lint | `uv run ruff check src tests` | exit 0 |
| Format | `uv run ruff format --check src tests` | exit 0 |

## Scope

**In scope**（変更してよいファイルはこれだけ）:

- `src/youtube_automation/agents/_tracking_io.py`
- `src/youtube_automation/agents/_complete_collection_executor.py`
- `src/youtube_automation/agents/short_uploader.py`
- `src/youtube_automation/agents/_collection_uploader_constants.py`
- `src/youtube_automation/utils/upload_core.py`（`_compress_thumbnail` のみ）
- `tests/test_collection_uploader.py`, `tests/test_short_uploader.py`, `tests/test_upload_core_thumbnail.py`（新規可）
- `CHANGELOG.md`（`[Unreleased]` 追記）

**Out of scope**（関連して見えても触らない）:

- `upload_core.py` の `_resumable_upload` リトライロジック本体 — 正しく動いており、テスト済み（`tests/integration/test_upload_core.py:212-225`）
- `_update_workflow_upload`（`_tracking_io.py:65-92`）の `write_text` — workflow-state はこのプランの対象外。tracking と違い書き込み頻度が低く、別途判断
- `youtube_auto_uploader.py` — 同種の catch があっても本プランでは触らない（スコープ膨張防止）
- tracking JSON のスキーマ変更（`schema_version` bump が要る変更は一切しない）

## Git workflow

- worktree 上で作業（`$REPO_ROOT/.worktrees/<slug>/`、リポジトリ規約）。base branch は main
- commit 規約: 日本語 Conventional Commits。例: `fix(agents): tracking JSON をアトミック書き込み化し QuotaExhaustedError を非終端化 (#<issue>)`（issue 未起票なら `(#N)` は省略可）
- push / PR 化はオペレーターの指示があるときのみ

## Steps

### Step 1: `_save_tracking` をアトミック書き込みにする

`_tracking_io.py` の `_save_tracking` を `history.py:65-71` と同じ tmp + `os.replace` パターンに変更する。`import os` を追加。外側の `try/except Exception` は「保存失敗でアップロード続行を止めない」という現行挙動を守るため**残してよい**が、`logger.warning` を `logger.error` に格上げし、メッセージにファイルパスを含める。

**Verify**: `uv run pytest tests/test_collection_uploader.py -q` → all pass

### Step 2: `_load_tracking` で「無い」と「壊れている」を区別する

`except Exception: return None` を以下に置き換える:

- `json.JSONDecodeError` / `UnicodeDecodeError` を catch した場合: 破損ファイルを `tracking_file.with_suffix(".json.corrupt")` へ `os.replace` で退避し、`logger.error` で「tracking 破損を検出、<path> へ退避。再アップロード前に dedup 探索が働く」と記録して `None` を返す（現行のリカバリ挙動は維持しつつ、証拠を保全し無言でなくす）
- `OSError` はそのまま raise させる（catch しない）

**Verify**: `uv run pytest tests/test_collection_uploader.py -q` → all pass

### Step 3: QuotaExhaustedError を Complete Collection 経路で非終端化する

1. `_collection_uploader_constants.py` に `ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED = "complete_collection_quota_exhausted"` を追加し `__all__` にも載せる
2. `_complete_collection_executor.py` の `except Exception` の**前**に追加:

```python
        except QuotaExhaustedError as e:
            # リトライ可能: tracking を failed にせず、resume URI（callback が永続化済み）を
            # 温存して次回実行に委ねる
            logger.error(f"⏸️  quota 枯渇のため中断（再実行で resume）: {e}")
            return {
                "action": ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
                "details": {"error": str(e), "retry_after_seconds": e.retry_after_seconds},
            }
```

import は `from youtube_automation.utils.exceptions import QuotaExhaustedError`。**tracking への `status="failed"` 書き込みをしない**のがこの分岐の要点。

**Verify**: `uv run pytest tests/test_collection_uploader.py -q` → all pass

### Step 4: QuotaExhaustedError を short_uploader 経路で区別する

`short_uploader.py:317` の `except Exception` の前に `except QuotaExhaustedError as e:` を追加し、`{"action": ACTION_FAILED, "details": {"error": str(e), "retryable": True, "retry_after_seconds": e.retry_after_seconds}}` を返す（exit code 挙動は :515 で従来どおり 1 のまま — 消費側変更なし）。ログは「quota 枯渇・時間をおいて再実行してください」と明示する。

**Verify**: `uv run pytest tests/test_short_uploader.py -q` → all pass

### Step 5: `_compress_thumbnail` の temp リークと oversize 続行を直す

失敗経路（while ループを抜けた後）で:

1. `compressed.unlink(missing_ok=True)` してから return する
2. `compressed.stat()` を呼ぶ前に `compressed.exists()` を確認する（ffmpeg が一度も出力しなかった場合の `FileNotFoundError` 回避）。ログは「圧縮失敗、元ファイル(<size>KB)のまま試行」の形に修正

返り値の意味（失敗時は元パスを返す）は変えない — `set_thumbnail` 側の挙動互換のため。

**Verify**: `uv run pytest tests/integration/test_upload_core.py -q` → all pass

### Step 6: CHANGELOG 追記 + 全体検証

`CHANGELOG.md` の `[Unreleased]` に Fixed として 3 点を 1 行ずつ追記。

**Verify**: `uv run pytest -q` → all pass / `uv run ruff check src tests` → exit 0 / `uv run ruff format --check src tests` → exit 0

## Test plan

既存テストの構造パターン: `tests/test_collection_uploader.py`（CollectionUploader をフェイク config で組み、mixin メソッドを直接叩く）と `tests/integration/test_upload_core.py:212-225`（`pytest.raises(QuotaExhaustedError)` の先例）。

新規テスト（各 Step の中で書いてもよいが、最終的に以下が揃うこと）:

1. `_save_tracking` 後に `*.tmp` が残っていない + 内容がラウンドトリップする
2. 破損 JSON（`"{truncated"` を書いたファイル）で `_load_tracking` → `None` が返り、`.json.corrupt` 退避ファイルが存在する
3. `upload_collection` が `QuotaExhaustedError(retry_after_seconds=42.0)` を raise するようモックした場合: 返り値 action が `complete_collection_quota_exhausted`、`details["retry_after_seconds"] == 42.0`、かつ tracking の `complete_collection.status` が `"failed"` になっ**ていない**こと
4. short_uploader: `upload_video` が `QuotaExhaustedError` を raise → `details["retryable"] is True`
5. `_compress_thumbnail`: `strategy.next_quality` が即 `None` を返すよう最小サイズ超ファイル + ffmpeg 不発を模擬（`subprocess.run` を monkeypatch）→ 返り値が元パスで、temp ファイルが残っていない（`tmp_path` fixture 配下を検査、または `tempfile.tempdir` を monkeypatch）

**Verification**: `uv run pytest tests/test_collection_uploader.py tests/test_short_uploader.py tests/integration/test_upload_core.py -q` → all pass、新規 5 ケースを含む

## Done criteria

- [ ] `uv run pytest -q` exit 0
- [ ] `uv run ruff check src tests` / `uv run ruff format --check src tests` exit 0
- [ ] `rg -n 'except Exception' src/youtube_automation/agents/_tracking_io.py` のヒットが `_save_tracking` 内の 1 件以下
- [ ] `rg -n 'QuotaExhaustedError' src/youtube_automation/agents/` が `_complete_collection_executor.py` と `short_uploader.py` の両方でヒットする
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] `git status` で in-scope 外の変更がない
- [ ] `plans/README.md` の 020 行を更新

## STOP conditions

以下が起きたら中断して報告（改変で乗り切らない）:

- Drift check で in-scope ファイルに差分があり、「Current state」の抜粋と実コードが一致しない
- `result["action"]` を閉集合として分岐する消費側が `short_uploader.py:515` 以外に見つかった（新 action 追加が安全でなくなる）
- tracking JSON の `schema_version` を変えないと実装できない事態になった
- Step の Verify が修正 1 回を挟んで 2 回失敗した

## Maintenance notes

- 将来 `_update_workflow_upload`（workflow-state 書き込み）もアトミック化するなら、Step 1 で入れたパターンを `utils/` の共有ヘルパーに昇格させる価値が出る（今回は 2 箇所目ができるまで YAGNI で見送り）
- レビューで見るべき点: (a) quota 分岐で tracking に `failed` が**書かれない**こと、(b) `.json.corrupt` 退避が `os.replace`（同一 FS 内 rename）であること
- 明示的に先送り: `youtube_auto_uploader.py` の同種 catch の監査、`get_recent_videos` 系（Plan 022 が担当）
