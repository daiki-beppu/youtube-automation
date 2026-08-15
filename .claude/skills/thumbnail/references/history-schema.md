# Thumbnail test history schema

## 保存先

各コレクションの `<collection-path>/20-documentation/thumbnail-test-history.json` に保存する。再テストを保持できるよう `entries` は append-only とし、同じ `video_id` と `completed_at` の組を重複させない。

Studio へ引き渡した進行中テストの候補対応は `<collection-path>/20-documentation/thumbnail-test-active.json` に保存する。結果記録ではこの active design だけを候補対応の正とし、履歴の検証成功後に削除する。

## Active design schema version 1

```json
{
  "schema_version": 1,
  "video_id": "YouTube video ID",
  "candidates": [
    {
      "id": "A",
      "file": "10-assets/thumbnail-v1.jpg",
      "composition": {
        "subject_position": "center",
        "subject_scale": "medium",
        "scene": "cafe-window"
      },
      "color_palette": ["amber", "brown"],
      "text_amount": "low",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    },
    {
      "id": "B",
      "file": "10-assets/thumbnail-v2.jpg",
      "composition": {
        "subject_position": "left",
        "subject_scale": "close_up",
        "scene": "cafe-piano"
      },
      "color_palette": ["navy", "gold"],
      "text_amount": "medium",
      "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    }
  ]
}
```

## Schema version 1

```json
{
  "schema_version": 1,
  "entries": [
    {
      "video_id": "YouTube video ID",
      "completed_at": "2026-07-13T09:00:00Z",
      "result": {
        "studio_label": "Winner",
        "status": "winner",
        "result_candidate_id": "B"
      },
      "candidates": [
        {
          "id": "A",
          "file": "10-assets/thumbnail-v1.jpg",
          "composition": {
            "subject_position": "center",
            "subject_scale": "medium",
            "scene": "cafe-window"
          },
          "color_palette": ["amber", "brown"],
          "text_amount": "low",
          "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
          "watch_time_share": 41.2
        },
        {
          "id": "B",
          "file": "10-assets/thumbnail-v2.jpg",
          "composition": {
            "subject_position": "left",
            "subject_scale": "close_up",
            "scene": "cafe-piano"
          },
          "color_palette": ["navy", "gold"],
          "text_amount": "medium",
          "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
          "watch_time_share": 58.8
        }
      ]
    }
  ]
}
```

## フィールド契約

| field | contract |
|---|---|
| `schema_version` | integer `1` |
| `entries` | array |
| `video_id` | non-empty string |
| `completed_at` | UTC の ISO 8601 string（`YYYY-MM-DDTHH:MM:SSZ`） |
| `result.studio_label` | Studio 表示をそのまま記録する `Winner` / `Performed Same` / `Inconclusive` |
| `result.status` | `winner` / `performed_same` / `inconclusive` |
| `result.result_candidate_id` | `winner` では candidates 内の ID、それ以外は `null` |
| `candidates` | 2〜3 items。ID は配列順に `A`, `B`（3 案では続けて `C`） |
| `file` | collection root 相対の `10-assets/` 直下パス。ファイル名は `thumbnail-v*.jpg` / `thumbnail-v*.png` / `thumbnail-codex-v*.png` / `thumbnail.jpg` / `thumbnail.png` のいずれか |
| `composition.subject_position` | `left` / `center` / `right` / `full_frame` / `no_subject` |
| `composition.subject_scale` | `close_up` / `medium` / `wide` / `object_focus` / `no_subject` |
| `composition.scene` | 場所と活動の記録用 non-empty kebab-case string（反復集計には使わない） |
| `color_palette` | 下記「候補分類ルール」の固定色語彙から 1〜3 個、重複なし |
| `text_amount` | 空白を除く画面内文字数が 0=`none`、1〜15=`low`、16〜30=`medium`、31 以上=`high` |
| `sha256` | Studio 引き渡し直前の候補ファイル内容を `shasum -a 256` で算出した 64 桁小文字 hex。active design と完了履歴で同じ値を保持する |
| `watch_time_share` | number、0〜100 |

候補の `watch_time_share` 合計は Studio の表示丸めを許容して 99〜101 とする。

## 候補分類ルール

- `composition.subject_position`: 主役中心が画像幅の左 1/3=`left`、中央 1/3=`center`、右 1/3=`right`。主役が全幅に及ぶ場合は `full_frame`、主役なしは `no_subject`。
- `composition.subject_scale`: 顔または主役が画像高の 60% 以上=`close_up`、30% 以上 60% 未満=`medium`、30% 未満=`wide`。人物・動物なしで物体が主役なら `object_focus`、主役なしは `no_subject`。
- `composition.scene`: 場所と活動を kebab-case で記録する（例: `cafe-piano`）。結果の説明用で、勝ちパターンの反復集計には使わない。
- `color_palette`: `black` / `white` / `gray` / `red` / `orange` / `amber` / `yellow` / `gold` / `green` / `teal` / `blue` / `navy` / `purple` / `pink` / `brown` / `beige` に色を分類し、画像面積の 20% 以上を占める色を面積順で最大 3 個記録する。該当色が 0 個なら最大面積の 1 色を記録する。
- `text_amount`: 空白を除く画面内文字の Unicode code point 数が 0=`none`、1〜15=`low`、16〜30=`medium`、31 以上=`high`。

Studio label の正規化:

| Studio label | `status` |
|---|---|
| `Winner` | `winner` |
| `Performed Same` | `performed_same` |
| `Inconclusive` | `inconclusive` |

## 検証

### Active design

`COLLECTION` を対象コレクションへ設定して実行する。最初の `jq -e` は構造と `workflow-state.json::upload.video_id` の一致、続く loop は各相対パスの実在と content hash の一致を検証する。すべて exit 0 の場合だけ Studio 引き渡しまたは結果記録へ進む。

