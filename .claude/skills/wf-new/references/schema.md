# workflow-state.json スキーマ v2

## 3フェーズワークフロー

```
Phase 1: 企画+素材準備    /wf-new     企画選択 → サムネイル+音楽素材を並列生成 → サムネイル承認
Phase 2: 制作             /wf-next    Suno DL or Lyria 生成 → ユーザーがミキシング+マスタリング
Phase 3: 公開             /wf-next    動画→概要欄→アップロード（全自動）
```

## phase 値

| phase | 意味 | 次のアクション |
|-------|------|--------------|
| `planning` | 企画提案前 | /wf-new で企画選択 |
| `prepared` | サムネ承認済み+音楽素材準備完了 | Suno 作成 or Lyria 生成 → ミキシング+マスタリング |
| `mastered` | 最終マスター音源配置済み | /wf-next で全自動公開 |
| `publishing` | 公開フロー実行中 | 自動完了待ち（エラー時は /wf-next で再実行） |
| `complete` | 全工程完了 | /analytics-analyze で初週パフォーマンス確認 |

`phase` は最後に実行した操作の結果を反映する。自動計算ではなくスキルが明示的に更新する。

## フィールド定義

```json
{
  "collection_name": "string",
  "theme": "string",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",
  "stage": "planning | live",
  "phase": "planning | prepared | mastered | publishing | complete",
  "selected_plan": "A | B | C | D | E",
  "track_count": 12,
  "music_engine": "suno | lyria",
  "planning": {
    "music": {
      "engine": "suno | lyria",
      "mood": ["mellow", "introspective"],
      "atmosphere": "rainy harbor at night, mellow jazz by the docks",
      "tempo": "slow",
      "instruments": ["soft piano", "saxophone", "upright bass"],
      "exclude": ["electric guitar", "heavy drums"]
    }
  },
  "assets": {
    "thumbnail": false,
    "loop_video": false,
    "music_prompts": false,
    "raw_master": null,
    "master_audio": null,
    "master_video": null,
    "description": false
  },
  "upload": {
    "video_id": null,
    "video_url": null,
    "publish_at": null
  }
}
```

### assets フィールド詳細

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `thumbnail` | boolean | サムネイル生成+承認済み（`10-assets/thumbnail.jpg`） |
| `loop_video` | boolean / `"failed"` | ループ動画生成済み（`10-assets/loop.mp4`） |
| `music_prompts` | boolean | 音楽プロンプト/composition 生成済み |
| `raw_master` | string / null | 自動生成された raw master のファイル名（/masterup or /lyria 出力） |
| `master_audio` | string / null | ユーザーがミキシング+マスタリングした最終マスターのファイル名 |
| `master_video` | string / null | 生成されたマスター動画のファイル名 |
| `description` | boolean | YouTube 概要欄生成済み（`20-documentation/descriptions.md`） |

### upload フィールド

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `video_id` | string / null | YouTube 動画 ID |
| `video_url` | string / null | YouTube 動画 URL |
| `publish_at` | string / null | 公開予約日時（ISO 8601） |

### planning フィールド詳細

`planning` は各企画フェーズスキルが populate する正規化メタデータ。`init_collection.py` は空オブジェクト `{}` で初期化する。

#### planning.music

`/suno` または `/lyria` 実行時に populate する。新規コレクションのみ必須化（既存コレクションは未マイグレーション、`/alignment-check` 側でフォールバック実装済み）。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|---|------|
| `planning.music.engine` | `"suno" \| "lyria"` | Yes | 音楽エンジン（top-level `music_engine` と一致）|
| `planning.music.mood` | string[] | Yes | 感情語 1-3 個（例: `["mellow", "introspective"]`）|
| `planning.music.atmosphere` | string | Yes | コレクション全体の世界観 1 文（英語）|
| `planning.music.tempo` | string | Yes | `"very slow"` / `"slow"` / `"gentle"` / `"moderate"` / `"lively"` のいずれか |
| `planning.music.instruments` | string[] | Yes | 主要楽器のリスト |
| `planning.music.exclude` | string[] | No | 除外楽器（任意）|

**冪等性**: スキル再実行時は `planning.music` 全体を上書きする（merge しない）。

#### その他の planning キー

他スキルが populate するキー（参考）:

| キー | populate するスキル | 用途 |
|-----|-------------------|-----|
| `planning.activities` | `/collection-ideate` 等 | プレイリストアクティビティの override (`scripts/playlist_manager.py`) |
| `planning.target_persona` | `/collection-ideate` | 企画選択時のターゲットペルソナ記録 |
| `planning.final_title` | `/collection-ideate` | 確定タイトル |
| `planning.generated` | `/collection-ideate` | 企画完了フラグ |

## ステージ移行

| タイミング | 移行 | トリガー |
|-----------|------|---------|
| `/video-upload` 完了 | `planning/` → `live/` | `upload.video_id` が記録された時点 |

## 冪等性ルール

`/wf-next` は `assets` フラグを確認し、`true` / 値ありのステップをスキップする。
途中エラーで `phase: "publishing"` のまま停止した場合、再実行で未完了ステップのみ実行される。

## 旧スキーマ互換

`steps` キーが存在する workflow-state.json は旧スキーマ（v1）として扱う。
`/wf-status` は `steps` キーの有無で旧/新スキーマを判別し、旧スキーマの場合は従来の表示を行う。
旧スキーマの live コレクションは変換不要（読み取り専用）。

## 更新ルール

- 各操作で `updated_at` を現在時刻（ISO 8601 UTC）に上書き
- `phase` は操作完了時にスキルが明示的に設定
- `assets` フラグは個別に更新（他フラグに影響しない）
