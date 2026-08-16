# Music generate mode

## エンジン自動分岐

対象 collection を確定したら、`config/channel/youtube.json::music_engine` を最初に読み、値を一度だけ解決する。

| `music_engine` | 実行経路 | 完了成果物 |
|---|---|---|
| `suno` | 下記 Suno 経路。collection server を起動または再利用し、Chrome 拡張で連続生成・playlist 追加・一括 download を行う | `02-Individual-music/` と strict 6 点 |
| `lyria` | 下記 Lyria 経路。Vertex AI Lyria 3 でセグメント生成・結合を行う | `01-master/master.mp3` |
| `minimax` | 下記 MiniMax 経路。MiniMax Music でインスト segment生成・結合を行う | `01-master/master.mp3` |

値が `suno` / `lyria` / `minimax` 以外、または未設定なら設定不整合として停止する。利用者に別 engine の skill を案内せず、同じ `/music --generate` の入口で自動分岐する。

## MiniMax 経路

`music_engine: minimax` では `.claude/skills/music/config.default.yaml::generate.minimax` と `config/skills/music.yaml::generate.minimax` を deep-merge する。対象 collection のテーマ、creative constraints、採用済み方向性から instrumental style prompt と filename slug を決め、生成回数と model を提示して generation approval を得た後、次を実行する。

```bash
uv run yt-generate-minimax-master \
  --prompt "<instrumental style prompt>" \
  --name "<slug>" \
  --target-duration <minutes> \
  --model <music-3.0|music-2.6> \
  --padding-min <minutes> \
  --collection <collection-path>
```

CLI は1 segmentを最大300秒として必要数を算出し、MiniMax Musicの `output_format: hex` / `is_instrumental: true` で逐次生成する。成功ごとに `data/audio_costs.json` へ `unit: song` を記録し、`02-Individual-music/<NN>_<slug>.mp3` をresume可能に保存する。全segmentが揃った場合だけ既存 `generate_master.generate_master()` へ渡し、`01-master/master.mp3` を生成する。中断時の支払い済みaudioは `tmp/minimax-recovered/<sha256>.mp3` へ退避する。

完了条件は `01-master/master.mp3` が非空で、実行時に新規生成したsegment数と同数の `unit: song` cost entryが残ること。失敗時は既存segmentを保持し、同じcommandの再実行で未生成分から再開する。

Suno 経路の server lifecycle は `.claude/skills/extension/references/serve.md` をファイル参照で読み、`--suno` の起動・既存 server 再利用・疎通確認・停止契約をそのまま実行する。`/extension` へ委譲せず、このファイルの手順を複製しない。

## Suno 経路


## 前後工程

