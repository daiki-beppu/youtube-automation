# 公開済み動画への AI 開示の遡及対応 (2026-05-30)

Issue: #606 公開済み動画への AI 開示の遡及対応（#603 是正前のアップロード分）
関連: #603 / PR #604（新規アップロード分の `containsSyntheticMedia=True` 是正）

## 1. 概要

#603 / PR #604 で **新規** アップロード分は `status.containsSyntheticMedia=True` に是正されたが、それ以前にアップロードされた公開動画は `False`（または未設定）のまま残る。本チャンネルは AI 生成音楽（Lyria / Suno）を主軸とするため公開済み動画も AI 開示（altered or synthetic content）の対象であり、ポリシー遵守のため遡及反映が必要。

本ドキュメントは遡及対応の手順と、API 不可時の手動 fallback を残すことを目的とする。

## 2. 調査結果: API での後付け反映は可能

issue 起票時の前提（「`videos.update` での後付け変更は反映されない／制約がある」）と異なり、公式 API ドキュメントでは `status.containsSyntheticMedia` は **`videos.insert` と `videos.update` の両方で書き込み可能**と明記されている。

- YouTube Data API v3 `videos` resource: <https://developers.google.com/youtube/v3/docs/videos>
  > In a `videos.insert` or `videos.update` request, this property allows the channel owner to disclose that a video contains realistic Altered or Synthetic (A/S) content.
- YouTube ヘルプ（AI 開示）: <https://support.google.com/youtube/answer/14328491>
  > YouTube 製 AI ツールで作成 / C2PA メタデータ付き / 手動レビュー後にラベル付けされたコンテンツは変更不可。それ以外は調整可能。

→ 本チャンネルの動画は YouTube 製 AI ツール由来ではないため、API での一括反映が可能。手動 Studio 運用ではなく CLI 一括反映を主手段とする。

## 3. CLI: `yt-bulk-update-synthetic-media`

実装: `src/youtube_automation/scripts/bulk_update_synthetic_media.py`

チャンネルの uploads playlist から全公開動画を列挙し、`videos().list(part="status")` で現状を確認、`containsSyntheticMedia` が `True` でないものだけ `videos().update(part="status")` で `True` に反映する。`upload_tracking.json` の日付 cutoff には依存せず、API 上の現状値で判定する（取りこぼし防止）。

### 使い方

```bash
# 1. dry-run（デフォルト。API は read のみ。対象動画を一覧表示）
uv run yt-bulk-update-synthetic-media

# 2. 実反映
uv run yt-bulk-update-synthetic-media --apply

# 3. private 動画も対象に含める（デフォルトは public / unlisted のみ）
uv run yt-bulk-update-synthetic-media --include-private

# 4. 再 dry-run で「遡及対象なし」になれば遡及完了
uv run yt-bulk-update-synthetic-media
```

> 既存 `yt-bulk-update-desc` / `yt-shorts-bulk-update-loc` は無指定で実反映だが、本 CLI は **デフォルト dry-run + `--apply`**（issue #606 指定。安全側に倒す）。

### read-modify-write の注意

`videos.update(part="status")` は status リソース **全体を置換** する。`containsSyntheticMedia` だけを送ると `privacyStatus` / `publishAt` / `selfDeclaredMadeForKids` 等が消える。本 CLI は `videos.list` で取得した現 status をコピーし、read-only キー（`uploadStatus` / `failureReason` / `rejectionReason` / `madeForKids`）を除去したうえで `containsSyntheticMedia=True` だけ差し替えて送る。

### 追跡

CLI は冪等のため、dry-run の対象一覧がそのまま「未対応リスト」を兼ねる。`--apply` 後に再 dry-run して「遡及対象なし」になれば完了。専用の追跡ファイルは作らない。

## 4. 手動 fallback（API が使えない / quota 切れ時）

YouTube Studio で 1 本ずつ設定する:

1. YouTube Studio → 左メニュー「コンテンツ」
2. 対象動画の「詳細」を開く
3. 「変更されたコンテンツまたは合成コンテンツ（Altered or synthetic content）」の項目で「はい」を選択
4. 保存

> 注意: YouTube 製 AI ツールで作成 / C2PA メタデータ付き / 手動レビュー後ラベルの動画は変更不可。

## 5. 検証

```bash
uv run --extra dev python -m pytest tests/test_bulk_update_synthetic_media.py -v
uv run yt-bulk-update-synthetic-media --help
```

実 API スモークは本番の公開動画に書き込むため、まず dry-run で対象数を確認し、`--apply` 後に Studio 上で 1 本の開示反映を目視確認してから全体完了とする。
