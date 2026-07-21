# Plan 027: open / ffmpeg に渡すパス引数を絶対パス化してフラグ誤解釈の余地を消す

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 37b362ce..HEAD -- src/youtube_automation/scripts/stock_preview.py src/youtube_automation/scripts/compare_thumbnails.py src/youtube_automation/utils/upload_core.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（`.resolve()` の付加のみ。挙動は同一）
- **Depends on**: none
- **Category**: security（defense-in-depth。悪用可能な欠陥ではない）
- **Planned at**: commit `37b362ce`, 2026-07-21

## Why this matters

`open` / `ffmpeg` の argv にファイルシステム由来のパスを渡す箇所が数箇所あり、仮に先頭が `-` のパスが混入するとフラグとして解釈される余地がある（shell は経由しないので RCE 経路は無く、実害は「想定外フラグで失敗する」程度）。第 5 回セキュリティ監査（2026-07-21）の vet では、**現状の全呼び出し箇所の入力はディレクトリ結合済み Path であり先頭 `-` になり得ない（= 現時点で悪用不能）** ことを確認済み。本プランは、将来のリファクタで相対パスが混入しても安全なままにする純粋な defense-in-depth であり、優先度は最低。手が空いたときに実施すればよい。

**重要**: サブエージェント監査が提案した「`--` セパレータの挿入」は採用しない。**ffmpeg は `--` による end-of-options をサポートしない**ため壊れる。正しい対策は「argv に渡す時点で絶対パスであることを保証する（`.resolve()`）」こと。絶対パスは `/` 始まりなのでフラグ解釈され得ない。

## Current state

対象 3 ファイル・4 箇所:

`src/youtube_automation/scripts/stock_preview.py:48,59` — stock 画像の一括プレビュー:

```python
    paths = [str(e.image_path) for e in entries]
    ...
    subprocess.run(["open", *paths], check=False)
```

`src/youtube_automation/scripts/compare_thumbnails.py:75-79` — サムネの 320px 縮小:

```python
            subprocess.run(
                ["ffmpeg", "-i", str(input_path), "-vf", f"scale={SMALL_WIDTH}:{SMALL_HEIGHT}", "-y", str(output_path)],
                capture_output=True,
                check=True,
            )
```

`src/youtube_automation/scripts/compare_thumbnails.py:149` — 比較ディレクトリを Finder で開く:

```python
            subprocess.run(["open", str(self.small_dir if small_only else self.compare_dir)])
```

`src/youtube_automation/utils/upload_core.py:271-274` — サムネの JPEG 圧縮:

```python
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(thumbnail_path), "-qscale:v", str(quality), str(compressed)],
                capture_output=True,
            )
```

リポジトリ規約: コメントは「コードで表せない制約」のみ日本語で書く。既存テスト `tests/test_upload_core_thumbnail.py` が `_compress_thumbnail` をカバー。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `uv run pytest tests/test_upload_core_thumbnail.py -q` | all pass |
| 全体テスト（高速レーン） | `uv run pytest -q -m "not slow and not repo_contract" -n auto` | all pass |
| Lint | `uv run ruff check src tests` | exit 0 |

## Scope

**In scope**:
- `src/youtube_automation/scripts/stock_preview.py`
- `src/youtube_automation/scripts/compare_thumbnails.py`
- `src/youtube_automation/utils/upload_core.py`
- `tests/test_upload_core_thumbnail.py`（アサート追加のみ）
- `CHANGELOG.md`（`[Unreleased]` 追記 — src 変更のため必須ゲート）
- `plans/README.md`（status 更新）

**Out of scope**:
- リポジトリ内の他の subprocess 呼び出し（監査で argv リスト形式・安全と確認済み。網羅的な書き換えはノイズ）
- `--` セパレータの導入（ffmpeg 非対応のため禁止）
- ffprobe 側（`utils/veo_generator.py:433` は既に `--` 付きで対応済み — ffprobe は `--` をサポートする）

