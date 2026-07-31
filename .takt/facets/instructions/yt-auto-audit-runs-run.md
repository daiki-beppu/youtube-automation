監査台帳を 1 パス分拡張してください。台帳を最初から作り直すのではなく、既存台帳を保持したまま未監査分を進めます。**ファイルは変更しません。**

**システムの動作（必ず理解すること）:** レポートフェーズであなたが出力した応答は、台帳ファイル `02-runs-audit-ledger.md` を**まるごと置き換える**。応答に含めなかった行は消滅し、次のパスへ引き継がれない。「既存行は保持する」と書いても保持されない。毎回、台帳の完全版（全行）を出力すること。

**重要:** 監査計画を参照してください:

{report:01-runs-audit-plan.md}

**重要:** 現在の監査台帳（この内容を保持したまま拡張する）:

{report:02-runs-audit-ledger.md}

## パスの種類を最初に判定する

- 台帳に ⏳（未監査）行が残っている → **拡張パス**
- 進捗行が N/N で全行 ✅ だが、supervise（blocking_issues）または review から不足を指摘されて差し戻された → **修正パス**
- supervise が table_broken（台帳の対象表が計画の Audit Targets と一対一でない: 行の欠落・集約・重複・番号ずれ）で差し戻した → **再整合パス**
- 台帳の進捗行・集計が本文の実際の行数と食い違っている（過去パスの出力欠落による破損）→ **本文の実行数を正**として進捗行・集計を修正し、実在する ✅ 行を ⏳ へ戻さずに拡張パスを続行する

## 拡張パスでやること

1. 台帳の ⏳ 行から、計画の監査順に従って今回パスの対象を**最低 4 件**（残りが 4 件未満なら全件）選ぶ
2. 対象が定義監査（#1〜#5）なら下の「定義監査の検査手順」、run 監査（#6 以降）なら「run 監査の分析手順」に従う
3. 判定を台帳へ記録する:
   - **OK**: 判定基準に対して**何と何を照合したか**を「確認結果」に書き、根拠を必ず添える。定義監査は照合した対象を明示しない ✅ を認めない
   - **Finding**: F 番号を採番して行に書き、Findings 節へ Issue 直貼り可能な粒度（何が・どこで・なぜ問題か・影響・推奨対応・完了条件・確認方法）で詳細を書く
4. 使ったコマンドと、確認できなかったこと（推測せず「未確認」と明記）を実行証跡へ記録する
5. 最初のパスでは併せて「Token Usage」節を機械集計で作る（下記）

## 定義監査の検査手順（#1〜#5）

定義ファイルはクローン内に git 追跡で存在する。`.takt/runs` の絶対パスは使わず、リポジトリルートからの相対パスで読む。

### #1 検査 E: spillover 複製の一致

`yt-auto-feature.yaml` / `yt-auto-fix.yaml` / `yt-auto-docs.yaml` / `yt-auto-maintenance.yaml` の `spillover` step 定義（**直前のコメントブロックを含む**）を突き合わせる。

- **意図された差分は「因果あり発見の戻し先」だけ** — `yt-auto-fix` は `diagnose`、他 3 つは `plan`（診断からやり直す fix と、計画からやり直す他レーンの違い）。この差分とそれを説明するコメント中の宛先表記は Finding にしない
- それ以外の差分（`quality_gates` / `rules` の順序と文言 / `policy` / `knowledge` / `provider_options` / `session` / **コメントの有無と文言**）はすべて乖離であり、該当ファイルの行を引用して Finding にする
- **コメントの欠落を「些細」として見逃さない。** rule の順序には「先に置かないと下の rule に吸われて素通りする」という非自明な理由があり、それを説明するコメントが一部のファイルにしか無い状態は、次に順序を触る人が理由を知らないまま壊せる状態を意味する

### #2 検査 F: callable のレポート境界

callable の子 workflow は**自分専用の report namespace を持ち、親のレポートを参照できない**（doctor は通るが実行時に壊れる）。

1. 親側（`yt-auto-feature.yaml` / `yt-auto-fix.yaml` / `yt-auto-docs.yaml` / `yt-auto-maintenance.yaml`）の `output_contracts` からレポート名を集める
2. callable（`yt-auto-intake.yaml` / `yt-auto-impl-review.yaml`）の各 step が参照する instruction facet のうち、リポ内（`.takt/facets/instructions/`）に実在するものを走査する
3. 親のレポート名への参照（report プレースホルダ記法経由を含む）や、自分の Report Directory の外を探索させる指示を検出したら Finding にする。根拠は facet 名と該当行の引用
4. リポ外の builtin facet は対象外とし、その旨を確認結果に書く

### #3 drift: 工程説明と実配線

工程説明 4 箇所 — (a) `.takt/workflows/*.yaml` の冒頭コメントと `description`、(b) `.takt/config.yaml` の冒頭コメント（workflow 一覧）、(c) `docs/takt-operations.md`、(d) `CLAUDE.md` の「開発ワークフロー」節 — を、YAML の実配線（step 名・遷移・loop monitor・callable の呼び出し）と照合する。

