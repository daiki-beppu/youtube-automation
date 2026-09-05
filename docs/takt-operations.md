# Issue / worktree 運用

> 開発方針の正本は `CLAUDE.md`「開発ワークフロー」。実装・検証・レビュー対応は worktree 上のエージェントセッションで直接進める。ファイル名は既存リンクとの互換性のため維持する。

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

1. issue がある作業は要件・完了条件・依存関係を確認する。新規起票が必要な場合は `gh issue create` または `/issue` を使う。
2. 最新の main から作業専用の linked worktree を作成する（issue がある場合は issue ごと）。
3. worktree 上のエージェントセッションで直接実装し、変更に必要なテストと品質ゲートを実行する。監査・レビューは対象に合う skill（例: `/improve` や `/code-review`）で行う。
4. PR 作成を依頼された場合は `gh stack` で commit → push → PR 作成を行い、CI とレビュー指摘に対応する。マージはユーザーの指示に従う。

既存 issue の `takt:*` ラベルは履歴メタデータとしてのみ扱い、新規に付与しない。

## linked worktree

親 checkout は main の同期と worktree 管理に使い、実装は行わない。作業開始時は main を fast-forward してから、issue ごとの branch と worktree を作る。

```bash
git switch main
git pull --ff-only
git worktree add .claude/worktrees/issue-<N>-<slug> -b issue-<N>-<slug> main
cd .claude/worktrees/issue-<N>-<slug>
nix develop
```

stack を組まない単独 PR の base branch は `main` 固定とする。stack の上段 branch は直下の branch を base に取るが、その chain は `gh stack` が管理するものであり、手で別 issue の未マージ branch を base に指定しない。stack に載せない依存 issue は、依存 PR の merge 後に main を更新し、rebase してから検証する。

worktree の置き場は `$REPO_ROOT/.claude/worktrees/<slug>/` に統一する(グローバル規約と同じ)。

1 worktree = 1 stack とする。旧い置き場 `.worktrees/` にはローカル環境によって `codex/*` の worktree が残っていることがあり、同じ branch が 2 箇所にチェックアウトされていると stack の branch 移動が exit 6 で失敗するため、stack 用の branch 名はそれらと衝突させない。`.gitignore` は移行期間中どちらの置き場も無視する。

## commit / push / PR(gh stack 前提)

PR は **stacked PR** を前提とする。1 PR = 1 振る舞い変更(テストと実装をセットにし、レビュアーが 1 つの意思決定で可否を判断できる単位。目安 200 行以内)に絞り、関連する変更は `gh stack` で積んでレビューと atomic merge を行う。

- commit: 日本語 Conventional Commits を使い、タイトル末尾に `(#<N>)` を付ける
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

### worktree 内で stack を積む

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

draft ではなく、head ref が `release/` で始まらない PR の opened / ready_for_review / synchronize で `.github/workflows/code-review.yml` が発火し、claude-code-action が mattpocock code-review(Standards / Spec の 2 軸)+ simplify 観点(reuse / simplification / efficiency)で差分をレビューして severity 付きの集約コメントを投稿する。すべての対象 PR に同じゲートが効く。

- **critical 指摘が 1 件以上あると `Code review` check が fail する**。warning / info のみなら success。`gh stack merge` の CI green 待ちにはこの check も含まれる
- review workflow 自体は `contents: read` のまま指摘の生成だけを担う。集約コメントに critical / warning / info が 1 件以上あれば、後続の CI autofix が全指摘の修正を試みる
- オプトアウトは PR に `skip-review` ラベルを付与する(誤検知が続く PR・機械生成の大量 PR 向け)。draft PR と `release/*` ブランチのリリース PR は最初から対象外
- `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` がどちらも未設定の環境では fail せず skip される(evals.yml と同じ慣行)
- 同一 PR への連続 push は進行中の run が cancel され、最新 commit のレビューだけが残る

## CI 失敗の自動修正(post-push の保険)

PR をゲートする 5 workflow(CI / Dashboard / Extensions / Audio Studio / Release notes site)のいずれかが PR で失敗した場合、または `Code review` の集約コメントに critical / warning / info の指摘がある場合、`.github/workflows/ci-autofix.yml` が `workflow_run` で発火する。claude-code-action は失敗ログまたはレビューコメントを診断し、修正 commit を PR ブランチへ push する。レビューが指摘 0 件なら何もせず終了する。worktree 上で修正・検証する一次経路に加えて、push 後に発生した回帰への保険として重ねる。

- **push は claude-code-action 既定の OIDC → Claude GitHub App トークン交換で行う**(`id-token: write`)。App トークンの push は `pull_request: synchronize` を発火させ、修正 commit の CI が自動で再検証される。code-review.yml が `contents: read` + 明示 `GITHUB_TOKEN` でレビューに閉じるのと対で、push 経路は本 workflow だけが持つ
- **修正試行は CI 起点・レビュー起点を通算して PR あたり 1 回。** commit body の `[ci-autofix]` マーカーで判定し、修正後の再レビューや CI で問題が残っても 2 回目以降はコメント報告のみ(コスト暴走・修正ループ防止)
- 修正不能・修正すべきでない(仕様矛盾・flaky・インフラ起因・同意できないレビュー指摘)と判断した場合は push せず診断コメントを投稿して正常終了する
- オプトアウトは PR に `skip-autofix` ラベルを付与する(`skip-review` と独立制御)。draft PR・fork からの PR は最初から対象外
- `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` がどちらも未設定の環境では fail せず skip される(code-review.yml と同じ慣行)
- モデルは opus(pytest 失敗の診断・修正はレビューより難易度が高く、sonnet 既定の code-review.yml とは別判断)

## 環境

親 checkout と新規 worktree の両方で devShell に入る。direnv があれば `direnv allow` で `.envrc` を allow し、なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する。非対話 shell は `nix develop --command <command>` を使う。

ローカル git hook は存在しない。品質ゲート(ruff / CHANGELOG / any 型)は CI が担保し(`docs/development.md` の「品質ゲート(CI)」)、push 前に変更に必要な検査を worktree 上で実行する。

## 旧 takt 状態

既存の `.takt/` 設定・runtime スクリプトは旧運用の残存資産であり、新規タスクの投入・実行には使わない。

`.takt/runs/` 配下の過去 run、`.takt/tasks.yaml` の完了済み task 履歴は過去実績の参照用。古い failed / pending task や `takt-worktrees/` の残骸を新しい作業へ再利用しない。不要な runtime 状態を掃除する場合は対象を明示して確認し、通常の issue worktree や未マージ変更を巻き込まない。
