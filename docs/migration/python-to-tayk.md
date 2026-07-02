# 【移行告知】Python 版の提供終了と `tayk` への移行ガイド

**公開日: 2026-07-02** / 対象読者: `uv add git+https://` または submodule で `youtube-channels-automation` を導入している全ユーザー

> **TL;DR: 本パッケージ（Python 版）は 2026-08 中に提供終了します。後継は TypeScript 製の `tayk`（npm パッケージ）です。cutover 当日に main ブランチが TS 実装へ切り替わり、Python コードは削除されます。**

本書は ADR-0015（開発ロードマップ）の移行戦略に基づく正式な移行告知であり、cutover までの正本ドキュメントとして随時更新する。関連 issue: #1416 / 決定記録: [ADR-0015](../adr/0015-development-roadmap.md), [ADR-0001](../adr/0001-ai-first-ts-rewrite.md), [ADR-0007](../adr/0007-rebrand-to-tayk.md), [ADR-0008](../adr/0008-cutover-merge-strategy.md)

---

## 1. タイムライン

| 時期 | 何が起きるか | あなたがやること |
|---|---|---|
| **2026-07（今）** | 本告知の公開。Python 版の最終 bug fix 期間 | 本書を読む。バージョン pin の確認（§4.1）。Python 版へのバグ報告はこの期間内に |
| **2026-08** | **cutover**: main ブランチが TS 実装に切り替わり、Python コードは削除。`tayk@0.1.0` を npm へ publish | cutover 後、§5 の手順で `tayk` へ移行 |
| **2026-09** | 外部ユーザー移行サポート期間 | 移行で問題があれば issue で報告 |

cutover の正確な日付は確定し次第、本書と GitHub Release で告知する。

## 2. 影響範囲

**影響を受ける人**: `uv add "git+https://github.com/daiki-beppu/youtube-automation@main"` のように **branch 参照**で導入しているユーザー。cutover 当日から dependency の再解決（`uv sync` / `uv lock --upgrade` など）が Python パッケージとして成立しなくなる。

**当面影響を受けない人**: `@v5.5.14` のように **tag 参照**で pin しているユーザー。git tag は cutover 後も削除しないため、既存環境はそのまま動き続ける（ただし §6 の通り修正は一切入らなくなる）。

## 3. 何が変わるか / 変わらないか

### 変わらないもの

- **ワークフローのエントリポイント**: `/wf-new` → `/wf-next` を起点とする Claude Code 上の運用は維持される。裏の実装が Python → TS に変わっても、日常の操作体験の破壊は最小化する（ADR-0015 §移行戦略 3）
- **チャンネルリポジトリの資産**: `config/channel/*.json` / `auth/` / `collections/` などチャンネル側のデータはそのまま引き継ぐ前提で設計している

### 変わるもの

| 項目 | Python 版（現行） | `tayk`（後継） |
|---|---|---|
| 配布 | `uv add git+https://`（git 参照） / submodule | **npm パッケージ `tayk`**。起動は `bunx tayk <cmd>` |
| パッケージ名 / バージョン | `youtube-channels-automation` v5.5.x | **`tayk`** v0.1.0（バージョンは reset） |
| CLI | `yt-*` 系 30 本超 | `tayk <cmd>` に統合 |
| skills | 60+ 個別 skill を `yt-skills sync` で配布 | **knowledge codec 5 本に集約**（`collection-lifecycle` / `channel-management` / `analytics` / `content-quality` / `distribution`） |
| agent 連携 | skill → Bash 経由で CLI 実行 | **MCP server** により agent が typed tool を直接呼ぶ |
| 動画レンダリング | ffmpeg 直叩き | Remotion renderer |
| ローカルデータ | JSON ファイル群 | libSQL local store（`<CHANNEL>/data/local.db`） |

内部構造の変更点（knowledge codec 集約・MCP tool 化）の詳細は cutover 時に本書へ追記する。

## 4. 今（2026-07 中に）やること

### 4.1 バージョン pin の確認

再現性確保のため、branch 参照で導入している場合は最終安定 tag への pin を推奨する:

```bash
# チャンネルリポジトリで
uv remove youtube-channels-automation
uv add "git+https://github.com/daiki-beppu/youtube-automation@v5.5.14"
```

tag pin にしておけば、cutover 当日に環境が突然壊れることはない（新規修正が入らなくなるだけ）。

### 4.2 Python 版のバグ報告

Python 版へのバグ修正が可能なのは **cutover まで**。legacy ブランチは設けないため（§6）、cutover 後に Python 版のバグを報告しても修正されない。気になっている問題がある場合は 7 月中に issue を立ててほしい。

## 5. cutover 後の移行手順（2026-08、`tayk@0.1.0` publish 後）

移行の骨子は「Python git 依存を外し、npm devDependency として `tayk` を載せる」パッケージ載せ替えになる。具体的なコマンド列・設定変換手順は `tayk@0.1.0` publish と同時に本書を更新し、GitHub Release で告知する。

想定している流れ（確定版は cutover 時に公開）:

1. チャンネルリポジトリから `youtube-channels-automation` の git 依存を外す
2. `tayk` を npm devDependency として追加する（`bunx tayk <cmd>` で起動）
3. skills 相当のセットアップ（knowledge codec 展開）を実行する
4. `/wf-new` → `/wf-next` は従来通り使える

## 6. 移行しない場合（legacy ブランチは無い）

ADR-0015 の決定により **legacy ブランチは設けない**。cutover 後の選択肢は次の 2 つのみ:

- **`tayk` へ移行する**（推奨）
- **最終 tag（v5.5.x 系の最終版）に pin して Python 版を使い続ける** — 動作はするが、bug fix・機能追加・サポートは一切行われない

cutover 後に TS 版で問題が起きた場合の一時退避も同様に「最終 Python tag へ pin を戻す」で行える（ADR-0008 §下流の復旧）。

## 7. 告知チャネル

- **正本**: 本ファイル（`docs/migration/python-to-tayk.md`）。cutover まで随時更新する
- **README / ONBOARDING**: 冒頭の告知バナーから本書へ誘導
- **GitHub Release**: 次回リリース以降、cutover 完了まで Release 本文に本告知への link を再掲する
