# マルチチャンネル workspace: 複数チャンネルの単一リポジトリ同居

## Status

accepted (2026-07-13)。workspace 解決と `yt-channel list` は #1947、コピー移行 CLI と移行ガイドは #1949 で実装。

複数チャンネルを `channels/<slug>/` として 1 リポジトリに同居させる **workspace** 構造を Python 版（本リポ）に導入する。単一チャンネルリポ構成は恒久サポートであり、workspace は opt-in。

## Context

運営者は 6 チャンネルを 6 つの独立リポで運用しており、`yt-skills sync` / automation-update / git 管理がチャンネル数分だけ重複していた。「1 つのディレクトリで複数チャンネルを管理したい」が動機。

本リポはメンテナンスモード（ADR-0021）だが、tayk は別リポで 0 ベース開発中であり日常運用は当面 Python 版で回る。本件は cutover までの運用負荷を下げる**メンテナンスモードの意図的な例外投資**である。

また ADR-0013 は「チャンネルは別ディレクトリのまま channel registry でパスを束ねる」前提を置いていたが、これは dashboard の起動時収集・表示対象を発見する手段であり、本決定と矛盾しない — registry のエントリが workspace 内の `channels/<slug>/` を指せばよい。

## Considered Options

### 実装レイヤー

1. **Python 版（本リポ）(採用)** — 現行運用に即効。解決チェーンの入口だけ拡張すれば singleton 以下の約 200 箇所は無傷
2. **tayk（TS 版）** — 別リポで 0 ベース開発中のため、現行運用の問題解決にならない
3. **運用レベルの monorepo 統合のみ** — ツール非対応のままでは重複コストが解消しない

### 構造

1. **フル同居: `channels/<slug>/` + ルート共有物 (採用)** — 共有物（`.claude/skills/` / CLAUDE.md / docs）はルートに 1 セット、per-channel 状態（config / auth / data / collections / assets）は各 slug 配下
2. **リポ分離維持 + 切替 UX のみ** — sync・git 管理の重複が残る
3. **新規チャンネルのみ同居の併存構造** — 全 CLI が 2 構造対応になり最悪

### チャンネル選択

1. **明示指定（`--channel <slug>` / `CHANNEL=<slug>`）+ cwd 祖先探索 (採用)** — チャンネル dir 内では従来通り暗黙、workspace ルートでは明示必須
2. **永続 active-channel 状態（kubectl context 方式）** — 切替忘れによる別チャンネル誤 upload（critical regression ①）の事故経路になるため**恒久的に作らない**

優先順位は `--channel` > env（`CHANNEL` / `CHANNEL_DIR` が矛盾する場合は `ConfigError`）> cwd 祖先探索。`--channel` と cwd が別チャンネルを指す場合は警告。workspace ルートの検出は規約ベース（`channels/` 配下に `*/config/channel/` を 1 つ以上持つ最初の祖先。マーカーファイルなし）。

## Decision

- `--channel` は**自チャンネル指定に予約**。benchmark 系 CLI の競合 slug 指定は `--competitor` へ即時リネーム（deprecated alias なし、CHANGELOG で告知）
- auth は per-channel 維持（`channels/<slug>/auth/` に token / client_secrets）。OAuth クライアント統合（再認証必須）はやらず、`yt-doctor` の推奨アラートに留める
- 移行は段階式: 6ch（harana-island-sounds）→ フルライフサイクル 1 周実走 → 残り 5 チャンネル。git 履歴は捨て、旧リポは archive として残す
- 移行 CLI `yt-channel-import <path>`（コピー + 検証。move しない）を提供し、first-party 移行で dogfood した上で external user にも同じ手順を提供する
- チャンネル横断の一括実行は v1 スコープ外（`yt-channel list` の列挙のみ）。将来必要になったら subprocess 分離のランナーで実現する。**プロセス内での singleton（`_channel_dir` / `_instance`）切替による横断実行は恒久禁止**（auth / cost tracker の状態がチャンネル間に漏れる）
- workspace リポの git 管理対象はデータ 4 分類に忠実化: ③生成成果物（master 音源・動画・stock 楽曲）は git 管理外。stock 楽曲は Suno プレイリストが正本で再ダウンロードで復旧可能。現行 6 リポの git 管理ファイル合計約 4.7GB を持ち込むと GitHub の実用上限に初日から張り付くため

## Consequences

- 単一チャンネルリポの external user には**破壊的変更なし**（解決チェーンの既存 2 段は不変）。ただし benchmark 系 `--channel` → `--competitor` リネームのみ breaking で、同梱 skills の参照更新と CHANGELOG 告知で吸収する
- 移行期間中は旧リポと workspace が併存し、`yt-skills sync` / automation-update は両方に打つ必要がある（段階移行のコスト）
- stock 楽曲のローカル喪失時は Suno からの手動再ダウンロードが必要になる（git バックアップの放棄）
- CONTEXT.md に workspace / channel slug / competitor を登録済み。channel registry（ADR-0013）は workspace 内パスも指せる定義に更新済み
