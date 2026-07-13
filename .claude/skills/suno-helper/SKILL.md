---
name: suno-helper
description: "Use when Suno UI に投入する曲をブラウザで連続生成 + playlist 追加 + 一括ダウンロードしたいとき。uv run yt-collection-serve で suno-prompts.json を配信し、suno-helper Chrome 拡張で 1 タブ完結の自動実行（pattern 注入 → Generate → 完了待機 → 次へ → 全件完了で playlist 一括追加 → ZIP 一括 DL）を回す operator 手順。`/suno` でプロンプトが揃った後、または既存 collection の途中再開で使用する"
---

## Overview

`<CHANNEL_DIR>/collections/planning/<theme>-collection/` の `suno-prompts.json` を `uv run yt-collection-serve` で配信し、Chrome 拡張 **suno-helper** が Suno (suno.com/create) タブ上で各 pattern の Style/Lyrics 注入 → Generate → 完了待ち → 次の pattern、を自動反復する。全件完了後に clip を一括選択 → Cmd+P → Add to Playlist dialog → 自動 playlist 化 → ZIP 一括ダウンロードまで進める。

このスキルはプロンプト生成（`/suno`）の **次工程** であり、マスター化（`/masterup`）の **前工程** にあたる。suno-helper は生成 → playlist 追加 → 一括ダウンロードまでを 1 タブで完結させるため、`/masterup` の DL ステップ（Step 2-3）は原則スキップされる。
新規 collection を `/wf-new` から開始した直後は、`/wf-new` が `uv run yt-collection-serve` の起動と疎通確認まで完了している場合がある。その場合、本スキルは既存 server を再利用し、browser use で Suno タブ上の suno-helper overlay を操作する。

## 完了条件

overlay の phase が `finished` に到達し、Step 6 の 6 点（playlist 紐付け / clip 数 = entry 数 × 2 / `02-Individual-music/` への音声配置 / `status = downloaded` / `suno_playlist_url` 記録 / `assets.music_downloaded = true`）がすべて確認できたとき完了とする（詳細は Step 6 が正）。`entry-failed` や clip 数不足が残る場合は完了扱いにせず、失敗分の再実行を提案する。

## When to Use

- `/suno` でプロンプトが揃い、Suno で実際に曲を生成したいとき
- ERROR で停止した collection を途中の entry から再開したいとき
- 「Suno で連続生成回して」「suno-helper で流して」「Suno に追加で N 曲生成して」と user が言ったとき

`/suno` がプロンプト設計（YAML → suno-prompts.json）だけを担当し、本スキルが **ブラウザ実行** を担当する役割分担。

## 前提

- Chrome に unpacked の suno-helper 拡張がロード済み（拡張アイコンが popup を出す。ID 検出に失敗した場合のみ `--allow-origin` fallback で拡張 ID を手動指定する）
- Suno (suno.com/create) にログイン済み・**Advanced タブ**が選択されている
- Style 入力欄が出ていること。prompt entry の `lyrics` が非空なら（インストゥルメンタルを含め）Lyrics mode = Write と Style / Lyrics 入力欄を使い、空のインストゥルメンタル entry なら Lyrics mode = Instrumental と Style 入力欄を使う
- automation リポジトリで `uv` が使える・`CHANNEL_DIR` 環境変数を当該チャンネルへ向けてある
- collection ディレクトリ名が **`*-collection` suffix** を持つ（dir mode 必須）。例: `20260201-soulful-grooves-rainy-night-soul-collection/`
- 7873 / 7874 など特定 port を既に他の collection で使っていないか確認（並走させる場合は明示的に分ける）

Chrome DevTools MCP は必須ではない。通常運用は browser use を primary path とし、DevTools MCP は DOM が見えない、拡張 overlay が応答しない、または debugger attach 競合を切り分ける場合の診断・補助・フォールバックに限る。`chrome.debugger` 権限は拡張内部が Cmd+P の trusted key event を送るための実装権限であり、agent が DevTools MCP を常時起動する前提ではない。

## Quick Reference

