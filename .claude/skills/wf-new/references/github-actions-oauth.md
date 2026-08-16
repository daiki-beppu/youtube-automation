# GitHub Actions 用 Claude サブスクリプション OAuth

この手順は、下流チャンネルリポジトリの GitHub Actions から Claude Code を headless 実行するためのものです。`CLAUDE_CODE_OAUTH_TOKEN` は Claude サブスクリプション用の長命 credential であり、YouTube の `auth/token.json` や `ANTHROPIC_API_KEY` とは別物です。

## 初回配備

前提は、信頼できるローカル端末で Claude Code にログイン済みであること、対象 private repository の Actions secrets を更新できること、GitHub CLI がその repository に認証済みであることです。

1. 信頼できるローカル端末で `claude setup-token` を実行し、表示された token を一時的にクリップボードへ保持します。token をファイル、shell 変数、コマンド引数、チャット、issue、ログへ保存しません。
2. 対象チャンネルリポジトリへ移動し、`gh secret set CLAUDE_CODE_OAUTH_TOKEN` を引数なしで実行します。標準入力の非表示 prompt に token を貼り付けます。`--body` や `echo ... |` は shell 履歴・process 出力への露出を避けるため使いません。
3. `gh secret list` で secret **名だけ**が存在することを確認します。GitHub は保存値を再表示しないため、値の照合は行いません。
4. repository の Actions failure 通知を受け取れるよう、GitHub の通知設定と repository の watch 設定を確認します。失敗時は workflow の job failure と Step Summary を通知経路の正とします。

workflow と定期 trigger の配布・設定は `/wf-new --schedule` が所有します。secret 配備のために workflow YAML を直接編集しません。

## 動作確認

定期実行を待たず、Actions 画面の **YouTube automation → Run workflow**、または次の手動 trigger を使います。

```bash
gh workflow run youtube-automation.yml --ref <default-branch>
gh run list --workflow youtube-automation.yml --limit 1
```

成功条件は job が成功し、headless agent 工程を通過することです。token 値をログへ出す確認はしません。失敗した場合は `gh run view <run-id> --log-failed` で認証エラーか、それ以外の runner エラーかを切り分けます。

## 失効検知と fail-closed

配布 workflow は Claude 経路で secret が空ならサンドイッチ runner を起動せず非 0 で停止します。token が失効・拒否されて Claude CLI が非 0 になった場合も、その status を維持して停止し、同じ job 内では再試行しません。失敗後の成果物 push や workflow-state commit は行われません。

job の Step Summary には secret 値を含めず、ローテーション手順への案内だけを記録します。GitHub Actions の failure 通知を受けたら、ログ内の認証診断を確認して次のローテーションへ進みます。認証以外の失敗を token 失効と決めつけて差し替えません。

## ローテーション

1. 認証失敗を確認したら、再配備が終わるまで `github_actions_schedule.py disable` で定期 trigger を停止します。実行中 job があれば完了を待ち、同じ secret を複数回差し替えません。
2. 信頼できるローカル端末で `claude setup-token` を再実行し、新しい token を発行します。
3. 対象 repository で `gh secret set CLAUDE_CODE_OAUTH_TOKEN` を実行し、非表示 prompt から新しい token へ置き換えます。
4. `workflow_dispatch` で1回だけ動作確認し、job success を確認します。失敗時は schedule を再開せず、ログを切り分けます。
5. 成功後に `/wf-new --schedule` の dry-run・承認手順を通して、以前と同じ UTC cron を再設定します。クリップボードの token は消去します。

旧 token の失効操作が Claude Code 側で必要になった場合は、その時点の公式なアカウント管理手順に従います。旧 token を repository secret に戻す rollback は行いません。復旧不能なら schedule を disabled のまま保ち、ADR-0025 の切替条件 4 に従って実行経路を再評価します。
