# Issue / worktree 運用(takt 正規経路)

> 2026-07-30(#2686)以降、このリポジトリの標準実装経路は takt + リポジトリ専用 workflow である。2026-07-23(#2453)の takt 廃止は「ドキュメントが前提とする workflow の実体が環境に存在しない」ことが原因だった。現在は workflow を `.takt/workflows/` で git 管理し、`takt workflow doctor` で機械検証するため、廃止の根拠は解消されている。

## 正規ルート

1. `gh issue create` または `/issue` で issue を起票する。
2. workflow を選んでタスクを投入する(`auto_pr` を必ず有効化する):

   ```bash
   takt add '#<issue番号>'   # 対話で workflow と auto_pr を設定
   takt run                  # pending タスクを実行
   ```

3. workflow が完走すると takt の `auto_pr` がサンドボックス外で commit → push → PR 作成を行う。
4. PR の CI・レビュー指摘への対応は人間が判断する。必要なら fix issue を起票して再キューする。**マージは人間が行う。**

`takt:*` ラベルは使わない(workflow の選択はタスク投入時に行う。既存 issue に残る `takt:*` ラベルは履歴メタデータとしてのみ扱う)。

### 対話用の代替ルート: `/issue-direct`

要件が固まっていない探索的タスクや、人間と対話しながら進めたい issue は takt に載せず `/issue-direct <N>`(または同等の手動手順)を使う。判断基準: **workflow の途中で人間に質問する必要が予見できるなら `/issue-direct`**、そうでなければ takt。

## workflow の使い分け

| workflow | 対象 | 骨子 |
| --- | --- | --- |
| `auto-feature` | 新機能・機能拡張(CLI 追加、skill 新設など) | intake → 計画 → テスト設計 → 設計レビュー 3 並列 → テスト先行実装 → 実装 → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `auto-fix` | バグ修正・回帰修正 | intake → 診断 → 診断レビュー 3 並列 → 再現テスト(red 確認)→ 修正 → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `auto-docs` | docs / skill / CLAUDE.md 限定の変更(実コード変更なし) | intake → 計画 → 実装 → 文書レビュー 2 並列 → CI 同等ゲート → spillover |
| `auto-maintenance` | 挙動を変えないリファクタリング | intake → 計画(維持契約の列挙)→ 計画レビュー 2 並列 → safety net → リファクタ → 実装レビュー 4 並列 → CI 同等ゲート → 最終ゲート → spillover |
| `auto-audit` | 汎用監査(テスト監査・タスク完了検収・アーキテクチャ監査など) | 計画(台帳スケルトン)→ 監査(追記型)→ 監督 ⇄ 再監査 → 検収 → docs/audits/ へ配置(+指示があれば起票) |
| `audit-unit-split` | ユニットテスト監査 16 分割(稼働中の特化 workflow) | 現状維持。汎用の監査は `auto-audit` を使う |

迷ったときの判定順: 壊れている → `auto-fix`。コードを変えず文書だけ → `auto-docs`。挙動を変えずに構造を変える → `auto-maintenance`。調査して報告するだけ → `auto-audit`。それ以外 → `auto-feature`。

`auto-intake` / `auto-impl-review` は共通の callable sub-workflow であり、直接投入しない。

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

base branch は `main` 固定とする。別 issue の未マージ branch を base にしない。依存 issue がある場合は依存 PR の merge 後に main を更新し、rebase してから検証する。takt が生成する worktree(`<repo-parent>/takt-worktrees/`)は takt CLI が管理し、この規約の対象外。

## commit / push / PR

- commit: 日本語 Conventional Commits を使い、タイトル末尾に `(#<N>)` を付ける(takt 経路では auto_pr が生成する)
- push: issue branch だけを push する
- PR: `Closes #<N>`、変更概要、検証コマンド、参照した公式資料を本文へ記載する
- merge: required CI 成功後に行う。チェックの削除・弱体化で green にしない

## 環境

親 checkout と新規 worktree の両方で devShell に入る。direnv があれば `direnv allow` で `.envrc` を allow し、なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する。非対話 shell は `nix develop --command <command>` を使う。

ローカル git hook は存在しない。品質ゲート(ruff / CHANGELOG / any 型)は CI が担保し(`docs/development.md` の「品質ゲート(CI)」)、takt 経路では `ci_verify` step が push 前に同等の検査をローカル実行する。

takt worker のサンドボックス対策(direnv / uv cache の TAKT_RUNTIME_ROOT 配下への再構成)は `.takt/runtime-prepare.sh` が行う(#2532)。

## 旧 takt 状態

`.takt/runs/` 配下の過去 run、`.takt/tasks.yaml` の完了済み task 履歴は過去実績の参照用。古い failed / pending task や `takt-worktrees/` の残骸を新しい作業へ再利用しない。不要な runtime 状態を掃除する場合は対象を明示して確認し、通常の issue worktree や未マージ変更を巻き込まない。
