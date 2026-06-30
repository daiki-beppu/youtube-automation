# Suno playlist capture（legacy）

> Legacy note: この文書は #893 の旧 playlist capture 仕様を保存するための記録であり、現行の suno-helper 一括生成フローでは使用しない。現行フローは playlist URL を `workflow-state.json` の `planning.music.suno_playlist_url` に保存し、ZIP 完了を `POST /collections/<id>/downloaded` で通知する。旧 route の削除は #1301 で追跡する。

## Current Flow

- サーバーは `yt-collection-serve "$CHANNEL_DIR/collections/planning" --allow-origin "chrome-extension://<EXTENSION_ID>"` で dir mode 起動する。
- popup は `GET /collections` で `status` / `pattern_count` / `downloaded_count` を読み、旧 mapped ベースの除外フラグは使わない。
- playlist 追加完了直後に `POST /collections/<id>/downloaded` へ `{ file_count: 0, format, suno_playlist_url }` を送って URL だけ記録する。
- ZIP ダウンロード完了後に `{ file_count, expected_file_count, format, suno_playlist_url, download_path }` を同 endpoint へ送り、サーバーが ZIP を展開して `workflow-state.json` の `assets.music_downloaded` を更新する。
- popup の手動 Capture / Send UI と、その専用 client API / route 定数は現行 extension surface から撤去済み。Python 側の `/suno/playlists` は既存運用向けの互換 route としてのみ残る。

## Legacy Spec

Suno UI 上のプレイリスト一覧を localhost サーバー経由で下流チャンネルの
`<root>/config/suno-playlists.json` に atomic merge write する機能の仕様（#893）。

下流チャンネルの `/wf-batch` 系スキルは `<channel>/config/suno-playlists.json` を入力に
「コレクション × Suno プレイリスト」マッピングからマスター化〜公開予約を直列実行する。
この JSON を手書きする運用コストを、Suno UI からの自動 capture で削減する。

この互換 route は、下流チャンネル repo の `/wf-batch` 系スキルが
`config/suno-playlists.json` を読まなくなり、`yt-collection-serve --playlist-capture-*`
を使う既存 operator 手順が無いことを確認できた時点で #1301 により撤去する。

prefix と出力先 root は CLI 引数（env fallback）で受け、**特定チャンネルにハードコードしない**。
prefix によるフィルタは拡張側ではなく **サーバー側 `normalize_suno_title` に閉じる**ことで
channel-agnostic を担保する（拡張は全 playlist を素のまま送る）。

## 契約文字列（SSOT）

| 値                                         | 定義箇所                                                                                      |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- |
| POST サブパス `/suno/playlists`            | `src/youtube_automation/scripts/suno_artifacts.py::SUNO_PLAYLISTS_ROUTE`（Python 互換 route） |
| 出力先 `<root>/config/suno-playlists.json` | `collection_serve.py::playlists_output_path`                                                  |
| 必要権限 `tabs`（自動 capture 用）         | `extensions/suno-helper/lib/manifest.ts::MANIFEST_PERMISSIONS`                                |

## サーバー（`yt-collection-serve`）

### 起動

```bash
yt-collection-serve <COLLECTIONS_DIR> \
  --allow-origin "chrome-extension://<EXTENSION_ID>" \
  --playlist-capture-root <ROOT> \
  --playlist-capture-prefix <PREFIX>
# env fallback: PLAYLIST_CAPTURE_ROOT / PLAYLIST_CAPTURE_PREFIX
```

- `--playlist-capture-root` 指定時のみ POST `/suno/playlists` を有効化する。
- mutating POST のため `--allow-origin "chrome-extension://<EXTENSION_ID>"` の exact lock が必須。
  `GET /auth/token` で取得した token を `X-Serve-Token` として送る。
- root / prefix の片方だけ指定は `ConfigError` で fail-loud（silent 無効化しない）。
- 起動メッセージに root / prefix を表示する。

### 純関数（モジュールレベル、単体テストでスペック化）

