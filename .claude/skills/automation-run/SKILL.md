---
name: automation-run
description: "Use when 既存設定や明示呼び出しが旧名 automation-run を指定しているとき。正規入口は /wf-auto。一段だけ進める場合は /wf-next、定期実行の設定は /automation-schedule"
---

## 前後工程

- `前工程`: `/automation-schedule`
- `後工程`: `/wf-auto`

## Compatibility alias

`/automation-run` は `/wf-auto` の **compatibility alias**。独自の orchestration、状態判定、lease、履歴実装を持たない。

呼び出されたら `.claude/skills/wf-auto/SKILL.md` を読み、その Hard Gates・実行手順・完了条件をそのまま実行する。reference script も `references/automation-run-state.py` から正規実装 `wf-auto/references/wf-auto-state.py` へ委譲する。

既存の `workflow.scheduled_automation.target_workflow: automation-run` は後方互換として受理する。新規設定の既定は `wf-auto` とする。

状態保存先 `.automation-run/` は既存 run の lease と履歴を継続利用するため変更しない。
