---
name: thumbnail-test
description: "Use when 長尺動画で YouTube Studio のサムネイル A/B テストを設計し、結果を記録するとき。「サムネ A/B テスト」「Test & Compare」「サムネテスト結果」で発動。公開前の競合・320px 視認性比較は /thumbnail-compare、候補生成は /thumbnail を使う"
---

## Overview

テキスト付きサムネイル候補を 2〜3 案に絞り、YouTube Studio で operator が行う A/B テストを設計する。完了後は watch time share と結果をコレクションの履歴 JSON に記録し、次回 `/thumbnail` が参照できる勝ちパターンを残す。

公開 API で扱える thumbnail resource の操作は `thumbnails.set` のみで、A/B テストの開始・結果取得は含まれない。Studio 操作は自動化しない。

## Hard Gates

- `<collection-path>/workflow-state.json` が存在しなければ、対象をコレクションとして確定できないため停止し、手動作成せず `/wf-new` でコレクションを初期化するよう案内する。
- `<collection-path>/10-assets/` が存在しなければ停止し、`uv run yt-collection-preflight <collection-path> --fix` で標準骨格を補完してから `/thumbnail` で候補を生成するよう案内する。補完と候補生成が完了するまで後続 Step へ進まない。
- operator に対象が長尺動画または live archive であり、Shorts / private / Made for Kids / mature audiences / Scheduled Live / Premiere のいずれでもないか 1 項目ずつ確認する。1 項目でも該当または未確認なら停止する。Premiere は終了して長尺動画へ変換された後なら対象にできる。
- 候補は `thumbnail-v*.jpg` / `thumbnail-v*.png` / `thumbnail-codex-v*.png` / 確定済み `thumbnail.jpg` / `thumbnail.png` から、実在する 2〜3 枚だけを使う。2 枚未満なら `/thumbnail` で候補を追加して停止する。
- operator に channel の advanced features が有効か確認する。未確認または無効なら Studio 設定へ進まず停止する。
- 全候補が 1280x720 以上であることを `sips` で確認する。1 枚でも下回れば Studio 設定へ進まず `/thumbnail` で再生成する。
- Studio へのアップロード・テスト開始は operator が行う。Chrome 拡張、ブラウザ自動操作、YouTube Data API で代行しない。
- Studio に完了結果が表示されるまでは履歴 JSON に推測値を書かない。実行中なら確認手順だけ提示して停止する。
- 結果記録モードでは `20-documentation/thumbnail-test-active.json` に固定した候補対応だけを使う。active design の欠落、構造不正、`video_id` 不一致、候補ファイルの欠落・SHA-256 不一致が 1 件でもあれば履歴 JSON を変更せず停止する。

## 完了条件

- 候補 2〜3 案について、相対パス、構図、配色、文字量を含む設計表を提示済み。
- Studio 引き渡し時は、候補の SHA-256 を含む `20-documentation/thumbnail-test-active.json` を保存・検証してから operator 向け設定手順を提示済み。
- 完了結果の記録依頼では、`20-documentation/thumbnail-test-history.json` に 1 entry を append し、`jq empty` と `references/history-schema.md` の検証コマンドが exit 0。
- 完了結果の記録依頼では、履歴検証成功後に `20-documentation/thumbnail-test-active.json` を削除済み。
- 記録後、Winner の構図・配色・文字量と次回 `/thumbnail` が参照する条件を表示済み。`Performed Same` / `Inconclusive` の場合は「還元なし」と表示済み。

## References

- `references/operator-guide.md` — Studio の eligibility、設定、結果確認手順。候補提示時に読む。
- `references/history-schema.md` — 候補分類、保存先、JSON schema、記録・検証手順。候補分類前と結果記録時に読む。

## 実行フロー

### Step 1: モードと対象を確定

ユーザー入力から `<collection-path>` を確定し、次のどちらかを宣言する。

- **設計モード**: 結果値が未提示。Step 2〜4 を行う。
- **結果記録モード**: Studio の結果ラベルと各候補の watch time share が提示済み。Step 2 で active design の固定済み対応を検証後、Step 5 を行う。

`workflow-state.json` から `upload.video_id` を読む。欠落または `null` ならアップロード済み動画を特定できないため、設計表までは提示してよいが Studio 設定手順へ進まず `/video-upload` 後の再実行を案内して停止する。この値を対象コレクションの記録用 `video_id` として保持し、Step 5 で唯一の正とする。

