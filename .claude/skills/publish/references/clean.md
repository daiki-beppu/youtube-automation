# Clean mode

## 前後工程

- `前工程`: `/publish --upload`, `/video --generate`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `なし`
- `読み込む`: `collections/live/<id>/workflow-state.json`, `config/skills/publish.yaml`, `config/skills/live-clean.yaml`

## Overview

`collections/live/` 配下の公開済みコレクションから、YouTube にアップロード済み or 再生成可能な大容量メディアファイルを安全に削除し、ディスク容量を回復する。あわせて、`collections/` 配下（live に限らず planning 等も含む）に残った `tmp/` ディレクトリ残骸の掃除モードを持つ。

いずれのモードも「スキャン → ドライラン表示 → 明示承認 → 削除 → 結果レポート」の同一安全フローに従い、承認なしの削除は絶対に行わない。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。削除対象と保護パターンはここで読んだ値を正とする。

1. `.claude/skills/publish/config.default.yaml::clean`
2. `config/skills/publish.yaml::clean`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("publish")["clean"]` と同じで、チャンネル上書きが優先される（リストは丸ごと置換）。存在しない override は未設定として扱い、勝手に作成しない。旧 `config/skills/live-clean.yaml` は `uv run yt-skills migrate-config` で `publish.yaml::clean` へ移行でき、移行前も `load_skill_config("live-clean")` が互換入口として機能する。

## 前提

以下を確認し、満たさなければ案内して終了する（外部 API・認証には依存しないローカル操作）:

- 実行場所がチャンネルリポジトリ（`CHANNEL_DIR`）配下で、`collections/` ディレクトリが存在すること。無ければ対象なしとして終了する
- 通常モードでは `collections/live/*/workflow-state.json` を持つ公開済みコレクションが 1 件以上存在すること。無ければ削除対象なしとして終了し、公開前なら `/publish --upload` が前工程であることを案内する（削除可否は Step 1 の 4 条件 — `stage: "live"` / `phase: "complete"` / `upload.video_id` 非空 / 存在する `upload.publish_at` の経過 — で機械判定する）
- `workflow-state.json` が読めない / JSON 破損のコレクションは安全条件未達としてスキップし、削除しない

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| なし | 全 live コレクションをスキャン | `/publish --clean` |
| テーマ名 | 部分一致でフィルタ | `/publish --clean harbor` |
| `tmp` | collections 配下の tmp/ 残骸を掃除（後述の tmp/ 残骸クリーンアップモード） | `/publish --clean tmp` |

`$ARGUMENTS` が `tmp` の場合は Step 1〜5 を実行せず、「tmp/ 残骸クリーンアップモード」セクションへ分岐する。

## Instructions

### Step 1: スキャン & 安全性検証

削除対象ファイルを列挙する前に、次の read-only preflight を 1 回実行する。この script は clean な Git worktree で `git pull --ff-only` を完了した後だけ、owner 経由で `collections/live/*/workflow-state.json` を読み、対象候補と安全条件未達を JSON に分類する。

```bash
uv run python .claude/skills/publish/references/clean-scan.py --channel-dir "$CHANNEL_DIR"
```

exit 20 または pull に失敗した場合は、表示された理由を報告して直ちに終了する。古いローカル state を読まず、削除対象の特定やドライラン表示へ進まないため、承認・削除も行わない。自動 merge / rebase や `--no-ff` への切り替えは行わない。

exit 0 の JSON にある `eligible` だけをクリーンアップ候補とし、`skipped` は理由とともに「安全条件未達（スキップ）」へ分類する。以下の **4条件すべて** を満たすコレクションだけが `eligible` になる。各候補の `distrokid` は、pull 後の `config/channel/distrokid.json` と typed state から `disabled` / `pending` / `submitted` のいずれかに確定済みである:

1. `stage` が `"live"`
2. `phase` が `"complete"`
3. `upload.video_id` が存在し、空文字でない
4. `upload.publish_at` が存在する場合は、timezone 付き ISO 8601 として解釈でき、現在時刻を経過済みである。field が無い、または `null` の既存コレクションは後方互換としてこの条件を満たす

未来の `upload.publish_at` は `publish_at_not_elapsed`、形式不正または timezone 無しは `publish_at_invalid` としてスキップし、削除しない。

`$ARGUMENTS` が指定されている場合は、コレクションのディレクトリ名に対する部分一致でフィルタする。

### Step 2: 削除対象ファイルの特定

安全性検証を通過したコレクションについて、Step 1 が各候補へ返した `delete_patterns` に一致するファイルの存在とサイズを確認する。このリストは skill-config（既定値と各パターンの理由コメントは `config.default.yaml` 参照）と pull 後の DistroKid 分類から確定済みである:

- `disabled`: 基底の `delete_patterns` をそのまま返し、`30-distrokid/` は削除候補へ加えない
- `pending`: `02-Individual-music/` と `30-distrokid/` 配下の pattern を除いて返す
- `submitted`: 基底 pattern に `distrokid_audio_patterns` を追加して返す

```bash
# 各コレクションディレクトリで実行（delete_patterns の内容に合わせて展開する。以下は既定値の例）
du -sh 01-master/master.mp3 01-master/master-mix.wav 01-master/*-Master.mp4 02-Individual-music/*.mp3 10-assets/loop_normalized.mp4 30-distrokid/*/*.mp3 2>/dev/null
```

**削除対象**: Step 1 の `eligible` に含まれるコレクションに限り、その候補に返された `delete_patterns`（YouTube に存在、再生成可能、または DistroKid 提出済みの音声コピーのみ）

**絶対に削除しないファイル**: skill-config `protect_patterns`（既定: `workflow-state.json` / `10-assets/main.png|jpg` / `10-assets/thumbnail.jpg|png` / 再生成不可のオリジナル `10-assets/loop.mp4` / `20-documentation/*` / `30-distrokid/spec.json` / `30-distrokid/*/metadata.md` / `30-distrokid/cover_art_3000.jpg` / `30-distrokid/README.md`）。`delete_patterns` や `distrokid_audio_patterns` と重なった場合は `protect_patterns` が優先。

削除対象ファイルが 1 つもないコレクションは「クリーンアップ済み」として表示する。

### Step 3: ドライラン表示

削除実行前に、必ず以下の形式でサマリーを表示する:

```
Live Collection クリーンアップ — ドライラン
============================================

