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
| `yt-auto-feature` | 新機能・機能拡張(CLI 追加、skill 新設など) | intake → 計画 / テスト設計 → 実装前設計レビュー 3 並列 + structured gate → red test → 実装 → 専門レビュー 6 並列 + structured gate → CI 同等ゲート → fail-closed final gate → spillover |
| `yt-auto-fix` | バグ修正・回帰修正 | intake → 原因診断(対立仮説を含む)→ 診断レビュー 3 並列 + structured gate → 修正前 red → root-cause repair → 専門レビュー 6 並列 + structured gate → CI 同等ゲート → fail-closed final gate → spillover |
| `yt-auto-docs` | docs / skill / instruction 限定の変更(実コード・runtime 変更なし) | intake → 文書限定計画 → 実装 → 文書レビュー 2 並列 → CI 同等ゲート → fail-closed final gate → spillover |
| `yt-auto-maintenance` | 挙動を変えないリファクタリング | intake → 維持契約の計画 / 設計レビュー + structured gate → 変更前 safety net → リファクタ → 専門レビュー 6 並列 + structured gate → CI 同等ゲート → fail-closed final gate → spillover |
| `yt-auto-audit` | 汎用監査(テスト監査・タスク完了検収・アーキテクチャ監査など) | 有限スコープ計画 / 初期台帳 → 追記型監査 → 監督 ⇄ 再監査 → 独立検収 → `docs/audits/` へ配置 |
| `yt-auto-audit-runs` | takt 資産そのものの監査(workflow 定義の整合 + 読み取り可能な実行トレース) | 定義 / run 証拠の有限棚卸し → 追記型監査 → 監督 ⇄ 再監査 → 独立検収 → `docs/audits/` へ配置 |
| `audit-unit-split` | ユニットテスト監査 16 分割(稼働中の特化 workflow) | 現状維持。汎用の監査は `yt-auto-audit` を使う |

迷ったときの判定順: 壊れている → `yt-auto-fix`。コードを変えず文書だけ → `yt-auto-docs`。挙動を変えずに構造を変える → `yt-auto-maintenance`。takt の workflow / facet / 実行トレース自体を点検する → `yt-auto-audit-runs`。それ以外を調査して報告するだけ → `yt-auto-audit`。それ以外 → `yt-auto-feature`。

`yt-auto-audit-runs` は issue 起点でなくてもよい定期点検レーン。run トレースの所在が 2 系統(メインチェックアウトの `.takt/runs` と、`.takt/clone-meta/*.json` の `clonePath` 配下)に分かれる点が他レーンと違う — takt はタスクを隔離クローンで実行するため、`yt-auto-*` の実行実績はクローン側にしか無い。クローンはスイープで消えるので、読める run 数は実行回数と一致しない。

## workflow 設計の要点(保守者向け)

公開定義は `.takt/workflows/`、takt 0.60.0 builtin から eject した共有 step とリポジトリ固有 step は `.takt/steps/`、固有 instruction / report contract だけを `.takt/facets/` に置く。一般的な plan / test-first / implementation review / fix / final gate は builtin 由来 fragment を正とし、旧内部構造への互換 adapter は持たない。

- **検証は実行時 takt を正とする。** 変更前に `takt --version` と `takt catalog` / `takt eject` の内容を確認し、全公開 workflow へ `takt workflow doctor`、各 workflow へ `takt prompt <workflow>` を実行する。`takt prompt` は `workflow_call` の final gate だけ `[ERROR] reportContent is required for report-based judgment` で止まる — builtin `review-fix-default` でも同じ位置で止まるため、その 1 点より前の全 step が合成できていれば正常
- **実行環境の権限は `capabilities` で宣言する。** workflow 直下の `capabilities: [readonly, enable-skills]` が全 step の既定になり、step 側の宣言は**継承ではなく置換**する。したがって `edit: true` の step は必ず `capabilities: [edit, enable-skills]` を自分で宣言する(落とすと readonly を継承して実行時に書き込めない)。`tests/repo/test_takt_workflow_contract.py::test_edit_boundaries_are_pinned_by_explicit_capability_sets` が静的に担保する
- **CI 同等ゲート(`ci_verify`)を final gate より前に置く。** 最低でも ruff check / format、全 pytest、any-usage gate、`git diff --check` を実行し、変更 path に応じた CI job も追加する。ローカルで実行できるゲートの失敗は `fail` として修正へ戻す。実測した環境でコマンドまたは前提リソースを利用できない項目は、項目名と理由を findings に列挙して CI-only とし、ローカル判定から除外して正本の CI へ委ねる。`ci_verify` の verdict は `pass` / `fail` の 2 値とし、環境差を理由に ABORT しない
- **レビューと final gate は fail-closed。** 専門レビューは未解決 finding / conflict / 判定不能を修正・再計画・ABORT へ送り、既知 verdict に一致しない出力も ABORT する。final gate も COMPLETE 以外をレビュー・修正・再計画・ABORT へ戻す
- **分岐は 1 個の strict structured schema と `when(structured.*)` で決定する。** 並列 reviewer は各 report を生成するだけにし、直後の gate が全 report を読み structured verdict を返す。これにより判定不能を fallback ABORT へ送り、`takt prompt` でも全 step を reportContent なしで合成できる
- **有限停止は root `max_steps` と loop monitor で担保する。** monitor は `ignore_steps` でゲートを挟む実際の cycle を追跡し、継続・再計画・ABORT を明示する。公開 lane から無制限 self-loop を作らない
- **編集境界を lane ごとに固定する。** docs は文書 / skill / instruction と repository-contract test だけ、audit は最終レポート配置だけ、audit-runs は takt 定義と trace の読み取り + 最終レポート配置だけ、maintenance は挙動維持契約と safety net の範囲だけを変更できる
- **監査台帳は追記型。** plan で有限な対象数を確定し、audit / supervise / review が物理行数と completed/total を照合する。既存 finding ID や証拠の要約削除を禁止し、検収後だけ `docs/audits/` へ配置する
- **spillover は外部副作用を起こさない。** 因果ありは lane へ戻し、非因果の actionable finding は手動起票用の草案として記録する。workflow 内で `gh`、issue 作成、comment、push、PR 作成を行わない