`20-documentation/thumbnail-test-active.json` が存在する場合は `references/history-schema.md` の active design 検証を行う。設計モードでは進行中テストとして内容を表示し、再選定・上書きせず結果確認後の再実行を案内して停止する。結果記録モードでは active design が存在しなければ、Studio に渡した対応を確定できないため履歴 JSON を変更せず停止する。

### Step 2: 候補を 2〜3 案に絞る

結果記録モードでは候補の再列挙、auto-selection、画像の再分類を行わない。`references/history-schema.md` の検証コマンドで active design の構造、`workflow-state.json::upload.video_id` との一致、各候補ファイルの現在の SHA-256 を検証する。すべて PASS の場合だけ active design の ID、相対パス、構図、配色、文字量、SHA-256 を固定済み候補表として表示し、Step 5 へ進む。1 件でも FAIL なら差分を表示し、active design と履歴 JSON を変更せず停止する。

設計モードでは以下を行う。

`10-assets/` の対象パターンを列挙し、画像を実際に表示して以下を候補ごとに記録する。

| 項目 | 記録内容 |
|---|---|
| ID | `A` / `B` / `C` |
| file | コレクションルート相対パス |
| composition | `subject_position` / `subject_scale` / `scene` |
| color_palette | 画面面積の 20% 以上を占める色を固定語彙で 1〜3 個 |
| text_amount | `none` / `low` / `medium` / `high` |
| sha256 | 候補ファイルの内容を `shasum -a 256 <candidate>` で算出した 64 桁小文字 hex |

次の順で採用する。

1. `config/skills/thumbnail.yaml::image_generation.auto_selection.enabled: true` なら、変更を伴わない採点を実行し、適格候補の distance 昇順を初期順位にする。

   ```bash
   uv run yt-thumbnail-auto-select <collection-path> --dry-run --json
   ```

2. auto-selection が無効なら CLI を実行せず、対象パターンの全画像を比較する。
3. 各候補の解像度を確認する。`pixelWidth < 1280` または `pixelHeight < 720` が 1 件でもあれば FAIL として停止する。

   ```bash
   sips -g pixelWidth -g pixelHeight <candidate-A> <candidate-B> [<candidate-C>]
   ```

4. `references/history-schema.md` の「候補分類ルール」を読み、構図・配色・文字量を分類する。上位から 3 field のいずれか 1 つ以上が別案と異なる候補を 2〜3 枚選ぶ。同一画像の拡張子違い・コピーは除外する。
5. 候補ごとに 320x180 の確認画像を `/tmp` へ生成する。

   ```bash
   sips -z 180 320 <candidate> --out /tmp/<candidate-name>-320.jpg
   ```

6. `/thumbnail-compare` と同じ 320px 観点で確認する。次の 3 条件がすべて PASS の候補だけを残す。
   - 文字: 画面内タイトルの全字を拡大なしで読み取れる。
   - 主役: 人物・動物・楽器・主役物体の種別を拡大なしで答えられる。
   - シーン: 屋内 / 屋外と活動を 3 秒以内に答えられる。

   1 条件でも FAIL の候補は除外する。候補が 2 枚未満になれば `/thumbnail` で追加生成して停止する。

### Step 3: テスト設計を提示

候補表に加え、各案で意図的に変えた項目を 1 行ずつ示す。複数項目を変えた場合はすべて列挙し、単一要因テストと誤記しない。

`references/operator-guide.md` を読み、対象動画の eligibility と現在の Studio 手順を operator 向けに表示する。結果は CTR ではなく watch time share で判定されること、完了まで数日〜2週間かかることを明記する。

Studio 設定へ進む前に次を PASS/FAIL で表示する。

- advanced features: operator が有効と確認済みなら PASS、それ以外は FAIL
- eligibility: operator が対象形式を確認し、Shorts / private / Made for Kids / mature audiences / Scheduled Live / Premiere の 6 項目をすべて「該当しない」と回答した場合だけ PASS。1 項目でも該当または未確認なら FAIL
- candidates: 2〜3 枚なら PASS、それ以外は FAIL
- resolution: 全候補 1280x720 以上なら PASS、それ以外は FAIL
- 320x180: 全候補が 3 条件を満たせば PASS、それ以外は FAIL

