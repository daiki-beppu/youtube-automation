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
| `cloud_owned` | Suno DL成果物のmanifest参照を記録し、工程所有権をcloudへ引き渡し済み | cloud executorがmanifest検証済み成果物からミキシング+マスタリングを再開 |
| `mastered` | 最終マスター音源配置済み | /wf-next で全自動公開 |
| `publishing` | 公開フロー実行中 | 自動完了待ち（エラー時は /wf-next で再実行） |
| `complete` | 全工程完了 | /analytics --analyze で初週パフォーマンス確認 |

`phase` は最後に実行した操作の結果を反映する。自動計算ではなくスキルが明示的に更新する。

## フィールド定義

```json
{
  "collection_name": "string",
  "theme": "string",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",
  "stage": "planning | live",
  "phase": "planning | prepared | cloud_owned | mastered | publishing | complete",
  "selected_plan": "A | B | C | D | E",
  "track_count": 12,
  "planning": {
    "activities": "Working",
    "target_persona": "deep-work listener",
    "final_title": "Rainy Harbor Jazz",
    "generated": true,
    "music": {
      "engine": "suno | lyria | minimax",
      "mood": ["mellow", "introspective"],
      "atmosphere": "rainy harbor at night, mellow jazz by the docks",
      "tempo": "slow",
      "instruments": ["soft piano", "saxophone", "upright bass"],
      "exclude": ["electric guitar", "heavy drums"],
      "suno_playlist_url": null
    }
  },
  "scene_phrases": {
    "en": "string",
    "<lang>": "string"
  },
  "title_template_check": {
    "allow_volume_patterns": true
  },
  "assets": {
    "thumbnail": false,
    "loop_video": false,
    "music_prompts": false,
    "music_downloaded": false,
    "raw_master": null,
    "master_audio": null,
    "master_video": null,
    "description": false
  },
  "handoff": {
    "point": "suno_download",
    "owner": "cloud",
    "manifest_key": "002ch/sample/suno-download/manifest.json",
    "root_sha256": "64 lowercase hex characters"
  },
  "human_tasks": {
    "distrokid_submission": {
      "completed_at": "ISO 8601"
    }
  },
  "music_pair_selection": {
    "updated_at": "ISO 8601",
    "exceptions_over_limit_count": 1,
    "exceptions_over_limit": [
      {
        "prompt_index": 1,
        "variant": "a",
        "title": "Song Title",
        "source": "01a-Song Title.mp3",
        "duration_sec": 479.4,
        "max_song_sec": 300.0,
        "reason": "all_candidates_over_max_song_sec; selected_shortest_over_limit"
      }
    ]
  },
  "upload": {
    "video_id": null,
    "video_url": null,
    "publish_at": null
  },
  "post_upload": {
    "shorts": [
      {
        "short_num": 1,
        "video_id": "string",
        "uploaded_at": "ISO 8601",
        "publish_at": null,
        "resume_session_uri": "string"
      }
    ]
  },
  "track_display_names": {
    "01-track.mp3": "Display Name"
  },
  "title_activity": "Working",
  "thumbnail_auto_selection": {
    "schema_version": 1,
    "mode": "selection_only | full",
    "selected": "thumbnail-v1.jpg",
    "distance": 0.125,
    "ranking": [
      {
        "candidate": "thumbnail-v1.jpg",
        "distance": 0.125,
        "width": 1280,
        "height": 720,
        "eligible": true,
        "reasons": []
      }
    ],
    "reference_images": ["assets/benchmarks/reference.jpg"],
    "reference_diagnostics": {
      "max_reference_distance": 0.5,
      "references": [
        {
          "reference_image": "assets/benchmarks/reference.jpg",
          "distance": 0.1,
          "outlier": false
        }
      ]
    },
    "executed_at": "ISO 8601"
  }
}
```