```bash
COLLECTION="<collection-path>"
ACTIVE="$COLLECTION/20-documentation/thumbnail-test-active.json"
WORKFLOW_VIDEO_ID="$(jq -r '.upload.video_id // empty' "$COLLECTION/workflow-state.json")"
jq empty "$ACTIVE" &&
jq -e --arg video_id "$WORKFLOW_VIDEO_ID" '
  .schema_version == 1 and
  (.video_id == $video_id and ($video_id | length > 0)) and
  (.candidates | type == "array" and length >= 2 and length <= 3) and
  ([.candidates[].id] == (["A", "B", "C"][:(.candidates | length)])) and
  ([.candidates[].file] | length == (unique | length)) and
  ([.candidates[].sha256] | length == (unique | length)) and
  (all(.candidates[];
    (.file | type == "string" and test("^10-assets/(thumbnail-v[^/]*\\.(jpg|png)|thumbnail-codex-v[^/]*\\.png|thumbnail\\.(jpg|png))$")) and
    (.composition.subject_position | IN("left", "center", "right", "full_frame", "no_subject")) and
    (.composition.subject_scale | IN("close_up", "medium", "wide", "object_focus", "no_subject")) and
    (.composition.scene | type == "string" and test("^[a-z0-9]+(-[a-z0-9]+)*$")) and
    (.color_palette | type == "array" and length >= 1 and length <= 3 and length == (unique | length) and all(.[]; IN("black", "white", "gray", "red", "orange", "amber", "yellow", "gold", "green", "teal", "blue", "navy", "purple", "pink", "brown", "beige"))) and
    (.text_amount | IN("none", "low", "medium", "high")) and
    (.sha256 | type == "string" and test("^[0-9a-f]{64}$"))
  ))
' "$ACTIVE" &&
while IFS=$'\t' read -r expected file; do
  actual="$(shasum -a 256 "$COLLECTION/$file" | awk '{print $1}')" || exit 1
  [ "$actual" = "$expected" ] || exit 1
done < <(jq -r '.candidates[] | [.sha256, .file] | @tsv' "$ACTIVE")
```

### Completed history

`HISTORY` を対象ファイルへ設定して実行する。

```bash
HISTORY="<collection-path>/20-documentation/thumbnail-test-history.json"
jq empty "$HISTORY" &&
jq -e '
  .schema_version == 1 and
  (.entries | type == "array") and
  (all(.entries[];
    (.video_id | type == "string" and length > 0) and
    (.completed_at |
      type == "string" and
      test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$") and
      (. as $value |
        (try ((fromdateiso8601 | strftime("%Y-%m-%dT%H:%M:%SZ")) == $value) catch false))) and
    ((.result.studio_label == "Winner" and .result.status == "winner") or
     (.result.studio_label == "Performed Same" and .result.status == "performed_same") or
     (.result.studio_label == "Inconclusive" and .result.status == "inconclusive")) and
    (.candidates | type == "array" and length >= 2 and length <= 3) and
    ([.candidates[].id] == (["A", "B", "C"][:(.candidates | length)])) and
    ([.candidates[].file] | length == (unique | length)) and
    ([.candidates[].sha256] | length == (unique | length)) and
    (all(.candidates[];
      (.id | IN("A", "B", "C")) and
      (.file | type == "string" and test("^10-assets/(thumbnail-v[^/]*\\.(jpg|png)|thumbnail-codex-v[^/]*\\.png|thumbnail\\.(jpg|png))$")) and
      (.composition.subject_position | IN("left", "center", "right", "full_frame", "no_subject")) and
      (.composition.subject_scale | IN("close_up", "medium", "wide", "object_focus", "no_subject")) and
      (.composition.scene | type == "string" and test("^[a-z0-9]+(-[a-z0-9]+)*$")) and
      (.color_palette | type == "array" and length >= 1 and length <= 3 and length == (unique | length) and all(.[]; IN("black", "white", "gray", "red", "orange", "amber", "yellow", "gold", "green", "teal", "blue", "navy", "purple", "pink", "brown", "beige"))) and
      (.text_amount | IN("none", "low", "medium", "high")) and
      (.sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
      (.watch_time_share | type == "number" and . >= 0 and . <= 100)
    )) and
    (([.candidates[].watch_time_share] | add) >= 99 and ([.candidates[].watch_time_share] | add) <= 101) and
    (if .result.status == "winner"
      then (.result.result_candidate_id as $id | any(.candidates[]; .id == $id))
      else .result.result_candidate_id == null
      end)
  )) and
  ([.entries[] | [.video_id, .completed_at] | join("|")] | length == (unique | length))
' "$HISTORY"
```

履歴へ新しい entry を末尾に append した後、active design を削除する前に次も実行する。`watch_time_share` を除く候補配列と `video_id` が active design と完全一致することを検証する。

```bash
ACTIVE="<collection-path>/20-documentation/thumbnail-test-active.json"
HISTORY="<collection-path>/20-documentation/thumbnail-test-history.json"
jq -e --slurpfile active "$ACTIVE" '
  .entries[-1].video_id == $active[0].video_id and
  ([.entries[-1].candidates[] | del(.watch_time_share)] == $active[0].candidates)
' "$HISTORY"
```

この節の各 `jq -e` 式を active design schema version 1、completed history schema version 1、active mapping 照合の機械検証ロジックの単一ソースとする。active design の全コマンドが exit 0 のときだけ Studio 引き渡しまたは結果記録へ進む。completed history の構造検証と active mapping 照合がともに exit 0 のときだけ記録完了とし、active design を削除する。
