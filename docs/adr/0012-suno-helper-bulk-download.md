# suno-helper に一括ダウンロード責務を追加: DOM + chrome.downloads 方式

## Status

accepted (2026-06-23、#1143 レビューで改訂 2026-06-29)。

Suno AI が一括ダウンロード機能（multi-select → "..." → Download all → フォーマット選択モーダル → ZIP ダウンロード）を追加したため、suno-helper Chrome 拡張の責務を「UI 自動生成 + playlist 作成 + 一括ダウンロード + ZIP パス通知」に拡張する。ダウンロード方式は Bridge fetch 傍受ではなく、DOM 操作 + `chrome.downloads` API + collection-serve への ZIP パス通知を採用する。現行 extension flow は playlist URL を捕捉しない。

併せて、楽曲生成の完了判定を `suno-playlists.json` から `workflow-state.json` + ファイルシステムに移行し、状態管理を collection 単位に一元化する。

## Considered Options

### ZIP の受け渡し方式

1. **Bridge で ZIP URL を傍受 → collection-serve に URL を POST → Python が DL + 展開**: 当初はこの方式を想定。suno-bridge が既に `/api/generate/` や `/api/feed/` を傍受しているため同じパターンで拾えると考えた
2. **DOM 操作 + `chrome.downloads` API（採用）**: 実機 DevTools 確認の結果、Download all はフォーマット選択モーダル（M4A / MP3 / WAV）を経由する標準的なブラウザダウンロードであり、「Download」ボタン押下前に API コールが走らないことが判明。Bridge 傍受は不要で、DOM 操作だけで完結する

Bridge 方式を却下した理由: Download all クリック → モーダル表示の段階では Suno API コールが発生しない。ZIP URL を取得するには「Download」ボタン押下後の response を傍受する必要があるが、ブラウザのネイティブダウンロードとして処理されるため fetch 経由で流れない可能性が高い。`chrome.downloads` API なら確実にファイルパスと完了状態を取得できる。

### 実行順序

~~Download all → Add to Playlist の順序を採用。~~ **改訂: Add to Playlist → Download all の順序を採用。**

- playlist 追加を先に行うことで、DL の成否に関わらず Suno 上に対象 clip 群を保存できる
- DL がブラウザクラッシュ等で失敗しても、Suno 上の playlist から手動リカバリしやすい
- playlist 追加の DOM 変化後のメニュー再表示は実機検証で安定性を確認する（当初の懸念は DL 先行の根拠だったが、playlist URL の永続性を優先）

### 楽曲生成の完了判定

1. **`suno-playlists.json` の `mapped` フラグ（旧方式）**: チャンネルルートの専用ファイルで collection slug → playlist URL をマッピング。DL 入力（masterup の CDN curl）と完了判定の 2 責務を兼ねていた
2. **`workflow-state.json` + ファイルシステム（採用）**: DL 入力の責務が suno-helper に移り `suno-playlists.json` の存在意義が消失。完了判定はファイルシステム（`02-Individual-music/` のファイル存在）を primary、`workflow-state.json` の `music_downloaded` を secondary に

`suno-playlists.json` を廃止する理由: DL が suno-helper 内で完結するため、playlist URL → CDN curl の導線が不要。完了判定は collection 単位の `workflow-state.json` に統合した方が状態の散在を防げる。チャンネルルートの設定ファイルが 1 つ減り、collection ごとの自己完結性が上がる。

### `/collections` API のレスポンス設計

1. **`has_prompts` + `mapped` フラグ（旧方式）**: `mapped: boolean` は `suno-playlists.json` 由来。2 フラグの組み合わせで状態を推定
2. **`status` enum（採用）**: `"needs_prompts" | "ready" | "downloaded"` の排他的状態。ファイルシステムから遅延判定し、`downloaded_count` で進捗も返す

enum を採用した理由: 状態が排他的（同時に 2 つにならない）ため enum が正確。拡張側の分岐もシンプルになる。

## Decision

### DL フロー

1. **suno-helper のフロー拡張**: 全 clip 完了後、multi-select → "..." → Add to Playlist → "..." → Download all → フォーマット選択（設定値に基づく、デフォルト MP3）→ Download → DL 完了検知
2. **新 Phase `DOWNLOADING`**: `ADDING_TO_PLAYLIST` の後に挿入
3. **`chrome.downloads` API**: manifest に `downloads` パーミッション追加。`onChanged` で完了検知、`search()` でファイルパス取得
4. **m4a をネイティブ対応**: generate-master の入力 glob を `*.{mp3,m4a,wav}` に拡張。FFmpeg は AAC を直接処理可能
5. **配置先**: ZIP から照合できた音声は `02-Individual-music/` に配置する。vocal の候補キュレーション分岐は本 PR のスコープ外とし、別設計で扱う
6. **Python 版に先行実装**: TS 版 collection-serve はマージ時に移植。設計はプロトコルレベル（HTTP + ファイルシステム規約）なので言語非依存

### 状態管理の刷新

7. **`suno-playlists.json` 廃止**: 新規 collection では使用しない。旧 Python 互換 route（`POST /suno/playlists`）と関連する playlist URL マッピング関数は #1301 で撤去済み。
8. **playlist URL は任意フィールドとして維持**: `planning.music.suno_playlist_url` は URL を持つ legacy/manual 入口がある場合だけ記録する。現行 extension flow の ZIP 完了通知では送らず、既存値も破壊しない
9. **`music_downloaded` フィールド追加**: `workflow-state.json` の `assets.music_downloaded` で DL 完了を明示記録
10. **完了判定の二重化**: `/collections` API はファイルシステム（`02-Individual-music/` のファイル数）から `status` を動的判定。`workflow-state.json` はスキル間連携の正式記録

### API 変更

11. **`GET /collections` レスポンス刷新**:

    ```json
    {
      "id": "20260611-soulful-grooves-midnight-mood-collection",
      "name": "midnight-mood",
      "channel": "soulful-grooves",
      "theme": "midnight-mood",
      "status": "ready",
      "pattern_count": 8,
      "downloaded_count": 8,
      "expected_file_count": 16
    }
    ```

    `mapped` / `playlist_name` フィールドは削除。playlist 名は拡張側で `channel` / `theme` を優先して `${channel} | ${theme}` として組み立てる。`channel` が無い旧形式では `id` と `name` から slug 境界を検証して導出する

12. **`POST /collections/<id>/downloaded`（新設、`/suno/download-complete` を置換）**: 冪等な PATCH セマンティクス。現行 extension flow は ZIP ダウンロード完了時に playlist URL なしで POST する。サーバーは来たフィールドで `workflow-state.json` をマージ更新し、`download_path` がある場合だけ ZIP を展開して `02-Individual-music/` へ配置する。

    URL を持つ legacy/manual 入口の任意 URL 記録:

    ```json
    {
      "file_count": 0,
      "format": "mp3",
      "suno_playlist_url": "https://suno.com/playlist/xxx"
    }
    ```

    ZIP 完了通知:

    ```json
    {
      "file_count": 16,
      "expected_file_count": 16,
      "format": "mp3",
      "download_path": "/Users/me/Downloads/suno-playlist.zip"
    }
    ```

    `download_path` は Chrome downloads API から得た絶対 ZIP パスで、相対パスは 400。playlist URL は ZIP 完了通知では不要で、サーバーは既存の `planning.music.suno_playlist_url` を破壊しない。`expected_file_count` は Suno が生成した全 clip 数で、サーバーは prompt 数 \* 2 と比較して大きい方を完了判定に使う。ZIP 展開数が期待値未満、または照合できる音声が 0 件なら 500 とし、`workflow-state.json` の `assets.music_downloaded` は更新しない。

13. **`POST /suno/playlists` は撤去済み**: 新規の playlist URL 記録は `POST /collections/<id>/downloaded` に統合する。旧 `/suno/playlists` route、`write_suno_playlists()`、`normalize_suno_title()`、`--playlist-capture-*` は #1301 で削除済み。

### masterup

14. **masterup は縮小存続**: DL ロジックは deprecated fallback として残置（`02-Individual-music/` にファイルがあれば skip）。主責務は `yt-generate-master` によるマスター音源生成 + `workflow-state.json` 更新

## Consequences

- `extensions/shared/constants.ts` に `DOWNLOADED_ROUTE`, `PHASE.DOWNLOADING`, `DOWNLOAD_FORMAT_DEFAULT` を追加
- `extensions/shared/api.ts` の `CollectionSummary` を `status` enum 型に改訂。`mapped` / `playlist_name` を削除
- `extensions/suno-helper/lib/download.ts` 新規作成（モーダル DOM 操作 + DL 完了検知）
- `extensions/suno-helper/entrypoints/background.ts` に `chrome.downloads.onChanged` リスナー追加
- `src/youtube_automation/scripts/collection_serve.py`: `POST /collections/<id>/downloaded` 追加、`build_collections_index()` を `status` enum 方式に改訂。旧 `POST /suno/playlists` / `write_suno_playlists` は #1301 で撤去済み
- `suno-helper/SKILL.md` と `masterup/SKILL.md` の改訂が必要
- `workflow-state.json` スキーマ v2 に `assets.music_downloaded` と `planning.music.suno_playlist_url` を追加
- `suno-playlists.json` 関連コード・ファイルは #1301 で撤去済み