| 役割 | コマンド |
|---|---|
| サーバー起動（必須: dir mode + 拡張 origin lock） | `uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" --allow-extension suno-helper` |
| 拡張 ID 手動指定（検出失敗時のみ） | `--allow-origin "chrome-extension://<EXTENSION_ID>"` |
| ポート変更（並走時） | 末尾に `--port 7874` |
| 拡張をリロード | chrome://extensions → suno-helper の再読み込みアイコン |
| Suno タブ | https://suno.com/create にアクセス、Advanced タブを選択 |
| agent 主経路 | browser use で Suno タブを開き、ページ内 overlay の `data-suno-*` signal と表示文言を観測 |

## Instructions

### Step 1. サーバーを起動または再利用する

起動（または再利用確認）の前に、対象コレクションの骨格プリフライトを実行する（fail-loud、#1494）:

```bash
uv run yt-collection-preflight <collection-dir-name>
```

`[NG]`（`01-master/` 等の欠落）が報告されたら `--fix` で補完してから進む。DL 完走後に初期化漏れへ気づく事故を防ぐため、このステップは省略しない。

**必ず dir mode + 拡張 origin lock 付き**で起動する。

```bash
uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
  --allow-extension suno-helper
```

`--allow-extension suno-helper` は Chrome の profile preferences から unpacked 拡張 ID を検出し、`chrome-extension://<id>` の exact origin lock として使う。検出 0 件・複数 ID 競合・Preferences 読み取り不可・Preferences JSON parse failure で失敗する場合のみ、エラーに表示された候補を確認して `--allow-origin "chrome-extension://<EXTENSION_ID>"` を手動指定する。`POST /collections/<id>/downloaded` と `GET /auth/token` はこの exact origin 以外を 403 にするため、未指定では ZIP 展開・DL 完了記録が動かない。

collection 単体パスを直接渡す single file mode は playlist phase がスキップされるため本 skill では使わない。dir mode で読まれるのは **`-collection` suffix を持つ dir のみ**。それ以外（例: `01-master` や雑多ファイル）は無視される。

`/wf-new` 完了ガイダンスに `Suno-helper server: ✅ http://<channel>.localhost:<PORT>` が出ている場合は、その URL を使って下記 3 点の確認だけ行い、追加起動しない。確認に失敗する場合のみ、空き port を選んで起動し直す。

起動後の確認（**3 点すべてパスすること**）:

1. `curl -s http://<channel>.localhost:7873/collections | python3 -m json.tool | head -20` が JSON array を返す（404 なら single file mode で起動してしまっている。名前解決に迷う場合は同じ port の `localhost` でも確認可）
2. 各 collection に `"status"` フィールド（`"needs_prompts"` / `"ready"` / `"downloaded"`）、`"pattern_count"`、`"downloaded_count"` がある（`playlist_name` は返らない）
3. サーバー出力の `detected extension: suno-helper -> <id> (chrome-extension://<id>)` を確認し、`curl -s -H "Origin: chrome-extension://<id>" http://<channel>.localhost:7873/auth/token | python3 -m json.tool` が `{ "token": "..." }` を返す

### Agent primary flow: browser use で操作する