- 乖離はすべて確認結果に記録し、**実体と明確に矛盾する記述**（存在しない step・実在しない遷移・廃止済み要素への言及・実在する workflow が一覧から欠けている）だけを Finding にする
- 表現の粗さや詳細度の違いは Finding にしない

### #4 ci_verify ゲートの実効性

本リポジトリはローカル git hook を持たず、`ci_verify` step が auto_pr による push を止める唯一の関門である。実装系 4 workflow（feature / fix / docs / maintenance）の `ci_verify` step と `yt-auto-ci-verify.md`、`.github/workflows/ci.yml` を照合する。

1. `ci.yml` の各 job が実行するコマンドを列挙する（条件付き job はその条件も）
2. `yt-auto-ci-verify.md` が実行を指示するゲートを列挙する（無条件のものと変更内容に応じた追加ゲートを分ける）
3. 両者を突き合わせ、片側にしか無いゲートを洗い出す
4. 4 workflow の `ci_verify` step 定義（`instruction` / `rules` / 差し戻し先）が揃っているかを確認する

**判定基準（乖離の向きで扱いが変わる。両方を同じ基準で見ない）:**

- **A: CI にあってローカルに無いゲート → 必ず Finding。** ローカル git hook を廃止した本リポジトリでは、`ci_verify` が green を出しても PR の CI が落ちる状態は「auto_pr が無検証で push する経路」そのものである。優先度は高
- **B: ローカルにあって CI に無いゲート → 規約文書が品質ゲートとして挙げている検査に限って Finding。** 判定の線は `CLAUDE.md` の品質ゲートの記述と `docs/development.md` の品質ゲート節に引く。そこに挙がっていない検査は「ローカルで先に見たいだけの追加」であり乖離ではない（確認結果に記録するだけ）。挙がっているのに CI に無いなら、CI 側の穴として Finding にする
- **除外**: `ci.yml` の条件付き job（`build-smoke` / `windows-cost-tracker` 等、変更内容次第で走らないもの）と、ローカルで原理的に再現できないゲート（`windows-latest` 等）は Finding にしない。**確認結果に「意図的な差分」として対象名と理由を記録する**（無言で省略しない）
- **4 workflow の `ci_verify` step 定義の不揃いは検査 E（#1）と同じ基準で判定する** — レーン固有の差し戻し先を除き、`instruction` / `rules` / `quality_gates` / コメントの差分は乖離として Finding にする

### #5 workflow 共通設定の一貫性

`.takt/workflows/*.yaml` 全件と `.takt/config.yaml`、`.takt/facets/partials/` を横断で照合する。新規 workflow 追加時に忘れやすい設定が対象。

- **`skills.repo: true`**: 本リポジトリは `.agents/skills`（→ `.claude/skills`）を Codex 向けに維持しており、takt 0.53 で workflow の Skill 継承が既定 off になった（#1081）。`yt-auto-*` の全 workflow が `workflow_config.provider_options.codex.skills.repo: true` を持つか確認する。`audit-unit-split` は v5 未実測ベースライン保全のため**意図的に不変更**であり、欠落を Finding にしない
- **persona の実体**: `.takt/config.yaml` の `provider_routing.personas` に列挙された persona が、takt builtin または `.takt/facets/personas/` に実在するか確認する。実体の無い persona へのルーティングは黙って既定モデルへフォールバックする（過去に `requirements-reviewer` で実踏済み）
- **`final-gate` タグ**: `final-gate` タグを持つ step と、`.takt/config.yaml` の `provider_routing.tags.final-gate` の定義が対応しているか確認する。builtin の `merge-readiness-final-gate` を `call` している workflow はタグを自前で持たないため、欠落を Finding にしない
- **partial include**: `.takt/facets/partials/instructions/` の各 partial が、対象とすべき instruction すべてから include ディレクティブで取り込まれているか確認する（include は二重波括弧の記法。この instruction 自身に書くと takt が実際の参照として解決してしまうため、検索は `partials/` 配下の partial 名で grep する）。実装系 instruction（コードを書く step の instruction）に入っていない partial があれば Finding にする

## run 監査の分析手順（#6 以降）

証拠は計画の Evidence Path Check が示した 2 系統にある。読み方:

- `meta.json` — workflow / status（completed / aborted / running）/ currentStep（止まった step）/ iterations（消費 step 数）
- `trace.md` — `## Iteration N: <step> (persona: ...)` の見出しから遷移系列を再構成できる。ABORT 原因・差し戻し経路はこの系列と各 Iteration の本文から読む
- `monitor.json` — OTel metrics。step ごとの実行回数と phase の状態

