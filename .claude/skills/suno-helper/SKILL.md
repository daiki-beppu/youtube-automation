---
name: suno-helper
description: "Use when Suno UI に投入する曲をブラウザで連続生成 + playlist 追加 + 一括ダウンロードしたいとき。yt-collection-serve で suno-prompts.json を配信し、suno-helper Chrome 拡張で 1 タブ完結の自動実行（pattern 注入 → Generate → 完了待機 → 次へ → 全件完了で playlist 一括追加 → ZIP 一括 DL）を回す operator 手順。`/suno` でプロンプトが揃った後、または既存 collection の途中再開で使用する"
---

## Overview

`<CHANNEL_DIR>/collections/planning/<theme>-collection/` の `suno-prompts.json` を `yt-collection-serve` で配信し、Chrome 拡張 **suno-helper** が Suno (suno.com/create) タブ上で各 pattern の Style/Lyrics 注入 → Generate → 完了待ち → 次の pattern、を自動反復する。全件完了後に clip を一括選択 → Cmd+P → Add to Playlist dialog → 自動 playlist 化 → ZIP 一括ダウンロードまで進める。

このスキルはプロンプト生成（`/suno`）の **次工程** であり、マスター化（`/masterup`）の **前工程** にあたる。suno-helper は生成 → playlist 追加 → 一括ダウンロードまでを 1 タブで完結させるため、`/masterup` の DL ステップ（Step 2-3）は原則スキップされる。

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
- chrome://extensions の suno-helper 詳細画面で拡張 ID を確認済み
- collection ディレクトリ名が **`*-collection` suffix** を持つ（dir mode 必須）。例: `20260201-soulful-grooves-rainy-night-soul-collection/`
- 7873 / 7874 など特定 port を既に他の collection で使っていないか確認（並走させる場合は明示的に分ける）

## Quick Reference

| 役割 | コマンド |
|---|---|
| サーバー起動（必須: dir mode + capture + 拡張 origin lock） | `uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" --playlist-capture-root "$CHANNEL_DIR" --playlist-capture-prefix <PREFIX> --allow-origin "chrome-extension://<EXTENSION_ID>"` |
| ポート変更（並走時） | 末尾に `--port 7874` |
| 拡張をリロード | chrome://extensions → suno-helper の再読み込みアイコン |
| Suno タブ | https://suno.com/create にアクセス、Custom Mode |

## Instructions

### Step 1. サーバーを起動する

**必ず dir mode + capture フラグ + 拡張 origin lock 付き**で起動する。

```bash
uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
  --playlist-capture-root "$CHANNEL_DIR" \
  --playlist-capture-prefix <PREFIX> \
  --allow-origin "chrome-extension://<EXTENSION_ID>"
```

`<PREFIX>` はコレクションディレクトリ名の channel 部分。dir 名 `<YYYYMMDD>-<channel>-<theme>-collection` の `<channel>` を指定する。例: `df365`（deepfocus365）、`rjn`、`soulful-grooves`。
`<EXTENSION_ID>` は chrome://extensions → suno-helper → 詳細の ID。`POST /collections/<id>/downloaded` と `GET /auth/token` はこの exact origin 以外を 403 にするため、未指定では ZIP 展開・DL 完了記録が動かない。

capture フラグが無いと:
- POST `/suno/playlists`（playlist 自動保存）が 404 になる

collection 単体パスを直接渡す single file mode は playlist phase がスキップされるため本 skill では使わない。dir mode で読まれるのは **`-collection` suffix を持つ dir のみ**。それ以外（例: `01-master` や雑多ファイル）は無視される。

起動後の確認（**3 点すべてパスすること**）:

1. `curl -s http://localhost:7873/collections | python3 -m json.tool | head -20` が JSON array を返す（404 なら single file mode で起動してしまっている）
2. 各 collection に `"status"` フィールド（`"needs_prompts"` / `"ready"` / `"downloaded"`）、`"pattern_count"`、`"downloaded_count"`、`"playlist_name"` がある
3. `curl -s -H "Origin: chrome-extension://<EXTENSION_ID>" http://localhost:7873/auth/token | python3 -m json.tool` が `{ "token": "..." }` を返す

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
| `downloading` | playlist 追加完了後、全 clip を ZIP 一括ダウンロード中 |
| `finished` | 完了（DL 含む） |
| `stopped` | user が停止ボタンで中断 |
| `error` | 失敗（赤色で停止）|

