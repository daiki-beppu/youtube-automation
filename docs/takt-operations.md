# Issue / worktree 運用(takt 正規経路)

> 2026-07-30(#2686)以降、このリポジトリの標準実装経路は takt + リポジトリ専用 workflow である。2026-07-23(#2453)の takt 廃止は「ドキュメントが前提とする workflow の実体が環境に存在しない」ことが原因だった。現在は workflow を `.takt/workflows/` で git 管理し、`takt workflow doctor` で機械検証するため、廃止の根拠は解消されている。

## issue の粒度

**1 issue = 1 PR = 1 振る舞い変更**を単位とする。PR は stacked PR 前提であり、レビューは 1 段ずつ独立に行う。次のいずれかに当たる issue は着手前に分割する。

- 要件が 3 件以上ある
- 影響ファイルが 4 件以上ある
- 独立した関心事が 2 つ以上混ざっている
- 実装が複数 PR に分かれる見込みがある

分割して得た各 issue は、加えて次を満たす。

- **単体で検証可能**: その issue だけを完了させた時点で挙動を実演または検証できる
- **全レイヤを貫く**: config / ロジック / CLI / skill を縦に貫通する狭い経路にする。1 レイヤだけを横に切らない
- **1 context に収まる**: 新規セッション 1 本で実装しきれる分量に収める
- **prefactor を先に置く**: 実装を楽にする下準備が必要なら、それを先行 issue として独立させる

分割は sub-issue(GraphQL `addSubIssue`)で親へ接続し、実装順の依存は `addBlockedBy` で表す。親子は階層であって依存関係ではないため両方を持たせる。着手は blocker がすべて close した子(frontier)から選ぶ。

リネームのように 1 つの機械的変更が全域へ波及する wide refactor は縦に切れない。expand(新しい形を旧い形の隣に追加)→ migrate(呼び出し側をディレクトリ単位のバッチで移す。各バッチを 1 issue とする)→ contract(旧い形を削除)の順に並べ、各段を stack の 1 段に対応させる。

## 正規ルート

1. `gh issue create` または `/issue` で issue を起票する。
2. workflow を選んでタスクを投入する(`auto_pr` を必ず有効化する):

   ```bash
   takt add '#<issue番号>'   # 対話で workflow と auto_pr を設定
   takt run                  # pending タスクを実行
   ```

3. workflow が完走すると takt の `auto_pr` がサンドボックス外で commit → push → PR 作成を行う。
4. PR の CI・レビュー指摘への対応は人間が判断する。必要なら fix issue を起票して再キューする。**マージは人間が行う。**
5. 関連する PR が複数できたら `gh stack link <下段PR> <上段PR> ...` で stack にまとめ、`gh stack merge <stack番号> --yes --squash` で atomic merge する(「commit / push / PR(gh stack 前提)」節)。

`takt:*` ラベルは使わない(workflow の選択はタスク投入時に行う。既存 issue に残る `takt:*` ラベルは履歴メタデータとしてのみ扱う)。

### 対話用の代替ルート: `/issue-direct`

要件が固まっていない探索的タスクや、人間と対話しながら進めたい issue は takt に載せず `/issue-direct <N>`(または同等の手動手順)を使う。判断基準: **workflow の途中で人間に質問する必要が予見できるなら `/issue-direct`**、そうでなければ takt。

## workflow の使い分け

| workflow | 対象 | 骨子 |
| --- | --- | --- |
| `yt-auto-feature` | 新機能・機能拡張(CLI 追加、skill 新設など) | intake → 計画 → テスト設計 → 設計レビュー 3 並列 → テスト先行実装 → 実装 → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `yt-auto-fix` | バグ修正・回帰修正 | intake → 診断 → 診断レビュー 3 並列 → 再現テスト(red 確認)→ 修正 → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `yt-auto-docs` | docs / skill / CLAUDE.md 限定の変更(実コード変更なし) | intake → 計画 → 実装 → 文書レビュー 2 並列 → CI 同等ゲート → spillover |
| `yt-auto-maintenance` | 挙動を変えないリファクタリング | intake → 計画(維持契約の列挙)→ 計画レビュー 2 並列 → safety net → リファクタ → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `yt-auto-audit` | 汎用監査(テスト監査・タスク完了検収・アーキテクチャ監査など) | 計画(台帳スケルトン)→ 監査(追記型)→ 監督 ⇄ 再監査 → 検収 → docs/audits/ へ配置(+指示があれば起票) |
| `yt-auto-audit-runs` | takt 資産そのものの監査(workflow 定義の整合 + 実行トレースの再発パターン) | 計画(証拠パス確認 + 固定 5 対象の採番)→ 監査(追記型)→ 監督 ⇄ 再監査 → 検収 → docs/audits/ へ配置(+指示があれば起票) |
| `audit-unit-split` | ユニットテスト監査 16 分割(稼働中の特化 workflow) | 現状維持。汎用の監査は `yt-auto-audit` を使う |

迷ったときの判定順: 壊れている → `yt-auto-fix`。コードを変えず文書だけ → `yt-auto-docs`。挙動を変えずに構造を変える → `yt-auto-maintenance`。takt の workflow / facet / 実行トレース自体を点検する → `yt-auto-audit-runs`。それ以外を調査して報告するだけ → `yt-auto-audit`。それ以外 → `yt-auto-feature`。

`yt-auto-audit-runs` は issue 起点でなくてもよい定期点検レーン。run トレースの所在が 2 系統(メインチェックアウトの `.takt/runs` と、`.takt/clone-meta/*.json` の `clonePath` 配下)に分かれる点が他レーンと違う — takt はタスクを隔離クローンで実行するため、`yt-auto-*` の実行実績はクローン側にしか無い。クローンはスイープで消えるので、読める run 数は実行回数と一致しない。

`yt-auto-intake` / `yt-auto-impl-review` は共通の callable sub-workflow であり、直接投入しない。

## workflow 設計の要点(保守者向け)

定義は `.takt/workflows/`、facet は `.takt/facets/`、structured output schema は `.takt/schemas/`。設計は tayk リポジトリの ADR-0008 を本リポジトリへ適合させたもの。変更時は以下を守る。

- **検証は `takt workflow doctor <name>` に一本化する。** schema・遷移グラフ・facet 参照の実在は doctor が見る。`.takt/workflows/` / `.takt/facets/` を変更したら必ず実行する(takt は CI 環境に無いためローカルのみ)
- **CI 同等ゲート(`ci_verify`)を final_gate の前に置く。** 本リポジトリはローカル git hook を持たず(#2534)、`auto_pr` の push を止める関門が無い。PR の CI で落ちる失敗は `ci_verify` が push 前に見つける。この step を削らない
- **レビュー ⇄ 修正のループ上限は 3。** loop monitor が supervisor 判定を起動する。ただし monitor の cycle 判定は「履歴末尾で *連続して* threshold 回反復」の厳密一致であり、**cycle の外から再入される step はカウントが 1 に戻る**。そのような step(`plan` / `design_fix` / `diagnose` / `reproduce` など)は `{step_iteration}` による自前上限を rules と instruction の両方に持つ。遷移を足すときは「cycle の外から再入されないか」を目視で確認する
- **callable sub-workflow は親のレポートを読めない**(子は専用の report namespace を持つ)。`spillover` を callable 化しない(職務が「親の全レポートの走査」そのもの)。境界をまたぐ情報は、前段レスポンス / 親レポートへの転記 / ソースコード(テストに埋めた要件 ID)のいずれかで渡す
- **決定的分岐は `condition: when(<式>)` で書く。** 素の文字列に落とすと LLM 判定に化ける。`structured.*` を参照する分岐は必ず `when()` で包む
- **要件 ID `REQ-<issue番号>-<2桁連番>`** が intake から最終ゲートまでを貫通する。担体はテストコードであり、PR 化後も差分から辿れる
- **スコープ外の発見は `spillover` が仕分けて起票する**(因果なし / 実害あり / 根拠ありの 3 条件)。「ついで直しをしない」の受け皿であり、削らない

persona の provider routing は `.takt/config.yaml` に全量を複製している(project 側の `provider_routing` 定義は global を丸ごと覆い隠すため。#2535)。persona を追加したら routing も追加する。

## linked worktree(`/issue-direct` 用)

親 checkout は main の同期と worktree 管理に使い、実装は行わない。作業開始時は main を fast-forward してから、issue ごとの branch と worktree を作る。

```bash
git switch main
git pull --ff-only
git worktree add .worktrees/issue-<N>-<slug> -b issue-<N>-<slug> main
cd .worktrees/issue-<N>-<slug>
nix develop
```

stack を組まない単独 PR の base branch は `main` 固定とする。stack の上段 branch は直下の branch を base に取るが、その chain は `gh stack` が管理するものであり、手で別 issue の未マージ branch を base に指定しない。stack に載せない依存 issue は、依存 PR の merge 後に main を更新し、rebase してから検証する。takt が生成する worktree(`<repo-parent>/takt-worktrees/`)は takt CLI が管理し、この規約の対象外。

1 worktree = 1 stack とする。`.worktrees/` には `codex/*` の worktree が多数あり、同じ branch が 2 箇所にチェックアウトされていると stack の branch 移動が exit 6 で失敗するため、stack 用の branch 名はそれらと衝突させない。

## commit / push / PR(gh stack 前提)

PR は **stacked PR** を前提とする。1 PR = 1 振る舞い変更(テストと実装をセットにし、レビュアーが 1 つの意思決定で可否を判断できる単位。目安 200 行以内)に絞り、関連する変更は `gh stack` で積んでレビューと atomic merge を行う。

- commit: 日本語 Conventional Commits を使い、タイトル末尾に `(#<N>)` を付ける(takt 経路では auto_pr が生成する)
- push: stack に属する branch だけを push する
- PR: `Closes #<N>`、変更概要、検証コマンド、参照した公式資料を本文へ記載する
- merge: required CI 成功後に `gh stack merge` で行う。チェックの削除・弱体化で green にしない

### セットアップ(clone 直後に 1 回)

```bash
gh extension install github/gh-stack
git config remote.pushDefault origin   # origin / contributor の 2 リモートがあるため必須
git config rerere.enabled true
```

`remote.pushDefault` は必須。`gh stack checkout` / `trunk` は `--remote` フラグを持たず、複数リモート下で default が無いと非対話実行がエラーになる。

### takt 経路: 生成された PR を後から link する

takt は 1 run = 1 branch = 1 PR、`base_branch: main` 固定で、ローカルに stack を作らない。関連する issue をそれぞれ takt へ投入し、できた PR を後から stack にまとめる。

```bash
gh stack link <下段PR> <上段PR> [...]     # 引数は bottom → top の順
gh stack link <stack番号> <追加PR>        # 既存 stack の上へ追加する
```

`link` はローカル追跡状態を作らず、base branch の chain を自動補正する(既存 PR の base が chain と食い違っていれば直す)。

**前提**: 各 issue が main ベースで独立に実装できる粒度であること。takt worker は他 issue の未マージ変更を見られないため、実装順に依存がある issue は `addBlockedBy` で順序を表し、下段 PR の merge 後に上段を投入する。

### `/issue-direct` 経路: worktree 内で stack を積む

```bash
gh stack init <下段branch>     # trunk は既定ブランチ(main)
gh stack add <上段branch>      # 上に積む。staging と commit は通常の git を使う
gh stack submit --auto         # push + PR 作成(draft)
gh stack view --json           # 状態確認
gh stack sync --prune          # 下段 merge 後の追随。merge 済みローカル branch も掃除する
```

下段を直したくなったら `gh stack down` で降りて直し、`gh stack rebase --upstack` で上段へ波及させる。上段の branch で下段の修正をしない(PR の差分が混ざる)。

### merge

`gh pr merge` は stacked PR に効かない。

```bash
gh stack merge <stack番号|PR番号> --yes --squash
```

指定 PR までを bottom から all-or-nothing で atomic merge する。**stack merge では ruleset の bypass が使えない**ため、admin 権限があっても全段で `lint` / `test` が green でなければ 1 件も入らない。

### 非対話実行の必須フラグ

| コマンド | 必須 | 無指定時 |
| --- | --- | --- |
| `gh stack view` | `--json` | TUI が起動してハングする |
| `gh stack submit` | `--auto` | PR タイトルを 1 件ずつ対話で聞く |
| `gh stack init` / `add` / `checkout` | branch 名・番号を positional で渡す | 対話メニューが出る |
| `gh stack merge` | `--yes` | 対話ウィザードが出る |

### 落とし穴

- **PR タイトル / 本文は自動生成で、`submit` に指定フラグが無い。** branch が単一 commit ならその commit subject がタイトルになるので、日本語 Conventional Commits + `(#<N>)` を満たすには 1 branch 1 commit に寄せる。複数 commit の branch はタイトルが branch 名から機械生成されるため、作成後に `gh pr edit` で直す
- **stack は厳密に線形。** 1 つの親に複数の子は持てない。並行させたい作業は別 stack にする
- `gh stack sync` はローカルとリモートの stack が diverge していると、非対話環境では何も変更せず `ℹ Sync aborted` を出して **exit 0 で終わる**。成功と読み違えない。解消は `gh stack unstack` してから作り直す
- `gh stack rebase` の conflict は exit 3。`git add` で解決を stage して `gh stack rebase --continue`、戻せなくなったら `--abort` で全 branch が rebase 前へ復元される

## 環境

親 checkout と新規 worktree の両方で devShell に入る。direnv があれば `direnv allow` で `.envrc` を allow し、なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する。非対話 shell は `nix develop --command <command>` を使う。

ローカル git hook は存在しない。品質ゲート(ruff / CHANGELOG / any 型)は CI が担保し(`docs/development.md` の「品質ゲート(CI)」)、takt 経路では `ci_verify` step が push 前に同等の検査をローカル実行する。

takt worker のサンドボックス対策(direnv / uv cache の TAKT_RUNTIME_ROOT 配下への再構成)は `.takt/runtime-prepare.sh` が行う(#2532)。

## 旧 takt 状態

`.takt/runs/` 配下の過去 run、`.takt/tasks.yaml` の完了済み task 履歴は過去実績の参照用。古い failed / pending task や `takt-worktrees/` の残骸を新しい作業へ再利用しない。不要な runtime 状態を掃除する場合は対象を明示して確認し、通常の issue worktree や未マージ変更を巻き込まない。
