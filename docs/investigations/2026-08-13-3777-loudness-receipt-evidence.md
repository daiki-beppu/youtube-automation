# #3777 masterup loudness receipt evidence

## 判定

#3760 の実データは repository / worktree に含まれず、同じ実音源を使った変更前後3回の時間比較は再現できなかった。そのため受け入れ条件の代替証拠として、決定的な12曲相当 fixture で「全入力を1回ずつ計測し、receipt 検証では計測を0回にする」呼び出し回数を契約テストで固定した。

## 再現コマンドと計測ログ

```text
$ uv run pytest tests/repo/test_masterup_loudness_deviation.py::test_receipt_records_one_full_scan_and_validates_without_measuring -q
1 passed

measurement log:
  receipt generation: 12 calls / 12 inputs (basename の決定的順序も完全一致)
  receipt validation: 0 calls
  receipt.full_collection_scans: 1
  receipt.track_count: 12
```

テストは計測関数へ渡された basename の完全な順序付きリストを12入力の一覧と比較する。receipt 自体にも `full_collection_scans: 1`、`track_count: 12`、`scan_duration_seconds` を保存し、親 orchestration の検証ログで走査回数と対象数を確認できる。

## Fail-closed 証拠

同じテストモジュールが receipt 欠落、JSON破損、入力内容変更、設定閾値変更、閾値違反を独立に検証する。state 更新境界は `tests/commands/media/test_check_raw_master.py` で receipt 検証失敗時に `assets.raw_master` と `updated_at` の両方が不変であることを確認する。
