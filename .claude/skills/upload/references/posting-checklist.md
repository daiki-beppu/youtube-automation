# アップロードチェックリスト

## 必須ファイル確認

- [ ] マスター動画（`01-master/00-master.mp4` または `03-Individual-movie/*master*.mp4`）
- [ ] サムネイル（`10-assets/thumbnail.jpg`）
- [ ] 概要欄（`20-documentation/descriptions.md` — `/description` スキルで生成済み）

## コンテンツ品質確認

- [ ] タイトルに誇張表現なし（Epic, Ultimate 等 不使用）
- [ ] AI 透明性・Usage & Attribution セクションあり
- [ ] ハッシュタグ 13個（base + theme 固有）
- [ ] SEO キーワード適切（`channel_config.json` の `tags.base` 参照）

## アップロード実行

```bash
# ドライラン（スケジュール確認）
python3 automation/agents/collection_uploader.py --plan [-c NAME]

# Complete Collection アップロード（デフォルト動作）
python3 automation/agents/collection_uploader.py [-c NAME]
```

## アップロード後確認

- [ ] `--status` で完了ステータスを確認
- [ ] YouTube URL が `upload_tracking.json` に記録された
- [ ] サムネイルが正しく設定されている
- [ ] `collections/planning/` → `collections/live/` に移動された
- [ ] YouTube Studio で「AI 生成コンテンツ」ラベルが表示されている
- [ ] Analytics 監視開始
