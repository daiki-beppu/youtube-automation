# youtube-automation ドメイン知識（用語の正書）

`docs/architecture.md`（プロジェクト用語集・主要モジュール表）とリポジトリルートの `CLAUDE.md` が正本。ここには判定に使う要点だけを置く。**用語や構造の定義を確認するときは必ず正本を Read すること。**

本ファイルの記述が正本と食い違っていたら、**正本に従って判定し、本ファイルの修正をレポートの「スコープ外の発見」に記録する**こと。要約を写した索引は放置すると必ずドリフトする。

## プロダクトの輪郭

`youtube-channels-automation` は YouTube チャンネル運営を自動化するツールキット（Analytics 収集、AI コンテンツ生成、動画アップロード、メタデータ生成、ベンチマーク分析）。**このリポジトリ自体（upstream）と、パッケージを導入した下流のチャンネルリポジトリの 2 層構造**で動く。本リポジトリは Python 版のメンテナンスモードであり、TS 版（tayk）の開発は別リポジトリで行う（ADR-0021）。**tayk core や削除済み `packages/` を本リポジトリへ持ち込んではならない。**

## 中核用語

**2 層構造**: upstream（本リポジトリ）は wheel（`youtube-channels-automation`）と skill を配布する。下流チャンネルリポジトリは `CHANNEL_DIR` が指す先で、`config/channel/` / `config/localizations.json` / `auth/` / `.claude/skills/` / `collections/` / `assets/stock/` を持つ。

**skill**: `.claude/skills/<name>/` の自動化手順書（Claude Code / Codex 共用）。wheel に `_skills/` として force-include され、`yt-skills sync` で下流へ展開される。`.agents/skills` は Codex CLI 探索パス用の symlink（実体は常に `.claude/skills/` 側を編集する）。付属スクリプトは該当 skill の `references/` に置き、ルート直下に `scripts/` は設けない。

**yt-\* CLI**: `pyproject.toml [project.scripts]` に登録された console script 群（30 件超）。全 CLI が `entrypoints.py` を経由して `commands/` 配下（11 domain）の `main` を呼ぶ thin adapter。新規 CLI は必ず `yt-*` prefix で entry point を登録する。

**channel config**: 下流の `config/channel/*.json`。責務別に分割される（meta / content / youtube / analytics / playlists / workflow / audio + optional の shorts / comments / pinned-comment / distrokid / community-draft）。チャンネル固有値は必ず `from youtube_automation.configuration import load_config` 経由で取得し、責務別ネームスペース（`config.meta.channel_name` / `config.content.tags.base` 等）でアクセスする。ハードコーディング禁止。Path のみ必要なら `channel_dir()`。

**collection**: 1 本の YouTube 動画としてまとめられる楽曲群と成果物一式。`collections/planning/<slug>/` で制作し、公開後 `collections/live/` へ移動する。アルバムや YouTube playlist とは別概念。

**dashboard**: 全 first-party チャンネルの analytics スナップショットを起動時に最新化して一覧表示するローカル Web UI。Python 側（`yt-dashboard`）が channel registry・起動時の直列収集・read model・JSON API・build asset 配信を所有し、`dashboard/` の React + Vite + shadcn/ui 表示層は同一 origin API の読み取りだけを行う。本リポジトリ唯一の dashboard 限定 TypeScript 例外（ADR-0013 / ADR-0021）。

**Chrome 拡張（`extensions/`）**: suno-helper / distrokid-helper / community-helper。WXT + React + TypeScript の独立 Node toolchain で開発する、dashboard とは別の既存例外。dashboard から `extensions/shared-ui` を直接 import しない。

**auth / secrets**: 下流の `auth/client_secrets.json` / `auth/token.json`（絶対にコミットしない）。シークレット解決順序は `os.environ` → `op read`（1Password CLI）→ `ConfigError`。参照定義は `utils/secrets.py` の `_SECRET_REFS`。AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要。

**ドメイン例外**: `infrastructure/errors.py`（`AutomationError` 基底、`ConfigError` / `YouTubeAPIError` / `ValidationError` / `UploadError`）。生の `Exception` / `KeyError` を catch しない。

**first-party / competitor**: first-party は運営者自身が保有するチャンネルリポジトリ。competitor は `analytics.benchmark.channels` に登録するベンチマーク分析対象の他者チャンネルで、CLI フラグは `--competitor`（`--channel` は自チャンネル指定に予約）。

## 用語の取り違え（禁止）

| 使ってはならない                                 | 正書                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------ |
| アルバム, プレイリスト（collection を指して）    | collection                                                               |
| tayk（本リポジトリの実装を指して）               | youtube-channels-automation（tayk は別リポで開発する TS 版ブランド）     |
| `--channel`（競合チャンネルを指して）            | `--competitor`                                                           |
| ルート直下 `scripts/`（skill 付属スクリプトの置き場として） | `.claude/skills/<skill>/references/`                          |

新しい概念を導入するときは、`docs/architecture.md` の用語集に既存の用語がないかを先に確認する。既存語で表せるものに別名を与えない。
