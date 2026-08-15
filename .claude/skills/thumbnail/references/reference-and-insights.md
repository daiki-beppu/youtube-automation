# 参照画像と検証済み insights

通常入口は、プロンプト構築前にこの reference を読む。ここで検証できない値をプロンプトへ入れず、既存の config 展開結果、TTP / anatomy / IP safety clause は変更・削除しない。

## 勝ちパターン参照ゲート

最初に `data/thumbnail-iterate/champion.json` の有無を確認する。存在する場合は `.claude/skills/thumbnail/references/state-contract.md` を読み、`file` が repository 内の実ファイル（symlink 不可）で、現在の SHA-256 が `sha256` と一致することを検証する。失敗時は黙って external TTP へ fallback せず対象と不一致を表示して停止する。検証済み champion は **internal TTP** として external benchmark より先に参照画像と `validated_elements` をプロンプトへ反映する。通常生成 mode から champion JSON を作成・更新しない。

`collections/planning/*/20-documentation/thumbnail-test-history.json` と `collections/live/*/20-documentation/thumbnail-test-history.json` を列挙する。各ファイルは `.claude/skills/thumbnail/references/history-schema.md` の `### Completed history` にある履歴構造検証コマンドだけで確認する。失敗した履歴は対象パスとエラーを表示して修正を案内し、集計から除外してよいが、未検証値をプロンプトへ入れない。

検証済み entry のうち `result.status == "winner"` だけを対象に、`result.result_candidate_id` と一致する candidate の `composition.subject_position` / `composition.subject_scale` / `color_palette[]` / `text_amount` を値ごとに集計する。自由記述の `composition.scene` は結果説明だけに使い、反復集計しない。

- 同じ値が 2 entry 以上で反復: 「検証済み勝ちパターン」として件数を示し、`Historical winners: subject_position=<value>, subject_scale=<value>, colors=<values>, text_amount=<value>.` のうち反復した field だけをプロンプト末尾へ追加する
- 1 entry だけ: 「単発観測」として表示するが、プロンプトの必須方針にはしない
- Winner が 0 件または履歴ファイルが 0 件: 「勝ちパターン履歴なし」と表示し、既存のプロンプト方針だけで続行する

履歴の `performed_same` / `inconclusive` は強い方針へ還元しない。履歴の作成・追記は `/thumbnail --test` の責務であり、このスキルから変更しない。

## 蓄積 insights 参照（lever=thumbnail）

過去サイクルの検証済みの学びは `data/insights.jsonl` から参照する。schema は `.claude/skills/analytics/references/insights-entry.schema.json` が単一ソースであり、この参照は前提ガードではない。

```bash
jq -c 'select(.status == "open" and .lever == "thumbnail")' data/insights.jsonl
```

- 該当エントリがある場合は、生成前に `finding` / `recommended_action` / `evidence` をユーザーへ提示し、差分プロンプトの方針（テキストサイズ・構図・配色など）へ反映する
- `data/insights.jsonl` が存在しない、または該当エントリが 0 件の場合は「thumbnail insights なし」と表示して既存フローで続行する
- 本スキルは insights を提示・参照するだけで、`status` を含むエントリの書き換え・追記はしない。status 反映は `/wf-new`、追記は `/analytics --analyze`、`/analytics --flop`、`yt-experiment judge` の責務である。`source` にかかわらず `status = open` かつ `lever = thumbnail` だけを読む