### assets フィールド詳細

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `thumbnail` | boolean | サムネイル生成+承認済み（`10-assets/thumbnail.jpg`） |
| `loop_video` | boolean / `"failed"` | ループ動画生成済み（`10-assets/loop.mp4`） |
| `music_prompts` | boolean | 音楽プロンプト/composition 生成済み |
| `music_downloaded` | boolean | Suno パスで `/music --generate` の一括 DL 完了を示すフラグ（`02-Individual-music/` に音源が揃った状態）。`raw_master` 生成前段の DL 完了を独立追跡する。判定は primary: `02-Individual-music/` のファイル実在、secondary: 本フラグ。`yt-init-collection` の初期状態には含まれず、DL 完了時に遅延追加される |
| `raw_master` | string / null | 自動生成された raw master のファイル名（/music --master or /music --generate 出力） |
| `master_audio` | string / null | ユーザーがミキシング+マスタリングした最終マスターのファイル名。`workflow.wf_next.skip_manual_mastering: true`（raw=final 運用）のチャンネルでは `/wf-next` が `raw_master` と同じファイル名を自動設定する。`workflow.wf_next.skip_audio_approval: false`（`wf_next` の boolean は全て true=手動工程を省く向き）のチャンネルでは確定前に `/wf-next` が承認を取る |
| `master_video` | string / null | 生成されたマスター動画のファイル名 |
| `description` | boolean | YouTube 概要欄の検証済み JSON+HTML pair 生成済み（`20-documentation/descriptions.{json,html}`） |

`music_downloaded: true` かつ `raw_master: null` は、Suno 楽曲が DL 済みで raw master（クロスフェード結合出力）が未生成の中間状態を表す。

### handoff フィールド詳細

`yt-workflow-state record-handoff` は `phase: prepared`、`planning.music.engine: suno`、`assets.music_downloaded: true` を検証してから、`phase` を `cloud_owned` へ一方向遷移する。同じmanifest参照での再実行は冪等で、別manifestへの上書きや逆遷移は拒否する。

| フィールド | 型 | 説明 |
|---|---|---|
| `handoff.point` | `"suno_download"` | local → cloud の引き渡し点 |
| `handoff.owner` | `"cloud"` | 現在の工程所有者。分散lockの代わりにresolverが参照する |
| `handoff.manifest_key` | string | R2上の完了marker `manifest.json` の相対key |
| `handoff.root_sha256` | string | manifest正準file一覧のroot SHA-256（lowercase 64 hex） |

stateにはmanifest全文やfile一覧を複製しない。正本はMediaStore上のmanifestであり、Git制御面はkeyとroot checksumだけを保持する。

### human_tasks フィールド詳細

`human_tasks.distrokid_submission.completed_at` は DistroKid Web への転記・アップロードを人間が確認した提出時点を記録する。`config/channel/distrokid.json` が通常ファイルとして存在するチャンネルだけが対象で、`yt-workflow-state record-distrokid-submission` が初回時刻を lock + atomic update する。再実行では初回時刻を上書きせず、human-tasks 生成と live-clean は owner の `distrokid_submission_completed_at` accessor を参照する。

### stage フィールド詳細

| 値 | 説明 |
|---|---|
| `planning` | `collections/planning/` で制作中 |
| `live` | upload 完了後に `collections/live/` へ移動済み |

`stage` は collection の配置段階を表し、制作工程の進行を表す `phase` とは独立して更新する。

### post_upload フィールド

`post_upload.shorts` は公開後 short の upload 状態を `short_num` ごとに保持する。`resume_session_uri` は再開可能 upload の途中だけ存在し、完了時の entry は `video_id`、`uploaded_at`、`publish_at` を持つ。

| フィールド | 型 | 説明 |
|---|---|---|
| `post_upload.shorts[].short_num` | integer / null | short の番号 |
| `post_upload.shorts[].video_id` | string | YouTube 動画 ID |
| `post_upload.shorts[].uploaded_at` | string | upload 日時（ISO 8601） |
| `post_upload.shorts[].publish_at` | string / null | 公開予約日時（ISO 8601） |
| `post_upload.shorts[].resume_session_uri` | string | 再開可能 upload session URI |

