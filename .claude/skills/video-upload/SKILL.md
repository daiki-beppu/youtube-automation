---
name: video-upload
description: "Use when コレクションの動画または release 型（単曲リリース）の楽曲リリース動画が完成し、YouTubeへのアップロード自動化が必要なとき。「楽曲リリースをアップロード」「リリース動画を公開」で発動。collection 型は Complete Collection のアップロードと live 移行、release 型は言語別アップロードを実行。動画ファイルの生成（MP3→MP4）は /videoup、リリースショート生成は /short-release"
---

## 前後工程

- `前工程`: `/automation-run`, `/videoup`, `/video-description`, `/playlist`, `/thumbnail`
- `後工程`: `/post-publish`, `/community-post`, `/metadata-audit`, `/pinned-comment`, `/live-clean`

## Overview

Complete Collection を YouTube にアップロードし、`planning/` → `live/` へ自動移行します。`/video-description` スキルで事前生成した概要欄・タイトル・タグを使用します。

## 完了条件

- **collection 型**: Complete Collection のアップロードが完了し、コレクションが `collections/live/` へ移動、`20-documentation/upload_tracking.json` に記録されている
- **release 型（単曲リリース）**: `content_model.languages` の全言語分のアップロード・プレイリスト追加・概要欄の相互リンク更新が完了している
- 公開タイミングを、collection 型では `--plan` の結果（即時公開 / 予約公開 / 限定・非公開）どおりにユーザーへ案内済み

## Subagent Contract

subagent として呼ぶ場合、メインエージェントは対象コレクション、content model、実行モード（plan / upload）、承認済み公開条件をリポジトリルート相対パスまたは値で入力に含める。実アップロード、公開時刻、メタデータの承認が必要なら、メインが承認を得るまで upload を subagent へ委譲しない。subagent は `workflow-state.json` を読み書きせず、`AskUserQuestion` を実行しない。plan の完了報告には `status: success | failure`、検証した動画とメタデータ成果物の絶対パス一覧、エラーを含める。state や tracking を更新する実アップロード CLI は承認後にメインが実行し、`20-documentation/upload_tracking.json` と対象動画の存在を検証する。直接実行時は既存手順を変更しない。

## 設定読み込みゲート

前提確認や Channel Adaptation に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/video-upload/config.default.yaml`
2. `config/skills/video-upload.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("video-upload")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。前提条件チェックの探索パターンは `preflight.*`、メタデータ基準の誇張語は `metadata.banned_exaggeration_words` を参照する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## When to Use

- コレクションの動画ファイルが揃い、YouTube へのアップロードが必要なとき
- アップロード設定の確認や OAuth 認証のセットアップが必要なとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | コレクションディレクトリパス（省略可） | `/video-upload collections/planning/20260304-clm-fairy-forest-collection` |
| 未指定 | `collections/planning/` の `phase=mastered` かつ `upload.video_id=null` の未公開候補が 1 件だけなら自動検出（0 件・複数件は `-c` 明示を要求） | `/video-upload` |

## Channel Adaptation

実行前に `config/channel/youtube.json` の `content_model` を読み取り、チャンネルに適応する:

| content_model.type | 動作 | 対応言語の出所 |
|-------------------|------|--------------|
| `collection` | Complete Collection アップロード → live 移動（単一動画） | `config/localizations.json` / `load_config().localizations.*` |
| `release` | 言語ごとに別動画をアップロード | `content_model.languages`（発音言語リスト） |

### collection 型
- 下記フローのとおり Complete Collection を1本アップロード
- `collection_uploader.py` を使用
- 多言語ローカライゼーションは `config/localizations.json` の `supported_languages` が Canonical ソース（v2.0.0 以降は単一ソース化）
- `supported_languages` が 2 言語以上の場合のみ `scene_phrases` / 概要欄多言語版 / YouTube localization メタデータを生成・検証する。単一言語チャンネルでは `scene_phrases` は不要

### release 型 + languages: ["jp","en"]（COT）
- **同日2本アップロード**: JP + EN を同日投稿（API クォータ: 2 × 1,600 = 3,200 ユニット）
- **プレイリスト管理**: `config/channel/playlists.json` の `playlists.jp` / `playlists.en` に自動追加
- **相互リンク**: アップロード後に概要欄を更新し、JP↔EN 動画 URL を相互記載
- `uv run yt-upload-auto` を使用
- release 型では `content_model.languages` が発音言語リストとして解釈される（collection 型とは意味が異なる）
- `uv run yt-upload-collection --plan` は collection 専用の事前確認であり、release 型では使わない。公開時刻は `uv run yt-upload-auto` の実アップロード経路（metadata の `publish_at` または `config/channel/youtube.json` の既定時刻 fallback）に従う

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本） | collection 型 1 本、release 型 JP+EN 2 本（2 × 1,600 = 3,200 ユニット） | アップロード本数 |
| thumbnails.set（50 units / 本） | アップロード本数分 | — |
| search.list（100 units、dedup 確認） | 約 2 | — |
| playlistItems.insert（50 units） | 割当プレイリスト数 P | プレイリスト構成 |

