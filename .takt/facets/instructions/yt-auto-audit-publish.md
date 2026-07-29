完成した監査レポートを `docs/audits/` へ配置し、order に起票指示がある場合のみ findings を GitHub issue へ起票してください。この step がこの workflow で唯一ファイルを書く工程です。

> タスククローンには git remote が無いため、`gh` はリポジトリを自動解決できない。**すべての `gh` コマンドに `-R daiki-beppu/youtube-automation` を付ける。** remote が無いこと自体は正常であり、失敗の理由にしない。

## 1. レポートの配置

1. Report Directory の `02-audit-ledger.md`（監査台帳 = 最終成果物）と `01-audit-plan.md` を Read で開く（直前の応答は渡されない）
2. 配置先ファイル名を決める:
   - order が issue に紐づく場合: `docs/audits/issue-<番号>-<スラッグ>.md`
   - それ以外: `docs/audits/<YYYYMMDD>-<スラッグ>.md`（日付は `date +%Y%m%d` の実行結果）
   - スラッグは order.md の主題から英小文字ケバブケースで付ける（例: `issue-2686-skill-frontmatter-audit.md`）。既存ファイルと衝突する場合はスラッグを変える。上書きしない
3. 台帳の全文をそのファイルへコピーし、**冒頭に出典ブロックだけを追記する**（本文は一字一句そのまま）:

   ```markdown
   > 出典: takt workflow `yt-auto-audit`
   > タスク: <order.md のタイトル>
   > 実施日: <YYYY-MM-DD>
   > 起票記録: <下記「3. 起票記録」の要約。起票指示がなければ「起票指示なし」>
   ```

## 2. findings の起票（order に起票指示がある場合のみ）

order.md に findings の起票指示が**明示されている場合のみ**行う。指示が無ければ起票せず、出典ブロックの起票記録を「起票指示なし」とする。

1. **重複照合（起票前に必須）**: 起票対象の finding ごとに既存の open issue を検索する。検索語は 1 つに絞らず、場所（ファイル名）・症状・関連するモジュール / CLI 名の 3 方向から引く:

   ```
   gh issue list -R daiki-beppu/youtube-automation --state open --search "<finding から抜いた語>" --json number,title
   ```

   既存が見つかった finding は起票せず、起票記録に「F{n}: 既存 #<番号> と重複のため見送り」と記す

2. **起票**: 重複がないものだけを **1 finding = 1 issue** で起票する。複数 finding を 1 issue へまとめない:

   ```
   gh issue create -R daiki-beppu/youtube-automation --title "[audit] F{n}: <Finding タイトル>" --body "<本文>"
   ```

   本文は台帳の Finding 全文（優先度・対象・場所・何が起きているか・なぜ問題か・影響・推奨対応・完了条件・確認方法）に、出典（配置先レポートのパスと order.md のタイトル）を添えたもの。タイトル・ラベル等の形式を order が指定している場合はそれを正とする。指定が無ければラベルは付けない（triage は人間の判断。既存の `takt:*` ラベルも付与しない — CLAUDE.md）

3. **起票記録**: 起票した issue 番号・重複見送り・失敗を、配置したレポート冒頭の出典ブロック（起票記録）へ記す

## 3. gh 操作に失敗した場合

権限・ネットワーク等で `gh` が失敗しても、**起票失敗を理由に workflow を止めない**（レポートの配置は完了しており、findings も追跡可能な形で残る）。ただし:

- 起票できなかった finding と、そのまま実行できる手動起票用の完全なコマンド（`gh issue create -R daiki-beppu/youtube-automation --title "..." --body "..."`）を、配置したレポート冒頭の出典ブロック内（起票記録の続き）へ追記して残す。本文への追記は行わない（冒頭への追記は出典ブロックのみ）
- 成功した場合とは別の判定として報告する（実行ログ上で区別がつかなくなるため）

## 判定 — 応答の最後に必ずいずれかを一字一句そのまま宣言する

- 配置が完了し、起票指示があればすべて起票（または重複見送り）できた: 「配置(および指示があれば起票)が完了」
- 配置は完了したが、gh の失敗で起票できなかった finding が残っている: 「gh issue の操作に失敗し、起票できなかった finding が残っている(配置は完了)」
- `02-audit-ledger.md` が存在しない、または docs/audits/ へ書き込めない: 「レポートが見つからない、または配置できない」

言い換え・語尾の変更は禁止（この宣言文はワークフローの遷移判定に照合される）。

## 厳禁

- レポート本文を書き換える・要約する・整形し直すこと（追記は冒頭の出典ブロックのみ）
- `docs/audits/` 以外のファイルを変更すること
- order に起票指示が無いのに issue を起票すること（レポートを見た人間が判断する）
- 既存 issue の close / edit を行うこと（起票のみ）
- commit / push すること（タスク実行の後処理が行う）