### track_display_names フィールド

`track_display_names` は音源ファイル名を概要欄で使う表示名へ対応付ける object（`{filename: display_name}`）。重複トラック名の解消結果を再実行時にも維持する。

### title_activity フィールド

`title_activity` は title template に使う collection 固有の activity 文字列。設定から解決した activity より優先する。

### thumbnail_auto_selection フィールド

自動選択を apply したときの監査 record。`mode`、採用候補と距離、候補 ranking、参照画像と外れ値診断、実行日時を保持する。`ranking[].reasons` は候補が不適格な理由の文字列配列である。

### 互換フィールド

`thumbnail.approved` と `description.generated` は既存 state の読み取り専用互換 field であり、workflow-state owner の `thumbnail_approved` / `description_generated` accessor だけが解釈する。新規 write はそれぞれ `assets.thumbnail` / `assets.description` だけを更新し、互換 field を出力しない。

top-level `music_engine` は既存 state の読み取り専用互換 field であり、workflow-state owner の `music_engine` accessor だけが解釈する。`planning.music.engine` と併存する場合は値の一致を必須とし、不一致なら停止する。新規 write は `planning.music.engine` だけを更新し、互換 field を出力しない。

#### wf-new --auto の判定責務

`/wf-new --auto` は active collection が無ければ state を事前作成せず `/wf-new` へ委譲し、初期化後は返された collection を固定する。active collection があれば本 state と実成果物を一段ごとに再評価し、Lyria / Suno / masterup / 制作 / 公開 / publish の委譲先を選ぶ。統合 runner 自身は本ファイルを更新せず、各既存 skill の検証済み更新契約を使う。`workflow.scheduled_automation.allow_external_publish` が `false` の場合はローカル動画・metadata 生成後、YouTube 書き込み前で停止する。`.automation-run/history.json` は停止理由と再開地点の監査記録であり、本 state や成果物の代替 source of truth ではない。

#### Suno 定期実行 checkpoint の責務

生成途中の entry index、観測済み clip ID、playlist/download 再試行情報は suno-helper の Chrome local storage（`sunoResumeState` / `sunoUnattendedRunState`）が所有し、`workflow-state.json` へ二重保存しない。workflow-state の正規成果物は従来どおり `planning.music.suno_playlist_url`、`assets.music_downloaded`、`02-Individual-music/` の実ファイルである。定期実行 state が `completed` でもこれらが揃わなければ完了ではなく、`checkpoint` / `manual-intervention` なら `/music --master` へ進めない。

### scene_phrases フィールド

多言語タイトル用の scene phrase 辞書（言語コード → phrase）。`uv run yt-populate-scene-phrases` が投入する optional top-level state（詳細: `references/scene_phrases.md`）。単一言語チャンネルや未投入のコレクションでは存在しない。

### title_template_check フィールド

意図的なシリーズ名を公開タイトルに使うコレクションだけに記録する optional top-level state。`allow_volume_patterns: true` のとき、upload preflight は LHS の `Vol.` / `Part` / `#N` / ローマ数字の巻数検出だけを許可する。未設定または `false` は既定どおり拒否し、RHS 鋳型・完全重複・核語彙の検査は常に継続する。

### music_pair_selection フィールド