■ Harbor Warehouse (harbor-warehouse)
  YouTube: https://www.youtube.com/watch?v=fbn_dSPzySk
  削除対象:
    01-master/master.mp3                 217 MB
    01-master/master-mix.wav             1.5 GB
    01-master/Harbor-Warehouse-Master.mp4 7.8 GB
    02-Individual-music/ (24 files)      169 MB
  小計: 9.7 GB

============================================
削除対象: N コレクション / M ファイル / X.X GB
クリーンアップ済み: N コレクション
安全条件未達（スキップ）: N コレクション
```

表示後、AskUserQuestion で確認を取る。質問文には削除対象の実数(「削除対象: N コレクション / M ファイル / X.X GB」)と「削除は取り消せません（rm -f による物理削除）」を含め、選択肢は「削除を実行する」「キャンセル」の明示 2 択とする(デフォルトを実行側にしない)。承認されるまで Step 4 へ進まない。「削除を実行する」が明示的に選ばれた場合のみ Step 4 へ進む。それ以外の応答（自由文・別話題・無回答）はすべてキャンセル扱いとし、絶対に削除を実行しない。AskUserQuestion 非対応環境(Codex 等)では同内容をテキストで提示し、ユーザーからの明示的な承認発言を待つ。無応答・曖昧な返答のまま Step 4 に進んではならない。

### Step 4: 削除実行

「削除を実行する」が明示的に選ばれた場合のみ、Step 1 が候補ごとに返した `delete_patterns` に一致するファイルをファイル単位で `rm -f` する（以下は既定値の例）。

```bash
# マスターファイル
rm -f "collections/live/<dir>/01-master/master.mp3"
rm -f "collections/live/<dir>/01-master/master-mix.wav"
rm -f collections/live/<dir>/01-master/*-Master.mp4

# 個別トラック
# distrokid=pending のコレクションでは実行しない
rm -f collections/live/<dir>/02-Individual-music/*.mp3

# DistroKid提出済みのdisc音声コピー（distrokid=submitted のときだけ）
rm -f collections/live/<dir>/30-distrokid/*/*.mp3

# キャッシュ
rm -f "collections/live/<dir>/10-assets/loop_normalized.mp4"
```

**禁止事項:**
- `rm -rf` は絶対に使わない
- ディレクトリ自体は削除しない（空のまま保持）

### Step 5: 結果レポート

```
クリーンアップ完了
==================
■ Harbor Warehouse: 9.7 GB 回復
  - 01-master/: 3 files deleted
  - 02-Individual-music/: 24 files deleted

