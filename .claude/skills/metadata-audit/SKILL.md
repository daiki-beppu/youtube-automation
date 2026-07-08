---
name: metadata-audit
description: "Use when ローカル descriptions.md と YouTube メタデータの整合を監査するとき。「メタデータ監査」「説明欄ずれてない？」で発動。修正は /video-description の責務"
---

## Overview

`yt-metadata-audit` のラッパー。`collections/live/<col>/20-documentation/descriptions.md` と `workflow-state.json` の整合性、および YouTube API 側 snippet/localizations の整合性を読み取り専用で監査する。

**修正は範囲外**。差分検出後の更新は `/video-description` で descriptions.md を再生成し、必要に応じて `yt-bulk-update-desc` 経由で push する。

## 設定読み込みゲート

Quick Reference や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/metadata-audit/config.default.yaml`
2. `config/skills/metadata-audit.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("metadata-audit")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。REMOTE チェックのチャプター上限は `chapters.remote_max` を参照する（実装 `metadata_audit.py` も同じ経路で読む）。

## When to Use

- 一括アップロード後に YouTube 側にメタデータが正しく反映されたか確認したいとき
- descriptions.md を手で編集したあと、live 動画と差分が出ていないか調べたいとき
- 多言語ローカライゼーションが期待通り反映されているか確認したいとき
- 多言語チャンネルで scene_phrases の言語抜けを検出したいとき

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-metadata-audit` | local + remote の両方を監査 |
| `uv run yt-metadata-audit --local` | `descriptions.md` / `workflow-state.json` のみ（API call 不要） |
| `uv run yt-metadata-audit --remote` | YouTube API 側 snippet/localizations のみ |
| `uv run yt-metadata-audit --strict` | 1 件でも issue が見つかれば exit 1（CI 用途） |

## Instructions

### Step 1: 監査の実行

引数なしで `uv run yt-metadata-audit` を実行する。`collections/live/` 配下を全件走査し、以下を検出する:

**LOCAL チェック**:
- `descriptions.md` の `タイトル案` / `Complete Collection 概要欄` セクション欠落
- タイトル 100 文字超過
- タイムスタンプ数 > `config/channel/audio.json::chapter_max`（チャンネル config が単一ソース、既定 100。variation expansion regression 検出）
- chapter 名のローマ数字（pattern I / II / III ... = variation expansion）
- `workflow-state.json` の存在・JSON 破損
- 多言語チャンネル（`supported_languages` が 2 言語以上）の `scene_phrases` 言語抜け
- タグ件数・YouTube タグ文字数制限
- master mp4 が残っている場合の動画尺チェック（target_duration_min/max）

**REMOTE チェック**（OAuth 必要）:
- video_id が YouTube 上に存在するか
- YouTube 側 title 100 文字超過
- `🎧  🌧` のように scene_phrase が脱落して空白だけ残った title
- description のタイムスタンプ数 > skill-config `chapters.remote_max`（既定 12。`.claude/skills/metadata-audit/config.default.yaml` を `config/skills/metadata-audit.yaml` で上書き可能。実装は `load_skill_config("metadata-audit")` 経由で読む）
- ja localized title に日本語文字が含まれていない
- zh コードが `['zh-CN', 'zh-TW']` 以外の組合せ（旧 `zh-Hans` / `zh-Hant` 残骸検出）

### Step 2: issue がある場合の対応

監査出力に基づき、ユーザーに次のアクションを案内する:

- **`descriptions.md` 側の問題**（タイトル長すぎ、timestamp 過多など） → `/video-description` で再生成
- **YouTube 側との差分**（local と remote がずれている） → `/video-description` で descriptions.md を最新化したあと、運用者が `yt-bulk-update-desc` で push（一括更新スクリプトは現状チャンネル固有のため別途運用）
- **`workflow-state.json` 不在・JSON 破損** → `/wf-new` から作られた正規 state を復旧し、手編集で辻褄合わせしない
- **多言語チャンネルの scene_phrases 言語抜け** → 該当コレクションで `yt-populate-scene-phrases` を再実行、または `workflow-state.json` を正規形式で補完（単一言語チャンネルでは `scene_phrases` 不在は正常）

### Step 3: CI 統合（オプション）

GitHub Actions や cron で常時監視する場合は `--strict` を付ける。1 件でも issue があれば exit 1 で失敗するため、定期実行 → 通知パイプラインに組み込める。

## 障害時ガイダンス

`--local` 実行時は YouTube API を呼ばないため OAuth/quota 起因の失敗は発生しない。API 経由（既定）では以下が該当する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |

## Cross References

- `/video-description` — descriptions.md の生成・更新（修正の入口）
- `yt-bulk-update-synthetic-media` — 公開済み動画の `status.containsSyntheticMedia` が `false` のまま残っている場合に `True` へ一括是正する（#606、#603 是正前のアップロード分の遡及）
- `pyproject.toml` の `yt-metadata-audit` entry point
- `src/youtube_automation/scripts/metadata_audit.py` — 実装本体
- `src/youtube_automation/utils/preflight_checks.py` — `extract_descriptions_md_tags` / `check_tags_count` / `check_tags_yt_chars` を共有