1. browser use で `https://suno.com/create` を開く。
2. ログイン済みで Advanced タブが選択されていることを確認する。prompt entry の `lyrics` が非空なら（インストゥルメンタルを含め）Lyrics mode = Write を選び、Style / Lyrics 入力欄が見えることを確認する。空のインストゥルメンタル entry なら Lyrics mode = Instrumental を選び、Style 入力欄が見えることを確認する。ログイン画面、CAPTCHA、Advanced タブ不在なら下記 handoff 条件に従い停止する。
3. 拡張アイコンをクリックして suno-helper overlay を Suno タブ内に表示する。overlay が最小化されている場合はヘッダーの展開ボタンを押す。
4. overlay ルート `[data-suno-helper="control-panel"]` を観測する。`data-suno-phase`、`data-suno-running`、`data-suno-error`、`data-suno-collection-id`、`data-suno-entry-count`、`data-suno-selected-entry-count` が browser use から読める。
5. `[data-suno-control="server-url"]` に Step 1 で確認した URL を入れる。
6. `[data-suno-control="collection-select"]` で対象 collection を選ぶ。選択後、Playlist 名が表示されること、`data-suno-collection-id` が対象 id になることを確認する。
7. `[data-suno-control="fetch-data"]`（表示文言: データ取得）を押す。`role="status"` の live region が `N パターンを取得しました。` になり、`data-suno-entry-count` が 1 以上、`[data-suno-entry-list]` に entry 行が並ぶことを確認する。
8. 必要な entry だけを checkbox で残す。各行は `data-suno-entry-index` / `data-suno-entry-state` / `data-suno-entry-selected` を持つ。通常は全選択のままにする。
9. preset と DL 形式を確認し、`[data-suno-control="run"]`（表示文言: 全パターンを連続実行 / 選択したN件を連続実行）を押す。
10. 実行中は Suno タブを reload / close せず、overlay の `data-suno-phase` と `role="status"` を監視する。agent は `finished` / `stopped` / `error` の終端 phase まで待つ。非終端 phase が変化しない場合は下記「無限待機を避ける監視ルール」で判断する。

Chrome 拡張 popup が別ウィンドウとして開く環境でも、操作対象と確認項目は同じ。Suno タブ上に overlay が出る場合は overlay を優先し、popup しか使えない場合だけ同じラベル・ボタン文言で操作する。

### Step 2. overlay / popup を開く

browser use で Suno タブを前面にし、拡張アイコンをクリックして overlay / popup を出す。確認・操作する項目:

| 項目 | 必須 | 説明 |
|---|---|---|
| ローカル配信元 | 必須 | `yt-collection-serve` が返すチャンネル名つき候補を選ぶ。既定は `http://youtube-automation.localhost:7873`、後方互換で `http://localhost:7873` も選択可能 |
| Collection 選択 | 必須 | ドロップダウンから対象 collection を選ぶ。選択した瞬間に下に "Playlist 名" が auto derive される |
| 前回失敗の resume バナー | ERROR 停止後 24h 以内 | "再開" を押すと保存済み位置から直接再開する。不要なら "閉じる" |
| Entry 選択 | 任意 | データ取得後の checkbox で実行対象を選ぶ。全選択なら全実行、不要 entry はチェック OFF |
| DL 形式 | 任意 | ZIP 内の音声形式。デフォルト MP3。MP3 / M4A / WAV から選択 |
| データ取得 | 初回必須 | サーバーから prompts JSON を fetch して一覧表示 |
| 連続実行 | 実行時 | 開始 |
| 停止 | 実行中のみ有効 | 任意中断 |

agent が優先して使う DOM signal:

| signal | 意味 |
|---|---|
| `[data-suno-helper="control-panel"]` | suno-helper 操作 panel の root |
| `data-suno-phase` | 現在 phase（`idle` / `loading` / `starting` / 下表の progress phase / `adopting`） |
| `data-suno-running` | 実行中なら `"true"` |
| `data-suno-error` | エラー表示中なら `"true"` |
| `data-suno-collection-id` | 選択中 collection id |
| `data-suno-entry-count` | 読み込まれた entry 数 |
| `data-suno-selected-entry-count` | 実行対象として選択されている entry 数 |
| `role="status"` + `data-suno-status` | 人間向け状態文言。`data-suno-status="error"` なら handoff 判断へ進む |
| `[data-suno-entry-index]` | entry 行。`data-suno-entry-state` と `data-suno-entry-selected` で個別状態を読む |
| `[data-suno-control="server-url"]` / `[data-suno-control="collection-select"]` | サーバー URL 入力 / collection 選択 |
| `[data-suno-control="fetch-data"]` / `[data-suno-control="run"]` / `[data-suno-control="stop"]` | データ取得 / 連続実行 / 停止 |
| `[data-suno-control="resume"]` / `[data-suno-control="dismiss-resume"]` | 前回中断 resume バナーの再開 / 閉じる |
| `[data-suno-control="adopt-selected-clips"]` | Suno 上の選択中 clip を採用 |
| `[data-suno-control="retry-playlist"]` / `[data-suno-control="retry-download"]` | playlist / download phase から再開 |