- `前工程`: `/wf-new`, `/music --prompt`, `/wf-new`
- `後工程`: `/music --master`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/02-Individual-music/*.mp3`, `collections/<id>/workflow-state.json`
- `読み込む`: `collections/<id>/20-documentation/suno-prompts.json`, `config/skills/suno-helper.yaml`, `config/skills/music.yaml::prompt`

## Overview

`<CHANNEL_DIR>/collections/planning/<theme>-collection/` の `suno-prompts.json` を `uv run yt-collection-serve` で配信し、Chrome 拡張 **suno-helper** が Suno (suno.com/create) タブ上で各 pattern の Style/Lyrics 注入 → Generate → 完了待ち → 次の pattern、を自動反復する。全件完了後に clip を一括選択 → Cmd+P → Add to Playlist dialog → 自動 playlist 化 → ZIP 一括ダウンロードまで進める。

suno-helper は生成 → playlist 追加 → 一括ダウンロードまでを 1 タブで完結させるため、`/music --master` の DL ステップ（Step 2-3）は原則スキップされる。
新規 collection を `/wf-new` から開始した直後は、`/wf-new` が `uv run yt-collection-serve` の起動と疎通確認まで完了している場合がある。その場合、本スキルは既存 server を再利用し、browser use で Suno タブ上の suno-helper overlay を操作する。

## 完了条件

overlay の phase が `finished` に到達し、Step 6 の 6 点（playlist 紐付け / clip 数 = entry 数 × 2 / `02-Individual-music/` への音声配置 / `status = downloaded` / `suno_playlist_url` 記録 / `assets.music_downloaded = true`）を確認後、collection server を停止してプロセスが残っていないとき strict 完了とする（詳細は Step 6 が正）。`finished` は download 通知の終端成功を示し、1 件以上配置できた部分成功も含むため、それだけで strict 完了とは判定しない。異常値再生成を OFF にした run は、さらに duration guard NG の clip を試聴し、NG clip が ZIP に含まれることを確認してから完了とする。`entry-failed`、clip 数不足、server プロセス残留のいずれかがある場合は完了扱いにしない。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/music/config.default.yaml::generate.suno`
2. `config/skills/suno-helper.yaml`（存在する場合）

読み込み後は `youtube_automation.configuration.skills.load_skill_config("suno-helper")` と同じ deep-merge 前提でチャンネル上書きを優先する。存在しない override は未設定として扱い、勝手に作成しない。`unattended` の値は定期実行 URL の既定にだけ使い、手動 overlay の Balanced preset は変更しない。

## When to Use

- `/music --prompt` でプロンプトが揃い、Suno で実際に曲を生成したいとき
- ERROR で停止した collection を途中の entry から再開したいとき
- 「Suno で連続生成回して」「suno-helper で流して」「Suno に追加で N 曲生成して」と user が言ったとき

`/music --prompt` がプロンプト設計（YAML → suno-prompts.json）だけを担当し、本スキルが **ブラウザ実行** を担当する役割分担。

## 前提

- Chrome に unpacked の suno-helper 拡張がロード済み（拡張アイコンが popup を出す。ID 検出に失敗した場合のみ `--allow-origin` fallback で拡張 ID を手動指定する）
- Suno (suno.com/create) にログイン済み・**Advanced タブ**が選択されている
- Style 入力欄が出ていること。**Advanced → More options を開く → Lyrics mode → Write** の順に選ぶ。prompt entry の `lyrics` が非空なら、`[Instrumental]` だけのインストゥルメンタル entry でも Write が必須。suno-helper は Lyrics 欄へその値を注入して歌詞なしを指定するため、Lyrics 欄を隠す Instrumental mode では実行できない。`lyrics` が真に空の entry だけは Lyrics mode = Instrumental と Style 入力欄を使える
- automation リポジトリで `uv` が使える・`CHANNEL_DIR` 環境変数を当該チャンネルへ向けてある
- collection ディレクトリ名が **`*-collection` suffix** を持つ（dir mode 必須）。例: `20260201-soulful-grooves-rainy-night-soul-collection/`
- 7873 / 7874 など特定 port を既に他の collection で使っていないか確認（並走させる場合は明示的に分ける）

Chrome DevTools MCP は必須ではない。通常運用は browser use を primary path とし、DevTools MCP は DOM が見えない、拡張 overlay が応答しない、または debugger attach 競合を切り分ける場合の診断・補助・フォールバックに限る。`chrome.debugger` 権限は拡張内部が Cmd+P の trusted key event を送るための実装権限であり、agent が DevTools MCP を常時起動する前提ではない。

## Quick Reference

| 役割 | コマンド |
|---|---|
| サーバー起動・再利用・停止 | `.claude/skills/extension/references/serve.md` の `--suno` 契約 |
| 拡張 ID 手動指定（検出失敗時のみ） | `--allow-origin "chrome-extension://<EXTENSION_ID>"` |
| ポート変更（並走時） | 末尾に `--port 7874` |
| 拡張をリロード | chrome://extensions → suno-helper の再読み込みアイコン |
| Suno タブ | https://suno.com/create にアクセス、Advanced タブを選択 |
| agent 主経路 | browser use で Suno タブを開き、ページ内 overlay の `data-suno-*` signal と表示文言を観測 |
| 定期実行 URL | `uv run yt-suno-unattended-request --base-url <URL> --collection-id <ID>` |

## Instructions

### Step 1. サーバーを起動または再利用する

`.claude/skills/extension/references/serve.md` を読み、`--suno` の起動・既存 server 再利用・疎通確認契約を実行する。server lifecycle のコマンドや判定は本 skill に複製しない。返された実 URL / port / detected origin を後続 Step で使う。

### Agent primary flow: browser use で操作する

1. browser use で `https://suno.com/create` を開く。
2. ログイン済みで **Advanced → More options を開く → Lyrics mode → Write** の順に選び、Style / Lyrics 入力欄が見えることを確認する。prompt entry の `lyrics` が非空なら、`[Instrumental]` だけでも suno-helper が Lyrics 欄へ注入するため Write が必須。`lyrics` が真に空の entry だけは Lyrics mode = Instrumental と Style 入力欄を使える。ログイン画面、CAPTCHA、Advanced タブ不在なら下記 handoff 条件に従い停止する。
3. 拡張アイコンをクリックして suno-helper overlay を Suno タブ内に表示する。overlay が最小化されている場合はヘッダーの展開ボタンを押す。
4. overlay ルート `[data-suno-helper="control-panel"]` を観測する。`data-suno-phase`、`data-suno-running`、`data-suno-error`、`data-suno-collection-id`、`data-suno-entry-count`、`data-suno-selected-entry-count` が browser use から読める。
5. `[data-suno-control="server-source-trigger"]` を押し、更新後に表示される `role="option"` から Step 1 で確認した URL の配信元候補を選ぶ。
6. `[data-suno-control="collection-select"]` で対象 collection を選ぶ。選択後、Playlist 名が表示されること、`data-suno-collection-id` が対象 id になることを確認する。
7. 配信元または collection の選択後に自動取得が完了し、`role="status"` の live region が `N パターンを取得しました。` になること、`data-suno-entry-count` が 1 以上で `[data-suno-entry-list]` に entry 行が並ぶことを確認する。配信元候補は selector を開き、候補更新後に表示された対象を選択する。実行前に overlay 自体が更新されない場合だけページを再読み込みし、手順 3 からやり直す。
8. 必要な entry だけを checkbox で残す。各行は `data-suno-entry-index` / `data-suno-entry-state` / `data-suno-entry-selected` を持つ。通常は全選択のままにする。
9. preset と DL 形式を確認し、`[data-suno-control="run"]`（表示文言: 全パターンを連続実行 / 選択したN件を連続実行）を押す。
10. 実行中は Suno タブを reload / close せず、overlay の `data-suno-phase` と `role="status"` を監視する。agent は `finished` / `stopped` / `error` の終端 phase まで待つ。非終端 phase が変化しない場合は下記「無限待機を避ける監視ルール」で判断する。

Chrome 拡張 popup が別ウィンドウとして開く環境でも、操作対象と確認項目は同じ。Suno タブ上に overlay が出る場合は overlay を優先し、popup しか使えない場合だけ同じラベル・ボタン文言で操作する。

### 定期実行 flow（scheduler / `/wf-next` からの再開）

対象が `assets.music_prompts = true`、`assets.music_downloaded != true` の Suno collection なら、server を Step 1 の契約で起動し、次の CLI が出力する URL を既ログイン Chrome で開く。上限既定は `.claude/skills/music/config.default.yaml::generate.suno.unattended`、チャンネル override は `config/skills/suno-helper.yaml` で deep-merge する。

```bash
uv run yt-suno-unattended-request \
  --base-url http://<channel>.localhost:7873 \
  --collection-id <collection-id>
```

必要な場合だけ `--entry-index`（0-based、複数可）、`--download-format mp3|m4a|wav`、`--max-entries`、`--max-concurrent-generations`、`--max-retries` を上書きする。同じ collection の resume state があれば未完了 entry / playlist / download から再開し、1 run の上限を超えた entry は次回へ繰り越す。既存 playlist の clip ID が失われている場合は新規生成しない。

ログイン、CAPTCHA、料金・credit 確認、Suno UI 非互換では `manual-intervention` を保存して停止する。Suno ページ root の `data-suno-unattended-collection-id` が対象と一致することを確認し、`data-suno-unattended-status` / `data-suno-unattended-checkpoint` / `data-suno-unattended-stop-reason` / `data-suno-unattended-required-action` を監視する。`manual-intervention` を検知した agent は自動クリックや追加購入で突破せず、人へ handoff する。完了判定は手動 flow と同じ Step 6 の 6 点であり、extension storage の `completed` だけでは `/music --master` へ進めない。

### Step 2. overlay / popup を開く

browser use で Suno タブを前面にし、拡張アイコンをクリックして overlay / popup を出す。確認・操作する項目:

| 項目 | 必須 | 説明 |
|---|---|---|
| ローカル配信元 | 必須 | 固定 registry から動的検出した稼働中候補を選ぶ。`http://youtube-automation.localhost:7873` は常に表示 |
| Collection 選択 | 必須 | ドロップダウンから対象 collection を選ぶ。選択した瞬間に下に "Playlist 名" が auto derive される |
| 前回中断の resume バナー | entry phase の ERROR / STOPPED 後 24h 以内 | "再開" を押すと保存済み entry から直接再開する。不要なら "閉じる" |
| Entry 選択 | 任意 | prompts 自動取得後の checkbox で実行対象を選ぶ。全選択なら全実行、不要 entry はチェック OFF |
| DL 形式 | 任意 | ZIP 内の音声形式。デフォルト MP3。MP3 / M4A / WAV から選択 |
| 自動取得 | 初回表示・配信元選択・collection 選択 | サーバーから prompts JSON を fetch。配信元候補は selector を開く操作で再検出し、更新完了後に選択肢を表示 |
| 連続実行 | 実行時 | 開始 |
| 停止 | 実行中のみ有効 | 任意中断 |

agent が優先して使う DOM signal:

| signal | 意味 |
|---|---|
| `[data-suno-helper="control-panel"]` | suno-helper 操作 panel の root |
| `data-suno-phase` | 現在 phase（`idle` / `loading` / `starting` / 下表の progress phase / `adopting`） |
| `data-suno-running` | 実行中なら `"true"` |
| `data-suno-error` | エラー表示中なら `"true"` |
| `data-suno-collection-id` | 選択中 collection id |
| `data-suno-entry-count` | 読み込まれた entry 数 |
| `data-suno-selected-entry-count` | 実行対象として選択されている entry 数 |
| `role="status"` + `data-suno-status` | 人間向け状態文言。`data-suno-status="error"` なら handoff 判断へ進む |
| `[data-suno-entry-index]` | entry 行。`data-suno-entry-state` と `data-suno-entry-selected` で個別状態を読む |
| `[data-suno-control="server-source-trigger"]` | ローカル配信元の動的検出を開始し、候補 listbox を開く |
| `role="option"` / `[data-suno-control="collection-select"]` | 動的検出したローカル配信元の選択 / collection 選択 |
| `[data-suno-control="run"]` / `[data-suno-control="stop"]` | 連続実行 / 停止 |
| `[data-suno-control="resume"]` / `[data-suno-control="dismiss-resume"]` | 前回中断 resume バナーの再開 / 閉じる |
| `[data-suno-control="adopt-selected-clips"]` | Suno 上の選択中 clip を採用 |
| `[data-suno-control="retry-playlist"]` / `[data-suno-control="retry-download"]` | playlist / download phase から再開 |

### Step 3. 実行対象を決める

- 通常は全 checkbox ON のままでよい（全パターン実行）
- 生成しない entry がある場合だけ checkbox を OFF にする
- 全 checkbox OFF では実行できない。少なくとも 1 件を選ぶ
- entry phase の ERROR / STOPPED から再開する場合は resume バナーの "再開" を押す。playlist / download phase の中断は **Playlist から再開** / **Download から再開** を使う
- prompts の自動取得後に **異常値の曲を再生成する** を選ぶ。通常は既定 ON（duration guard NG の entry を最大 2 回再生成）。追加生成を避ける運用では OFF にし、NG を含む生成済み全 clip が playlist / download 候補に残ることを了承して進む
- duration guard の閾値は `suno-prompts.json` の `duration_filter`（既定 60〜300 秒）を使う。長尺 BGM チャンネル等で範囲を変える場合はチャンネル側 `config/skills/music.yaml::prompt.duration_filter` を override して `uv run yt-generate-suno` で再生成する（`/music --prompt` SKILL.md Step 2 参照）。resume は run 開始時点の閾値を保持するため、閾値変更を効かせるには再開ではなく新規 run で実行する

### Step 4. "連続実行" を押す

開始後、popup を閉じても処理は継続する（Suno タブが content script を保持する）。ただし以下は禁止:

- 進行中の Suno タブを reload / close しない
- 同タブで他の操作（曲再生 / 検索）を入れない
- Chrome を強制終了しない

### Step 5. 進捗 phase を読む

overlay / popup 上部の live region と root の `data-suno-phase` に進捗が出る:

| phase | 意味 |
|---|---|
| `injecting` | Style/Lyrics を当該 entry に注入中 |
| `generating` | Generate 押下後、Suno の生成完了待ち（最大 3 分） |
| `waiting-generation` | Generate 投入後、生成完了の検知待ち |
| `waiting-captcha` | CAPTCHA / bot check の解消待ち。多くは自動 verify 後に `generating` へ戻る |
| `waiting-slot` | Suno のキュー上限に達した。空きスロット待ち（in-flight 変化があれば継続）|
| `submitted` | 高速モード（内部値: queue）のみ。投入 ACK 済み・生成未完了（琥珀色）。全 entry 投入後の完了待ちで `done` へ遷移 |
| `done` | 当該 entry 完了、次へ進む |
| `entry-failed` | 当該 entry は失敗としてスキップし、run 全体は次 entry へ継続 |
| `adding-to-playlist` | 全 entry 完了、clip を一括 playlist 化中 |
| `downloading` | playlist 追加完了後、全 clip を ZIP 一括ダウンロード中 |
| `placing-archive` | browser download 完了後、server が ZIP を検証・配置中 |
| `finished` | DL 通知成功。`placed > 0` なら部分配置も終端成功とし、status に配置数 / 期待数 / 欠損数と `missing_reasons` の内訳を表示 |
| `stopped` | user が停止ボタンで中断 |
| `error` | server reject を含む失敗（赤色で停止）。`placed = 0` は成功へ縮退せずこの phase |

**phase 遷移の詳細**: `done`（最終 entry）→ `adding-to-playlist` → `downloading` → `finished`。playlist 追加完了直後に `postDownloaded(file_count: 0)` を呼んで playlist URL のみをサーバーに記録し、ZIP ダウンロード完了後に `postDownloaded(file_count: N)` で実ファイル数を報告する。後者の server 応答で `placed > 0` なら期待数未満でも `finished` へ進み、status は `完了 (placed/expected clip 配置, missing clip 欠損 — 内訳: Suno 未生成 N / 配置 skip N)` を表示する。ZIP からの `placed = 0` は server が reject し、拡張は `error` のまま resume state を保持する。

無限待機を避ける監視ルール:

- `loading` が 30 秒以上続く、または `role="status"` に `取得失敗` が出た場合: server URL、`GET /collections`、`GET /auth/token` を再確認する。改善しなければ handoff。
- `starting` が 30 秒以上続く、または `開始失敗` が出た場合: Suno タブで Advanced タブが選択されているか、拡張リロード後にタブをハードリロードしたか確認する。改善しなければ handoff。
- `waiting-captcha` は自動 verify されることがあるため待つ。ただし 10 分以上変化しない、または CAPTCHA が明示表示されている場合は user に手動解決を依頼して停止する。
- `waiting-slot` は queue 空き待ちの正常 phase。overlay の status が更新される限り待つ。10 分以上 in-flight 集合が変化しない場合は拡張が `error` に遷移するため、agent は独自に再クリックせず error 文言を読む。
- `entry-failed` は run 全体は継続中。`finished` が一部失敗を示した場合は「失敗分のみ再実行」を提案し、自動で無限再試行しない。
- status に `duration guard NG` と `再生成 OFF` が出た場合は run を継続する。対象 clip は除外されず playlist / download 候補に残るため、entry 名と NG 理由を完了確認へ引き継ぐ。
- `adding-to-playlist` / `downloading` が 10 分以上無変化なら overlay の status、Downloads、server log を確認し、同じ操作を連打しない。`error` になったら resume / retry ボタンで再開するか handoff する。

handoff 条件（agent は自動突破しない）:

- Suno ログインが必要、または account / payment / token 消費に関わる確認が出ている
- CAPTCHA / reCAPTCHA / hCaptcha が表示され、手動解決が必要
- suno-helper 拡張がロードされていない、overlay / popup が開かない、または `data-suno-helper="control-panel"` が見つからない
- server 接続失敗、`/collections` が 404、`/auth/token` が 403、または origin lock の拡張 ID が不明
- Generate ボタン、Advanced タブ、または prompt entry の `lyrics` が非空のときの Style / Lyrics 欄・空のインストゥルメンタル entry の Style 欄が見つからない
- 生成が `stopped` になった、または `error` になり原因文言の対応が必要
- playlist 追加失敗、Add to Playlist dialog が見つからない、multi-select 数が合わない
- ZIP ダウンロードが失敗、Downloads 権限・保存先・ZIP 展開で確認が必要

### Step 6. 完了確認

`finished` 表示後、以下を確認:

最初に、overlay の `role="status"` に保持された server 応答 summary、`workflow-state.json`、`02-Individual-music/` の実ファイルを照合する。server 応答の `placed_count` / `expected_file_count` / `missing_file_count` は、それぞれ実ファイル数 / `planning.music.actual_file_count`、`planning.music.expected_file_count`、`planning.music.missing_file_count` と一致すること。部分配置では `planning.music.missing_reasons` の `suno_unfulfilled` / `apply_skipped` が status の「Suno 未生成」/「配置 skip」と一致し、`suno_unfulfilled + apply_skipped = missing_file_count` であること。不一致なら成功表示のまま進めず、server log と配置 skip を調査する。

1. Suno 側で対象 playlist に collection の全 clip が紐付いている
2. clip 数 = collection の entry 数 × 2（数が合わなければ resume で残りを回す）
3. `02-Individual-music/` に mp3/m4a/wav が配置されている
4. `GET /collections` で対象 collection の `status` が `downloaded`、`downloaded_count` が期待 clip 数以上になっている
5. `workflow-state.json` の `planning.music.suno_playlist_url` に playlist URL が記録されている
6. `workflow-state.json` の `assets.music_downloaded` が `true` になっている（DL 完了時）

`placed_count > 0` かつ `missing_file_count > 0` の partial FINISHED は download 通知としては成功だが、strict 完了ではない。`status = downloaded` や `assets.music_downloaded = true` だけを根拠に `/music --master` へ進めない。不足分の再実行または手動解決を行い、上記 6 点と `missing_file_count = 0` が揃ってから後工程へ進む。

**異常値の曲を再生成する** を OFF にした場合は、上記に加えて status / console warning で記録された duration guard NG の clip を playlist 上で試聴し、手動採否を確認する。NG clip も意図どおり ZIP に含まれていることを確認してから完了とする。

音声配置と `workflow-state.json` 更新の両方に成功した後、ユーザーの Downloads 配下にある Suno ZIP は自動削除される。削除に失敗しても配置済み音声と workflow-state は維持され、警告が記録される。完了判定は ZIP の存在ではなく、展開済み音声ファイルと `workflow-state.json` を見る。

上記 6 点を確認したら、`.claude/skills/extension/references/serve.md` の停止契約を、起動時に記録した実 port へ適用する。対象 process が残る場合は完了扱いにしない。

### Step 7. 中断時

- **entry phase の任意停止 / ERROR**（`stopped` / `error`）: 24h 以内なら次回 popup 起動時に resume バナーが出る。"再開" で保存した entry から再実行し、元 run の異常値再生成 option も引き継ぐ
- **playlist / download phase の任意停止 / ERROR**: resume バナーは出ない。**Playlist から再開** / **Download から再開** を使い、元 run の異常値再生成 option と警告を引き継ぐ
- ERROR 文言の代表例（いずれも fail-loud で停止する）:
  - `Lyrics mode が Instrumental になっています。Write に切り替えてください。` が出たら、前提条件の **Advanced → More options → Lyrics mode → Write** をやり直す。`[Instrumental]` も Lyrics 欄へ注入する値なので Write が必要
  - `Create form mode が Simple になっています。Advanced タブを選択してください。`
  - 状態を特定できない場合は Advanced タブ / Lyrics mode = Write / UI 言語（英語推奨）のチェックリストを表示する
  - `reCAPTCHA を検知しました。手動で解決してから再開してください。`
  - `Clip multi-select verification failed: expected N selected, got M`
  - `中断: Add to Playlist dialog を検出できませんでした。clip が selected 状態であることを確認してください。Suno の UI 変更の可能性があります。`

## 一括ダウンロード

playlist 追加が完了すると、拡張が全 clip を multi-select して "Download all" から ZIP を取得し、
`POST /collections/<id>/downloaded` でサーバーへ報告する。DL 形式は popup の "DL 形式"
（`chrome.storage` の `sunoDownloadFormat`、既定 `mp3`）。

DL が止まる・形式が違う・`workflow-state.json` へ反映されない場合は
[references/download-flow.md](download-flow.md) を読む。POST は冪等なので再開時の再送は安全。

## Gotchas

- **origin lock 無しで起動すると token 取得と DL 完了 POST が 403 になる**。検出と fallback は `extension/references/serve.md` の `--suno` 契約を使う。
- **誤って single file mode で起動すると playlist phase がスキップされる**。`/collections` 404 が返り、popup 側で derivedPlaylistName が undefined になり playlist phase に分岐しない。Step 1 の `curl /collections` 確認を必ず通すこと。
- **Advanced → More options → Lyrics mode を毎回確認**。prompt entry の `lyrics` が非空なら、`[Instrumental]` を含め Write と Style / Lyrics 欄を使う。`lyrics` が真に空の entry だけは Instrumental と Style 欄を使える。Suno が UI 状態を覚えていないことがあり、`lyrics` が非空の entry で Lyrics 欄が消えていると Step 5 開始直後に ERROR で止まる。
- **Cmd+P を手動で押す必要はない**。拡張は background script から `chrome.debugger` の `Input.dispatchKeyEvent` で trusted key event を送る。dispatchEvent では Suno listener に届かない（isTrusted=false）ため、user 側で打鍵してはいけない（衝突する）。失敗時は拡張 manifest の `debugger` 権限、対象 Suno tab への attach 失敗、DevTools/別 debugger の競合を確認する。
- **dir 名規約は `<YYYYMMDD>-<channel>-<theme>-collection`**。拡張が dir 名の `<channel>` と collection name の `<theme>` から playlist 名（`<channel> | <theme>`）を導出する。独自規約で切ると playlist 名が壊れる。
- **7873 / 7874 を並走させる場合は明示的に port を分ける**。両方を 7873 で立てると後者が起動失敗するので、必ず `--port` を指定して popup のローカル配信元を選び直す。
- `yt-collection-serve collections/planning --port 49152` の稼働情報は `http://localhost:7872/.well-known/yt-collection-serve` から動的検出する。selector を開く操作で更新し、更新完了後に選択肢を表示する。`http://youtube-automation.localhost:7873` は常に表示される。
- **下流チャンネルの venv が古いと `/collections` の status / count 契約が古い場合がある**。automation リポに機能追加した後は下流で `uv lock --upgrade-package youtube-channels-automation && uv sync` を実行し、サーバーを再起動する。Step 1 の確認で検出できる。
- **playlist URL が記録されない場合**: (1) `/auth/token` が 200 を返すか、(2) popup の対象 collection が正しいか、(3) `POST /collections/<id>/downloaded` の 1 回目（`file_count: 0`）が 2xx で返っているかを確認する。
- **ZIP 展開後も downloaded にならない場合**: (1) Download all ZIP が完了しているか、(2) `download_path` が絶対パスで POST されているか、(3) ZIP 内音声数が `expected_file_count` 以上か、(4) `02-Individual-music/` に mp3/m4a/wav が配置されたかを確認する。

## Rules

- 必ず dir mode で起動する（single file mode は playlist phase がスキップされるため使わない）
- 進行中の Suno タブを reload / close しない
- popup の "ローカル配信元" を変える前に `curl <URL>/collections` が応答するか確認する
- ERROR で止まったら原因を見ずに即 resume しない（同じ entry で再失敗するので、文言で root cause を切り分ける）

## Cross References

- プロンプト生成: `/music --prompt`
- マスター化: `/music --master`（DL は本スキルが完了済みのため Step 2-3 スキップ）
- 拡張本体のコード: `extensions/suno-helper/` / `extensions/shared/`
- サーバー CLI: `src/youtube_automation/commands/collections/collection_serve.py`
- POST downloaded エンドポイント: `src/youtube_automation/commands/collections/collection_serve.py`
- 連続実行ペーシング定義: `extensions/shared/constants.ts::BALANCED_RUN_PACING`
- DL フォーマット storage key: `extensions/shared/constants.ts::sunoDownloadFormat`


## Lyria 経路


## 前後工程

- `前工程`: `/wf-new`, `/wf-next`
- `後工程`: `/video --generate`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `collections/<id>/20-documentation/lyria-prompt.json`, `collections/<id>/20-documentation/lyria-prompt.html`, `collections/<id>/01-master/master.mp3`, `collections/<id>/workflow-state.json`
- `読み込む`: `config/skills/lyria.yaml`, `config/channel/audio.json`, `config/channel/youtube.json`

## Overview

Vertex AI Lyria 3 REST API (`interactions` エンドポイント) を使い、`config/skills/lyria.yaml` のスタイル定義とユーザー指定テーマからプロンプトを組み立て、Lyria 3 API を呼んでマスター音源を生成する。

Lyria 3 Pro は **1 リクエストあたり最大約 184 秒（~3 分）** までのオーディオを返す。本スキルは `config/channel/audio.json` の `audio.target_duration_min` から必要セグメント数 N を自動算出し、`yt-generate-lyria-master` CLI 経由で N セグメント生成 → クロスフェード結合まで一気通貫で実行する（`generate_master.generate_master()` の WAV 経路を再利用）。

## 完了条件

`01-master/master.mp3` が生成され、`workflow-state.json` の `planning.music` / `assets.music_prompts = true` / `assets.raw_master` が更新されたとき完了とする（詳細は Step 5 が正）。`assets.master_audio` の確定と `phase: "mastered"` への遷移は `/wf-next` の責務で、本スキルには含まれない。

## Subagent Contract

- **入力**: 対象コレクション、テーマ、確定済み生成条件
- **成果物**: `01-master/master.mp3`、音楽プロンプト成果物
- **委譲しない処理**: `skip_generation_approval: false` のときの課金承認と候補選択。メインが確定してから起動する（`true` なら保存済み生成条件を渡して起動できる）

subagent は `workflow-state.json` へ書き込まず `AskUserQuestion` を実行しない。承認が要る処理は、メインが承認を得るまで委譲しない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラー。成果物の存在検証と owner CLI 実行はメインが行う。

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/music/config.default.yaml::generate.lyria`
2. `config/skills/lyria.yaml`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("lyria")` と同じで、チャンネル上書きが優先される。存在しない override は未設定として扱い、勝手に作成しない。

## Lyria 前提

以下が揃っていること:

1. `config/channel/` が存在する（`config/channel/audio.json` の `audio.target_duration_min` を参照）
2. skill-config の `_disabled` が **false** であること（`config/skills/lyria.yaml` で上書きしない限り、配布された `config.default.yaml` の default `false` が使われる）
3. Vertex AI ADC 初期化済み（`gcloud auth application-default login` + `set-quota-project`）。Vertex AI interactions エンドポイントは ADC で呼び、project_id は ADC quota project から自動解決される（`GOOGLE_CLOUD_PROJECT` は任意で上書き可）

`config/skills/lyria.yaml` はオプション。`yt-skills sync` で配布される `config.default.yaml` がそのまま使われるため、default 動作で問題なければ作成不要。カスタマイズしたい場合のみ `config.default.yaml` をコピーして `config/skills/lyria.yaml` に置き、必要な値だけ上書きする（deep-merge される）。

不足する場合、ユーザーに確認:
- **`config/channel/` が無い新規チャンネル** → `/setup --channel` を案内
- **`config/channel/` が無い既存チャンネル** → `/setup --import` を案内
- **`_disabled: true` のチャンネル** → `/music --prompt` を案内して終了する（Lyria を使わない方針）

## When to Use

- 新コレクションのテーマが確定し、音楽を生成するとき
- `/music --prompt` + `/music --master` の代替として、API 完全自動の音楽生成を行いたいとき
- Lyria 3 API（最大 ~184 秒/リクエスト）でセグメントを複数取得して結合し、長尺マスター音源を作りたいとき

### 選択タイミング（どこで lyria が選ばれるか）

1. **チャンネルのデフォルト** — `/channel-strategy --direction`（方向性検討モード）で `suno` / `lyria` / `minimax` を検討 → `/setup --regenerate` が `config/channel/youtube.json` の `music_engine` に書き込む
2. **コレクション単位の上書き** — `/wf-new` の `yt-init-collection --music-engine lyria` でコレクション毎に上書き可能（省略時はチャンネル設定を継承）
3. **このスキルが呼ばれるとき** — `/wf-new` が `workflow-state.json` の `music_engine = "lyria"` を判定して `/music --generate` を自動実行する。手動で `/music --generate <theme>` を叩いた場合もこのスキルに入る

## Quick Reference

| コマンド | 説明 | 例 |
|---------|------|-----|
| `/music --generate <theme>` | プロンプト設計 + Lyria 3 API 呼び出し（N セグメント生成 + 結合） | `/music --generate rain-against-glass` |

### 引数の解釈

```
$ARGUMENTS
```

$ARGUMENTS → コレクションのテーマ指定

## Channel Adaptation

実行前に `config/skills/lyria.yaml` から base 設定を読み取り、テーマに最適化されたプロンプトを設計する。

| skill-config キー | 用途 |
|------------|------|
| `_disabled` | true なら /music --prompt を案内して終了 |
| `skip_generation_approval` | true なら保存済みプロンプト・パラメータの生成前承認だけを省略（既定 false） |
| `model` | 本生成モデル (`lyria-3-pro-preview`) |
| `prompt_prefix` | プロンプト先頭の共通ジャンル句 |
| `style_hints` | 補足スタイル句（optional） |
| `ng_words` | プロンプトに使用禁止の語（Claude がプロンプト設計時にチェック） |
| `duration_padding_min` | `audio.target_duration_min` に上乗せする余裕分（分）。`yt-generate-lyria-master` が `ceil((target + padding) * 60 / 184)` でセグメント数を算出する（上限 60 セグメント、超過時は clamp + warning） |
| `default_bpm` | チャンネル共通 BPM（generate_music() の `bpm` 引数に流用、個別上書き可） |
| `default_intensity` | チャンネル共通 intensity（generate_music() の `intensity` に流用、個別上書き可） |
| `default_mode` | チャンネル共通 mode（generate_music() の `mode` に流用、個別上書き可） |
| `default_reference_image` | チャンネル共通参照画像パス（generate_music() の `reference_image` に流用、個別上書き可） |

読み込み確認:

```bash
uv run python -c "from youtube_automation.configuration.skills import load_skill_config; import json; print(json.dumps(load_skill_config('lyria'), indent=2, ensure_ascii=False))"
```

`config/channel/audio.json` からは `audio.target_duration_min`（コレクション全体の基準長）のみ参照する。1 リクエストあたり ~184 秒の制約があるため、`yt-generate-lyria-master` がこの値と `duration_padding_min` から必要セグメント数 N を自動算出する。

## Advanced Parameters（Lyria 3 API 入力）

`lyria_client.generate_music()` は以下の構造化パラメータを受け取れる（1 リクエスト 1 セグメント返り）。

| キー | 型 | 説明 |
|------|-----|------|
| `prompt` | string | プロンプト本文。skill-config の `prompt_prefix` ＋ `style_hints` ＋ テーマに合わせた主役楽器・演奏指示で組み立てる |
| `model` | string | `lyria-3-pro-preview`（本生成）/ `lyria-3-clip-preview`（30 秒固定、通常は使わない） |
| `reference_image` | Path | 参照画像パス。textless 動画背景 / ビジュアル参照画像 `10-assets/main.png` を指せば音源の雰囲気が画像に寄る。対応形式: `.png`/`.jpg`/`.jpeg`/`.webp` |
| `bpm` | int | BPM。プロンプトに `", {bpm} BPM"` として自動合成される。目安 60-180 |
| `intensity` | `"low"` / `"medium"` / `"high"` | それぞれ `"mellow, low-energy"` / `"balanced, moderate energy"` / `"driving, high-energy"` に展開される |
| `mode` | `"instrumental"` / `"vocal"` | `instrumental` は末尾に `". Instrumental."` を付加、`vocal` は lyrics 未指定時のみ `". With vocals."` を付加 |
| `lyrics` | string | 歌詞。末尾に `". Lyrics: ..."` として合成される。`[Verse]` `[Chorus]` の section tag 使用可 |

**API 仕様上の注意**: Lyria 3 `interactions` で真の構造化入力は `reference_image` のみ。`bpm`/`intensity`/`mode`/`lyrics` は独立フィールドではなく、プロンプトテキストへの自然言語埋め込みとして送信される。

**duration の制約**: Lyria 3 Pro は 1 リクエスト ~184 秒が上限。長さはプロンプトのヒント扱いでぴったり一致せず、レスポンス全体をそのままクロスフェード結合する運用になる。N セグメント生成 → 結合は `yt-generate-lyria-master` が自動化する（後述 Step 4）。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| Vertex AI Lyria 3（yt-generate-lyria-master） | N call、N = ceil((audio.target_duration_min + duration_padding_min) × 60 / 184)（上限 60） | `audio.target_duration_min` / `--target-duration` / `--padding-min`。失敗時は `--max-retries`（既定 3）で最悪 N×4。既存セグメントは skip（resume）され再課金なし |

- 上限 / 承認: CLI 側に y/N プロンプトはないが、セグメント数は hard cap 60 で clamp + WARNING される。実行前に Step 3 のユーザー確認（承認ゲート）を必ず経る。

## Instructions

あなたは Lyria 3 音源生成のオーケストレーターです。
`config/skills/lyria.yaml` の値からプロンプトと API 入力パラメータを組み立て、`yt-generate-lyria-master` CLI に委譲して N セグメント生成 + クロスフェード結合を実行します。

`_disabled: true` の場合、以下を出力して終了:
> Lyria はこのチャンネルで無効化されています (`config/skills/lyria.yaml` の `_disabled: true`)。音楽生成は `/music --prompt <theme>` を使用してください。

### 対象テーマ

```
$ARGUMENTS
```

---

## Step 1: コレクションの特定

1. `collections/planning/` の `workflow-state.json` を検索
2. 該当テーマのコレクション、または `thumbnail-approved` フェーズのコレクションを対象
3. 複数ある場合はユーザーに選択を促す

## Step 2: プロンプト設計

### 設計原則

1. **prompt_prefix は最小限に**: `config/skills/lyria.yaml` の `prompt_prefix` をそのまま使用。楽器名・ムード語を追加しない
2. **プロンプトは「動作指示」で書く**: 状態描写ではなく、メロディの動き（wandering freely, phrases rising and falling）を指示する
3. **簡潔な修飾**: 形容詞は 1-2 個で十分
4. **禁止形容詞チェック**: `config/skills/lyria.yaml` の `ng_words` と `/music --prompt` 側 `references/suno-examples.md` の禁止形容詞リストに準拠

詳しい推奨値・NG パターンは `references/lyria-tuning-guide.md` を参照。

### プロンプト組み立て

最終的に `generate_music(prompt=..., ...)` に渡す文字列は以下のような構造で組み立てる:

```
{prompt_prefix}, {style_hints}, {主役楽器の演奏指示}, {テーマに沿った最小限の情景描写}
```

例（テーマ: `rain-against-glass`、skill-config の `prompt_prefix = "celtic folk only, clean dry recording, no pads"`）:

```
celtic folk only, clean dry recording, no pads, gentle melodic phrases rising and falling, solo fingerpicked acoustic guitar
```

### API 入力パラメータの確定

`skill-config` のチャンネル共通値（`default_bpm` / `default_intensity` / `default_mode` / `default_reference_image`）を初期値とし、テーマに応じて個別調整してから `yt-generate-lyria-master` のフラグに渡す。

- `reference_image`: コレクションの `10-assets/main.png`（存在すれば）
- `bpm`: テーマに沿った値（`default_bpm` を出発点）
- `intensity`: テーマに沿った値（`default_intensity` を出発点）
- `mode`: 通常 `instrumental`

## Step 3: 設定の書き出しとユーザー確認

1. 設計したプロンプトと API 入力パラメータを `music-prompt.schema.json` 準拠の未公開candidateに書き出す。`style` に最終prompt、`options` に model / reference_image / bpm / intensity / mode / duration / segment count、`track_role`、review結果、provenanceを保存する:
   - ヘッダー（Engine, Channel, Model）
   - 最終プロンプト本文
   - API 入力パラメータ（`reference_image` / `bpm` / `intensity` / `mode`）
   - `audio.target_duration_min`、`duration_padding_min`、算出したセグメント数（60 超過時は clamp 前後の値）
   - 設計上の意図（主役楽器、雰囲気、テーマとの関係）
   - 品質チェックリスト

2. deep-merge 後の `skip_generation_approval` で分岐する:
   - `false`（既定）: ユーザーにプロンプト・パラメータの確認を求める。Claude Code では AskUserQuestion で「この内容で生成する」「修正する」の明示 2 択を出す。AskUserQuestion 非対応環境（Codex 等）では同じ情報をテキストで提示し、明示承認まで Step 4 を実行しない
   - `true`: candidate保存と機械verify・semantic reviewを確認し、`music-prompt-documents.md` のwriterで `lyria-prompt.json` / `.html` を公開してから、同じ検証済みJSONのプロンプト・パラメータで確認なしに Step 4 へ進む。60 セグメント hard cap と warning は省略しない
3. `skip_generation_approval: false` で修正があればcandidateを編集し、機械verify→semantic review→pair公開を再実行する。Markdown/HTMLを入力にしない

## Step 4: 音楽生成 + マスター結合

ユーザー承認後、または `skip_generation_approval: true` で検証済み `lyria-prompt.json` / `.html` pairを確認後、JSONの `style` / `options` だけを `yt-generate-lyria-master` CLIへ渡す。MarkdownやHTMLをparseしない。CLI が以下を一気通貫で実行する:

1. `audio.target_duration_min` + skill-config `duration_padding_min` から必要セグメント数 N を自動算出（`ceil((target + padding) * 60 / 184)`）。上限は 60 セグメント（= Lyria API リクエスト数の hard cap）で、超過時は 60 に clamp して warning を stderr に出力する
2. `lyria_client.generate_music()` を N 回呼び、レスポンスを `02-Individual-music/{NN}_{name}.wav` に PCM s16le 48 kHz stereo で保存（既存ファイルは skip = resume 可能）
3. 失敗時は `--max-retries` 回までリトライ
4. 全セグメント揃ったら `generate_master.generate_master()` 経由でクロスフェード結合し `01-master/master.mp3` を出力（`masterup.audio.crossfade_duration` を参照）

```bash
uv run yt-generate-lyria-master \
  --prompt-document 20-documentation/lyria-prompt.json \
  --collection <collection-path>
```

主要フラグ:

| フラグ | 用途 |
|------|------|
| `--prompt-document` (必須) | 同 basename HTMLと対応する検証済み `lyria-prompt.json`。prompt/name/optionsをここから読む |
| `--max-retries N` | 1 セグメントあたりの失敗時リトライ回数（default: 3） |
| `--collection PATH` | コレクションディレクトリ（省略時は CWD） |

低水準の互換入口 `--prompt` / `--name` と個別option flagは既存呼出しのため残るが、skillの正規経路では使わない。新規実行は必ず `--prompt-document` を使い、JSONとCLI flagの二重正本を作らない。

> **認証**: Vertex AI は ADC を使う。project ID は ADC quota project（必要時のみ `GOOGLE_CLOUD_PROJECT` process env override）、location は Lyria 用にアプリが決定する。

**注意点**:
- Vertex AI の Lyria クォータ（プロジェクト単位）は有限。他チャンネルと同時に大量生成すると 429 エラーが発生する（クォータ管理・並列実行制御は本スキルの責務外）
- CLI は逐次実行のため、N セグメントの生成には `N × 約 30〜90 秒` 程度を要する
- フェーズ展開（セグメントごとにプロンプトを切り替える DJ 的展開）は本 CLI の責務外。同一プロンプトの N 回呼び出しに留める

## Step 4.1: ワークツリーからメインへのコピー

生成完了後、コレクションディレクトリから `worktree_sync.sh` を実行する。
ワークツリー検出・パス算出・コピーをすべて自動で行う（メインリポジトリで実行時は自動スキップ）。

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/music/references/worktree_sync.sh"
```

**コピー対象**:
- `01-master/master.mp3` → メインの `01-master/`
- `10-assets/main.png` → メインの `10-assets/`

事前確認には `--dry-run` を付ける。

## Step 5: owner CLI による完了時の更新

- 下記 `planning.music` object を JSON として `uv run yt-workflow-state --collection <collection-path> set-planning music <json-value>` へ渡す
- `uv run yt-workflow-state --collection <collection-path> set-asset music_prompts true` を実行する
- 生成されたマスター音源ファイル名（例: `master.mp3`）を JSON string として `set-asset raw_master <json-value>` へ渡す

最終マスター確定（`assets.master_audio`）と `phase: "mastered"` への遷移は、ユーザーがミキシング+マスタリングした最終ファイルを `01-master/` に配置した後に `/wf-next` が検出して更新する（本スキルの責務外）。

### planning.music スキーマ

`/audit --alignment` がコレクション横断で音楽 mood × サムネ × タイトルの整合を機械的に判定できるよう、上記 owner CLI に渡す `planning.music` object を組み立てる。新規制作分は必須。

```json
{
  "planning": {
    "music": {
      "engine": "lyria",
      "mood": ["meditative", "warm"],
      "atmosphere": "slow fingerpicked guitar in a quiet hall",
      "tempo": "slow",
      "instruments": ["fingerpicked guitar", "soft piano"],
      "exclude": ["orchestral", "synthesizer"]
    }
  }
}
```

**書き方ガイド**:

| フィールド | ソース | 補足 |
|-----------|--------|------|
| `engine` | 固定値 `"lyria"` | — |
| `mood` | `intensity` + `style_hints` + プロンプトから蒸留 | 感情語 1-3 個（例: `["meditative", "warm"]`）|
| `atmosphere` | プロンプトの世界観 1 文（`prompt_prefix` の意図 + 主役楽器の集約） | 個別 prompt をそのまま貼らず、コレクション全体を 1 文で言い切る |
| `tempo` | `bpm` から自然言語化 | `<60` → `very slow` / `60-79` → `slow` / `80-99` → `gentle` / `100-119` → `moderate` / `≥120` → `lively`。bpm 未指定なら `intensity` から（`low` → `slow` / `medium` → `moderate` / `high` → `lively`）|
| `instruments` | プロンプトの楽器名を集約（重複排除） | "solo fingerpicked guitar" → `fingerpicked guitar` のように楽器名のみ抽出。主役 3-5 個に絞る |
| `exclude` (optional) | `config/skills/lyria.yaml` の `ng_words` から**楽器系のみ** | `orchestral` / `synthesizer` / `ambient pads` 等。環境音系は対象外 |

**冪等性**: 既存値があっても `planning.music` 全体を上書きする（merge しない）。スキル再実行 = プロンプト設計やり直しと見なす。

---

## 品質チェック

プロンプトと API 入力パラメータの品質チェック:

- [ ] `prompt_prefix` が `config/skills/lyria.yaml` の `prompt_prefix` に基づいていること
- [ ] プロンプトに主役楽器の演奏指示が含まれていること
- [ ] `ng_words` に含まれる語がプロンプトに使われていないこと
- [ ] 環境音系の語（`rain beginning to tap` 等）が使用されていないこと
- [ ] `reference_image` を使う場合、コレクションの `10-assets/main.png` を指していること
- [ ] `bpm` を指定する場合は 60-180 の整数で、チャンネル audio config と整合していること
- [ ] `intensity` は `"low"` / `"medium"` / `"high"` のいずれかであること
- [ ] `mode` は `"instrumental"` / `"vocal"` のいずれかであること

## 所要時間と完了報告

`yt-generate-lyria-master` は Lyria 3 API を N セグメント分逐次呼び出し、最後にクロスフェード結合まで行うため **N × 30〜90 秒**（典型的にコレクション全体で 5〜20 分）。

ログを `/tmp/lyria-$(date +%s).log` へ redirect し、完了後は末尾から生成セグメント数と `01-master/master.mp3` のパスを報告する。429 / クォータエラーはそのエラー行を抜き出し、`--max-retries` の調整やリトライタイミングを提案する。background 実行フラグを持たない環境（Codex 等）では `nohup ... > <log> 2>&1 &` を使い、完了はログ末尾で確認する。

## オーディオビジュアライザー / オーバーレイ

`/music --generate` は**音源（WAV）を作る工程**で、映像オーバーレイ（ビジュアライザー・波形・購読ボタンポップアップ等）は扱わない。
ユーザーから「ビジュアライザー付きで」「波形を出して」等の指示があっても、`/music --generate` 段階では何も合成できない。

ビジュアライザー周りの現行仕様は `/video --generate` の「オーディオビジュアライザー / オーバーレイについて」節を参照。必要な場合は `/video --generate` 実行前に `config/channel/youtube.json::overlays.enabled: true` と overlay 詳細設定を用意する。
誤指示の事故防止のため、lyria 着手前に動画にオーバーレイが必要かをユーザーへ確認すること（#646 feedback）。

## Next Step

- `/video --generate` で動画生成を実行（WAV → MP4 変換は既存の generate_videos.sh を使用）
