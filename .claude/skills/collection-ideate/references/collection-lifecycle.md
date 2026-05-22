# コレクション作成ライフサイクル

## ディレクトリ構造テンプレート

```
XXX-collection-name/
├── 01-master/           # マスター音声・動画（00-master.wav, 00-master.mp4）
├── 02-Individual-music/ # 個別音声ファイル（WAV）
├── 03-Individual-movie/ # 個別動画ファイル（MP4）
├── 10-assets/           # サムネイル・静止画素材（main.png, thumbnail.jpg）
├── 20-documentation/    # 作業文書・プロンプト
└── workflow-state.json  # 進捗トラッキング（コレクションルート）
```

## ワークフロー段階

ディレクトリベースの2段階管理:

```
collections/planning/XXX-name/    → 企画〜制作中（Step 1-4）
collections/live/XXX-name/        → 投稿済み・公開中（Step 5 完了後）
```

### 1. 企画段階（planning/）
1. `/wf-new` で分析フェーズを開始
2. `/channel-status` → `/analytics-collect` → `/analytics-analyze` でチャンネル分析
3. `/collection-ideate` で企画候補生成（既定: テキスト N 案 → 確認 → N 枚一括生成 → 比較選択、N = `preview.candidate_count`、デフォルト 3）→ ユーザーがテーマを選択
4. テーマ確定後にディレクトリ作成・`workflow-state.json` 初期化
5. `/thumbnail` で本番サムネイルプロンプト生成・`yt-generate-image` で画像生成 → `10-assets/thumbnail.jpg`
6. サムネイル確定（ビジュアル方向性確定）

### 2. 制作段階（planning/ 継続）
1. `/suno <theme>` でプロンプト生成・楽曲制作・WAV ファイル整理

### 3. 仕上げ・公開（live/）
1. `/videoup <path>` で動画生成
2. `/video-description <path>` で概要欄作成
3. `/video-upload <path>` で YouTube アップロード実行
4. `planning/` → `live/` に移行（Step 5 完了時）
3. YouTube URL を記録
4. Analytics 監視開始

## チェックリスト

### 制作完了チェック
- [ ] 全楽曲（15-40曲）制作完了
- [ ] 個別音声ファイル整理（WAV）
- [ ] 個別動画ファイル作成（MP4）
- [ ] マスター音声ファイル作成
- [ ] マスター動画ファイル作成
- [ ] サムネイル作成（thumbnail.jpg）

### 投稿準備チェック
- [ ] 概要欄作成（誇張表現なし・AI透明性記載あり）
- [ ] タイムスタンプ作成（afinfo ベース）
- [ ] ハッシュタグ確認（`config/channel/content.json` の `descriptions.hashtags` 参照）
- [ ] YouTube 投稿設定
- [ ] プレイリスト設定

### 投稿後チェック
- [ ] URL 記録（upload_tracking.json）
- [ ] 相互リンク更新（Collection ↔ Individual ↔ Playlist）
- [ ] Analytics 初期確認