### Step 3. 実行対象を決める

- 通常は全 checkbox ON のままでよい（全パターン実行）
- 生成しない entry がある場合だけ checkbox を OFF にする
- 全 checkbox OFF では実行できない。少なくとも 1 件を選ぶ
- 前回 ERROR から再開する場合は resume バナーの "再開" を押すと、保存済み位置から直接実行が始まる

### Step 4. "連続実行" を押す

開始後、popup を閉じても処理は継続する（Suno タブが content script を保持する）。ただし以下は禁止:

- 進行中の Suno タブを reload / close しない
- 同タブで他の操作（曲再生 / 検索）を入れない
- Chrome を強制終了しない

### Step 5. 進捗 phase を読む

overlay / popup 上部の live region と root の `data-suno-phase` に進捗が出る:

| phase | 意味 |
|---|---|
| `injecting` | Style/Lyrics を当該 entry に注入中 |
| `generating` | Generate 押下後、Suno の生成完了待ち（最大 3 分） |
| `waiting-captcha` | CAPTCHA / bot check の解消待ち。多くは自動 verify 後に `generating` へ戻る |
| `waiting-slot` | Suno のキュー上限に達した。空きスロット待ち（in-flight 変化があれば継続）|
| `submitted` | 高速モード（内部値: queue）のみ。投入 ACK 済み・生成未完了（琥珀色）。全 entry 投入後の完了待ちで `done` へ遷移 |
| `done` | 当該 entry 完了、次へ進む |
| `entry-failed` | 当該 entry は失敗としてスキップし、run 全体は次 entry へ継続 |
| `adding-to-playlist` | 全 entry 完了、clip を一括 playlist 化中 |
| `downloading` | playlist 追加完了後、全 clip を ZIP 一括ダウンロード中 |
| `finished` | 完了（DL 含む） |
| `stopped` | user が停止ボタンで中断 |
| `error` | 失敗（赤色で停止）|

**phase 遷移の詳細**: `done`（最終 entry）→ `adding-to-playlist` → `downloading` → `finished`。playlist 追加完了直後に `postDownloaded(file_count: 0)` を呼んで playlist URL のみをサーバーに記録し、ZIP ダウンロード完了後に `postDownloaded(file_count: N)` で実ファイル数を報告する。

無限待機を避ける監視ルール:

- `loading` が 30 秒以上続く、または `role="status"` に `取得失敗` が出た場合: server URL、`GET /collections`、`GET /auth/token` を再確認する。改善しなければ handoff。
- `starting` が 30 秒以上続く、または `開始失敗` が出た場合: Suno タブで Advanced タブが選択されているか、拡張リロード後にタブをハードリロードしたか確認する。改善しなければ handoff。
- `waiting-captcha` は自動 verify されることがあるため待つ。ただし 10 分以上変化しない、または CAPTCHA が明示表示されている場合は user に手動解決を依頼して停止する。
- `waiting-slot` は queue 空き待ちの正常 phase。overlay の status が更新される限り待つ。10 分以上 in-flight 集合が変化しない場合は拡張が `error` に遷移するため、agent は独自に再クリックせず error 文言を読む。
- `entry-failed` は run 全体は継続中。`finished` が一部失敗を示した場合は「失敗分のみ再実行」を提案し、自動で無限再試行しない。
- `adding-to-playlist` / `downloading` が 10 分以上無変化なら overlay の status、Downloads、server log を確認し、同じ操作を連打しない。`error` になったら resume / retry ボタンで再開するか handoff する。

handoff 条件（agent は自動突破しない）:

