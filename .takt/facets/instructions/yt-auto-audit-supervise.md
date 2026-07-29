監査の完全性と品質を判定してください。**あなたは判定のみを行い、監査台帳を書き換えません。**

**重要:** 次のレポートを参照してください:

- 監査計画: {report:01-audit-plan.md}
- 監査台帳: {report:02-audit-ledger.md}

## 検証手順

1. 計画の Audit Targets の行数を数える（= `targets_total`）
2. 台帳の監査台帳表を Audit Targets と一対一で照合する。行の欠落・集約・重複・番号ずれがあれば **table_broken**
3. 台帳で ✅ の行数を数える（= `targets_audited`）。進捗行の申告値ではなく、表の実際の行数を数える。進捗行と実際の行数が食い違っていたら blocking_issues に記載して **rework**
4. ✅ の行から High Priority の対象をいくつか選び、根拠（`file:line`）のファイルを自分でも読んで判定に無理がないか検証する。根拠のない ✅、根拠が実在しない ✅ は監査済みと認めず **rework**
5. Finding 判定の行すべてに Findings 節の詳細があるか、Findings が Issue 直貼り可能な品質か確認する — 何が・どこで（`file:line`）・なぜ問題か（どの判定基準に反するか）・影響・推奨対応が揃っているか
6. ⏳ が残っている、または品質不足なら **rework**。全行 ✅ かつ品質十分なら **approve**

## structured output の記入

- `verdict`: 上の判定（approve / rework / table_broken）
- `targets_total` / `targets_audited`: 数えた実数。推測で書かない
- `blocking_issues`: rework / table_broken の根拠。**次の audit への差し戻し指示になる**ので、対象の # と何が不足かを具体的に書く（例:「#12: 判定 OK だが根拠が `src/module.py` のファイル名のみで行番号がなく、確認結果と対応づかない」）。approve なら空配列
- `summary`: 1-2 文の判定要約

## 厳禁

- 台帳・レポートを書き換えること（判定のみ。台帳の修正は audit の責務）
- 表を数えずに verdict を申告すること
- スコープ外の未監査を理由に rework とすること（スコープは計画の Audit Targets が正、その根拠は order.md）
- テスト・ビルドの再実行、またはその実行証跡の不足を差し戻し理由にすること（実行証跡は台帳の実行証跡節を正とする。この step は readonly であり実行の再要求は成立しない）
