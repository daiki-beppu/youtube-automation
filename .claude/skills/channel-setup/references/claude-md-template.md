# CLAUDE.md v1.0

## 基本方針
- **不明な点は「わからない」と答え、確認を求める**
- **各作業は必ず適切な専用スキルを使用する**
- **最新情報は `uv run yt-channel-status` で取得**
- **チャンネル固有値は `config/channel/*.json` で責務別に管理（v2.0.0 以降）**

## プロジェクト概要

YouTube チャンネル自動運用テンプレート — チャンネル固有値は `config/channel/*.json` に責務別で集約。

- **設定ファイル**: `config/channel/meta.json` / `content.json` / `youtube.json` / `analytics.json` / `playlists.json` / `workflow.json` / `audio.json`
- **ローカライゼーション**: `config/localizations.json`（`config/` 直下）
- **統計・コレクション一覧**: `uv run yt-channel-status` で動的取得

## 技術スタック

- **Python 3.11+** / ruff (lint, line-length=120) / pytest (test)
- **Google API**: YouTube Data API v3 + Analytics API v2
- **OAuth 2.0**: `auth/` に認証情報（セットアップは `auth/SETUP.md`）
- **macOS**: afinfo/ffprobe/FFmpeg
- **設定管理**: `youtube_automation.utils.config.load_config()` 経由で参照（責務別 dataclass）

## コマンド

```bash
# 最新チャンネル情報
uv run yt-channel-status

# Analyticsデータ収集
uv run yt-analytics

# Lint
ruff check src/
ruff check src/ --fix --unsafe-fixes  # 自動修正

# テスト
python3 -m pytest tests/

# 動画アップロード
uv run yt-upload-collection
```

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

youtube-automation パッケージの構造は GitHub リポジトリ（daiki-beppu/youtube-channels-automation）の `CLAUDE.md` を参照。

## ワークフロー

### コレクション制作フロー（3フェーズ）
```
Phase 1: 企画+素材準備  /wf-new   企画選択 → サムネ+音楽素材を並列生成 → サムネ承認
Phase 2: 制作           /wf-next  Suno DL or Lyria 生成 → ミキシング+マスタリング
Phase 3: 公開           /wf-next  動画→概要欄→アップロード→コミュニティ→ショート（全自動）
```
データ収集は `/collect`（`yt-analytics` ラッパー）で実施。分析は `/ideate` 内部で自動実行。必要に応じて cron / launchd に `yt-analytics` を登録して定期化。

### ステージ管理
```
planning/ → live/
```
- `/upload` 完了時: `planning/` → `live/`

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
- **scene_phrases**: `collections/*/workflow-state.json` に `default_language + supported_languages` 全てのチャプター情景フレーズ翻訳が必要
- **ランタイム参照**: `load_config().localizations.supported_languages`（`localizations.json` が唯一の Canonical ソース）
- **`content_model.languages`**: `config/channel/youtube.json` で定義。collection 型では未使用（`localizations.supported_languages` を使う）。single_release 型では発音言語リストとして解釈される

## 音楽制作ルール
- SunoAIプロンプト作成は必ず `/suno` スキルを使用
- 楽曲ダウンロード + マスター音源生成は `/masterup` スキルを使用
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
- テーマ別パフォーマンスは `/analyze` で都度確認（静的記述は陳腐化するため）

## Gotchas

- **動的パス解決**: `Path(__file__).resolve().parents[N]` パターン使用、ハードコード禁止
- **E402 不可避**: `sys.path.append` パターンのため import-not-at-top は許容
- **設定キャッシュ**: `load_config()` はシングルトン。テスト時は `from youtube_automation.utils.config import reset; reset()` でリセット
- **ruff `--unsafe-fixes`**: unused import 削除に必要
- **pip3**: PEP 668 のため `--break-system-packages` が必要（macOS）

---

*v1.0 - /channel-new で自動生成*