合計回復容量: X.X GB
```

最後に live ディレクトリ全体のディスク使用量を表示:

```bash
du -sh collections/live/
```

## tmp/ 残骸クリーンアップモード（`/publish --clean tmp`）

`collections/` 配下の各コレクションディレクトリに残った `tmp/` ディレクトリ（中間生成物・作業ファイルの残骸）を、一覧提示 → 明示承認のうえで除去する。live に限らず `collections/planning/` 等の全ステージが対象。

### 対象と判定基準

**削除対象:**
- `collections/` 配下でディレクトリ名が **正確に `tmp`** のディレクトリとその中身（下記コマンドで検出されたもの）

**削除対象外（検出されても必ずスキップ）:**
- `<CHANNEL_DIR>/tmp/`（channel ルート直下）。`tmp/veo-operations/`（Veo 中断 resume 用 state）と `tmp/lyria-recovered/`（Lyria 退避音源）は各 skill が管理する復旧用データであり、本モードのスコープ外
- symlink（`find -type d` は symlink を辿らないため通常は検出されないが、万一 symlink が対象に含まれた場合は削除せず報告のみ）

### 手順

**T1: スキャン**

```bash
find collections -type d -name tmp
```

検出 0 件なら「tmp/ 残骸なし」と報告して終了する。検出があれば各 tmp/ について中身とサイズを確認する:

```bash
du -sh <検出パス>
find <検出パス> -type f | head -20
```

**T2: ドライラン表示**

```
tmp/ 残骸クリーンアップ — ドライラン
====================================
■ collections/planning/harbor-warehouse/tmp/   12 MB (8 files)
■ collections/live/rainy-cafe/tmp/             3.2 MB (2 files)
====================================
削除対象: N ディレクトリ / M ファイル / X.X MB
```

表示後、AskUserQuestion で確認を取る。質問文には削除対象の実数と「削除は取り消せません（物理削除）」を含め、選択肢は「削除を実行する」「キャンセル」の明示 2 択とする（デフォルトを実行側にしない）。「削除を実行する」が明示的に選ばれた場合のみ T3 へ進む。それ以外の応答（自由文・別話題・無回答）はすべてキャンセル扱いとし、絶対に削除を実行しない。AskUserQuestion 非対応環境（Codex 等）では同内容をテキストで提示し、ユーザーからの明示的な承認発言を待つ。

**T3: 削除実行**

`rm -rf` 禁止の方針は tmp/ 掃除でも維持する。tmp/ はディレクトリごと除去したいが、`rm -rf` の代わりに「ファイル単位 `rm -f` → 空になったディレクトリを `rmdir`」で行う。`rmdir` は空でないディレクトリに対して失敗するため、想定外のファイルを巻き込んで消すことがない:

```bash
# 承認された各 tmp/ ディレクトリに対して実行
find "<tmp-path>" -type f -exec rm -f {} +
find "<tmp-path>" -depth -type d -exec rmdir {} \;
```

`rmdir` が失敗した場合（隠しファイル等が残存）は、残存ファイルを提示して個別に判断を仰ぐ。無断で削除方法をエスカレートしない。

**T4: 結果レポート**

```
tmp/ 残骸クリーンアップ完了
==========================
■ collections/planning/harbor-warehouse/tmp/ 除去（12 MB 回復）
■ collections/live/rainy-cafe/tmp/ 除去（3.2 MB 回復）

合計回復容量: X.X MB
```

## 棲み分け

| 責務 | 担当 |
|------|------|
| live コレクションの大容量メディア削除（容量回復の本丸） | 本 skill の Step 1〜5 |
| collections 配下の tmp/ 残骸掃除（衛生維持） | clean mode の tmp/ 分岐（`/publish --clean tmp`） |
| `<CHANNEL_DIR>/tmp/veo-operations/` の resume state | /thumbnail --loop（不要時の手動削除手順は同 skill 参照） |
| `<CHANNEL_DIR>/tmp/lyria-recovered/` の退避音源 | /music --generate |

tmp/ 掃除は「スキャン → ドライラン → 明示承認 → 削除 → レポート」という本 skill の既存安全フローと完全に同型であり、削除 CLI（yt-clean 等）を新設すると承認ゲートを CLI 側に再実装する重複が生じるため、本 skill への統合とした（#1671）。通常モードの `clean-scan.py` は pull 後の安全条件分類だけを担う read-only preflight で、削除・承認は行わない。

## 障害時ガイダンス

ファイル削除はローカル操作で、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 対象ファイル不在 | 削除対象が見つからない | 対象コレクションのパスを確認（外部サービスに依存しないため API 障害・quota の影響は受けない） |
| Ctrl+C（SIGINT）で削除途中に中断 | Step 4 / T3 の実行中に中断し、一部ファイルだけ削除済み | 削除はファイル単位の `rm -f` で idempotent なため、途中中断しても壊れた状態にはならない（`workflow-state.json` は保護対象のため Step 1 の安全性検証は再実行でもそのまま機能する）。スキルを再実行すれば Step 1 / T1 の再スキャンで残存ファイルのみが削除対象として再検出され、残件から継続できる（削除済みのファイルは `du` / `find` に現れず、全件削除済みのコレクションは「クリーンアップ済み」表示になる）。再実行時も承認ゲート（Step 3 / T2）は改めて通る |
