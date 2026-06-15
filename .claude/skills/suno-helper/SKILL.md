---
name: suno-helper
description: "Use when Suno UI に投入する曲をブラウザで連続生成 + playlist 追加したいとき。yt-collection-serve で suno-prompts.json を配信し、suno-helper Chrome 拡張で 1 タブ完結の自動実行（pattern 注入 → Generate → 完了待機 → 次へ → 全件完了で playlist 一括追加）を回す operator 手順。`/suno` でプロンプトが揃った後、または既存 collection の途中再開で使用する"
---

## Overview

`<CHANNEL_DIR>/collections/planning/<theme>-collection/` の `suno-prompts.json` を `yt-collection-serve` で配信し、Chrome 拡張 **suno-helper** が Suno (suno.com/create) タブ上で各 pattern の Style/Lyrics 注入 → Generate → 完了待ち → 次の pattern、を自動反復する。全件完了後に clip を一括選択 → Cmd+P → Add to Playlist dialog → 自動 playlist 化まで進める。

このスキルはプロンプト生成（`/suno`）の **次工程** であり、Suno DL + マスター化（`/masterup`）の **前工程** にあたる。

## When to Use

- `/suno` でプロンプトが揃い、Suno で実際に曲を生成したいとき
- ERROR で停止した collection を途中の entry から再開したいとき
- 「Suno で連続生成回して」「suno-helper で流して」「Suno に追加で N 曲生成して」と user が言ったとき

`/suno` がプロンプト設計（YAML → suno-prompts.json）だけを担当し、本スキルが **ブラウザ実行** を担当する役割分担。

## 前提

- Chrome に suno-helper 拡張がロード済み（拡張アイコンが popup を出す）
- Suno (suno.com/create) にログイン済み・**Custom Mode** が選択されている
- Style 入力欄が出ていること（Instrumental ON/OFF はパターンに依存、Lyrics ありなら OFF）
- automation リポジトリで `uv` が使える・`CHANNEL_DIR` 環境変数を当該チャンネルへ向けてある
- collection ディレクトリ名が **`*-collection` suffix** を持つ（dir mode 必須）。例: `20260201-soulful-grooves-rainy-night-soul-collection/`
- 7873 / 7874 など特定 port を既に他の collection で使っていないか確認（並走させる場合は明示的に分ける）

## Quick Reference

| 役割 | コマンド |
|---|---|
| サーバー起動（必須: dir mode + capture） | `uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" --playlist-capture-root "$CHANNEL_DIR" --playlist-capture-prefix <PREFIX>` |
| ポート変更（並走時） | 末尾に `--port 7874` |
| 拡張をリロード | chrome://extensions → suno-helper の再読み込みアイコン |
| Suno タブ | https://suno.com/create にアクセス、Custom Mode |

## Instructions

### Step 1. サーバーを起動する

**必ず dir mode + capture フラグ付き**で起動する。

```bash
uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
  --playlist-capture-root "$CHANNEL_DIR" \
  --playlist-capture-prefix <PREFIX>
```

`<PREFIX>` はコレクションディレクトリ名の channel 部分。dir 名 `<YYYYMMDD>-<channel>-<theme>-collection` の `<channel>` を指定する。例: `df365`（deepfocus365）、`rjn`、`soulful-grooves`。

capture フラグが無いと:
- popup のコレクション一覧で `mapped` が全件 false になり、処理済み collection が非表示にならない
- POST `/suno/playlists`（playlist 自動保存）が 404 になる

collection 単体パスを直接渡す single file mode は playlist phase がスキップされるため本 skill では使わない。dir mode で読まれるのは **`-collection` suffix を持つ dir のみ**。それ以外（例: `01-master` や雑多ファイル）は無視される。

確認: 起動後に `curl http://localhost:7873/collections` が JSON array を返せば dir mode で起動できている（404 が返るのは single file mode で起動してしまった状態）。各 collection の `"mapped"` フィールドが `true` / `false` を返していれば capture フラグも有効。

### Step 2. Chrome の popup を開く

拡張アイコンをクリックして popup を出す。確認・操作する項目:

| 項目 | 必須 | 説明 |
|---|---|---|
| サーバー URL | 必須 | デフォルト `http://localhost:7873`。port を変えたら書き換える |
| Collection 選択 | 必須 | ドロップダウンから対象 collection を選ぶ。選択した瞬間に下に "Playlist 名" が auto derive される |
| 前回失敗の resume バナー | ERROR 停止後 24h 以内 | "再開" を押すと range が auto prefill される。不要なら "閉じる" |
| 実行範囲 | 任意 | "全パターン"（デフォルト） / "範囲指定"（1-based 開始 + 任意の終了）|
| Preset | 任意 | Step 3 を参照。デフォルト Balanced |
| データ取得 | 初回必須 | サーバーから prompts JSON を fetch して一覧表示 |
| 連続実行 | 実行時 | 開始 |
| 停止 | 実行中のみ有効 | 任意中断 |

### Step 3. preset を選ぶ

