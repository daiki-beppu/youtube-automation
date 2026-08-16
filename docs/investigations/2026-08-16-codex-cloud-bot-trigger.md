# Codex Cloud bot メンション発火実測（Issue #4059）

## 結論

GHA cron から `github-actions[bot]` が投稿する `@codex` メンションは、Codex Cloud の自動起動には使えない。同じ repository・issue・指示形式で人間 actor が投稿した positive control は Codex integration に受け付けられた一方、bot actor の投稿には受付 reaction も返信も付かなかった。

したがって ADR-0025 決定 7 の序列を入れ替える。自動起動可能な第一 escape は公式 `openai/codex-action@v1`、Codex Cloud は人間が `@codex` を投稿する第二 escape とする。月次 canary は第一 escape を対象にする。

> 実測日: 2026-08-16（UTC / Asia/Tokyo）。GitHub App の actor policy は将来変わり得るため、再評価時は同じ control を再実行する。

## 実測条件

public repository `daiki-beppu/youtube-automation` の issue #4059 に、ファイル変更・branch作成・PR作成を禁止し、固定markerだけの返信を求める同型のコメントを投稿した。

| control | actor | 投稿日時 (UTC) | 指示marker |
|---|---|---|---|
| bot trigger | `github-actions[bot]` | 2026-08-16 08:32:43 | `CODEX_CLOUD_BOT_TRIGGER_OK:31936715562` |
| positive control | `daiki-beppu` | 2026-08-16 08:36:09 | `CODEX_CLOUD_HUMAN_TRIGGER_OK:20260816T0836Z` |

bot comment は public repository の pull request CIから、job-scoped `issues: write` と `${{ github.token }}` を使って `gh issue comment` で投稿した。workflow run `31936715562` 自体は成功しており、issue comment の作成も成功した。token や外部API keyは追加していない。

## 観測結果

| control | Codex受付 reaction | Codex返信 | 判定 |
|---|---:|---:|---|
| `github-actions[bot]` | なし | 10分25秒の観測窓でなし | 自動発火しない |
| human actor | 処理中に `eyes` あり | 3分41秒後に固定markerとtask linkを返信 | Codex Cloud taskが正常完了 |

bot comment は human positive control より先に投稿され、投稿から10分25秒、human task完了から3分18秒を過ぎても無反応だった。human controlには `chatgpt-codex-connector[bot]` が2026-08-16 08:39:50 UTCに要求どおり返信し、Codex taskへのlinkも付与した。所要時間は投稿から3分41秒だった。repository、issue、mention、権限、Codex integration の有無が共通で actor だけが異なるため、integration未設定やworkflow投稿失敗では説明できない。少なくとも現在の GitHub App event filtering では、Actions bot actor のコメントは Codex Cloud task 起動対象外と判断する。

Codex Cloud の内部実行logは GitHub APIから取得できないため、処理中の `eyes` reaction を受付の観測点とし、要求した固定marker返信とtask linkを完了の観測点とした。今回は副作用を禁止した短いcontrolであり、branch・PR・repository fileはCodex Cloud側から作成されていない。

## 運用上の決定

1. GHA cron からissueへ `@codex` をbot投稿するworkflowは採用しない。
2. 自動escapeと月次canaryは `openai/codex-action@v1` を使う。API従量・secret・spend capは実装issue #4060でfail-closedにする。
3. Codex Cloud は人間がGitHub上で明示的に `@codex` を投稿する復旧経路として保持する。
4. actor policyの変更を示す公式仕様または実測結果が得られた場合だけ序列を再評価する。

## 証跡

- GitHub Actions run: `31936715562`（全job成功）
- bot comment: issue comment `5306548831`
- human positive-control comment: issue comment `5306560869`
- human control reply: issue comment `5306574066`
- 一時的なprobe jobは実測後にworkflowから除去し、恒久CIには残さない。