## linked worktree(`/issue-direct` 用)

親 checkout は main の同期と worktree 管理に使い、実装は行わない。作業開始時は main を fast-forward してから、issue ごとの branch と worktree を作る。

```bash
git switch main
git pull --ff-only
git worktree add .claude/worktrees/issue-<N>-<slug> -b issue-<N>-<slug> main
cd .claude/worktrees/issue-<N>-<slug>
nix develop
```

stack を組まない単独 PR の base branch は `main` 固定とする。stack の上段 branch は直下の branch を base に取るが、その chain は `gh stack` が管理するものであり、手で別 issue の未マージ branch を base に指定しない。stack に載せない依存 issue は、依存 PR の merge 後に main を更新し、rebase してから検証する。takt が生成する worktree(`<repo-parent>/takt-worktrees/`)は takt CLI が管理し、この規約の対象外。

worktree の置き場は `$REPO_ROOT/.claude/worktrees/<slug>/` に統一する(グローバル規約と同じ)。takt が生成する `<repo-parent>/takt-worktrees/` だけが例外で、takt CLI が管理する。

1 worktree = 1 stack とする。旧い置き場 `.worktrees/` にはローカル環境によって `codex/*` の worktree が残っていることがあり、同じ branch が 2 箇所にチェックアウトされていると stack の branch 移動が exit 6 で失敗するため、stack 用の branch 名はそれらと衝突させない。`.gitignore` は移行期間中どちらの置き場も無視する。

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

## PR 自動コードレビュー(マージ前ゲート)

draft でない PR の opened / ready_for_review / synchronize で `.github/workflows/code-review.yml` が発火し、claude-code-action が mattpocock code-review(Standards / Spec の 2 軸)+ simplify 観点(reuse / simplification / efficiency)で差分をレビューして severity 付きの集約コメントを投稿する。生成経路(takt / `/issue-direct` / 手動)によらず全 PR に同じゲートが効く。

- **critical 指摘が 1 件以上あると `Code review` check が fail する**。warning / info のみなら success。`gh stack merge` の CI green 待ちにはこの check も含まれる
- simplify 系の提案はコメントに載るだけで、CI が PR ブランチへ修正を push することはない(workflow は `contents: read`)
- オプトアウトは PR に `skip-review` ラベルを付与する(誤検知が続く PR・機械生成の大量 PR 向け)。draft PR は最初から対象外
- `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` がどちらも未設定の環境では fail せず skip される(evals.yml と同じ慣行)
- 同一 PR への連続 push は進行中の run が cancel され、最新 commit のレビューだけが残る

## 環境

親 checkout と新規 worktree の両方で devShell に入る。direnv があれば `direnv allow` で `.envrc` を allow し、なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する。非対話 shell は `nix develop --command <command>` を使う。

ローカル git hook は存在しない。品質ゲート(ruff / CHANGELOG / any 型)は CI が担保し(`docs/development.md` の「品質ゲート(CI)」)、takt 経路では `ci_verify` step が push 前に同等の検査をローカル実行する。

takt worker のサンドボックス対策(direnv / uv cache の TAKT_RUNTIME_ROOT 配下への再構成)は `.takt/runtime-prepare.sh` が行う(#2532)。

## 旧 takt 状態

`.takt/runs/` 配下の過去 run、`.takt/tasks.yaml` の完了済み task 履歴は過去実績の参照用。古い failed / pending task や `takt-worktrees/` の残骸を新しい作業へ再利用しない。不要な runtime 状態を掃除する場合は対象を明示して確認し、通常の issue worktree や未マージ変更を巻き込まない。