## Git workflow

- 作業は worktree（`$REPO_ROOT/.worktrees/<slug>/`）上で行う
- Branch 例: `advisor/027-argv-absolute-path-hardening`
- Commit 例: `fix(scripts): subprocess へ渡すパス引数を絶対パス化する`
- push / PR はオペレーターの指示があるまで行わない

## Steps

### Step 1: 4 箇所のパス引数に `.resolve()` を付加

- `stock_preview.py:48`: `paths = [str(e.image_path.resolve()) for e in entries]`（`--print-only` の出力も絶対パスになるが、絶対パス表示はプレビュー用途としてむしろ望ましい）
- `compare_thumbnails.py:76`: `str(input_path.resolve())` / `str(output_path.resolve())`（`output_path` は `-y` の後ろの出力先。resolve は親が存在すれば非存在ファイルでも動く — `small_dir` は L92-93 で `mkdir` 済み）
- `compare_thumbnails.py:149`: `str((self.small_dir if small_only else self.compare_dir).resolve())`
- `upload_core.py:272`: `str(thumbnail_path.resolve())`（`compressed` は `NamedTemporaryFile` 由来で常に絶対パスなのでそのままでよいが、揃えて `.resolve()` しても害はない）

**Verify**: `uv run ruff check src` → exit 0

### Step 2: 回帰アサートの追加

`tests/test_upload_core_thumbnail.py` の既存テスト構造に倣い、`subprocess.run` を monkeypatch して受け取った argv の入力パス（`-i` の次要素）が `os.path.isabs()` で True であることを assert する 1 ケースを追加（相対パスの `thumbnail_path` を渡して確認）。

**Verify**: `uv run pytest tests/test_upload_core_thumbnail.py -q` → all pass（新規 1 ケース含む）

### Step 3: CHANGELOG 追記と最終確認

`CHANGELOG.md` の `[Unreleased]` に追記（例: 「open / ffmpeg へ渡すパス引数を絶対パス化（defense-in-depth）」）。

**Verify**: `uv run pytest -q -m "not slow and not repo_contract" -n auto` → all pass

## Test plan

Step 2 の 1 ケースのみ（`_compress_thumbnail` 経由で argv 絶対パスを assert）。`stock_preview` / `compare_thumbnails` は表示系スクリプトで既存テストが薄ければ新設不要（変更が `.resolve()` 付加のみで、失敗モードは既存と同一のため）。

## Done criteria

- [ ] 上記 4 箇所すべてに `.resolve()` が入っている
- [ ] `rg -n '"--"' src/youtube_automation/scripts/stock_preview.py src/youtube_automation/scripts/compare_thumbnails.py src/youtube_automation/utils/upload_core.py` → 0 件（誤って `--` 方式を採らなかったことの確認）
- [ ] `uv run pytest tests/test_upload_core_thumbnail.py -q` → all pass
- [ ] `uv run pytest -q -m "not slow and not repo_contract" -n auto` → all pass
- [ ] `uv run ruff check src tests` → exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記あり
- [ ] in-scope 外のファイルに変更なし（`git status`）
- [ ] `plans/README.md` の status 更新

## STOP conditions

- "Current state" の抜粋と実コードが一致しない（drift）
- `.resolve()` 付加でテストが fail し、原因が symlink 解決による期待パスのズレだった場合（`compare_thumbnails` は symlink を作る — L126。resolve が symlink 実体を指して既存挙動と変わるようなら、そのファイルだけ `Path.absolute()` に切り替えて報告）

## Maintenance notes

- 今後 subprocess にパスを渡すときの規約: argv に入れる時点で絶対パス（`.resolve()`）にする。`--` は ffmpeg では使えない
- レビュー観点: `compare_thumbnails.py` の symlink（L126）と resolve の相互作用のみ
- 見送った follow-up: 全 subprocess 呼び出し（~30 箇所）への一括適用 — 監査で安全確認済みのためノイズと判断