**phase 遷移の詳細**: `done`（最終 entry）→ `adding-to-playlist` → `downloading` → `finished`。playlist 追加完了直後に `postDownloaded(file_count: 0)` を呼んで playlist URL のみをサーバーに記録し、ZIP ダウンロード完了後に `postDownloaded(file_count: N)` で実ファイル数を報告する。

### Step 7. 完了確認

`finished` 表示後、以下を確認:

1. Suno 側で対象 playlist に collection の全 clip が紐付いている
2. clip 数 = collection の entry 数（数が合わなければ resume で残りを回す）
3. ZIP ダウンロードが完了し、Chrome のダウンロードフォルダに ZIP ファイルが存在する
4. `workflow-state.json` の `planning.music.suno_playlist_url` に playlist URL が記録されている
5. `workflow-state.json` の `assets.music_downloaded` が `true` になっている（DL 完了時）

### Step 8. 中断時

- **任意停止**（`stopped`）: 次回 popup 起動時に resume バナーは出ない
- **ERROR**（`error`）: 24h 以内なら resume バナーが出る。"再開" で失敗 entry から再実行
- ERROR 文言の代表例（いずれも fail-loud で停止する）:
  - `Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。`
  - `reCAPTCHA を検知しました。手動で解決してから再開してください。`
  - `Clip multi-select verification failed: expected N selected, got M`
  - `中断: Add to Playlist dialog を検出できませんでした。clip が selected 状態であることを確認してください。Suno の UI 変更の可能性があります。`

## 一括ダウンロード機能

### ダウンロードフロー

playlist 追加完了後、拡張は以下の手順で ZIP 一括ダウンロードを実行する:

1. 全 clip を multi-select（生成完了後の clip 行をすべて選択）
2. 任意の行の "More menu contents" ボタンをクリック
3. コンテキストメニューから "Download all" をクリック
4. フォーマット選択モーダルが表示される（M4A / MP3 / WAV）
5. `chrome.storage` キー `sunoDownloadFormat` から設定値を読み取り（デフォルト: `"mp3"`）、該当フォーマットを選択
6. `chrome.downloads` API 経由で ZIP ダウンロードが開始

### フォーマット設定

ダウンロードフォーマットは `chrome.storage` キー `sunoDownloadFormat` で設定する。

| 値 | 説明 |
|---|---|
| `"mp3"` | MP3 形式（デフォルト） |
| `"m4a"` | M4A (AAC) 形式 |
| `"wav"` | WAV (非圧縮) 形式 |

popup UI からも設定可能。設定は `chrome.storage.local` に永続化される。

### POST エンドポイント

ダウンロード状態はサーバーの `POST /collections/<id>/downloaded` エンドポイントに報告される。

| 呼び出しタイミング | payload | 目的 |
|---|---|---|
| playlist 追加完了直後 | `{ file_count: 0, format: "<fmt>", suno_playlist_url: "<url>" }` | playlist URL のみ記録 |
| ZIP ダウンロード完了後 | `{ file_count: N, format: "<fmt>", suno_playlist_url: "<url>" }` | DL 完了をマーク |

このエンドポイントは冪等（idempotent）であり、同じ payload で複数回呼んでも問題ない。

### playlist_name の構築

拡張はコレクションメタデータから `${PREFIX} | ${name}` 形式で playlist 名を構築する。これはサーバー側の `playlist_name` 算出ロジックと同じ規約。

### DOWNLOADING phase のエラーハンドリング

ダウンロードが途中で失敗した場合（ネットワーク断、Chrome のダウンロードキャンセル等）、拡張はリトライを試みる。POST エンドポイントが冪等なため、再送しても安全。リトライ不能な場合は `error` phase に遷移し、ユーザーに手動ダウンロードへのフォールバックを促す。

### 状態管理の変更点

| 項目 | 旧（DL 機能なし） | 新（DL 機能あり） |
|---|---|---|
| playlist URL の記録先 | `suno-playlists.json` | `workflow-state.json` の `planning.music.suno_playlist_url` |
| DL 完了判定（primary） | N/A | `02-Individual-music/` にファイルが存在するか（ファイルシステム） |
| DL 完了判定（secondary） | N/A | `workflow-state.json` の `assets.music_downloaded` |
| `suno-playlists.json` | 新規コレクションでも使用 | **新規コレクションでは使用しない**（レガシー互換で残存） |

