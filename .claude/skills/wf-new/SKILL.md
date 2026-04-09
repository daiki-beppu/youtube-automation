---
name: wf-new
description: Use when 新しいコレクション制作を開始したいとき。「新しいコレクション」「制作開始」「スタート」「新規ワークフロー」など、新規コレクションの立ち上げに関わる場面で必ず使用すること
---

## Overview

新コレクション開始オーケストレーター。企画選択 + サムネイル承認の2箇所のみ一時停止する。

## 前提

`config/channel_config.json` が存在すること。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

テーマはこの段階では不要。企画の結果でテーマが決定される。

データ収集は `daily_collect.sh`（launchd で毎朝 9:00 自動実行）が担当するため、workflow からは呼び出さない。

### Phase 1: 企画（自動実行 + ユーザー選択で一時停止）

```
Step 1（企画）を自動実行中...
```

1. **Skill ツールで `/ideate` を実行** — 日次収集データ + ベンチマークを基に分析 + ペルソナ別3つの企画候補をプレビューサムネイル付きで生成

`/ideate` の出力が表示された後、**ユーザーに企画選択のみ求める**:
- 選択肢: 提示された候補のいずれか
- **トラック数・音楽エンジンは確認しない**（`channel_config.json` の設定に従う）
- **ここでフローが一時停止し、ユーザーの入力を待つ**

**エラーハンドリング:**
- `/ideate` がエラー → エラー内容を表示して中断。分析データの確認を案内

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
- `--music-engine`: 選択された音楽エンジン（suno または lyria）

スクリプトが以下を自動実行:
- `collections/planning/YYYYMMDD-<short>-<theme>-collection/` ディレクトリ作成
- サブディレクトリ（10-assets, 20-documentation）作成
- `workflow-state.json` 初期化（stage=planning, phase=planning-approved）

出力されたパスを後続ステップで使用する。フルスキーマは `references/schema.md` を参照。

#### 2b. ドキュメント保存

Phase 1 の成果物を `20-documentation/` に保存:
- 企画候補一覧と選択結果

#### 2c. サムネイル確定 + 音楽素材生成

1. 選択した企画のプレビュー画像をコレクションの `10-assets/main.png` にコピー（`/ideate` で本番品質で生成済み）
2. プレビューディレクトリの自セッション分を削除
3. **サムネイル確定**:
   - `single_step` モードの場合: `/ideate` のプレビュー画像がテキスト込みの完成サムネイルなので、`/thumbnail` は**不要**。
     `main.png` をそのまま `thumbnail.jpg` にコピーする:
     ```bash
     cp <collection-path>/10-assets/main.png <collection-path>/10-assets/thumbnail.jpg
     ```
   - それ以外のモード: `/thumbnail <theme>` を Agent で実行（テキストオーバーレイ生成）
4. **音楽素材生成**: Agent ツールで音楽エンジンに応じたスキルを実行:
   - Suno: `/suno <theme>` を Skill ツールで実行（プロンプト生成）
   - Lyria: `/lyria <theme>` を Skill ツールで実行（composition.json 生成のみ。セグメント生成はしない。`/wf-next` で実行）
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
     - 再生成 → `/ideate` のプレビュー段階で調整済みのため、diff_prompt を修正して `generate_image.py` で再生成
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
   - **Lyria**: 「`/wf-next` を実行するとセグメント自動生成が始まります → ミキシング+マスタリング後に再度 `/wf-next`」

**重要**: `/wf-next` への自動接続はしない。ユーザーが手動で `/wf-next` を呼ぶ。

## Cross References

- 企画生成: `/ideate` スキル
- サムネイル生成: `/thumbnail` スキル
- ループ動画生成: `/loop-video` スキル
- 音楽プロンプト生成: `/suno` スキル
- 音楽コンポジション生成: `/lyria` スキル
- 後続ステップ管理: `/wf-next`
- 進捗確認: `/wf-status`
