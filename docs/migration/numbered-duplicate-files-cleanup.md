# 番号付き重複ファイル (`yt-analytics 2` 等) のクリーンアップ手順

下流チャンネルリポジトリの `.venv/bin/` や `.claude/skills/` に
`yt-analytics 2`, `SKILL 2.md` のような「スペース + 連番」付きの重複ファイルが
蓄積した場合の復旧手順。原因調査の詳細は
[#1409](https://github.com/daiki-beppu/youtube-automation/issues/1409)、
検知機能の整備は [#1410](https://github.com/daiki-beppu/youtube-automation/issues/1410) を参照。

## 症状

- `.venv/bin/` に `<コマンド名> <数字>` 形式のファイルが大量に溜まる
- `.claude/skills/` にも同形式の重複が混入し、気づかず commit されることがある
- `uv run` のたびに以下の warning が出て uninstall → reinstall が繰り返される

```
warning: Failed to uninstall package at .venv/lib/python3.X/site-packages/youtube_channels_automation-X.X.X.dist-info due to missing `RECORD` file.
```

## 原因 (#1409 調査結果の要約)

「スペース + 連番」は **iCloud Drive の同期コンフリクト解決 (bounced file name,
[Apple TN2336](https://developer.apple.com/library/archive/technotes/tn2336/_index.html))
固有の命名**で、uv / `yt-skills sync` はこの形式を生成しない
(Dropbox / Google Drive / OneDrive も別形式)。リポジトリまたは `.venv` が
iCloud Drive の同期対象 (例: `~/Desktop`, `~/Documents`, iCloud Drive フォルダ)
に置かれていると、同期のたびに重複が生成され、`RECORD` / `direct_url.json` の
欠損によって「`uv run` のたびに再インストール」も恒久化する
(uv 側の既知 issue: [astral-sh/uv#9902](https://github.com/astral-sh/uv/issues/9902))。

## 検知

```bash
uv run yt-doctor                      # numbered_duplicates チェックが warn を出す
find . -name '* [0-9]*' | head -50    # 手動で分布を確認する場合
```

`yt-skills sync` も sync 先に重複を検知すると warning を出す。

## クリーンアップ手順

### 1. `.venv` — 再作成する (個別修復はしない)

`RECORD` 欠損の dist-info 残骸は uv の uninstall では消えず、部分修復は不毛。
丸ごと再作成が正:

```bash
rm -rf .venv
uv sync
```

### 2. `.claude/skills/` — 重複を削除して再展開する

```bash
# 削除対象の確認 (git 管理下なので必ず目視してから)
find .claude/skills -name '* [0-9]*'

# 問題なければ削除
find .claude/skills -name '* [0-9]*' -exec rm -rf {} +

# 正規ファイルを同梱版で上書きして整合を取る
uv run yt-skills sync --asset skills --force

# 検知が消えたことを確認
uv run yt-doctor
```

重複が commit 済みの場合は、削除後に通常どおり commit する。

### 3. その他の場所 — git 管理ファイルへの波及を確認する

リポジトリ全体で `find . -name '* [0-9]*'` を実行し、`.git/refs/` 配下に
`main 2` のような bounce があれば git リポジトリ自体が破損しかけている。
その場合は同期対象外への移設 (下記) を最優先で行うこと。

## 再発防止 (恒久対策)

**リポジトリ (少なくとも `.venv`) を iCloud Drive 同期対象の外に置く**ことが唯一の根本対策:

1. リポジトリが `~/Desktop` / `~/Documents` (「デスクトップと書類」同期の対象) や
   iCloud Drive フォルダ配下にある場合は、同期対象外 (例: `~/dev/`, `~/02-yt/`) へ移設する
2. 移設できない場合は `UV_PROJECT_ENVIRONMENT` 環境変数で venv だけを
   同期対象外パスへ逃がす

対症療法 (根本対策までのつなぎ。重複生成そのものは止まらない):

- `uv run --no-sync` — venv への sync 自体をスキップし再インストールを止める
  (`--frozen` は lockfile 再解決を止めるだけで sync は走るため**効果がない**)
- `UV_NO_INSTALLER_METADATA=1` — uv#9902 の公式ワークアラウンド

## 確認

| 項目 | コマンド | 期待結果 |
|---|---|---|
| 重複の再発 | `uv run yt-doctor` | `numbered_duplicates` が ok |
| 再インストールループ | `uv run yt-skills list` を 2 回 | 2 回目に warning が出ない |
| 同期状態 | リポジトリ直下で `brctl status` | iCloud 管理下でない |