| preset | 想定 | 1 曲あたりの待ち |
|---|---|---|
| ⚡ Fast | 〜10 entries の小 collection / 過去に hCaptcha 履歴なし / 急ぎ | 3s 固定 / jitter なし |
| ⚖️ Balanced（デフォルト） | 20-55 entries の標準 collection | 6s ±3s |
| 🐢 Safe | 30+ entries / ban 履歴あり / リスク最優先で抑えたい | 20s ±5s |

判断に迷ったら **Balanced のままで OK**。preset は `chrome.storage.local` に永続化されるので、次回 popup を開いた時も維持される。

### Step 4. 実行範囲を決める

- 通常は "全パターン" でよい
- 途中まで生成済みで残りだけ追加する場合は "範囲指定" にして開始 entry (1-based) / 終了 entry を入れる
- 終了は空でも OK（末尾まで実行）
- 前回 ERROR から再開する場合は resume バナーで自動 prefill されるのでそのまま実行

### Step 5. "連続実行" を押す

開始後、popup を閉じても処理は継続する（Suno タブが content script を保持する）。ただし以下は禁止:

- 進行中の Suno タブを reload / close しない
- 同タブで他の操作（曲再生 / 検索）を入れない
- Chrome を強制終了しない

### Step 6. 進捗 phase を読む

popup 上部に進捗が出る:

| phase | 意味 |
|---|---|
| `injecting` | Style/Lyrics を当該 entry に注入中 |
| `generating` | Generate 押下後、Suno の生成完了待ち（最大 3 分） |
| `waiting-slot` | Suno のキュー上限 (10 clip) に達した。空きスロット待ち（最大 5 分）|
| `done` | 当該 entry 完了、次へ進む |
| `adding-to-playlist` | 全 entry 完了、clip を一括 playlist 化中 |
| `finished` | 完了 |
| `stopped` | user が停止ボタンで中断 |
| `error` | 失敗（赤色で停止）|

### Step 7. 完了確認

`finished` 表示後、以下を確認:

1. Suno 側で対象 playlist に collection の全 clip が紐付いている
2. clip 数 = collection の entry 数（数が合わなければ resume で残りを回す）
3. clip 名が Suno デフォルトの自動生成名のまま（リネーム / DL は次工程 `/masterup`）

### Step 8. 中断時

- **任意停止**（`stopped`）: 次回 popup 起動時に resume バナーは出ない
- **ERROR**（`error`）: 24h 以内なら resume バナーが出る。"再開" で失敗 entry から再実行
- ERROR 文言の代表例（いずれも fail-loud で停止する）:
  - `Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。`
  - `reCAPTCHA を検知しました。手動で解決してから再開してください。`
  - `Clip multi-select verification failed: expected N selected, got M`
  - `中断: Add to Playlist dialog を検出できませんでした。clip が selected 状態であることを確認してください。Suno の UI 変更の可能性があります。`

## Gotchas

- **capture フラグ無しで起動すると mapped が全件 false、POST `/suno/playlists` が 404 になる**。`--playlist-capture-root "$CHANNEL_DIR"` と `--playlist-capture-prefix <PREFIX>` を必ず両方付けること。片方だけ指定すると ConfigError で起動自体が失敗する（fail-loud）。
- **誤って single file mode で起動すると playlist phase がスキップされる**。`/collections` 404 が返り、popup 側で derivedPlaylistName が undefined になり playlist phase に分岐しない。Step 1 の `curl /collections` 確認を必ず通すこと。
- **Custom Mode + Instrumental 設定を毎回確認**。Suno が UI 状態を覚えていないことがあり、Lyrics 欄が消えていると Step 5 開始直後に ERROR で止まる。
- **Cmd+P を手動で押す必要はない**。拡張は実際の keydown を press_key 経由で送る実装。dispatchEvent では Suno listener に届かない（isTrusted=false）ため、user 側で打鍵してはいけない（衝突する）。
- **dir 名規約は `<YYYYMMDD>-<channel>-<theme>-collection`**。dir 名から theme が抽出され `extractPlaylistName(id, theme)` で playlist 名が組まれる。独自規約で切ると playlist 名が壊れる。
- **7873 / 7874 を並走させる場合は明示的に port を分ける**。両方を 7873 で立てると後者が起動失敗するので、必ず `--port` を指定して popup の URL も書き換える。

## Rules

- 必ず dir mode で起動する（single file mode は playlist phase がスキップされるため使わない）
- 30+ entries は Balanced か Safe を選ぶ（Fast は ban リスクが上がる）
- 進行中の Suno タブを reload / close しない
- popup の "サーバー URL" を書き換える前に `curl <URL>/collections` が応答するか確認する
- ERROR で止まったら原因を見ずに即 resume しない（同じ entry で再失敗するので、文言で root cause を切り分ける）

## Cross References

- 前工程（プロンプト生成）: `/suno`
- 後工程（DL + マスター化）: `/masterup`
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `src/youtube_automation/scripts/collection_serve.py`
- preset 定義: `extensions/shared/constants.ts::SPEED_PRESETS`
