---
name: wf-new
description: "Use when まだコレクションディレクトリが存在せず、新規コレクション制作を立ち上げたいとき。「新しいコレクション始めたい」「制作開始」「新規ワークフロー」など、企画選択からディレクトリ作成・素材準備までを行う初期化フェーズで使用する。既存コレクションの進行は /wf-next"
---

## Overview

新コレクション開始オーケストレーター。企画選択 + サムネイル承認の2箇所のみ一時停止する。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**（CLAUDE.md §6 参照）。

## When to Use

| 状況 | 使う？ |
|---|---|
| 制作中コレクションが無い + 新しく始めたい | ✅ 使う |
| 「次なに作る？」とだけ聞かれた（企画候補が未確定） | ❌ 先に `/collection-ideate` で候補を出す（`/wf-new` 内部でも呼ぶが、単独で候補だけ見たいなら直接 `/collection-ideate`）|
| 既存コレクションを次工程へ進めたい | ❌ `/wf-next` を使う |
| 進捗だけ知りたい | ❌ `/wf-status` を使う |

`/wf-new` は `workflow-state.json` を **新規作成し自動更新する**。ユーザーが手で編集してはいけない（[扱い基準](../../../docs/workflow-cheatsheet.md#workflow-statejson-の扱い)）。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

テーマはこの段階では不要。企画の結果でテーマが決定される。

データ収集は `/analytics-collect`（`yt-analytics` のラッパー）が担当するため、workflow からは呼び出さない。必要に応じてユーザー側で cron / launchd に登録する運用。

### Phase 1: 企画（自動実行 + ユーザー選択で一時停止）

```
Step 1（企画）を自動実行中...
```

1. **Skill ツールで `/collection-ideate` を実行** — 日次収集データ + ベンチマークを基に分析 + ペルソナ別3つの企画候補をプレビューサムネイル付きで生成

`/collection-ideate` の出力が表示された後、**ユーザーに企画選択のみ求める**:
- 選択肢: 提示された候補のいずれか
- **トラック数・音楽エンジンは確認しない**（`config/channel/*.json` の設定に従う）
- **ここでフローが一時停止し、ユーザーの入力を待つ**

**エラーハンドリング:**
- `/collection-ideate` がエラー → エラー内容を表示して中断。分析データの確認を案内

### Phase 2: 選択後の処理（自動）

ユーザーが企画を選択したら、以下を自動実行する:

#### 2a. コレクション初期化（ディレクトリ + workflow-state.json）

以下の Python スクリプトを実行してコレクションディレクトリと workflow-state.json を自動生成する:

```bash
uv run yt-init-collection "<Collection Name>" "<theme-slug>" --track-count <N> --selected-plan <A-E> --music-engine <suno|lyria>
```

- `<Collection Name>`: 企画で決定したコレクション表示名
- `<theme-slug>`: ハイフン区切りのテーマスラッグ（例: `brigid-hearth`）
- `--track-count`: 確認済みトラック数（デフォルト 12）
- `--selected-plan`: 選択された企画（A〜E）
- `--music-engine`: 音楽エンジン（`suno` / `lyria`）。**省略時は `config/channel/youtube.json` の `music_engine` が使われる**。コレクション単位で上書きしたいときのみ明示する

スクリプトが以下を自動実行:
- `collections/planning/YYYYMMDD-<short>-<theme>-collection/` ディレクトリ作成
- サブディレクトリ（10-assets, 20-documentation）作成
- `workflow-state.json` 初期化（stage=planning, phase=planning-approved）

出力されたパスを後続ステップで使用する。フルスキーマは `references/schema.md` を参照。

#### 2a-2. scene_phrases 初期化（多言語対応コレクションのみ）

多言語タイトル生成で必須となる `workflow-state.json.scene_phrases` を投入する:

```bash
uv run yt-populate-scene-phrases <collection-dir-name>
```

- `<collection-dir-name>`: 2a で作成された `YYYYMMDD-<short>-<theme>-collection` のディレクトリ名
- 英語フレーズは `config/channel/content.json` の `title.theme_scenes[<theme>].scene` から自動解決され、Vertex AI Gemini で `localizations.json.supported_languages` 全件に翻訳されて書き込まれる
- **`supported_languages` が 1 言語以下のチャンネルでは CLI 側で自動スキップ**されるため、条件分岐は不要（そのまま呼んで構わない）
- 既に `scene_phrases` が存在する場合もスキップ（`--overwrite` で上書き可能）
- `theme_scenes[<theme>]` が未定義の場合は `--en "<custom phrase>"` で英語フレーズを明示指定する。詳細は `references/scene_phrases.md` 参照

**エラーハンドリング:**
- `theme_scenes` 未定義 + `--en` 未指定 → エラー終了。`config/channel/content.json` の `title.theme_scenes` に該当 theme を追加するか、`--en` を渡して再実行
- Gemini 呼び出し失敗 → エラーを報告して続行（メタデータ生成前に `/wf-next` から再実行可能）

#### 2b. ドキュメント保存

Phase 1 の成果物を `20-documentation/` に保存:
- 企画候補一覧と選択結果

#### 2c. サムネイル確定 + 音楽素材生成

1. 選択した企画のプレビュー画像をコレクションの `10-assets/main.png` にコピー（`/collection-ideate` で本番品質で生成済み）
2. プレビューディレクトリの自セッション分を削除
3. **サムネイル確定**:
   - `single_step` モードまたは `image_generation.provider: codex` の場合: `/collection-ideate` のプレビュー画像がテキスト込みの完成サムネイルなので、`/thumbnail` は**不要**。
     ただし **QA は必ず通す**（#570、プレビュー = 最終 thumbnail だと品質チェックが一切走らない経路を塞ぐ）:
     1. **必須 QA（最低限）**: Read ツールで `main.png` を等倍プレビューし、以下を目視確認する
        - [ ] **手・指の解剖学**: キャラが手を出している場合、各手 5 本指・指の分離が明瞭・指の融合や本数異常・溶融が無い（特に楽器持ち・指を伸ばすポーズで Gemini が破綻しやすい）
        - [ ] **テキスト破綻**: タイトル文字が読める・誤字脱字・grbage character・記号化が無い
        - [ ] **署名 / 透かし / ロゴ**: 参照元の signature / autograph / watermark / brand mark が転写されていない（#569）
     2. **NG だった場合**: `4-4` の diff_prompt_template に `${anatomy_clause}` を強調挿入して再生成、または codex プロバイダー（人体破綻に強い傾向）へ切り替えて再生成。`/collection-ideate` の Phase 4 から再実行する
     3. **OK だった場合**のみ `main.png` を `thumbnail.jpg` にコピーする:
        ```bash
        cp <collection-path>/10-assets/main.png <collection-path>/10-assets/thumbnail.jpg
        ```
   - それ以外のモード: `/thumbnail <theme>` を Agent で実行（テキストオーバーレイ生成。`/thumbnail` の品質チェック節で同等 QA が走る）
4. **音楽素材生成**: Agent ツールで音楽エンジンに応じたスキルを実行:
   - Suno: `/suno <theme>` を Skill ツールで実行（プロンプト生成）
     - **`/suno` 呼び出し前提条件チェック**（#571）: `config/skills/suno.yaml::genre_line` を読み、空のときは `config/channel/analytics.json::benchmark.channels[].slug` 全件について `data/video_analysis/<slug>/*.json` の存在を確認する。**両方とも未充足**（`genre_line` 空 AND 全 slug で分析結果不在）であれば `/suno` を起動せず、`uv run yt-video-analyze --source benchmark --channel <slug> --top 5` を先行実行するようユーザーに案内して Phase 2c を一旦停止する（`data/benchmark_*.json` が無ければさらにその前段で `/benchmark` を案内）。AI が `genre_line` を手書きで埋めて続行することは禁止
   - Lyria: `/lyria <theme>` を Skill ツールで実行（プロンプト設計のみ。Lyria 3 API 呼び出しは `/wf-next` で実行）
5. `workflow-state.json` を更新:
   - `assets.music_prompts`: `true`

**エラーハンドリング:**
- ループ動画生成失敗 → `assets.loop_video = "failed"` を記録して**続行**
- 音楽素材生成失敗 → エラーを報告して続行

#### 2d. サムネイル承認

1. サムネイルをプレビューで開く:
   ```bash
   open <collection-path>/10-assets/thumbnail.jpg
   ```

2. AskUserQuestion でサムネイルの承認を求める:
   ```
   question: "サムネイルを承認しますか？"
   options:
     - 承認する → assets.thumbnail = true に更新 → ループ動画生成へ
     - 再生成 → `/collection-ideate` のプレビュー段階で調整済みのため、diff_prompt を修正して `generate_image.py` で再生成
     - 中断 → ここで一旦停止（後で `/wf-next` で再開可能）
   ```

4. **承認された場合**、ループ動画を生成:
   - `/loop-video` を Skill ツールで実行（`main.png` → `loop.mp4`）
   - `workflow-state.json` を更新: `assets.loop_video`: `true` / `"failed"`
   - phase = "prepared" に更新

5. 完了ガイダンスを表示:

   ```
   `/wf-new` 完了！

   コレクション: <collection_name>
   テーマ: <theme>
   トラック数: <track_count>
   音楽エンジン: <suno|lyria>
   ディレクトリ: collections/planning/YYYYMMDD-<short>-<theme>-collection/
   現在のフェーズ: prepared
   ループ動画: ✅ 生成済み / ⚠️ 失敗（`/wf-next` で再試行可能）
   ```

   音楽エンジンに応じた次ステップ案内:
   - **Suno**: 「`suno-prompts.md` のプロンプトを SunoAI に投入 → プレイリスト作成後 `/wf-next` を実行してください」
   - **Lyria**: 「`/wf-next` を実行すると Lyria 3 API が呼ばれ、コレクション尺に応じてセグメントが生成されます → ミキシング+マスタリング後に再度 `/wf-next`」

**重要**: `/wf-next` への自動接続はしない。ユーザーが手動で `/wf-next` を呼ぶ。

## Cross References

- 企画生成: `/collection-ideate` スキル
- サムネイル生成: `/thumbnail` スキル
- ループ動画生成: `/loop-video` スキル
- 音楽プロンプト生成: `/suno` スキル
- 音楽プロンプト設計 + Lyria 3 API 呼び出し: `/lyria` スキル
- 後続ステップ管理: `/wf-next`
- 進捗確認: `/wf-status`
