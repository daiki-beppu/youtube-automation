```markdown
# Runs Audit Plan

## Evidence Path Check

<!-- 証拠パスは 2 系統。定義監査はクローン内に git 追跡で存在するため確認対象外 -->

| 系統                    | Command                                                        | Result                                  |
| ----------------------- | -------------------------------------------------------------- | --------------------------------------- |
| メインチェックアウト    | `ls /Users/mba/02-yt/00-automation/.takt/runs`                 | {読めたか。run の件数。読めないならエラー全文} |
| 隔離クローン            | {clone-meta の clonePath から run を集めたコマンド}            | {現存したクローン数 / run の件数}       |

- 読めた run の合計: {件数}
- クローンが消失していた分: {件数}（スイープ済み。障害ではない）

## Enumeration Evidence

- Commands used:
  - {meta.json の集計に使ったコマンド}
- Scope notes:
  - {order.md のスコープ指定（対象期間 / 対象 workflow）との対応。指定なしなら全 run}

## Run Inventory

| #   | Workflow      | Runs   | Aborted | Completed | Running | Note                     |
| --- | ------------- | ------ | ------- | --------- | ------- | ------------------------ |
| 1   | {workflow 名} | {総数} | {件数}  | {件数}    | {件数}  | {現行 / 廃止済みなどの区分} |

## Audit Targets

<!-- #1〜#5 は定義監査の固定対象。毎回この # ・この対象名で置く。run 対象は #6 から採番 -->

| #   | Audit Target                       | 対象（run ではなく定義ファイル）                                                                   | 確認すること                                    | Priority            |
| --- | ---------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ------------------- |
| 1   | 検査 E: spillover 複製の一致       | `yt-auto-feature.yaml` / `yt-auto-fix.yaml` / `yt-auto-docs.yaml` / `yt-auto-maintenance.yaml`      | 複製された spillover step 定義の乖離            | Medium              |
| 2   | 検査 F: callable のレポート境界     | `yt-auto-intake.yaml` / `yt-auto-impl-review.yaml` と参照先 facet                                   | 親レポート・親 Report Directory への参照        | Medium              |
| 3   | drift: 工程説明と実配線             | 各 workflow 冒頭コメント / `.takt/config.yaml` / `docs/takt-operations.md` / `CLAUDE.md`            | 工程説明と YAML 実配線の乖離                    | Medium              |
| 4   | ci_verify ゲートの実効性            | 実装系 4 workflow の `ci_verify` step / `yt-auto-ci-verify.md` / `.github/workflows/ci.yml`         | ローカルゲートと CI の検査項目の乖離            | High                |
| 5   | workflow 共通設定の一貫性           | `.takt/workflows/*.yaml` 全件 / `.takt/config.yaml` / `.takt/facets/partials/`                      | skills.repo / persona 実体 / partial include の抜け | Medium          |
| 6   | {同じ問いで束ねた run 群}           | {run ディレクトリ名列挙（所在系統を併記）}                                                          | {ABORT 原因 / 差し戻し経路 / loop monitor 発火} | High / Medium / Low |

## 判定基準

<!-- 固定 5 対象の基準は instruction が与える。run 対象の基準のみここで明文化する -->

| #   | 観点   | OK の条件            | Finding の条件          | 出典                    |
| --- | ------ | -------------------- | ----------------------- | ----------------------- |
| {n} | {観点} | {何を満たせば OK か} | {何があれば Finding か} | {order.md の節 / 規約文書} |

## Audit Order

- {監査順。High Priority から。固定 5 対象は run 対象より先に置く}

## Out of Scope Runs

- {対象外とした run 群と、その理由（正常完走・実験用 workflow 等）}

## Clarifications / Risks

- {確認事項や制約。なければ「なし」}
```

**Audit Targets の契約（後続の全レポートがこの表を骨格として使う）:**

- **#1〜#5 は定義監査の固定対象**。毎回この # ・この対象名で置き、対象列には run ではなく定義ファイル（クローン内・相対パス）を列挙する。run 対象は **#6 から採番する**
- 対象数は固定 5 対象を含めて **24 以下**（run 対象は 19 以下）。超える場合は優先度の低い run 対象同士を統合する（max_steps 32、audit 1 パス最低 4 対象からの逆算値）
- 1 対象 = 監査者が 1 パスで対象 run のトレースを読み切れる粒度（束ねる run は 1 対象あたり概ね 10 件以内。超える場合は代表 run を明示して層化する）
- **run 対象は 1 対象 = 1 run ではなく、同じ問いで束ねられる run 群**（例:「workflow X の aborted run 群」「日付 Y 前後の連続失敗」）とする
- **# は以降の全レポートで不変**。監査台帳（02-runs-audit-ledger.md）の監査台帳表はこの表と一対一（同じ # ・同じ行数・同じ対象名）で照合される
- run が 1 件も読めない場合はこのレポートを出さず ABORT する（空の Run Inventory や推測で埋めた計画を出さない）。定義監査だけが成立する状態は「監査成立」とみなさない
