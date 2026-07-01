# アップロードチェックリスト

## 必須ファイル確認

- [ ] マスター動画（`01-master/00-master.mp4` または `03-Individual-movie/*master*.mp4`）
- [ ] サムネイル（候補順: `10-assets/thumbnail.jpg` → `10-assets/thumbnail.png`。`main.png/jpg` は textless 動画背景なので使わない）
- [ ] 概要欄（`20-documentation/descriptions.md` — `/video-description` スキルで生成済み）

## 初投稿プレイリスト確認

`config/channel/playlists.json` が存在するチャンネルでは、初投稿前に未作成プレイリストを初期化する。

```bash
uv run yt-playlist-status
uv run yt-playlist-manager --init --dry-run
uv run yt-playlist-manager --init
```

- [ ] `uv run yt-playlist-status` で `(未作成)` の有無を確認した
- [ ] `(未作成)` がある場合、`uv run yt-playlist-manager --init --dry-run` の内容を確認した
- [ ] ユーザー確認後に `uv run yt-playlist-manager --init` を実行し、`playlist_id` が `config/channel/playlists.json` に書き戻された
- [ ] 初回動画の追加は `/video-upload` 内部の自動 assign に任せる。手動 `--assign` は実行しない

## コンテンツ品質確認

- [ ] タイトルに誇張表現なし（Epic, Ultimate 等 不使用）
- [ ] AI 透明性・Usage & Attribution セクションあり
- [ ] ハッシュタグ 13個（base + theme 固有）
- [ ] SEO キーワード適切（`config/channel/content.json` の `tags.base` 参照）

## アップロード実行

アップロード実行前に、ユーザーに公開方法を提示するための公開タイミングを必ず確定する。

```bash
# スケジュール計算（アップロード API は叩かない。予約日時計算で YouTube read API を呼ぶ場合がある）
uv run yt-upload-collection --plan [-c NAME]
```

- [ ] plan 結果が `📅 公開設定: 即時公開 (public)` の場合だけ「即時公開」と表現する
- [ ] plan 結果が `📅 公開予定: <日時>` の場合は「今アップロード → `<日時>` に自動で一般公開」と、実際の公開予定時刻を明示した

```bash

# Complete Collection アップロード（デフォルト動作）
uv run yt-upload-collection [-c NAME]
```

## アップロード後確認

- [ ] `--status` で完了ステータスを確認
- [ ] YouTube URL が `upload_tracking.json` に記録された
- [ ] サムネイルが正しく設定されている
- [ ] `collections/planning/` → `collections/live/` に移動された
- [ ] YouTube Studio で「AI 生成コンテンツ」ラベルが表示されている
- [ ] Analytics 監視開始
