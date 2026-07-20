---
name: community-draft
description: "Use when コレクションの YouTube コミュニティ投稿を JSON バッチ生成するとき。『投稿バッチ』『community-draft --batch』で発動。Studio を開いて単発投稿を手動準備する場合は /community-post を使う"
---

## 前後工程

- `前工程`: `/collection-ideate`
- `後工程`: `なし`

## Hard Gates

- `CLAUDE.md` と `docs/adr/0019-community-helper-extension.md` を読む。
- `config/channel/community-draft.json` が存在し、`load_config().community_draft.posts`
  が空でないこと。欠落時は
  `examples/channel_config.example/community-draft.example.json` をコピーしてチャンネル値へ
  書き換えるよう案内し、設定が完了するまで停止する。
- 対象 collection の `workflow-state.json::planning.final_title` と
  `planning.publish_target_at` が非空であること。`final_title` 欠落時は
  `/collection-ideate` で企画を確定するよう案内して停止する。`publish_target_at` 欠落時は
  planned YouTube publish datetime を ISO 8601（例 `2026-06-25T18:00:00+09:00`）で
  同フィールドへ記録するよう案内し、記録されるまで停止する。
- 対象 collection は `CHANNEL_DIR` 配下の実在パスを指定する。

## 完了条件

generator が exit 0 で終了し、`<collection>/30-promo/community-posts.json` の全投稿に
`text`、timezone 付き `scheduled_at`、channel root 相対 `image_path`、
`visibility: public` が存在することを確認した時点。Studio への転記・投稿は後工程の責務。

## Overview

`config/channel/community-draft.json::community_draft` の投稿テンプレートから
`<collection>/30-promo/community-posts.json` を決定的に生成する。実行モードは
`--batch` のみ。変数解決・日時計算・path 検証・JSON schema の単一ソースは
`references/generate_batch.py` と `docs/adr/0019-community-helper-extension.md` とし、
SKILL.md 側で再実装しない。

## 実行

1. ユーザー指定または現在の制作文脈から対象 collection を一意に決める。複数候補で
   推測できない場合だけ確認する。
2. 次を実行する。

   ```bash
   uv run python .claude/skills/community-draft/references/generate_batch.py \
     --batch \
     --collection <collection-dir>
   ```

3. exit 0 と出力パスを確認し、完了条件を検査する。

## 出力

```json
{
  "posts": [
    {
      "text": "展開済みテキスト",
      "scheduled_at": "2026-06-24T18:00:00+09:00",
      "image_path": "collections/planning/20260625-rain/main.png",
      "visibility": "public"
    }
  ]
}
```