- `normalize_suno_title(title: str, prefix: str) -> str | None`
  `<prefix> | <theme>` を `<prefix>-<theme-slug>` に正規化する。prefix 一致時のみ slug を返し、
  不一致は `None`。大小無視・連続空白の `-` 1 つ畳み込み。prefix はパイプ直前トークンと
  完全一致する必要があり、前方一致の部分トークン（`df` が `df365 | x` を拾う等）は弾く。
  実装の核は以下の動的 regex（prefix をハードコードしない）:

  ```python
  re.compile(rf"^{re.escape(prefix)}\s*\|\s*(.+)$", re.IGNORECASE)
  ```

- `write_suno_playlists(root: Path, payload: list[dict], *, prefix: str) -> int`
  `<root>/config/suno-playlists.json` へ atomic merge write（`tempfile.mkstemp` → `os.replace`）。
  prefix 不一致 item は skip、同 slug は `captured_at` 後勝ちで上書き、既存 JSON 破損は空 dict
  扱いで再作成。書き込み件数を返す。
- 既存ファイルが旧 wf-batch list スキーマ `[{slug, suno_url, suno_title, captured_at}]` の場合は、
  `write_suno_playlists` の merge 前読み込みで dict スキーマ `{slug: {title, url, captured_at}}` へ写像する（#976）。正準スキーマは dict（write は常に dict で書く）。
- `derive_collection_slug(collection_id: str, prefix: str) -> str | None`
  collection dir 名から `normalize_suno_title` と同じ slug 形を導出する（マージキー突合の不変条件）。

### HTTP 振る舞い

| 条件                                 | レスポンス                                      |
| ------------------------------------ | ----------------------------------------------- |
| exact extension Origin + valid `X-Serve-Token` + JSON list body | 200 `{written, path}`                           |
| exact extension Origin から `GET /auth/token` | 200 `{token}`                                   |
| Origin 未設定 / 許可リスト外         | 403                                             |
| `X-Serve-Token` 未設定 / 不一致      | 403                                             |
| capture 無効（root 未設定）/ 別パス  | 404                                             |
| body が JSON list でない / 不正 JSON | 400                                             |
| `OPTIONS /suno/playlists`            | `Access-Control-Allow-Methods` に `POST` を含む |

CORS は既存 `is_origin_allowed` を再利用する。ただし `/auth/token` と mutating POST は
`--allow-origin` の完全一致 lock が無い起動では 403 になり、read-only route の既定許可とは分離する。

## レガシー拡張（suno-helper）

- `extensions/shared/playlist-scrape.ts::scrapePlaylistsFromMe(doc)`: Suno `/me` の
  `a[href^="/playlist/"]` を走査し `[{title, url}]` を抽出（title は aria-label 優先・textContent
  fallback、空 title skip、url dedup、host 絶対化）。
- 旧実装では popup 下部の手動 Capture / Send UI から POST `/suno/playlists`
  を呼んでいたが、現行 extension からは撤去済み。
- 旧 collection ドロップダウンはサーバーの `mapped: bool` と mapped ベースの除外フラグを使っていたが、
  現行 API は `status: "needs_prompts" | "ready" | "downloaded"` に置換済み。

## 具体例: DeepFocus365

DF365 チャンネルでの起動コマンド（prefix=`df365`, root=`~/02-yt/deepfocus365`）:

```bash
yt-collection-serve <COLLECTIONS_DIR> \
  --allow-origin "chrome-extension://<EXTENSION_ID>" \
  --playlist-capture-root ~/02-yt/deepfocus365 \
  --playlist-capture-prefix df365
```

Suno `/me` → overlay の Capture → `GET /auth/token` → `X-Serve-Token` 付き Send →
`~/02-yt/deepfocus365/config/suno-playlists.json` 更新。
別チャンネル（例: `rjn`）は `--playlist-capture-prefix rjn` に変えるだけで同じ機構が使える。
複数チャンネルを同時に capture したい場合は別ポート・別プロセスで起動する（1 プロセス 1 prefix）。
