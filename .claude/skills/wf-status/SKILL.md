---
name: wf-status
purpose: 進める
description: "Use when コレクション制作の進捗を読むだけで確認するとき（実行しない）。「どこまで進んだ？」「制作中コレクション一覧」で発動。登録者・再生回数など YouTube 統計は /analytics --status"
---

## 前後工程

- `前工程`: `/wf-new`
- `後工程`: `/wf-new`, `/wf-next`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `tmp/reviews/workflow-status.html`（表示専用snapshot。毎回atomic overwrite）
- `読み込む`: `collections/{planning,live}/<id>/workflow-state.json` と実成果物

## Overview

アクティブなコレクションの進捗一覧・詳細を、固定pathのread-only HTML snapshotで表示する。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**。

## When to Use

| 状況 | 使う？ |
|---|---|
| 「どこまで進んだ？」「読むだけ」 | ✅ 使う |
| 「次のステップ実行して」 | ❌ `/wf-next` を使う（`/wf-status` は **実行系を一切呼ばない**） |
| 「企画から公開後処理まで継続して」 | ❌ `/wf-new --auto` を使う（`/wf-status` は **実行系を一切呼ばない**） |
| 「workflow-state.json を見せて」 | ✅ 使う（生 JSON ではなく phase / assets を整形表示する） |
| 「YouTube 側の登録者数・再生数を見せて」 | ❌ `/analytics --status` を使う |

`/wf-status` は読み取り専用で、`workflow-state.json` と成果物を一切更新しない。HTMLは一時的なviewであり、workflowの正本・入力・再開判定には絶対に使わない。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内

## Instructions

### 手順

1. チャンネルrootで `uv run yt-workflow-status` を実行する。
2. CLIが `collections/planning/` と `collections/live/` のcanonical `workflow-state.json`、および企画・thumbnail・音楽prompt・master音源・master動画・publishの実成果物を突合する。
3. `tmp/reviews/workflow-status.html` を検証後にatomic overwriteし、既定browserで開く。
4. HTML上の「すべて / 企画中 / 公開工程 / 完了」はclient-sideの表示filterだけで、stateや成果物を変更しない。
5. browserを開けない場合はnon-zero終了し、表示された絶対pathをユーザーへ案内する。生成済みsnapshotは保持する。

HTMLには実行buttonやstate更新導線を置かない。表示内容は毎回canonical stateと実成果物から作り直し、過去HTMLを読み込まない。

### 補足

- `workflow-state.json` が不在・破損したコレクションも、他のコレクションを隠さず不整合cardとして表示する
- stateと実成果物の食い違いはblockerとして表示し、このskillから修復しない
- スキーマ詳細はcanonical owner `youtube_automation.domains.collections.workflow_state` と `.claude/skills/wf-new/references/schema.md` を参照

## 障害時ガイダンス

進捗表示はローカルのcanonical stateと成果物を読むだけで外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| workflow-state.json 不在/破損 | 対象ディレクトリに状態ファイルが無い | `/wf-new` で初期化するかパスを確認（外部サービスに依存しないため API 障害・quota の影響は受けない） |

## Cross References

- 新規開始: `/wf-new`
- 一気通貫の開始・再開: `/wf-new --auto`
- 次ステップ実行: `/wf-next`