新規コレクションでは `suno-playlists.json` は参照されない。playlist URL は `workflow-state.json` に一元管理される。

## Gotchas

- **capture フラグ無しで起動すると POST `/suno/playlists` が 404 になる**。`--playlist-capture-root "$CHANNEL_DIR"` と `--playlist-capture-prefix <PREFIX>` を必ず両方付けること。片方だけ指定すると ConfigError で起動自体が失敗する（fail-loud）。
- **`--allow-origin` 無しで起動すると token 取得と DL 完了 POST が 403 になる**。`chrome-extension://<EXTENSION_ID>` を exact 指定し、Step 1 の `/auth/token` 確認を通すこと。
- **誤って single file mode で起動すると playlist phase がスキップされる**。`/collections` 404 が返り、popup 側で derivedPlaylistName が undefined になり playlist phase に分岐しない。Step 1 の `curl /collections` 確認を必ず通すこと。
- **Custom Mode + Instrumental 設定を毎回確認**。Suno が UI 状態を覚えていないことがあり、Lyrics 欄が消えていると Step 5 開始直後に ERROR で止まる。
- **Cmd+P を手動で押す必要はない**。拡張は実際の keydown を press_key 経由で送る実装。dispatchEvent では Suno listener に届かない（isTrusted=false）ため、user 側で打鍵してはいけない（衝突する）。
- **dir 名規約は `<YYYYMMDD>-<channel>-<theme>-collection`**。サーバーが `--playlist-capture-prefix` と dir 名から `playlist_name`（`<prefix> | <theme>`）を算出し、拡張はその値をそのまま使う。独自規約で切ると playlist 名が壊れる。
- **7873 / 7874 を並走させる場合は明示的に port を分ける**。両方を 7873 で立てると後者が起動失敗するので、必ず `--port` を指定して popup の URL も書き換える。
- **下流チャンネルの venv が古いとサーバーの `playlist_name` が `null` になる**。automation リポに機能追加した後は下流で `uv lock --upgrade-package youtube-channels-automation && uv sync` を実行し、サーバーを再起動する。Step 1 の確認 3 で検出できる。
- **auto-capture 後にコレクションが消えない場合**: (1) サーバーが起動しているか、(2) `suno-playlists.json` にエントリが書き込まれたか、(3) Suno の playlist 名が `<prefix> | <theme>` 形式になっているか（旧バグで `soulful | grooves-theme` のように壊れている場合は Suno 側で Edit Playlist Details からリネームする）。
- **Suno が UI/URL を変更した場合の対処**: auto-capture は `https://suno.com/me/playlists` を開いて `a[href^="/playlist/"]` をスクレイプする。Suno の URL 変更やセレクタ変更で 0 件になったら、(1) DevTools で `document.querySelectorAll('a[href^="/playlist/"]').length` を確認、(2) 0 件なら `background.ts` の `SUNO_ME_URL` や `shared/playlist-scrape.ts` の `PLAYLIST_ANCHOR_SELECTOR` を修正する。

## Rules

- 必ず dir mode で起動する（single file mode は playlist phase がスキップされるため使わない）
- 30+ entries は Balanced か Safe を選ぶ（Fast は ban リスクが上がる）
- 進行中の Suno タブを reload / close しない
- popup の "サーバー URL" を書き換える前に `curl <URL>/collections` が応答するか確認する
- ERROR で止まったら原因を見ずに即 resume しない（同じ entry で再失敗するので、文言で root cause を切り分ける）

## Cross References

- 前工程（プロンプト生成）: `/suno`
- 後工程（マスター化）: `/masterup`（DL は本スキルが完了済みのため Step 2-3 スキップ）
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `src/youtube_automation/scripts/collection_serve.py`
- POST downloaded エンドポイント: `src/youtube_automation/scripts/collection_serve.py`
- preset 定義: `extensions/shared/constants.ts::SPEED_PRESETS`
- DL フォーマット storage key: `extensions/shared/constants.ts::sunoDownloadFormat`
