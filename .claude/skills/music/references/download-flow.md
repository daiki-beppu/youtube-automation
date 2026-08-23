# 一括ダウンロードの内部仕様

playlist 追加後の ZIP 一括 DL について、拡張とサーバーの間で何が起きているか。
DL が途中で止まった / 形式が想定と違う / `workflow-state.json` に反映されない、といった
症状を切り分けるときに読む。正常系の操作手順は SKILL.md 本体の Step 4〜6 を見る。

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
| ZIP ダウンロード完了後 | `{ file_count: N, expected_file_count: N, format: "<fmt>", download_path: "<absolute zip path>" }` | ZIP 展開、実数・欠損数・DL 完了マークを 1 回で行う |

このエンドポイントは冪等（idempotent）であり、同じ payload で複数回呼んでも問題ない。

### playlist_name の構築

拡張は collection id と collection name から `${PREFIX} | ${theme}` 形式で playlist 名を構築する。サーバーは `playlist_name` を返さない。

### DOWNLOADING phase のエラーハンドリング

ダウンロードが途中で失敗した場合（ネットワーク断、Chrome のダウンロードキャンセル等）、拡張は resume state を保持して `error` phase に遷移する。ユーザーは overlay の Download 再開操作で `retryDownload` を実行できる。POST エンドポイントは冪等（idempotent）なので、再開時に同じ ZIP 情報を送っても安全。

### 状態管理の変更点

| 項目 | 旧（DL 機能なし） | 新（DL 機能あり） |
|---|---|---|
| DL 完了判定（primary） | N/A | `02-Individual-music/` にファイルが存在するか（ファイルシステム） |
| DL 完了判定（secondary） | N/A | `workflow-state.json` の `assets.music_downloaded` |
| `suno-playlists.json` | 新規コレクションでも使用 | 使用しない（新規・レガシー互換とも廃止） |

`suno-playlists.json` は新規・レガシー互換のどちらでも参照されない。完了判定は正準 prompt、期待数、ローカル実数、欠損数、`assets.music_downloaded` を使い、Suno URL は参照しない。
