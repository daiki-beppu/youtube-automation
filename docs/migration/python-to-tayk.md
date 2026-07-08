# 【移行告知】Python 版のメンテナンスモード移行と `tayk` への移行ガイド

**初版公開: 2026-07-02 / 最終改訂: 2026-07-08（日付ベースの計画を撤回しイベントベースに変更）** / 対象読者: `uv add git+https://` または submodule で `youtube-channels-automation` を導入している全ユーザー

> **TL;DR: 本パッケージ（Python 版）はメンテナンスモード（バグ修正のみ、新機能なし）に移行しました。後継の TypeScript 製 `tayk`（npm パッケージ）は専用の別リポジトリで開発中です。Python 版の提供終了（cutover）は「tayk が実運用カバレッジに達した」時点で判断し、具体的な期日は約束しません。次の告知は tayk の dogfood（first-party チャンネルでの実運用検証）完走後に行います。**

本書は [ADR-0021](../adr/0021-separate-repo-restart.md) に基づく正式な移行告知であり、cutover までの正本ドキュメントとして随時更新する。関連 issue: #1416 / 関連決定: [ADR-0021](../adr/0021-separate-repo-restart.md), [ADR-0007](../adr/0007-rebrand-to-tayk.md), [ADR-0006](../adr/0006-npm-distribution.md)

> **改訂について**: 初版（2026-07-02）で提示した日付ベースのタイムライン（2026-08 末まで最終 bug fix / 2026-09 cutover）は、ADR-0021 の決定により**撤回**した。日付ベースの計画は過去 2 回破綻しており、3 度目の期日は約束しない。以後の進行はすべて下記のマイルストーン（イベント）ベースで告知する。

---

## 1. マイルストーン（イベントベース）

日付は提示しない。各マイルストーンの**到達をもって**次の段階へ進み、その都度本書と GitHub Release で告知する。

| 順序 | マイルストーン | 到達すると何が起きるか |
|---|---|---|
| ✅ 済 | 本告知の公開・Python 版のメンテナンスモード移行 | Python 版は以後バグ修正のみ（新機能は追加しない） |
| ⏳ 進行中 | `tayk` 開発リポジトリの始動（別リポ・0 ベース） | 本リポの TS レイヤー（`packages/`）は削除され、開発は新リポへ移る |
| 未 | `tayk` v0.1.0: collection フルライフサイクル 1 周の dogfood 完走 | **次回告知**。移行手順の具体化・新リポの案内を本書に追記 |
| 未 | first-party チャンネルの日常運用が `tayk` のみで回る（実運用カバレッジ到達） | **cutover 判断**。判断が固まり次第、実施前に本書と GitHub Release で告知 |
| 未 | cutover 実施 | main ブランチから Python コードを削除。以後の修正は `tayk` のみ |
| 未 | 外部ユーザー移行サポート期間 | 移行で問題があれば issue で報告 |

## 2. 影響範囲

**影響を受ける人**: `uv add "git+https://github.com/daiki-beppu/youtube-automation@main"` のように **branch 参照**で導入しているユーザー。cutover 実施後は dependency の再解決（`uv sync` / `uv lock --upgrade` など）が Python パッケージとして成立しなくなる。

**当面影響を受けない人**: `@v5.5.15` のように **tag 参照**で pin しているユーザー。git tag は cutover 後も削除しないため、既存環境はそのまま動き続ける（ただし §6 の通り cutover 後は修正が一切入らなくなる）。

## 3. 何が変わるか / 変わらないか

### 変わらないもの

- **ワークフローのエントリポイント**: `/wf-new` → `/wf-next` を起点とする Claude Code 上の運用は維持される。裏の実装が Python → TS に変わっても、日常の操作体験の破壊は最小化する
- **チャンネルリポジトリの設定資産**: `config/channel/*.json` の JSON 形式は `tayk` でもそのまま維持する（ADR-0021 の下流契約）。`auth/` / `collections/` などチャンネル側のデータも引き継ぐ前提で設計している

### 変わるもの

| 項目 | Python 版（現行） | `tayk`（後継） |
|---|---|---|
| 開発リポジトリ | 本リポ | **専用の別リポジトリ**（0 ベース開発。公開時に本書で案内） |
| 配布 | `uv add git+https://`（git 参照） / submodule | **npm パッケージ `tayk`**。起動は `bunx tayk <cmd>` |
| パッケージ名 / バージョン | `youtube-channels-automation` v5.5.x | **`tayk`** v0.1.0〜（バージョンは reset。機能は 1 リリース 1 テーマで順次追加） |
| CLI | `yt-*` 系 30 本超 | `tayk <cmd>` に統合 |
| skills | 60+ 個別 skill を `yt-skills sync` で配布 | knowledge codec への集約（v0.2 以降に順次） |
| agent 連携 | skill → Bash 経由で CLI 実行 | **MCP server** により agent が typed tool を直接呼ぶ |
| ローカルデータ | JSON ファイル群 | libSQL local store（`<CHANNEL>/data/local.db`） |

`tayk` v0.1.0 のスコープは「collection フルライフサイクル 1 周」の縦スライス 1 本（ADR-0021）。上表の残りの要素は v0.2 以降に 1 リリース 1 テーマで順次積む。詳細は各リリース時に本書へ追記する。

## 4. 今やること

### 4.1 バージョン pin の確認

再現性確保のため、branch 参照で導入している場合は最終安定 tag への pin を推奨する:

```bash
# チャンネルリポジトリで
uv remove youtube-channels-automation
uv add "git+https://github.com/daiki-beppu/youtube-automation@v5.5.15"
```

tag pin にしておけば、cutover 当日に環境が突然壊れることはない（cutover 後に新規修正が入らなくなるだけ）。

### 4.2 Python 版のバグ報告

Python 版はメンテナンスモードとして cutover まで**バグ修正を継続する**（新機能は追加しない）。期限は設けないが、cutover は §1 のマイルストーン到達次第実施されるため、気になっている問題があれば早めに issue を立ててほしい。

## 5. cutover 後の移行手順（`tayk` publish 後）

移行の骨子は「Python git 依存を外し、npm devDependency として `tayk` を載せる」パッケージ載せ替えになる。具体的なコマンド列・設定変換手順は `tayk` の publish と同時に本書を更新し、GitHub Release で告知する。

想定している流れ（確定版は cutover 時に公開）:

1. チャンネルリポジトリから `youtube-channels-automation` の git 依存を外す
2. `tayk` を npm devDependency として追加する（`bunx tayk <cmd>` で起動）
3. skills 相当のセットアップ（knowledge codec 展開）を実行する
4. `/wf-new` → `/wf-next` は従来通り使える

## 6. 移行しない場合（legacy ブランチは無い）

cutover 後も **legacy ブランチは設けない**。cutover 後の選択肢は次の 2 つのみ:

- **`tayk` へ移行する**（推奨）
- **最終 tag（v5.5.x 系の最終版）に pin して Python 版を使い続ける** — 動作はするが、bug fix・機能追加・サポートは一切行われない

cutover 後に TS 版で問題が起きた場合の一時退避も同様に「最終 Python tag へ pin を戻す」で行える。

## 7. 告知チャネル

- **正本**: 本ファイル（`docs/migration/python-to-tayk.md`）。cutover まで随時更新する
- **README / ONBOARDING**: 冒頭の告知バナーから本書へ誘導
- **GitHub Release**: 次回リリース以降、cutover 完了まで Release 本文に本告知への link を再掲する