1. 担当 run の `meta.json` で結末を掴む
2. `trace.md` の見出しから遷移系列を再構成し、ABORT 原因・差し戻し経路・loop monitor 発火を特定する
3. 遷移系列から **loop monitor 不発**を検査する:
   - 同一 step の訪問回数を数える。並列サブ step は同じ Iteration 番号を共有するので 1 訪問、`Iteration N-M: a ↔ b loop (K cycles)` の圧縮見出しは各 step K 訪問と数える
   - 同一 step が **4 回以上**現れ、その反復の間に当該 step を含む `_loop_judge_...` の Iteration が無ければ**不発の疑い**（別 step の挟み込みで cycle の連続一致が途切れ、threshold 未達のまま反復した）。各再入の直前 Iteration の step を**再入元**として記録する
   - 現行の `.takt/workflows/` に同名 workflow・同名 step が存在するか確認し、存在するなら rules と instruction facet に `{step_iteration}` の自前上限があるか確認する
   - 自前上限なし → **高確度発見**（Findings に Category: loop-monitor で載せる）。自前上限あり / 現行定義に workflow・step が無い（builtin workflow・削除済み step を含む）→ **記録のみ**（「Loop Monitor 不発の疑い」節にのみ載せる）
4. **self-loop（同一 step が自分自身へ遷移する構成）は loop monitor のパターン一致対象外**であり、不発ではなく設計上の既知の限界である。`max_steps` が唯一のガードになっている step を見つけたら、不発の疑いとしてではなく容量リスク（Category: capacity）として記録する
5. 発見を **run 名 + トレース引用**（`trace.md` の該当箇所の引用）を根拠として記録する
6. 対象単体の観測に加えて、**複数 run にまたがる再発パターン**を 1 Finding にまとめる（Finding ごとに該当 run をすべて列挙する。run ごとに Finding を割らない）

## Token Usage の機械集計（最初のパスでのみ実行）

**コマンドで機械的に集計する**（jsonl を 1 件ずつ精読しない）。対象は計画の Run Inventory と同じスコープの全 run（Audit Targets に選ばれなかった run も含む）。

1. 各 run の `logs/*-usage-events.phase.jsonl` を読む。`usage_missing` が true の行は除外し、`usage.total_tokens` を run ごとに合算する（セッションが複数あればすべて合算）
2. 有効な usage を 1 行も持たない run は**集計対象外**とし、件数と理由（phase.jsonl が無い / 全行 usage_missing）を内訳で明示する。集計対象外があっても集計を壊さず、残りの run で集計を完遂する
3. workflow 別（`meta.json` の workflow で束ねる）に、集計対象 run 数・total_tokens 合計・run あたり中央値を出す
4. step 別（jsonl の `step` フィールド）に消費を集計し、workflow ごとに消費上位の step と workflow 合計に占める割合を出す
5. 単一 step が workflow 合計の 3 割を超える場合は突出として所見に明記する。**費用の偏りは所見として記録するだけで、Findings に書かない・起票候補にしない**（見合うか・削るかは人間の判断）。ただし偏りの原因が根拠を示せる欠陥（例: 差し戻しループによる浪費）である場合、その欠陥は通常どおり Findings に書く

2 パス目以降は Token Usage 節を**そのまま保持する**（再集計しない。節が欠けている場合のみ補う）。

## 修正パスでやること

1. 指摘された行・Finding・集計**だけ**を修正する。指摘されていない行は一字一句そのまま維持する
2. ✅ 行を ⏳ へ戻さない。台帳をゼロから再構築しない
3. 修正内容と対応する指摘（blocking_issues の項目 / review の指摘）を応答本文で対応付けて報告する

## 再整合パスでやること

1. 計画の Audit Targets を骨格として、台帳の監査台帳表を一対一（同じ # ・同じ行数・同じ対象名）に再構成する
2. 既に監査済みの内容（✅ 行の判定・確認結果・根拠・Findings）は該当する # の行へ移し替えて維持する。実際に監査した記録を捨てない
3. 欠落していた対象は ⏳ 行として追加する。番号は計画の # に合わせる

## レポートフェーズ（共通）

既存台帳の全行（✅ 行・Findings・Loop Monitor 不発の疑い・Token Usage・実行証跡）を一字一句保持したまま、今回分の更新を反映した**完全版**を出力する。出力前に本文の ✅ 行数を数え、進捗行「監査済み: n/N」・集計と一致することを確認する。

## 応答の最後に必ずいずれかを一字一句そのまま宣言する

- 進捗行が N/N に達し ⏳ 行が残っていない場合のみ: 「スコープ全件の監査・判定が完了した」
- それ以外: 「台帳を拡張したが未監査の残件がある」（今回監査した件数と残件数を数値で添える）
- 証拠パスの消失など、監査の続行が不可能な場合のみ: 「監査を継続できない障害がある」（何が障害かを具体的に書く）

言い換え・語尾の変更は禁止（この宣言文はワークフローの遷移判定に照合される）。

## 禁止事項

- 「既存行は保持する」等の宣言で行の再掲を省略すること（行の物理消滅を招く）
- 既存の ✅ 行・Findings・Token Usage を要約・削除・言い換えすること
- 実際に読んでいない対象を ✅ へ変更すること
- 定義監査で、何と何を照合したかを書かずに ✅ とすること
- 「〜が怪しい」で止めること。遷移系列と引用で示せない主張は、根拠不足として明記する
- 進捗行と表の実際の行数が食い違う報告をすること
- 複数対象を 1 行へ集約すること、# を振り直すこと
- リポジトリのファイルを変更すること
