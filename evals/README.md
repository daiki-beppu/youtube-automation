# Skill E2E evaluations

`promptfoo` から `claude -p` を起動し、自然言語で定義された skill の実挙動を確認するローカル評価です。通常の `pytest` には含まれず、Claude Code の認証とモデル利用料金が必要です。

## wf-status

第一弾は、v1 / v2 の状態を持つ評価専用チャンネルで `/wf-status` を実行します。

```bash
nix develop --command pnpm dlx promptfoo@0.122.0 eval -c evals/promptfooconfig.yaml
```

次の契約を決定的な Python assertion で判定します。

- 許可外 tool の呼び出し試行が `claude -p --output-format json` の `permission_denials` に無い
- `workflow-state.json` が実行前後で不変
- fixture 全体が実行前後で不変

provider は cwd と `CHANNEL_DIR` を `evals/fixtures/channel/` に固定します。利用可能な built-in tool は Read / Glob / Grep / Bash だけで、Bash は fixture の v2 state に対する読み取り専用 `yt-raw-master-check` 1 コマンドへ完全一致で限定します。`dontAsk`、project settings のみ、空の strict MCP config を併用するため、それ以外の実行は承認待ちにならず拒否されます。

実行中に fixture の変更を検出した場合、assertion を fail にした後で開始時の byte 列へ復元します。終了後は次でも確認できます。

```bash
git diff --exit-code -- evals/fixtures/channel
```

### assertion の検出力

モデルを呼ばず、意図的な禁止 tool 試行と state 変更を表す保存済み出力へ同じ assertion を適用できます。このコマンドは非 0 で終了するのが正常です。

```bash
nix develop --command pnpm dlx promptfoo@0.122.0 eval \
  --assertions evals/assertions/wf_status_violation_check.yaml \
  --model-outputs evals/fixtures/wf-status-violation.json
```

promptfoo の履歴と cache は既定で `~/.promptfoo/` に保存されます。リポジトリ内へ明示出力する場合は ignore 済みの `evals/results/` を使ってください。
