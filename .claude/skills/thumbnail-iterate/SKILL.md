---
name: thumbnail-iterate
description: "Use when 伸びた動画を起点にサムネの勝因を分解し、統制した A/B 比較で次の勝ちサムネへ更新するとき。「伸びた動画のサムネ改善」「伸びた動画起点のサムネ A/B テスト」「伸びたサムネテスト」で発動。新規候補生成だけなら /thumbnail、単独の Studio Test & Compare は /thumbnail-test、失速原因分析は /flop-analysis、競合横並びは /thumbnail-compare、整合性監査は /alignment-check を使う"
---

## 前後工程

- `前工程`: `/analytics-report`, `/thumbnail-test`
- `後工程`: `/thumbnail`, `/thumbnail-test`, `/flop-analysis`

## Hard Gates

- 対象動画とチャンネル平均の同一期間・同一定義の impressions CTR、および対象動画の Browse features + Suggested videos 構成比が揃うまで停止する。公開後 D+2 未満など Analytics の確定待ちは推測で補わない。
- `target CTR / channel average CTR >= 1.20` かつ `Browse + Suggested >= 50%` の両方を満たす場合だけサムネ寄与ありとして進む。満たさなければ記録して停止し、原因分析を `/flop-analysis`（旧 `/postmortem`）または `/analytics-analyze` へ委譲する。
- 勝因仮説は `composition` / `text` / `color` / `subject` / `expression` に分解・順位付けし、上位 1〜2 個を提示してユーザー合意を得るまで候補生成しない。
- 通常 round の control A は現在の勝ちサムネで変更 0、B/C は 1 案につき合意済み要素を厳密に 1 個だけ変える。候補は control を含め最大 3 枚。
- Studio の Test & Compare 操作と結果記録は `/thumbnail-test` に委譲する。ブラウザ/API で代行せず、Studio の確定結果が出るまで champion を更新しない。
- `data/thumbnail-iterate/champion.json` は helper が検証済み履歴からのみ更新する。手編集、推測勝者、hash 不一致、symlink を許可しない。

## 完了条件

- 因果判定、合意済み仮説、候補パス・変更要素・SHA-256 が `data/thumbnail-iterate/runs/<video-id>.json` に保存済み。
- `/thumbnail-test` が最大 3 案の手動 Studio 比較を完了し、対象 collection の `20-documentation/thumbnail-test-history.json` に確定結果を記録済み。
- Winner があれば helper で champion を昇格済み。`Performed Same` / `Inconclusive` は champion を変更していない。
- 異なる要素が別 round で勝った場合は機械的に合成せず、`synthesis-required.json` を受けて一貫した 1 枚を再生成し、現 champion を control に最終比較済み。

## References

- `references/state-contract.md` — 保存形式、CLI、停止コード。計画保存と昇格前に読む。
- `references/thumbnail-iterate-state.py` — パス・hash・差分数・履歴対応を検証して状態を原子的に更新する唯一の writer。
- `../thumbnail-test/references/history-schema.md` — Studio 候補と完了履歴の正本。`/thumbnail-test` 委譲前に読む。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Vertex AI Gemini / OpenAI Images（`yt-generate-image`、`/thumbnail` 経由） | 1〜2 | 合意した上位 1〜2 仮説に対応する B/C 各 1 枚。provider retry は `/thumbnail` の設定に従う |

- 上限 / 承認: 因果 gate 通過後に上位 1〜2 要素と生成費用をユーザーが承認した場合だけ `/thumbnail` へ委譲し、control を除く生成候補を最大 2 枚に制限する。

## Workflow

### 1. 対象と因果を確定

`/analytics-report` の同一期間データから対象 CTR、チャンネル平均 CTR、Browse features と Suggested videos の流入比率を取得する。対象コレクション、`workflow-state.json::upload.video_id`、根拠ファイル/期間を表示する。

閾値を満たさない、値が欠落する、期間がずれる場合は改善案を作らない。helper の `plan` で停止記録を残し、サムネ以外も含む `/flop-analysis` へ route する。

### 2. 勝因を分解して合意

勝ちサムネを実際に表示し、次の順で差分を表にする。

1. `composition`: 主役位置、余白、視線誘導
2. `text`: 文言、文字数、サイズ
3. `color`: 明度、彩度、コントラスト
4. `subject`: 人物/物体、占有率
5. `expression`: 表情、視線、感情強度

根拠の強い順に並べ、検証する上位 1〜2 要素をユーザーへ確認する。合意前に画像を生成しない。

### 3. 統制候補を生成

現 winner を A として無変更で保持する。B と任意 C は `/thumbnail` の既存 `yt-generate-image` / `codex-image.sh` 生成経路を使い、それぞれ別の合意済み要素を 1 個だけ変える。ファイル名、変更要素、視覚差分を提示する。

計画 JSON を作り、次を実行する。入力と保存 schema は `references/state-contract.md` に従う。

```bash
python .claude/skills/thumbnail-iterate/references/thumbnail-iterate-state.py plan \
  --repo . --input /tmp/thumbnail-iterate-plan.json
```

### 4. Studio 比較を委譲

対象 collection と A/B/C の対応を渡して `/thumbnail-test` を実行する。advanced features/動画 eligibility/1280x720/hashes の gate、operator の Studio 設定、watch time share と結果の記録はすべて `/thumbnail-test` の責務とする。

### 5. Winner を昇格

Studio 完了履歴が保存された後だけ実行する。

```bash
python .claude/skills/thumbnail-iterate/references/thumbnail-iterate-state.py promote \
  --repo . --video-id VIDEO_ID \
  --history COLLECTION/20-documentation/thumbnail-test-history.json
```

- exit `0`: winner 昇格または勝者なしを安全に記録。
- exit `3`: 別要素の独立 winner がある。一貫した構図として `/thumbnail` で再生成し、`round_type: coherent_synthesis` で現 champion と最終比較する。
- exit `1`: 契約違反。表示された不一致を直し、手動で JSON を迂回しない。

昇格した champion は次回 `/thumbnail` が external benchmark より先に internal TTP として参照する。
