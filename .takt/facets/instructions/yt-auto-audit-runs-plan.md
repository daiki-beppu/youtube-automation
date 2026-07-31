takt 資産の監査を始める前に、証拠パスの読み取りを確認し、監査対象を棚卸しして計画と台帳スケルトンを作ってください。**この step ではファイルを変更せず、監査そのものも行いません。**

この workflow は 2 系統を監査します:

- **定義監査** — `.takt/workflows/*.yaml` と `.takt/facets/` の整合。固定 5 対象（#1〜#5）として毎回検査する
- **run 監査** — `.takt/runs` の実行トレースを run 横断で分析する

## 1. 証拠パスの確認（最初に必ず行う）

run トレースの所在は 2 系統ある。takt はタスクを隔離クローンで実行するため、`yt-auto-*` の実行トレースはメインチェックアウトではなくクローン側に作られる。**両方を走査すること。**

**(a) メインチェックアウト:**

```bash
ls /Users/mba/02-yt/00-automation/.takt/runs
```

**(b) 隔離クローン（`.takt/clone-meta/*.json` の `clonePath` から辿る）:**

```bash
python3 -c "
import json, glob, os
for f in glob.glob('/Users/mba/02-yt/00-automation/.takt/clone-meta/*.json'):
    try:
        p = json.load(open(f)).get('clonePath')
    except Exception:
        continue
    r = os.path.join(p or '', '.takt/runs')
    if os.path.isdir(r):
        print(r)
"
```

- **クローンは takt のスイープで消える。** 現存しない clonePath が大半でも障害ではない。読めた分だけで監査を進め、消失件数を計画に記録する
- **必ず `clone-meta` 経由で辿ること。** クローンの置き場（`<repo-parent>/takt-worktrees/`）は同じ親ディレクトリの他リポジトリと共有されており、直接 glob すると**他リポジトリの run が混入する**。混入検査として、各 run の `meta.json` の `workflow` が本リポジトリの workflow 名（`yt-auto-*` / `audit-unit-split` / takt builtin）であることを確認する
- 両系統を合わせて run を **1 件も読めない場合**は、計画を作らず ABORT を申告する。空の Run Inventory や推測で埋めた計画を出してはならない。ABORT の申告には実行したコマンドとエラー出力をそのまま含める（サンドボックスの read 制限やリポジトリ移動の検出を兼ねる）
- 定義ファイルは**クローン内に git 追跡で存在する**ため、証拠パス確認の対象にしない。相対パスで読む

## 2. 定義監査の固定対象（#1〜#5。毎回必ず含める）

Audit Targets の先頭に、この 5 対象をこの # ・この対象名で置く。run 対象は **#6 から採番する**。

| #   | Audit Target                   | 対象ファイル                                                                                  | 確認すること                                        |
| --- | ------------------------------ | --------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| 1   | 検査 E: spillover 複製の一致   | `yt-auto-feature.yaml` / `yt-auto-fix.yaml` / `yt-auto-docs.yaml` / `yt-auto-maintenance.yaml` | 複製された spillover step 定義の乖離                |
| 2   | 検査 F: callable のレポート境界 | `yt-auto-intake.yaml` / `yt-auto-impl-review.yaml` と参照先 facet                              | 親レポート・親 Report Directory への参照            |
| 3   | drift: 工程説明と実配線        | 各 workflow 冒頭コメント / `.takt/config.yaml` / `docs/takt-operations.md` / `CLAUDE.md`       | 工程説明と YAML 実配線の乖離                        |
| 4   | ci_verify ゲートの実効性       | 実装系 4 workflow の `ci_verify` step / `yt-auto-ci-verify.md` / `.github/workflows/ci.yml`    | ローカルゲートと CI の検査項目の乖離                |
| 5   | workflow 共通設定の一貫性      | `.takt/workflows/*.yaml` 全件 / `.takt/config.yaml` / `.takt/facets/partials/`                 | skills.repo / persona 実体 / partial include の抜け |

- 固定対象の Priority は **#4 を High**（ローカル git hook 廃止後、`ci_verify` が auto_pr の push を止める唯一の関門であり、抜けると無検証の PR が出る）、他は既定 Medium とする。run 対象の緊急度に応じて上下してよい
- 具体的な検査手順は audit step の instruction が持つ。この step では対象の確定だけを行う