- Suno ログインが必要、または account / payment / token 消費に関わる確認が出ている
- CAPTCHA / reCAPTCHA / hCaptcha が表示され、手動解決が必要
- suno-helper 拡張がロードされていない、overlay / popup が開かない、または `data-suno-helper="control-panel"` が見つからない
- server 接続失敗、`/collections` が 404、`/auth/token` が 403、または origin lock の拡張 ID が不明
- Generate ボタン、Advanced タブ、または prompt entry の `lyrics` が非空のときの Style / Lyrics 欄・空のインストゥルメンタル entry の Style 欄が見つからない
- 生成が `stopped` になった、または `error` になり原因文言の対応が必要
- playlist 追加失敗、Add to Playlist dialog が見つからない、multi-select 数が合わない
- ZIP ダウンロードが失敗、Downloads 権限・保存先・ZIP 展開で確認が必要

### Step 6. 完了確認

`finished` 表示後、以下を確認:

1. Suno 側で対象 playlist に collection の全 clip が紐付いている
2. clip 数 = collection の entry 数 × 2（数が合わなければ resume で残りを回す）
3. `02-Individual-music/` に mp3/m4a/wav が配置されている
4. `GET /collections` で対象 collection の `status` が `downloaded`、`downloaded_count` が期待 clip 数以上になっている
5. `workflow-state.json` の `planning.music.suno_playlist_url` に playlist URL が記録されている
6. `workflow-state.json` の `assets.music_downloaded` が `true` になっている（DL 完了時）

音声配置と `workflow-state.json` 更新の両方に成功した後、ユーザーの Downloads 配下にある Suno ZIP は自動削除される。削除に失敗しても配置済み音声と workflow-state は維持され、警告が記録される。完了判定は ZIP の存在ではなく、展開済み音声ファイルと `workflow-state.json` を見る。

### Step 7. 中断時

- **任意停止**（`stopped`）: 次回 popup 起動時に resume バナーは出ない
- **ERROR**（`error`）: 24h 以内なら resume バナーが出る。"再開" で失敗 entry から再実行
- ERROR 文言の代表例（いずれも fail-loud で停止する）:
  - `Lyrics mode が Instrumental になっています。Write に切り替えてください。`
  - `Create form mode が Simple になっています。Advanced タブを選択してください。`
  - 状態を特定できない場合は Advanced タブ / Lyrics mode = Write / UI 言語（英語推奨）のチェックリストを表示する
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
5. popup の "DL 形式" で保存された `sunoDownloadFormat` を読み取り（デフォルト: `"mp3"`）、該当フォーマットを選択
6. `chrome.downloads` API 経由で ZIP ダウンロードが開始

### フォーマット設定

ダウンロードフォーマットは popup の "DL 形式" で設定する。値は `chrome.storage` キー `sunoDownloadFormat` に保存される。

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
| ZIP ダウンロード完了後 | `{ file_count: N, expected_file_count: N, format: "<fmt>", suno_playlist_url: "<url>", download_path: "<absolute zip path>" }` | playlist URL 記録、ZIP 展開、DL 完了マークを 1 回で行う |

このエンドポイントは冪等（idempotent）であり、同じ payload で複数回呼んでも問題ない。

### playlist_name の構築

拡張は collection id と collection name から `${PREFIX} | ${theme}` 形式で playlist 名を構築する。サーバーは `playlist_name` を返さない。

### DOWNLOADING phase のエラーハンドリング

ダウンロードが途中で失敗した場合（ネットワーク断、Chrome のダウンロードキャンセル等）、拡張は resume state を保持して `error` phase に遷移する。ユーザーは overlay の Download 再開操作で `retryDownload` を実行できる。POST エンドポイントは冪等（idempotent）なので、再開時に同じ playlist URL / ZIP 情報を送っても安全。

### 状態管理の変更点

| 項目 | 旧（DL 機能なし） | 新（DL 機能あり） |
|---|---|---|
| playlist URL の記録先 | `suno-playlists.json` | `workflow-state.json` の `planning.music.suno_playlist_url` |
| DL 完了判定（primary） | N/A | `02-Individual-music/` にファイルが存在するか（ファイルシステム） |
| DL 完了判定（secondary） | N/A | `workflow-state.json` の `assets.music_downloaded` |
| `suno-playlists.json` | 新規コレクションでも使用 | 使用しない（新規・レガシー互換とも廃止） |

