# Implementation Plans

## 第 1 回監査（distrokid-helper 本体 + yt-collection-serve、2026-06-12、基準 commit `fa296fe`）

このリポジトリの規約: 作業は必ず worktree 上で行う（`$REPO_ROOT/.worktrees/<slug>/`）。`src/youtube_automation/` を触るプランは `CHANGELOG.md` の `[Unreleased]` 追記が必須（pre-push ゲートあり）。

| Plan | Title | Priority | Effort | Depends on | Issue | Status |
|------|-------|----------|--------|------------|-------|--------|
| 001 | POST /distrokid/releases の入力検証 + POST body サイズ上限 | P1 | S | — | [#953](https://github.com/daiki-beppu/youtube-automation/issues/953) | TODO |
| 002 | distrokid-helper の dev ツールチェーンを suno-helper と統一 | P2 | M | — | [#954](https://github.com/daiki-beppu/youtube-automation/issues/954) | DONE |
| 003 | distrokid-helper に lint / format ゲート + CI パリティ | P2 | M | 002 | [#955](https://github.com/daiki-beppu/youtube-automation/issues/955) | DONE |
| 004 | サーバー URL 既定値を shared/constants.ts に集約 | P3 | S | — | [#956](https://github.com/daiki-beppu/youtube-automation/issues/956) | DONE |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) | REJECTED (with one-line rationale)

## Dependency notes

- 003 は 002 の後に実行する（両方が package.json と pnpm-lock.yaml を編集するため conflict）→ 両方 DONE
- 001 と 004 は完全に独立

## Findings considered and rejected

- **App.tsx:128 の「stale closure バグ」**: by design。コメント（App.tsx:113-114）が意図を明記済み
- **`write_distrokid_release` の TOCTOU race**: 単一オペレーター設計で実発生確率ほぼゼロ
- **CORS の `chrome-extension://` scheme 全許可**: `--allow-origin` が既に存在。Plan 001 で POST 側を緩和
- **`/distrokid/assets` の拡張子 whitelist**: 脅威前提が非現実的
- **`_send_json_error` のメッセージ切り詰め**: 信頼クライアント（自前拡張）のみ。実害なし
- **StatusBanner の XSS**: React JSX 自動エスケープで安全

## 監査で plan 化を見送った残課題

- **popup（App.tsx 301 行）のユニットテスト新設**（テスト, M）
- **README 運用エッジケース補強**（docs, S）
- **`waitForRemoval` のエラーメッセージ修正**（正確性, S）
- **Direction: セレクタ pre-flight check / fill 後検証チェックリスト**（M）
