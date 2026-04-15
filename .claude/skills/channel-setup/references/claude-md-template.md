# CLAUDE.md v1.0

## 基本方針
- **不明な点は「わからない」と答え、確認を求める**
- **各作業は必ず適切な専用スキルを使用する**
- **最新情報は `uv run yt-channel-status` で取得**
- **チャンネル固有値は `config/channel_config.json` で一元管理**

## プロジェクト概要

YouTube チャンネル自動運用テンプレート — チャンネル固有値は `config/channel_config.json` に集約。

- **設定ファイル**: `config/channel_config.json`（チャンネル名・タグ・説明文等）
- **統計・コレクション一覧**: `uv run yt-channel-status` で動的取得

## 技術スタック

- **Python 3.11+** / ruff (lint, line-length=120) / pytest (test)
- **Google API**: YouTube Data API v3 + Analytics API v2
- **OAuth 2.0**: `auth/` に認証情報（セットアップは `auth/SETUP.md`）
- **macOS**: afinfo/ffprobe/FFmpeg
- **設定管理**: `ChannelConfig` シングルトン (`utils/channel_config.py`)

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

ルート `.claude/skills/` の共通スキルを使用。`channel_config.json` で動的に {{CHANNEL_NAME}} 向けに適応される。
詳細はルート `.claude/CLAUDE.md` のスキル一覧を参照。

## チャンネルディレクトリ構造

```
{{DIR_NAME}}/
├── config/                # channel_config.json, localizations.json, schedule_config.json, upload_settings.json
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

## 音楽制作ルール
- SunoAIプロンプト作成は必ず `/suno` スキルを使用
- 楽曲ダウンロード + マスター音源生成は `/masterup` スキルを使用
- 音源スタイルは `channel_config.json` の `genre.style` で管理

## 必須ルール

### 運用原則
- **スキル活用必須**: 各作業は専用スキルを使用
- **誇張表現完全回避**: Epic/Ultimate等の使用禁止（CTR戦略）
- **AI透明性維持**: コミュニティとの誠実対応
- **データドリブン**: 重要判断の前に `uv run yt-channel-status` で最新情報確認

### 技術ルール
- **macOS最適化**: afinfo/ffprobe使用、FFmpeg安定動作
- **collections/管理**: planning → live 移行ワークフロー
- **設定一元管理**: チャンネル固有値は `channel_config.json` → `ChannelConfig.load()` で取得

### 戦略的知見
- 音源スタイルは `channel_config.json` で管理（Analytics実証に基づく）
- **Complete Collection のみ投稿**
- テーマ別パフォーマンスは `/analyze` で都度確認（静的記述は陳腐化するため）

## Gotchas

- **動的パス解決**: `Path(__file__).resolve().parents[N]` パターン使用、ハードコード禁止
- **E402 不可避**: `sys.path.append` パターンのため import-not-at-top は許容
- **`ChannelConfig`**: シングルトンパターン。テスト時は `ChannelConfig.reset()` でリセット
- **ruff `--unsafe-fixes`**: unused import 削除に必要
- **pip3**: PEP 668 のため `--break-system-packages` が必要（macOS）

---

*v1.0 - /channel-new で自動生成*