`suno-playlists.json` は新規・レガシー互換のどちらでも参照されない。playlist URL は `POST /collections/<id>/downloaded` 経由で `workflow-state.json` の `planning.music.suno_playlist_url` に一元管理される。

## Gotchas

- **`--allow-extension` / `--allow-origin` 無しで起動すると token 取得と DL 完了 POST が 403 になる**。通常は `--allow-extension suno-helper` で検出し、検出失敗時のみ `--allow-origin "chrome-extension://<EXTENSION_ID>"` を exact 指定して Step 1 の `/auth/token` 確認を通すこと。
- **誤って single file mode で起動すると playlist phase がスキップされる**。`/collections` 404 が返り、popup 側で derivedPlaylistName が undefined になり playlist phase に分岐しない。Step 1 の `curl /collections` 確認を必ず通すこと。
- **Advanced タブ + Lyrics mode を毎回確認**。prompt entry の `lyrics` が非空なら（インストゥルメンタルを含め）Write と Style / Lyrics 欄、空のインストゥルメンタル entry なら Instrumental と Style 欄を選ぶ。Suno が UI 状態を覚えていないことがあり、`lyrics` が非空の entry で Lyrics 欄が消えていると Step 5 開始直後に ERROR で止まる。
- **Cmd+P を手動で押す必要はない**。拡張は background script から `chrome.debugger` の `Input.dispatchKeyEvent` で trusted key event を送る。dispatchEvent では Suno listener に届かない（isTrusted=false）ため、user 側で打鍵してはいけない（衝突する）。失敗時は拡張 manifest の `debugger` 権限、対象 Suno tab への attach 失敗、DevTools/別 debugger の競合を確認する。
- **dir 名規約は `<YYYYMMDD>-<channel>-<theme>-collection`**。拡張が dir 名の `<channel>` と collection name の `<theme>` から playlist 名（`<channel> | <theme>`）を導出する。独自規約で切ると playlist 名が壊れる。
- **7873 / 7874 を並走させる場合は明示的に port を分ける**。両方を 7873 で立てると後者が起動失敗するので、必ず `--port` を指定して popup のローカル配信元を選び直す。
- **下流チャンネルの venv が古いと `/collections` の status / count 契約が古い場合がある**。automation リポに機能追加した後は下流で `uv lock --upgrade-package youtube-channels-automation && uv sync` を実行し、サーバーを再起動する。Step 1 の確認で検出できる。
- **playlist URL が記録されない場合**: (1) `/auth/token` が 200 を返すか、(2) popup の対象 collection が正しいか、(3) `POST /collections/<id>/downloaded` の 1 回目（`file_count: 0`）が 2xx で返っているかを確認する。
- **ZIP 展開後も downloaded にならない場合**: (1) Download all ZIP が完了しているか、(2) `download_path` が絶対パスで POST されているか、(3) ZIP 内音声数が `expected_file_count` 以上か、(4) `02-Individual-music/` に mp3/m4a/wav が配置されたかを確認する。

## Rules

- 必ず dir mode で起動する（single file mode は playlist phase がスキップされるため使わない）
- 進行中の Suno タブを reload / close しない
- popup の "ローカル配信元" を変える前に `curl <URL>/collections` が応答するか確認する
- ERROR で止まったら原因を見ずに即 resume しない（同じ entry で再失敗するので、文言で root cause を切り分ける）

## Cross References

- 前工程（プロンプト生成）: `/suno`
- 後工程（マスター化）: `/masterup`（DL は本スキルが完了済みのため Step 2-3 スキップ）
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `src/youtube_automation/scripts/collection_serve.py`
- POST downloaded エンドポイント: `src/youtube_automation/scripts/collection_serve.py`
- 連続実行ペーシング定義: `extensions/shared/constants.ts::BALANCED_RUN_PACING`
- DL フォーマット storage key: `extensions/shared/constants.ts::sunoDownloadFormat`
