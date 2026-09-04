# Studio Multitrack export の内部仕様

playlist 追加後の WAV ZIP export について、拡張とサーバーの間で何が起きているか。
export が途中で止まった / `workflow-state.json` に反映されない、といった
症状を切り分けるときに読む。正常系の操作手順は SKILL.md 本体の Step 4〜6 を見る。

### ダウンロードフロー

playlist 追加完了後、拡張は以下の手順で ZIP export を実行する:

1. `https://suno.com/studio` を開き、空の project を作成する
2. project 名を collection id に変更し、Library の All Songs を開く
3. 対象 clip をそれぞれ別 track の位置 0 へドラッグ＆ドロップする
4. In Project の配置数が対象 clip 数と一致することを検証する
5. Export → Multitrack を押し、WAV を格納した ZIP を開始する。実画面では `blob:https://suno.com/...` または `https://suno-ai--studio-bounce-prod-web.modal.run/...` が download item URL になる
6. `chrome.downloads` API で ZIP 完了を監視する

download watcher は `blob:` の場合は origin が `https://suno.com` と一致するものだけを許可し、HTTPS の場合は Studio export 専用の `suno-ai--studio-bounce-prod-web.modal.run` を exact hostname で許可する。旧 Download all 用の `suno-ai--bulk-download-prod-web.modal.run` や任意の `modal.run` subdomain は許可しない。

Suno Studio は Premier プラン限定。Studio を開けない、project を作れない、配置数が一致しない、
または Multitrack が無効な場合は export せず、overlay に具体的な理由を表示して `ERROR` で停止する。
作成した project は手動確認・復旧に利用できるよう削除しない。

### POST エンドポイント

ダウンロード状態はサーバーの `POST /collections/<id>/downloaded` エンドポイントに報告される。

| 呼び出しタイミング | payload | 目的 |
|---|---|---|
| ZIP ダウンロード完了後 | `{ file_count: N, expected_file_count: N, format: "wav", download_path: "<absolute zip path>" }` | ZIP 展開、実数・欠損数・DL 完了マークを 1 回で行う |

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
