# YouTube Studio A/B test operator guide

## Eligibility

- コンピュータ版 YouTube Studio で操作する。
- channel の advanced features が有効であることを確認する。
- private ではない長尺動画または live archive を対象にする。
- Shorts、Scheduled Live、Premiere、Made for Kids、mature audiences、private の動画は対象外。Premiere は終了して長尺動画へ変換された後なら対象にできる。

## テスト開始

1. YouTube Studio にログインする。
2. 左メニューの Content から対象動画を開く。
3. Title 欄または Thumbnail 欄の `A/B Testing` を選ぶ。
4. thumbnail-only のテストを選び、候補を最大 3 枚アップロードする。SKILL.md で割り当てた A、B、C の順序を維持する。
5. `Done` を選ぶ。

テストは数日〜2週間で完了する。結果は CTR ではなく watch time share に基づく。候補のいずれかが 1280x720 未満の場合は、すべてのテスト画像が 854x480 へ縮小されるため、候補はすべて 1280x720 以上を使う。

## 結果確認

1. YouTube Studio の Content から対象動画を開く。
2. Analytics を選ぶ。
3. Reach タブを選ぶ。
4. `How your A/B test is going` の `Manage test` を開く。
5. 完了後に表示された結果ラベルと、A〜C の watch time share を転記する。

結果ラベルは `Winner` / `Performed Same` / `Inconclusive`。画面のラベルを `studio_label` にそのまま記録し、`history-schema.md` の対応表で `status` を正規化する。

実行中に動画の title または thumbnail を変更するとテストは停止する。途中停止したテストは完了結果ではないため履歴へ記録しない。

## 公式資料

- YouTube Help: https://support.google.com/youtube/answer/16391400
- YouTube Data API thumbnail resource（公開メソッドは `thumbnails.set`）: https://developers.google.com/youtube/v3/docs/thumbnails