1 件でも FAIL なら Step 4 へ進まず停止する。

### Step 4: operator へ引き渡す

次を表示した後、通常のユーザー確認（Claude Code では AskUserQuestion）で `Studio 設定を行う` / `中止する` の明示 2 択を提示する。承認されるまで operator に設定を依頼しない。

```text
[EXTERNAL CHANGE]
候補のアップロードと Done は YouTube Studio に反映され、公開後は視聴者へテスト候補が表示されます。
実行中に title または thumbnail を変更するとテストは停止します。
選択肢: Studio 設定を行う / 中止する
```

`Studio 設定を行う` が選ばれた場合だけ次を表示する。

表示前に、Step 1 で保持した `video_id` と Step 2 の A/B/C 対応（相対パス、構図、配色、文字量、SHA-256）を `20-documentation/thumbnail-test-active.json` へ保存する。既存 active design を上書きしない。`references/history-schema.md` の active design 構造・`video_id`・content hash 検証がすべて exit 0 になった場合だけ Studio へ引き渡す。

```text
[HUMAN STEP]
YouTube Studio で候補 A〜C をアップロードし、Done を選んで A/B テストを設定してください。
テスト中は候補ファイルと thumbnail-test-active.json を変更・削除しないでください。
完了後、Studio の結果ラベル、A〜C それぞれの watch time share、結果を確認した日時を指定して /thumbnail-test を再実行してください。候補対応は保存済み active design から読みます。
```

`中止する` が選ばれた場合は外部反映なしで停止する。

### Step 5: 結果を記録

`references/history-schema.md` を読み、Step 2 で検証済みの active design を候補対応の唯一の正とする。Step 1 で保持した `workflow-state.json::upload.video_id` を履歴 entry の `video_id` に使う。active design またはユーザー入力・Studio 表示の `video_id` は照合にだけ使い、保持した値と完全一致しなければ各値を表示して active design と履歴 JSON を変更せず停止する。以下を確定し、不足が 1 つでもあれば不足項目を列挙して両 JSON を変更せず停止する。

- `completed_at`（operator が完了結果を確認した日時を UTC の `YYYY-MM-DDTHH:MM:SSZ` へ正規化）
- Studio の結果ラベルと正規化した `result.status`
- 各候補の `watch_time_share`（0〜100）
- `result_candidate_id`（Winner の候補。該当なしは `null`）
- active design に固定された候補情報（ID、相対パス、構図、配色、文字量、SHA-256）。再分類・再計算した値で置き換えない

同じ `video_id` と `completed_at` の entry が既にあれば重複 append せず停止する。既存ファイルがある場合は内容を保持して `entries` の末尾に追加し、存在しない場合だけ `schema_version: 1` と空の `entries` から新規作成する。

書き込み後は `references/history-schema.md` の履歴構造検証と active mapping 照合を実行する。失敗した場合は完了を宣言せず、記録前の内容へ戻して active design を保持したままエラーを提示する。両方の検証成功後だけ `20-documentation/thumbnail-test-active.json` を削除する。

### Step 6: 還元内容を表示

`result.status == "winner"` のときだけ `result_candidate_id` に対応する候補の `composition` / `color_palette` / `text_amount` を「今回の勝ちパターン」として表示する。

`performed_same` / `inconclusive` は勝ちパターンなしとして表示し、次回 `/thumbnail` の強い方針には含めない。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| A/B test が表示されない | Studio の Thumbnail 欄に入口がない | desktop Studio、advanced features、動画の eligibility を `references/operator-guide.md` で再確認 |
| テスト実行中 | Reach に進行中レポートがある | 推測記録せず、完了後に再実行 |
| active design 不整合 | ファイル欠落、`video_id` または SHA-256 不一致、構造検証が非0 | active design と履歴を変更せず、Studio に渡した候補ファイルを復元して全検証後に再実行 |
| 候補不足 | 対象画像が 0〜1 枚、または 320x180 判定後に 1 枚以下 | `/thumbnail` で差分のある候補を追加 |
| JSON 不正 | `jq empty` または構造検証が非0 | 記録前の内容を維持し、不足・型違反・重複 entry を修正して再検証 |