## 3. run 対象の棚卸し

1. order.md が指定する監査スコープ（対象期間 / 対象 workflow）を確認する。指定がなければ読めた全 run
2. 各 run の `meta.json` から workflow / status / currentStep / iterations を**コマンドで機械的に集計する**（全 run を 1 件ずつ精読しない）
3. 分析価値の高い run を特定する — `status: aborted` の run、iterations が突出して多い run（差し戻しを繰り返した末の完走）、同一 workflow で失敗が連続している時期、loop monitor 発火が疑われる run（`trace.md` に judge step の Iteration が現れる）、同一 step の Iteration が judge を挟まず 4 回以上再出現する run（cycle 外からの再入による loop monitor 不発の疑い）
4. **1 対象 = 1 run ではなく、同じ問いで束ねられる run 群**（例:「`yt-auto-fix` の aborted run 群」「日付 Y 前後の連続失敗」）を 1 対象として採番する
5. 再発パターンの抽出に効く順（失敗の集中度・最近性・現行 workflow との関連）で監査順を作る

## 4. 判定基準の確定

run 対象については、観点ごとに「何を満たせば OK / 何があれば Finding」を明文化する。order に判定基準があればそれを正とし、無ければリポジトリの規約文書（`CLAUDE.md` / `docs/takt-operations.md` / `docs/adr/` の有効 ADR）から導出して出典を書く。後段の audit はこの基準だけで判定する — 「品質が十分か」のような判定者依存の基準を残さない。固定 5 対象の基準は audit の instruction が与えるため、ここで再定義しない。

## 5. 台帳スケルトンの作成

レポートフェーズで 2 つのファイルを出力する:

- 監査計画（01-runs-audit-plan.md）
- 監査台帳の初期版（02-runs-audit-ledger.md）: Audit Targets の全対象を同じ # ・同じ対象名の ⏳（未監査）行として 1 行ずつ列挙し、進捗行を「監査済み: 0/N」、Status を IN_PROGRESS とする。「Loop Monitor 不発の疑い」節と「Token Usage」節は見出しだけ置き、本文は「未集計」とする

## Audit Targets の粒度と上限（後続の全工程がこの表を骨格として使う）

- **対象数は固定 5 対象を含めて 24 以下**（run 対象は 19 以下）にする。超える場合は優先度の低い run 対象同士を統合する。この上限は workflow の容量（max_steps 32、audit 1 パス最低 4 対象）から逆算した値であり、超えると完走できない
- 1 run 対象 = 監査者が 1 パスで対象 run の `trace.md` / `meta.json` / `monitor.json` を読み切れる範囲。束ねる run は 1 対象あたり概ね 10 件以内とし、超える場合は代表 run を明示して層化する
- 採番した **# は以降の全レポートで不変**。台帳の監査台帳表はこの表と一対一（同じ # ・同じ行数・同じ対象名）で照合される

## 重要

- 台帳スケルトンにはスコープ全対象を省略せず列挙する。「以下同様」等の省略記法は禁止
- 台帳スケルトンの出力を省略しない。次 step は台帳ファイル（02-runs-audit-ledger.md）を注入参照するため、ファイル未存在だと失敗する
- 疑わしい数 run だけではなく、まずスコープ全体の run を機械的に集計してから対象を選ぶ
- completed の run も、iterations が突出して多いものは差し戻しの再発源として対象に含める
- 対象外とした run 群も、その理由（正常完走・実験用 workflow 等）を計画に明記する

## 判定 — 応答の最後に必ずいずれかを一字一句そのまま宣言する

- 監査対象表と初期台帳を出力した: 「対象の棚卸しと監査対象表・初期台帳の作成が完了」
- order が監査タスクではなく質問だった: 「ユーザーが質問をしている(監査タスクではない)」
- 両系統の証拠パスから run を 1 件も読めなかった: 「run 証拠を両系統とも読めず、定義監査だけでは監査が成立しない」— このときは実行したコマンドとエラー出力をそのまま添える
- スコープ・観点が確定できない、または対象数が上限に収まらない: 「スコープが不明確で監査対象を確定できない」— このときは何が決まれば監査できるか（不足している情報、またはスコープ分割案）を必ず列挙する

言い換え・語尾の変更は禁止（この宣言文はワークフローの遷移判定に照合される）。
