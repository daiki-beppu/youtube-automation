# PROTOTYPE #4896 — fal.ai H3 Max / Turbo vs Veo Fast 実測比較

使い捨て。wayfinder map #4892 の prototype チケット #4896 を解くための実測スクリプトと成果物。
リポジトリの engine 実装には組み込まない（実装は #4898 で起票する issue 群が担う）。

## 何を答えるか

同一 `main.png`・同一プロンプト・8 秒・first = last 同一画像で、fal 経由の MiniMax H3 Max Turbo / H3 Max（768P）を
承認済み Veo 3.1 Fast 1080p の `loop.mp4` と並べ、コスト・速度・目視 3 観点（継ぎ目 / 静止対象の逸脱 / 画質）で
「Veo と同等以上か」を判定する材料を出す。

## 使い方

```bash
PY=/Users/mba/ghq/github.com/daiki-beppu/youtube-automation/.venv/bin/python
$PY fal_h3_compare.py pricing   # GET api.fal.ai/v1/models/pricing の応答形 → out/pricing.json
$PY fal_h3_compare.py run       # 5 本生成 + 後処理 → out/results.json, comparison.md, compare.html
$PY metrics.py                  # 継ぎ目 / 逸脱 / 忠実度の客観指標 → out/metrics.json, comparison.md 末尾
$PY fal_h3_compare.py recheck   # response_url / CDN URL の保持確認 → out/retention.jsonl（翌日も手動で 1 回）
open out/compare.html           # 目視: 6 本を並べて再生、評価 JSON を書き出す
```

`FAL_KEY` は `op read op://Personal/fal_API_Key/credential`。動画・PNG は `.gitignore` で除外し、JSON / md / html だけを残す。

## 成果物

- `out/comparison.md` — 比較表、expanded_prompt、静止指示の残存、客観指標、目視記入欄
- `out/compare.html` — 6 本並列プレビュー（2 周連結、継ぎ目へジャンプ、評価 JSON 書き出し）
- `out/results.json` — request_id / 3 URL / poll 履歴 / timings / ffprobe / 単価
- `out/<candidate>/expanded_prompt.txt`, `result.json`
- `out/retention.jsonl` — 完了直後・1 時間後・2 時間後・翌日の保持確認
- `out/pricing.json` — 単価 API の応答
