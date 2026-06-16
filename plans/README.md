# Implementation Plans

improve スキルによる distrokid-helper（拡張本体 + `yt-collection-serve` の `/distrokid/*`）監査（standard レベル、2026-06-12、基準 commit `fa296fe`）から生成。下記の順に実行すること。各 executor はプランを最後まで読んでから着手し、STOP conditions を遵守し、完了時に自分の行を更新する。

このリポジトリの規約: 作業は必ず worktree 上で行う（`$REPO_ROOT/.worktrees/<slug>/`）。`src/youtube_automation/` を触るプランは `CHANGELOG.md` の `[Unreleased]` 追記が必須（pre-push ゲートあり）。

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | Status |
|------|-------|----------|--------|------------|-------|--------|
| 001 | POST /distrokid/releases の入力検証 + POST body サイズ上限 | P1 | S | — | [#953](https://github.com/daiki-beppu/youtube-automation/issues/953) | TODO |
| 002 | distrokid-helper の dev ツールチェーンを suno-helper と統一 | P2 | M | — | [#954](https://github.com/daiki-beppu/youtube-automation/issues/954) | TODO |
| 003 | distrokid-helper に lint / format ゲート + CI パリティ | P2 | M | 002 | [#955](https://github.com/daiki-beppu/youtube-automation/issues/955) | TODO |
| 004 | サーバー URL 既定値を shared/constants.ts に集約 | P3 | S | — | [#956](https://github.com/daiki-beppu/youtube-automation/issues/956) | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) | REJECTED (with one-line rationale)

## Dependency notes

- 003 は 002 の後に実行する。両方が `extensions/distrokid-helper/package.json` と `pnpm-lock.yaml` を編集するため、並行実行すると conflict する。また 003 の lint 初回適用は 002 で統一した TS 5.9 / typescript-eslint 8.60 の組で行うのが整合的。
- 001 と 004 は完全に独立。いつでも実行可。

## Findings considered and rejected

次回の監査で再調査しないための記録:

- **App.tsx:128 の「stale closure バグ」**（`prev = collections[selectedIndex]` が古い state を参照）: by design。`prev` は「ユーザーが選択操作をした時点のリスト上の disc」を表すのが正しく、新リストを index 参照する「修正」はむしろバグになる。コメント（App.tsx:113-114）も意図を明記済み。
- **`write_distrokid_release` の TOCTOU race**（collection_serve.py:175-199）: ThreadingHTTPServer のため理論上は read-modify-write race が存在するが、単一オペレーターが 1 popup から叩く設計で実発生確率がほぼゼロ。ロック導入のコスト > 価値。
- **CORS の `chrome-extension://` scheme 全許可**（collection_serve.py:415-428）: 同一マシンの他拡張がレスポンスを読める点は事実だが、unpacked 拡張は ID がマシン・パスごとに変わるため ID pin は運用コストが高い。`--allow-origin` による固定手段は既に存在する。Plan 001 の POST 実在検証で書き込み側の実害は緩和される。
- **`/distrokid/assets` の拡張子 whitelist**: 前提となる脅威（攻撃者が collection ディレクトリへの FS 書き込み権限を獲得済み）が成立した時点でより深刻な問題が起きており、防御として意味が薄い。
- **`_send_json_error` のメッセージ切り詰め**: エラーメッセージはサーバー内部由来で信頼できるクライアント（自前拡張）にしか届かない。実害なし。
- **822 行の `distrokid-injector.ts` の分割リファクタ**: 凝集度は高く、#813→#877→#888 とセレクタ契約が活発に変化している領域。今リファクタするとセレクタ修正と衝突するリスクが整理の価値を上回る。沈静化後に再検討。
- **StatusBanner の XSS**: React の JSX 自動エスケープで安全。`dangerouslySetInnerHTML` 不使用を確認済み。
- **React 19 vs 18 / @webext-core/messaging 2 vs 3 の統一**: rejected ではなく**先送り**。ランタイム依存のため実機スモーク込みの別プランが必要（Plan 002 の Maintenance notes 参照）。

## 監査で plan 化を見送った残課題（ユーザー判断）

ユーザーが今回 plan 化を選択しなかった finding。価値はあるため将来の候補:

- **popup（App.tsx 301 行）のユニットテスト新設 + inject-session の stop-race テスト**（テスト, M）— dir-mode の disc 選択維持・`payloadSourceRef` 束縛・エラー表示分岐が無防備。
- **README 運用エッジケース補強**（docs, S）— `distrokid.json` 未配置/disabled 時の復旧、空コレクション、spec.json が album_title の SSOT である旨、実 distrokid.com での dev ループ手順。
- **`waitForRemoval` のエラーメッセージ修正**（正確性, S）— `distrokid-injector.ts:591` が selector を `AI_MODAL_SELECTORS.modal` 固定で報告（現呼び出しは modal 1 箇所のみで実害なしの潜在バグ）。
- **Direction: セレクタ pre-flight check / fill 後検証チェックリスト**（M）— #813→#877→#888 のセレクタ刷新サイクルと 25 トラック目視確認の手作業が根拠。
