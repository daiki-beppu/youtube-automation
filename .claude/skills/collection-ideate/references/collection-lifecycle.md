# コレクション作成ライフサイクル

## ディレクトリ構造テンプレート

```
XXX-collection-name/
├── 01-master/           # マスター音声・動画（*.mp3, *.mp4）
├── 02-Individual-music/ # 個別音声ファイル（*.mp3）
├── 03-Individual-movie/ # 個別動画ファイル（MP4）
├── 10-assets/           # サムネイル・静止画素材（thumbnail.jpg, textless main.png/jpg, planning-preview.png）
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
2. 入力モードを判定
   - analytics mode: 同じファイル名日付の `reports/analysis_*.md` / `.json` ペアが存在し、`.claude/skills/analytics-analyze/references/analysis-json-validator.md` の validator が exit 0 で、stale ではない。日次収集データ + 構造化分析 JSON + ベンチマーク + config を使う
   - benchmark fallback mode: `reports/analysis_*.md` が存在せず、`data/benchmark_*.json` が存在する。ベンチマーク + config を使う
   - minimal mode: `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない。`ttp_mode: false` は企画候補生成前にテーマ / ジャンル / 雰囲気を直接確認し、その入力 + config を使う。`true` は `/benchmark` を案内して停止し、`data/benchmark_*.json` が生成されるまで企画候補を生成しない
3. 最新 `reports/analysis_*.md` に同日付 JSON がない、または validator が失敗した場合は fallback せず停止。Markdown / JSON ペアが stale（最新 `data/analytics_data_*.json` より古い、または最新データが実行日から `freshness_days` を超えて古い）なら freshness-rules.md の stale action とコスト承認へ分岐し、承認済みの自動分析後にペア・validator・鮮度を再検証する。絶対 stale は `/analytics-collect` → `/analytics-analyze` の順で実行する
4. `/collection-ideate` で企画候補生成（既定: テキスト N 案 → 確認 → N 枚一括生成 → 比較選択、N = `preview.candidate_count`、デフォルト 3）→ ユーザーがテーマを選択
5. テーマ確定後にディレクトリ作成・`workflow-state.json` 初期化
6. `/thumbnail` で本番背景プロンプト生成・画像生成 → textless `10-assets/main.png` または `main.jpg`
7. 承認済み `main.png/jpg` からテキスト付き `10-assets/thumbnail.jpg` を生成し、サムネイルと動画背景を別成果物として確定

### 2. 制作段階（planning/ 継続）
1. `/suno <theme>` または `/lyria <theme>` でプロンプト生成・楽曲制作・個別音声整理（公開ワークフローの共通契約は MP3。WAV は Lyria / DAW の中間成果物）

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
- [ ] 個別音声ファイル整理（`02-Individual-music/*.mp3`。WAV は中間成果物）
- [ ] 個別動画ファイル作成（MP4）
- [ ] マスター音声ファイル作成
- [ ] マスター動画ファイル作成
- [ ] textless 動画背景作成（main.png または main.jpg）
- [ ] サムネイル作成（テキスト付き thumbnail.jpg）

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