- 上限 / 承認: `--plan` は API を一切叩かないドライラン。dedup search が二重 insert を回避し、quota 枯渇時は `QuotaExhaustedError` で中断する（collection 型 1 実行 ≈ 1,900+ units）。

## Instructions

あなたは YouTube アップロード自動化スペシャリストです。YouTube Data API v3、OAuth 2.0 認証、Collection Uploader の運用に精通しています。

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合はそのディレクトリを対象にします。未指定の場合は `collections/planning/` 配下で `phase=mastered` かつ `upload.video_id=null` の未公開コレクションを自動検出します。候補が 0 件または複数件の場合は停止するため、`-c` で対象を明示します。`collections/live/` の公開済みコレクションは自動検出の対象外です。

### 前提条件チェック

アップロード前に以下を確認する（詳細は `references/posting-checklist.md` 参照）:

1. **マスター動画**: skill-config `preflight.master_video_globs`（既定 `01-master/*.mp4` → `03-Individual-movie/*master*.mp4`）の順に探索 — 存在しなければエラー終了
2. **サムネイル**: skill-config `preflight.thumbnail_candidates`（既定 `10-assets/thumbnail.jpg` → `10-assets/thumbnail.png`）の候補順で探索 — いずれも存在しなければエラー終了。`main.png/jpg` は textless 動画背景なので upload thumbnail には使わない
3. **概要欄**: `20-documentation/descriptions.md` — **存在しない場合は `/video-description` スキルを実行して自動生成する**（対象コレクションパスを引き継ぐ）。生成完了後にアップロードフローへ進む
4. **初投稿時のプレイリスト初期化**: `config/channel/playlists.json` が存在する場合は `/playlist` スキルで `uv run yt-playlist-status` を実行する。`(未作成)` があるときは、初投稿前に `uv run yt-playlist-manager --init --dry-run` → ユーザー確認 → `uv run yt-playlist-manager --init` で playlist ID を作成・書き戻してからアップロードへ進む

### collection アップロードフロー

`content_model.type = "collection"` のとき、以下を自動実行:

0. **公開タイミング確定（必須）** — ユーザーに公開方法を案内・確認する前に必ず `uv run yt-upload-collection --plan [-c NAME]` を実行し、実際の公開挙動を確定する。`config/schedule_config.json` の予約設定や `config/channel/youtube.json` の既定時刻により、`privacy=public` でも `status.publishAt` が設定される場合があるため、plan 結果なしに「即時公開」と案内しない
1. **Complete Collection アップロード** — マスター動画、メタデータ（descriptions.md から読み込み）、サムネイル設定
2. **live 移動** — `collections/planning/` → `collections/live/`
3. **公開後処理** — `load_config().workflow.post_publish.configured` が `true` なら、live 移動後のコレクションパスを `/post-publish` に引き継ぎ、manifest 順の `community-post → pinned-comment → metadata-audit` を実行する。チェーン側の承認・履歴・再開契約に委ね、ここで子スキルを個別に再実装しない。未設定（`false`）なら後方互換として、`config/channel/community.json` が存在する場合だけ従来どおり `/community-post` を案内し、後続 2 スキルは手動実行のままとする

メタデータは `descriptions.md` から title / description / tags を優先使用。存在しない場合は `BAHMetadataGenerator` で自動生成にフォールバック。

プレイリストへの動画追加は後続のアップロード経路が担う。`collection` 型では `collection_uploader` 内部の `assign_video()` に任せる。初投稿時に `/playlist` で行うのは未作成プレイリストの作成と `playlist_id` 書き戻しであり、個別動画の手動 assign ではない。

### release アップロードフロー

`content_model.type = "release"` のときは `uv run yt-upload-auto` を使い、言語ごとに別動画をアップロードする。`uv run yt-upload-collection --plan` は collection uploader の公開予定計算なので、この分岐では実行しない。公開時刻を案内する場合は、`uv run yt-upload-auto` が読む metadata の `publish_at` と `config/channel/youtube.json` の既定時刻 fallback に基づくことを明示し、collection 用 plan 結果を流用しない。

