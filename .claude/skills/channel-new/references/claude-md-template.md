# CLAUDE.md v1.0

## 基本方針
- **不明な点は「わからない」と答え、確認を求める**
- **各作業は必ず適切な専用スキルを使用する**
- **最新情報は `uv run yt-channel-status` で取得**
- **チャンネル固有値は `config/channel/*.json`（責務別分割）で一元管理**

## プロジェクト概要

YouTube チャンネル自動運用テンプレート — チャンネル固有値は `config/channel/*.json` に責務別分割で集約。

- **設定ファイル**: `config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json` + `config/localizations.json` 等
- **統計・コレクション一覧**: `uv run yt-channel-status` で動的取得

## 技術スタック

- **Python 3.11+** / uv (パッケージ管理) / ruff (lint) / pytest (test)
- **youtube-channels-automation**: `uv run yt-*` で全 CLI エントリポイントを提供
- **Google API**: YouTube Data API v3 + Analytics API v2
- **Gemini API**: サムネイル分析 + 画像生成
- **OAuth 2.0**: `auth/token.json`（チャンネル固有）+ `client_secrets.json`
- **macOS**: afinfo/ffprobe/FFmpeg
- **設定管理**: `load_config()`（`youtube_automation.utils.config`、依存パッケージ `youtube-channels-automation` 内。frozen dataclass を返す）

## コマンド

```bash
# 最新チャンネル情報
uv run yt-channel-status

# Analyticsデータ収集
uv run yt-analytics                    # 上位50本 + 直近30日（デフォルト）
uv run yt-analytics --all-time         # 全期間データ

# ベンチマーク収集
uv run yt-benchmark-collect            # 鮮度チェック → 古いもののみ更新
uv run yt-benchmark-collect --force    # 全チャンネル強制更新

# 動画アップロード
uv run yt-upload-collection            # コレクション一括アップロード
uv run yt-upload-auto                  # planning/ 配下を自動検出して順次アップロード
```

**注意**: OAuth 認証で `client_secrets.json` が必要。`auth/` に配置するか `CLIENT_SECRETS_DIR` 環境変数で指定。

## スキル

ルート `.claude/skills/` の共通スキルを使用。`config/channel/*.json` で動的に {{CHANNEL_NAME}} 向けに適応される。
詳細はルート `.claude/CLAUDE.md` のスキル一覧を参照。

## チャンネルディレクトリ構造

```
{{DIR_NAME}}/
├── config/
│   ├── channel/           # 責務別分割設定（meta/content/youtube/analytics/playlists/workflow/audio）
│   └── localizations.json # 多言語テンプレート
├── auth/                  # token.json（チャンネル固有 OAuth トークン）
├── collections/           # コレクション本体
│   ├── planning/          # 制作中
│   └── live/              # 公開済み
├── data/                  # Analytics JSON スナップショット
├── reports/               # 生成レポート
├── docs/                  # benchmarks/, plans/
├── branding/              # チャンネルブランディング素材
├── tools/                 # チャンネル固有ツール
└── tests/                 # チャンネル固有テスト
```

youtube-automation パッケージの構造は GitHub リポジトリ（`daiki-beppu/youtube-automation`）の `CLAUDE.md` を参照。名前空間が紛らわしいが GitHub repo 名は `youtube-automation` / PyPI 配布名は `youtube-channels-automation` / import 名は `youtube_automation` で 3 つは別物。

## ワークフロー

### コレクション制作フロー
```
/wf-new  企画選択 → サムネ生成 → サムネ承認 → 音楽生成 → 動画 → 概要欄 → アップロード
```
`/wf-new` 1コマンドで企画から公開まで一気通貫。ミキシング工程なし。音楽生成は `config/channel/youtube.json` の `music_engine` に応じたスキル（`/suno` or `/lyria`）が使われる。

### ステージ管理
```
planning/ → live/
```
- `/video-upload` 完了時: `planning/` → `live/`

### 標準ディレクトリ構造
```
XXX-collection-name/
├── 01-master/           # マスター音声・動画
├── 02-Individual-music/ # 個別音声ファイル
├── 03-Individual-movie/ # 個別動画ファイル
├── 10-assets/           # 静止画素材
├── 20-documentation/    # 作業文書・プロンプト
└── workflow-state.json  # 進捗トラッキング（コレクションルート）
```

### 投稿システム（Collection Uploader）
Complete Collection アップロード + live 移動を実行:
1. Complete Collection（マスター動画）アップロード
2. `collections/planning/` → `collections/live/` 自動移動

## 多言語ローカライゼーション（単一ソース原則）

- **Canonical 宣言**: `config/localizations.json` の `supported_languages` + `default_language`
- **翻訳データ**: `config/localizations.json` の `languages.<lang>` に title/description/hashtag テンプレート
- **scene_phrases**: `supported_languages` が 2 言語以上の場合のみ、`collections/*/workflow-state.json` に `supported_languages` 全てのチャプター情景フレーズ翻訳が必要。単一言語チャンネルでは populate / preflight / metadata audit / localizations 生成が `scene_phrases` を要求しない
- **ランタイム参照**: `load_config().localizations.supported_languages`（`localizations.json` が唯一の Canonical ソース）
- **`content_model.languages`**: `config/channel/youtube.json` で定義。collection 型では未使用（`localizations.supported_languages` を使う）。release 型（単曲リリース）では発音言語リストとして解釈される

## 音楽制作ルール
- **音楽エンジンは `config/channel/youtube.json` の `music_engine` で切替**
  - `suno` → `/suno` スキル
  - `lyria` → `/lyria` スキル
- ミキシング・マスタリング工程なし（エンジン出力をそのまま使用）
- 音源スタイルは `config/channel/content.json` の `genre.style` で管理

## 必須ルール

### 運用原則
- **スキル活用必須**: 各作業は専用スキルを使用
- **誇張表現完全回避**: Epic/Ultimate等の使用禁止（CTR戦略）
- **AI透明性維持**: コミュニティとの誠実対応
- **データドリブン**: 重要判断の前に `uv run yt-channel-status` で最新情報確認

### 技術ルール
- **macOS最適化**: afinfo/ffprobe使用、FFmpeg安定動作
- **collections/管理**: planning → live 移行ワークフロー
- **設定一元管理**: チャンネル固有値は `config/channel/*.json` → `load_config()` で取得（責務別ネームスペース）

### 戦略的知見
- 音源スタイルは `config/channel/content.json` の `genre.style` で管理（Analytics実証に基づく）
- **Complete Collection のみ投稿**
- テーマ別パフォーマンスは `/analytics-analyze` で都度確認（静的記述は陳腐化するため）

## Gotchas

- **動的パス解決**: `Path(__file__).resolve().parents[N]` パターン使用、ハードコード禁止
- **uv run**: 全 CLI コマンドは `uv run yt-*` で実行（`python3` 直接実行は非推奨）
- **`yt-channel-status`**: `uv run yt-channel-status` で実行（旧 `get_channel_status` は廃止）
- **`load_config()`**: frozen dataclass を返す。テスト時は `youtube_automation.utils.config.reset()` でシングルトン state をリセット
- **OAuth 認証**: `client_secrets.json` は `auth/` に配置するか `CLIENT_SECRETS_DIR` 環境変数で共有ディレクトリを指定

---

*v1.0 - /channel-new で自動生成*
