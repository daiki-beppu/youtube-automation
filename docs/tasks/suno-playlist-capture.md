# Suno playlist capture（channel-agnostic）

Suno UI 上のプレイリスト一覧を localhost サーバー経由で下流チャンネルの
`<root>/config/suno-playlists.json` に atomic merge write する機能の仕様（#893）。

下流チャンネルの `/wf-batch` 系スキルは `<channel>/config/suno-playlists.json` を入力に
「コレクション × Suno プレイリスト」マッピングからマスター化〜公開予約を直列実行する。
この JSON を手書きする運用コストを、Suno UI からの自動 capture で削減する。

prefix と出力先 root は CLI 引数（env fallback）で受け、**特定チャンネルにハードコードしない**。
prefix によるフィルタは拡張側ではなく **サーバー側 `normalize_suno_title` に閉じる**ことで
channel-agnostic を担保する（拡張は全 playlist を素のまま送る）。

## 契約文字列（SSOT）

| 値 | 定義箇所 |
|----|---------|
| POST サブパス `/suno/playlists` | `src/youtube_automation/scripts/suno_artifacts.py::SUNO_PLAYLISTS_ROUTE` ／ `extensions/shared/constants.ts::PLAYLISTS_CAPTURE_ROUTE` |
| 出力先 `<root>/config/suno-playlists.json` | `collection_serve.py::playlists_output_path` |
| 必要権限 `tabs`（自動 capture 用） | `extensions/suno-helper/lib/manifest.ts::MANIFEST_PERMISSIONS` |

## サーバー（`yt-collection-serve`）

### 起動

```bash
yt-collection-serve <COLLECTIONS_DIR> \
  --playlist-capture-root <ROOT> \
  --playlist-capture-prefix <PREFIX>
# env fallback: PLAYLIST_CAPTURE_ROOT / PLAYLIST_CAPTURE_PREFIX
```

- `--playlist-capture-root` 指定時のみ POST `/suno/playlists` を有効化する。
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
- `read_mapped_slugs(root: Path) -> set[str]`
  既存 JSON の slug 集合（不在・破損は空集合）。
- 既存ファイルが旧 wf-batch list スキーマ `[{slug, suno_url, suno_title, captured_at}]` の場合は
  dict スキーマ `{slug: {title, url, captured_at}}` へ写像して読む（#976）。mapped 判定が効き、
  merge write でも既存マッピングを消失させない。正準スキーマは dict（write は常に dict で書く）。
- `derive_collection_slug(collection_id: str, prefix: str) -> str | None`
  collection dir 名から `normalize_suno_title` と同じ slug 形を導出する（マージキー突合の不変条件）。

### HTTP 振る舞い

| 条件 | レスポンス |
|------|-----------|
| 許可 Origin + JSON list body | 200 `{written, path}` |
| Origin 未設定 / 許可リスト外 | 403 |
| capture 無効（root 未設定）/ 別パス | 404 |
| body が JSON list でない / 不正 JSON | 400 |
| `OPTIONS /suno/playlists` | `Access-Control-Allow-Methods` に `POST` を含む |

CORS は既存 `is_origin_allowed`（`chrome-extension://` scheme + suno.com / distrokid.com web origin、
`--allow-origin` 指定時は完全一致 lock）を再利用する。

## 拡張（suno-helper）

- `extensions/shared/playlist-scrape.ts::scrapePlaylistsFromMe(doc)`: Suno `/me` の
  `a[href^="/playlist/"]` を走査し `[{title, url}]` を抽出（title は aria-label 優先・textContent
  fallback、空 title skip、url dedup、host 絶対化）。
- `extensions/shared/api.ts::postCapturedPlaylists(baseUrl, items)`: POST `/suno/playlists`
  （body は配列のまま、非 2xx は fail-loud throw）。
- `components/PlaylistCaptureTab.tsx`: overlay 下部の Capture / Send to localhost 2 ボタン。
  Capture は runner content（background 中継）経由で現在ページの playlist を scrape し、
  Send はレスポンスの `{written, path}` を status に出す。
- 自動 capture（連続実行の playlist 化完了時）: runner → background の `requestPlaylistCapture` を
  trigger に、background が bg `/me` tab を開いて scrape → POST → close する。**fail soft**（失敗は
  warning log のみで `PHASE.FINISHED` へ進める）。`tabs` 権限はこの bg tab 開閉のために追加する。
- collection ドロップダウン: サーバーの `mapped: bool`（`build_collections_index`）を使い、
  `excludeMappedCollections` で未マッピング collection のみ表示する。prefix 未指定の旧運用は
  `mapped` が全 false で全件表示 = 後方互換維持。

## 具体例: DeepFocus365

DF365 チャンネルでの起動コマンド（prefix=`df365`, root=`~/02-yt/deepfocus365`）:

```bash
yt-collection-serve <COLLECTIONS_DIR> \
  --playlist-capture-root ~/02-yt/deepfocus365 \
  --playlist-capture-prefix df365
```

Suno `/me` → overlay の Capture → Send → `~/02-yt/deepfocus365/config/suno-playlists.json` 更新。
別チャンネル（例: `rjn`）は `--playlist-capture-prefix rjn` に変えるだけで同じ機構が使える。
複数チャンネルを同時に capture したい場合は別ポート・別プロセスで起動する（1 プロセス 1 prefix）。