`uv run yt-suno-select-tracks --allow-best-effort-over-max` で、全候補が `pair_selection.max_song_sec` を超過した prompt から最短候補を例外採用した場合のみ populate される optional top-level state。通常選曲成功時は読み書きしない。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `updated_at` | string | 例外採用情報を記録した日時（ISO 8601 UTC） |
| `exceptions_over_limit_count` | integer | `max_song_sec` 超過を例外採用した候補数 |
| `exceptions_over_limit` | object[] | 例外採用候補の詳細 |
| `exceptions_over_limit[].prompt_index` | integer | Suno prompt の 1-based index |
| `exceptions_over_limit[].variant` | string / null | `01a-...` の `a` などの variant |
| `exceptions_over_limit[].title` | string | 採用候補の title |
| `exceptions_over_limit[].source` | string | 元音源ファイル名 |
| `exceptions_over_limit[].duration_sec` | number | 実測 duration 秒 |
| `exceptions_over_limit[].max_song_sec` | number | 設定上限秒 |
| `exceptions_over_limit[].reason` | string | 例外採用理由 |

### upload フィールド

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `video_id` | string / null | YouTube 動画 ID |
| `video_url` | string / null | YouTube 動画 URL |
| `publish_at` | string / null | 公開予約日時（ISO 8601） |

### planning フィールド詳細

`planning` は各企画フェーズスキルが populate する正規化メタデータ。`init_collection.py` は正準の音楽エンジンを `{"music": {"engine": "..."}}` に初期化する。

#### planning.music

`/music --prompt` または `/music --generate` 実行時に populate する。新規コレクションのみ必須化（既存コレクションは未マイグレーション、`/audit --alignment` 側でフォールバック実装済み）。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|---|------|
| `planning.music.engine` | `"suno" \| "lyria" \| "minimax"` | Yes | 音楽エンジンの正準キー |
| `planning.music.mood` | string[] | Yes | 感情語 1-3 個（例: `["mellow", "introspective"]`）|
| `planning.music.atmosphere` | string | Yes | コレクション全体の世界観 1 文（英語）|
| `planning.music.tempo` | string | Yes | `"very slow"` / `"slow"` / `"gentle"` / `"moderate"` / `"lively"` のいずれか |
| `planning.music.instruments` | string[] | Yes | 主要楽器のリスト |
| `planning.music.exclude` | string[] | No | 除外楽器（任意）|
| `planning.music.suno_playlist_url` | string / null | No | Suno playlist URL（`/music --generate` が DL 完了時に記録。Suno エンジンのみ。Lyria エンジンでは使用しない）|

**冪等性**: スキル再実行時は `planning.music` 全体を上書きする（merge しない）。

#### その他の planning キー

他スキルが populate するキー（参考）:

| キー | populate するスキル | 用途 |
|-----|-------------------|-----|
| `planning.activities` | `/wf-new` 等 | プレイリストアクティビティの override (`scripts/playlist_manager.py`) |
| `planning.target_persona` | `/wf-new` | 企画選択時のターゲットペルソナ記録 |
| `planning.final_title` | `/wf-new` | 確定タイトル |
| `planning.generated` | `/wf-new` | 企画完了フラグ |

## ステージ移行

| タイミング | 移行 | トリガー |
|-----------|------|---------|
| `/publish --upload` 完了 | `planning/` → `live/` | `upload.video_id` が記録された時点 |

## 冪等性ルール

`/wf-next` は `assets` フラグを確認し、`true` / 値ありのステップをスキップする。
途中エラーで `phase: "publishing"` のまま停止した場合、再実行で未完了ステップのみ実行される。

## 旧スキーマ互換

`steps` キーが存在する workflow-state.json は旧スキーマ（v1）として扱う。
`/wf-status` は `steps` キーの有無で旧/新スキーマを判別し、旧スキーマの場合は従来の表示を行う。
旧スキーマの live コレクションは変換不要（読み取り専用）。

旧 top-level `video_id` は公開対象の判定に使用しない。`/publish --pinned` など公開後処理を再開する場合は、`uv run yt-workflow-state --collection <path> set-upload --video-id <video-id>` で正準の `upload.video_id` へ修復する。

## 更新ルール

- 各操作で `updated_at` を現在時刻（ISO 8601 UTC）に上書き
- `phase` は操作完了時にスキルが明示的に設定
- `assets` フラグは個別に更新（他フラグに影響しない）