### コマンドリファレンス

```bash
# Complete Collection アップロード（デフォルト動作）
uv run yt-upload-collection [-c NAME]

# 進捗確認
uv run yt-upload-collection --status [-c NAME]

# スケジュール計算（ドライラン）
uv run yt-upload-collection --plan [-c NAME]

# release 型アップロード
uv run yt-upload-auto
```

### エラーハンドリング

- トラッキングによるリジューム（中断後の再実行で未完了分のみ処理）
- 指数バックオフによるリトライ（5xx エラー時、最大5回）
- `20-documentation/upload_tracking.json` (v3 スキーマ) へのログ保存

### リファレンス

- アップロード前の詳細チェックリストは `references/posting-checklist.md` を参照
- 予約投稿（YouTube `status.publishAt`）のセットアップは `references/scheduled-publish.md` を参照

### 予約投稿（スケジュール公開）

CC は `config/schedule_config.json` の `schedule` セクションに応じて即時公開と予約公開を切り替える。

- **予約公開を有効化** — 以下のいずれかを `schedule` 内に設定する:
  - `auto_schedule_enabled: true`（明示的に有効化）
  - `cadence: ["tue", "thu", "sat"]` のような曜日リスト（暗黙オプトイン）
  - `publish_time: "20:00"` のような時刻指定（暗黙オプトイン）
- **チャンネル既定時刻** — `config/channel/youtube.json` の `youtube.default_publish_time` / `default_publish_timezone` を設定すると、`schedule_config.json` で予約設定が無い場合の fallback として次回の予約時刻を自動適用する
- **即時公開のまま** — `auto_schedule_enabled: false` を明示すれば、他のキーが設定されていても即時公開を強制する

collection 型では、ユーザーに公開方法を提示する前の挙動確認は必ず `--plan` を実行する。`--plan` はアップロード API は叩かないが、予約日時計算のため YouTube read API を呼ぶ場合がある:

```bash
uv run yt-upload-collection --plan -c <NAME>
# → "📅 公開予定: 2026-06-15T20:00:00+09:00" が出れば予約公開、
#   "📅 公開設定: 即時公開 (public)" なら即時公開、
#   "📅 公開設定: 限定公開 (unlisted)" / "📅 公開設定: 非公開 (private)" ならその公開範囲でアップロード
```

「即時公開」と断定してよいのは、plan 結果が `📅 公開設定: 即時公開 (public)` の場合のみ。`📅 公開設定: 限定公開 (unlisted)` / `📅 公開設定: 非公開 (private)` が出た場合は、その公開範囲でアップロードされることを明示する。`📅 公開予定: <日時>` が出た場合は「今アップロード → `<日時>` に自動で一般公開」と、実際の公開予定時刻を明示して案内する。

詳細とトラブルシュート（"設定したのに即時公開された" の早期発見手順）は `references/scheduled-publish.md` を参照。

### API ステータス設定（自動適用）

アップローダーが `config/channel/youtube.json` の値（単一ソース。skill-config には置かない）を自動設定する（手動指定不要）:

- `status.selfDeclaredMadeForKids` ← `self_declared_made_for_kids`（既定 `false` — 子ども向けコンテンツではない）
- `status.containsSyntheticMedia` ← `contains_synthetic_media`（既定 `true` — AI 生成コンテンツの申告）

### メタデータ基準

- YouTube タイトル長制限準拠（100文字）
- 誇張表現回避（skill-config `metadata.banned_exaggeration_words`、既定 Epic / Ultimate 等の禁止）
- SEO 最適化タグ（`config/channel/content.json` の `tags.base` 参照）
- AI 透明性・Usage & Attribution の記載

## 障害時ガイダンス

アップロードは `upload_core` の再開可能アップロードを使うため、ネットワーク中断後はコマンド再実行で途中から続行できる。

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |

## Cross References

- `/video-description` — アップロード前に descriptions.md を生成
- `/playlist` — 初投稿前のプレイリスト初期化、状態確認、手動 assign、クリーンアップ（アップロード時の自動 assign は本スキル内で実行される）
- `/metadata-audit` — アップロード後のローカル ↔ YouTube 整合性監査
- `/post-publish` — `workflow.post-publish` 設定時、アップロード完了後の 3 段チェーンを承認・履歴付きで実行
- `/community-post` — `workflow.post-publish` 未設定時の後方互換。コミュニティ投稿テンプレを展開して Studio を起動（`config/channel/community.json` がある場合のみ）
