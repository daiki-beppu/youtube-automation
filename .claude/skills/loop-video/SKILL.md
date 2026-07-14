---
name: loop-video
description: "Use when テキストなし main.png/jpg から Veo でループ動画背景を生成するとき。「ループ動画」「背景動画」「loop.mp4」で発動"
---

## Overview

Veo 3.1 API を使い、コレクションのテキストなし `main.png/jpg` から 8秒のシームレスループ動画を生成します。
生成された `loop.mp4` は `generate_videos.sh` が自動検出し、静止画の代わりに動画背景として使用します。

`thumbnail.jpg` は YouTube アップロード用のテキスト付きサムネイルであり、`/loop-video` の入力には使わない。`/thumbnail` で先に生成・承認したテキストなし `main.png` または `main.jpg` を入力にする。

## 完了条件

`10-assets/loop.mp4` が生成され、ユーザーの品質確認（「ステップ」5-6）を通過したとき完了とする。継ぎ目補正が必要になった場合は、`--smooth` 適用後の `loop.mp4` をユーザーが確認するまでを完了条件に含める。

## Subagent Contract

subagent として呼ぶ場合、メインエージェントは対象コレクション、入力 `10-assets/main.png/jpg`、確定済み mode と prompt をリポジトリルート相対パスまたは値で入力に含める。Veo 課金、再生成、品質確認の承認が必要なら、メインが承認を得るまで subagent を起動しない。subagent は `workflow-state.json` を読み書きせず、`AskUserQuestion` を実行しない。完了報告には `status: success | failure`、生成または補正した `10-assets/loop.mp4` の絶対パス、使用 mode、エラーを含める。メインはファイル存在を検証し、品質確認を担当する。直接実行時は既存手順を変更しない。

## 設定読み込みゲート

前提確認や Step 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/loop-video/config.default.yaml`
2. `config/skills/loop-video.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("loop-video")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

**ループ動画化の有効/無効**: skill-config の `enabled`（default `true`）で制御する。`config/skills/loop-video.yaml::enabled: false` のチャンネルでは本スキルは実行不可で、`yt-generate-loop-video` は fail-loud で停止する（Veo 課金を防ぐ）。この場合は `/thumbnail` で作成したテキストなし `main.png/jpg` を静止画背景として使う。サムネが完成済みでループ動画のリターンが Veo コストに見合わないチャンネルは `false` にする。

**バックアップ保持数**: 通常生成で既存 `loop.mp4` を `loop-v{n}.mp4` へ退避した後、skill-config の `max_backups`（default `3`）を超えた最古のバックアップを自動削除する。チャンネル別の保持数は `config/skills/loop-video.yaml::max_backups` で上書きできる。`--skip-existing` / `--smooth` 経路では退避も削除も行わない。

## Script

| スクリプト | 役割 | 場所 |
|-----------|------|------|
| `generate_loop_video.py` | テキストなし main.png/jpg → 8秒ループ動画 (Veo 3.1) | entry point: `uv run yt-generate-loop-video` |

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-generate-loop-video <collection-path> -y` | 指定コレクションでループ動画生成（既存 `loop.mp4` は `loop-v{n}.mp4` に退避し、`max_backups` 超過分を古い順に削除して **Veo 再課金**） |
| `uv run yt-generate-loop-video -y` | CWD のコレクションでループ動画生成 |
| `uv run yt-generate-loop-video <path> --skip-existing -y` | **既存 `loop.mp4` があれば Veo を叩かず skip して exit 0**（冪等再実行・再課金回避） |
| `uv run yt-generate-loop-video <path> --smooth -y` | **post-process 専用**: 既存 `loop.mp4` に FFmpeg クロスフェード補正のみ適用（**Veo を叩かない**） |
| `uv run yt-generate-loop-video <path> --motion-targets "leaves,steam" --static-targets "character,two animals (count remains 2)" -y` | 構造化プロンプトで生成（推奨） |
| `uv run yt-generate-loop-video <path> --prompt "..." -y` | カスタムプロンプトで全文上書き |

## 再実行時のコスト警告

**Veo 3.1 は課金 API**（モデルにより 1 本あたり数十円〜数百円）。デフォルト経路は **既存 `loop.mp4` を skip せず**、`loop-v{n}.mp4` に退避してから Veo を再度叩く（=フル再課金）。退避後のバックアップは `max_backups`（default `3`）まで保持し、超過分は最古から削除する。同じコレクションで `yt-generate-loop-video <path>` を素で繰り返すと、その回数だけ Veo クレジットが消費される点に注意。

### 既存 `loop.mp4` がある状態での挙動マトリクス

| コマンド | 既存 `loop.mp4` の扱い | Veo 呼び出し | FFmpeg post-process | 課金 |
|---|---|---|---|---|
| `yt-generate-loop-video <path> -y` （素） | `loop-v{n}.mp4` に退避し、保持上限超過分を削除 | **あり**（新規生成） | あり | **フル再課金** |
| `yt-generate-loop-video <path> --skip-existing -y` | 温存（退避なし） | なし（早期 exit 0） | なし | **0 円** |
| `yt-generate-loop-video <path> --smooth -y` | クロスフェード補正で in-place 更新 | なし（post-process 専用） | あり | **0 円** |
| `yt-generate-loop-video <path> --skip-existing --smooth -y` | `--smooth` が優先（明示アクション > no-op） | なし | あり | **0 円** |

既存ファイル不在で `--smooth` を指定した場合は `[ERROR] --smooth は既存 loop.mp4 を必要としますが見つかりません` で exit 1（fail-loud）。Veo を叩かずに失敗する。

### 運用ガイドライン

- **冪等再実行のデフォルト**: バッチや CI から繰り返し叩く経路では `--skip-existing` を必ず付ける。既存があれば 0 円で no-op、無ければ通常生成にフォールバック（ではなく early exit のため事前に生成済みの前提を明示）。
- **継ぎ目だけ直したいとき**: `--smooth` を **単独 mode** として使う。`/loop-video` で 1 度生成 → 品質確認 → 継ぎ目が気になる → `--smooth` 再実行、という二段運用にすれば Veo は 1 回しか叩かない。
- **本気で作り直したいとき**: 素の `yt-generate-loop-video <path> -y` を再実行。既存は `loop-v{n}.mp4` に自動退避され、`max_backups` まで保持される。ただし **必ず Veo 再課金が発生する**ので意図的に行うこと。

## Instructions

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合、そのコレクションを対象とします。
未指定の場合、`collections/planning/` から `thumbnail.approved = true` かつ `loop.mp4` が未生成のコレクションを自動検出します。

### 前提条件

- `10-assets/main.png` または `main.jpg` が存在すること（`/thumbnail` で先に生成・承認したテキストなし動画背景）
- `10-assets/thumbnail.jpg` ではなく、テキストなし `main.png/jpg` を入力にすること
- Vertex AI ADC が初期化されていること (`gcloud auth application-default login` + `set-quota-project`)。project_id は ADC quota project から自動解決される（`GOOGLE_CLOUD_PROJECT` は任意で上書き可）。region は `generate_loop_video.py` 側で `us-central1` を明示固定するため `GOOGLE_CLOUD_LOCATION` は不要

### ステップ

1. **有効/無効確認**: `config/skills/loop-video.yaml::enabled` を確認。`false` なら Veo を実行せず、`main.png/jpg` の静止画背景運用として終了する
2. **対象確認**: `10-assets/` にテキストなし `main.png` or `main.jpg` があることを確認。文字入り `thumbnail.jpg` しか無い場合は `/thumbnail` に戻って textless 背景を生成・承認する
3. **プロンプト検討**: シーンに応じた自然な動きを指定
   - デフォルトプロンプトは skill-config (`config/skills/loop-video.yaml` または `.claude/skills/loop-video/config.default.yaml`) の `veo.default_prompt` を使用
   - シーンに合わない場合は `--prompt` でカスタマイズ
4. **生成実行**: `uv run yt-generate-loop-video <collection-path> -y`
   - 冪等再実行が必要な場面（CI / バッチ / 「もう生成済みか分からない」ケース）では `--skip-existing` を付けて Veo 再課金を避ける
5. **品質確認**: ユーザーに `loop.mp4` を確認してもらう
6. **ループ確認**: 継ぎ目が気になる場合は **`--smooth` 単独 mode で再実行**（`uv run yt-generate-loop-video <path> --smooth -y`）。Veo は叩かず FFmpeg クロスフェード補正のみ適用するため **追加課金は発生しない**。`--smooth` は post-process 専用 mode で、生成と post-process は別コマンドとして 2 段に分かれている — 「再生成 + post-process」を 1 コマンドでまとめる API は **意図的に提供していない**（再生成は明示的なフル再課金イベントとして扱うため）

### 構造化プロンプト（推奨）

「動かす対象」と「固定対象」をリストで明示する方式。Veo 3.1 公式推奨のポジティブ表現テンプレートに展開される。`default_prompt` の単一文字列より事故率が低い（動物の数が変わる / 肩から鳥が湧く等の現象を抑制）。

**プロンプト解決の優先順位**:

| 順位 | 入力 | 用途 |
|---|---|---|
| 1 | `--prompt "..."` | 全文上書き（最強、structured 系は無視される） |
| 2 | `--motion-targets / --static-targets` | コレクション単位の都度上書き |
| 3 | skill-config の `motion_targets` / `static_targets` | チャンネル単位デフォルト |
| 4 | skill-config の `default_prompt` | freeform 上書き（後方互換） |
| 5 | ハードコード `DEFAULT_PROMPT` | 最終フォールバック |

**Veo 3.1 公式推奨**:
- **ポジティブ表現**で書く（"do not animate X" より "only Y moves, the rest remains exactly as in the source image"）
- **count / shape を肯定文で固定**: `"two animals (count remains 2)"`, `"the character (same posture)"` のように数や形を明示
- **微動語彙**: `subtle`, `gentle`, `slight`, `barely perceptible`, `slow sway`, `living painting`
- I2V は 50〜100 words が目安（テンプレが既に圧縮されている）

**動きの強度は motion_targets の文言のみで制御する**（issue #1747）:
- 既定 `prompt_template` は `{motion_clause}` に強度断定（`subtle` 等）を付加しない。強度語は motion_targets の各項目に含める
- 静かな動き: `subtle steam rising from coffee`, `gentle candle flame flicker` のように微動語彙を対象側に書く
- はっきりした動き: `clearly rolling ocean waves`, `steady rain falling` のように書けば、テンプレ側の弱化文言と矛盾せずそのまま効く

**動かす対象（motion_targets）の例**:
- `slow leaves swaying`, `gentle leaves fluttering`（屋外）
- `subtle steam rising from coffee`, `steam from mug`（カフェ/書斎）
- `gentle candle flame flicker`, `slow candle flicker`（室内）
- `slight character breathing`（人物のみ動かしたいとき）
- `soft light shifts on surfaces`（光のみ）
- `rain streaks on window`（雨シーン）
- `slow subtle ripples on water surface`（水辺）
- `subtle monitor glow shifts`（書斎・モニター）

**固定対象（static_targets）の例**:
- `the character (same posture, same expression)` — 人物の姿勢/表情固定
- `two animals (count remains 2)` — 動物の数固定
- `keyboard`, `monitor frame`, `books`, `desk objects` — オブジェクト固定
- `interior structure`, `background elements` — 背景固定
- `dessert plates`, `cups and saucers` — 小物固定

### チャンネル別 structured 設定例

`config/skills/loop-video.yaml` の上書き例:

**rjn（lo-fi jazz × rainy night）**:
```yaml
veo:
  motion_targets:
    - "rain streaks on window"
    - "subtle steam rising from coffee"
    - "soft light shifts on surfaces"
  static_targets:
    - "the character (same posture, same expression)"
    - "dessert plates and cups"
    - "interior structure"
```

**deepfocus365（deep focus × deep house）**:
```yaml
veo:
  motion_targets:
    - "subtle monitor screen glow shifts"
    - "slow steam from coffee mug"
    - "slight character breathing"
  static_targets:
    - "the character (same posture)"
    - "keyboard and monitor frame"
    - "books and desk objects"
```

**bobble（cafe ambience）**:
```yaml
veo:
  motion_targets:
    - "subtle steam from coffee"
    - "soft light shifts"
  static_targets:
    - "the character"
    - "cups, plates, and counter items"
```

### freeform プロンプトガイドライン（後方互換）

`default_prompt` を直接書く旧方式。structured が使えない場合のみ。

**基本テンプレート**:
```
Static scene with only natural subtle movements: [シーン固有の動き].
No smoke, no magical effects, no particles, no falling objects.
Keep the scene calm and grounded, like a living painting.
```

**避けるべき表現**:
- smoke, particles, falling leaves（不自然な追加要素が生成される）
- magical effects（原画にない要素が追加される）
- butterflies, insects（描画品質が低く不自然になる）
- dramatic movement（BGM チャンネルには過度な動き）

### サードパーティ IP ガードレール

Veo 3.1 は画像内容からディズニー等の IP を認識すると **生成をブロック** する。
PD（パブリックドメイン）の童話キャラでも、ディズニー版に似た見た目だと弾かれる。

| 画像タイプ | 結果 |
|-----------|------|
| オリジナルファンタジーキャラ | OK |
| PD 騎士・魔法使い（ジャンヌ・ダルク等） | OK |
| ラプンツェル（金髪ロングヘア+塔） | NG（Tangled 誤認） |
| 白雪姫風・人魚姫風 | 要テスト（NG の可能性あり） |

**ブロックされた場合の対策**:
- プロンプト変更では回避不可（画像自体が判定される）
- 背景のみの画像を別途生成して Veo に渡す
- または静止画背景のまま運用

### 設定

skill-config (`.claude/skills/loop-video/config.default.yaml`) で管理。チャンネル側上書きは `config/skills/loop-video.yaml`:

ループ動画化を停止したいチャンネルは 1 行で無効化できる:

```yaml
# config/skills/loop-video.yaml
enabled: false  # default: true。/loop-video は fail-loud 停止、/videoup は静止背景を使用
```

```yaml
veo:
  model: "veo-3.1-fast-generate-001"

  # structured prompt（推奨）
  motion_targets:
    - "slow leaves swaying"
    - "subtle steam rising from coffee"
  static_targets:
    - "the character"
    - "two animals (count remains 2)"

  # freeform プロンプト（後方互換、structured 未指定時のみ使用）
  default_prompt: |
    Static scene with only natural subtle movements...

  duration_seconds: 8
  crossfade_sec: 0.5
```

| 項目 | 既定 | 説明 |
|---|---|---|
| `enabled` | `true` | このチャンネルでループ動画化を行うか。`false` で CLI は fail-loud 停止（Veo 課金防止）、`/videoup` は静止画背景にフォールバック |
| `veo.model` | veo-3.1-fast-generate-001 | Veo API モデル（選択肢: veo-3.1-fast-generate-001 / veo-3.1-generate-001 / veo-3.1-lite-generate-preview） |
| `veo.motion_targets` | `[]` | 動かす対象のリスト。structured prompt に展開される |
| `veo.static_targets` | `[]` | 固定対象のリスト。count や shape を肯定文で書く |
| `veo.prompt_template` | 公式 5 要素テンプレ | `{motion_clause}` / `{static_clause}` / `{base_rules}` をプレースホルダに持つ。強度断定（subtle 等）は付加せず、強度は motion_targets の文言で制御（#1747） |
| `veo.base_rules` | アンビエンス固定文 | `{base_rules}` に差し込まれる共通追加ルール |
| `veo.default_prompt` | 汎用微動プロンプト | structured 未使用時の freeform プロンプト |
| `veo.duration_seconds` | 8 | 生成尺（Veo API 制約で 8 秒固定） |
| `veo.crossfade_sec` | 0.5 | FFmpeg ループ補正のクロスフェード秒数 |
| `compression.enabled` | `true` | Veo 出力直後に libx264 で再エンコードして容量削減（Issue #175）。`false` で完全 skip |
| `compression.crf` | 22 | H.264 CRF。22 で約 40% 削減、24 なら約 55% 削減（攻める設定） |
| `compression.preset` | slow | libx264 preset |

## Integration

`loop.mp4` が `10-assets/` に存在すると、`generate_videos.sh`（v14）が自動検出し、
静止画の代わりにループ動画を背景として使用します（24fps、CRF 22 で正規化）。

パイプラインは **Veo 生成 → strip_audio → CRF 圧縮**（`compression.enabled=true` のとき）。
`--smooth` 経路でも同じ crf/preset が適用されるため、`/loop-video` → `--smooth` のいずれの順でも
最終的な `loop.mp4` ビットレートは設定値（既定 CRF 22 ≒ 3〜4 Mbps）に揃う。

## 中断 (Ctrl+C) 時の挙動

`yt-generate-loop-video` の Veo 生成中に Ctrl+C を送ったときの挙動は、運用上以下の通り厳密に決まっている。**「中断 = キャンセル = 無料」ではない**ことに注意。

### 現状のコード挙動 (cancel API 未利用)

| フェーズ | Ctrl+C の効き | API 側 operation | クレジット消費 | 再開可否 |
|---|---|---|---|---|
| `client.models.generate_videos(...)` 送信中（submit 中） | ローカルプロセスは即停止 | submit が成立していれば API 側で開始済み | submit 後ならフル課金 | **不可**（operation_name を持たない） |
| polling 中（submit 済み、生成待ち） | ローカルプロセスは即停止 | **継続実行される**（cancel されない） | フル課金（中断しても止まらない） | **可**（同じ model・同じ入力画像なら、`<CHANNEL_DIR>/tmp/veo-operations/` に保存された operation_name を次回実行で resume） |
| polling 中の `operations.get` 一時障害 | 例外捕捉、state を保持 | API 側継続 | フル課金 | 可 |
| polling 中の `operations.get` で失効（404） | state を削除 | （失効済み） | 課金済み bytes は取りこぼし | 不可 |

ポイント:

- **Veo API には `operations.cancel` 相当が現状未実装** (`client.operations.cancel` は未提供)。本スキルの実装 (`utils/veo_generator.py`) も `KeyboardInterrupt` を捕捉してメッセージ表示と state 保存だけを行い、cancel API を呼んでいない。**Ctrl+C はあくまでローカルプロセスを止めるだけで、API 側のジョブとクレジット消費は止められない**。
- submit が成功した時点で課金は確定する想定で運用する。中断は「節約」にはならず、せいぜい「次回の二重課金を resume で防ぐ」効果しかない。
- 中断 → 同じ model・同じ入力画像で即再実行すれば、保存済み operation_name から resume して既課金分を回収できる（loop.mp4 を取り出せる）。**再課金は発生しない**。
- model または入力画像を変えて完全に作り直す場合は、state を手動削除する必要はない。次回 `yt-generate-loop-video` 実行時に自動で state を破棄して新規 submit する。

### 運用ガイドライン

- **submit 成功後の Ctrl+C は「無料化」ではなく「次回 resume の予約」と思え**。クレジット節約目的で中断してはいけない。
- 真に止めたい（誤プロンプトでの submit など）場合でも、submit が通った後は API 側のジョブを止める手段が（現状コードからは）ない。submit 前に prompt を確認すること。
- ループ動画化そのものを停止したいチャンネルは `config/skills/loop-video.yaml::enabled: false` で CLI ごと無効化する（`yt-generate-loop-video` が fail-loud で停止し、submit 自体が走らない）。
- 将来 Veo API が `operations.cancel` を公開し、本スキルの実装が対応した場合は、Ctrl+C で API 側 operation も cancel して以降のクレジット消費を停止する挙動に変わる予定。**現状はその段階に到達していない**ため、上記の「中断してもクレジットは消費される」前提で運用する。

### state ファイルの場所

- パス: `<CHANNEL_DIR>/tmp/veo-operations/<output-hash>.json`
- 中身: `{ "operation_name": "operations/...", "model": "veo-3.1-fast-generate-001", "output_path": "...", "input_image_sha256": "..." }`
- 再実行時は model と入力画像内容の SHA-256 が両方一致した state だけを resume する。不一致または旧形式の state は破棄して新規 submit する
- 再開不要なら手動削除可（次回実行は新規 submit になる）

## 長時間処理の取り扱い

`yt-generate-loop-video` は Veo 3.1 API を同期ポーリングするため **30〜90 秒** 程度（モデルとリージョン次第）かかる。**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。Codex など `run_in_background` 非対応の実行環境では、同コマンドを `nohup ... > <log> 2>&1 &` で background 起動し、完了はログ末尾で確認する読み替えとする。

spawn 例:

```bash
uv run yt-generate-loop-video <collection-path> -y > /tmp/loop-video-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ Veo 3.1 でループ動画を生成中（推定 30〜90 秒）。完了まで他の質問にもお答えできます。
> ログ: /tmp/loop-video-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "loop-video" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "loop-video"` + `cmux notify --title "loop-video 完了"` を呼ぶ（非 cmux 環境では skip）。

完了通知が届いたらログ末尾から結果サマリー（`10-assets/loop.mp4` のパス）をユーザーへ返す。`--smooth` 再実行時も同じパターンで起動する。IP ガードレールでブロックされた場合のエラーメッセージはログから抜き出して報告する。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| GCP ADC 未取得/失効 | `ConfigError` / ADC 認証エラー | `gcloud auth application-default login`（必要なら `set-quota-project`）を再実行 |
| Vertex AI rate | HTTP 429 | 時間を置いて再実行。並列実行を避け順次処理する |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud（Vertex AI）のステータスを確認し、時間を置いて再実行 |
| 生成の途中失敗（課金済み） | プロセス中断・IP ガードレールでブロック | コストは発生済み。`10-assets/loop.mp4` の生成有無を確認し、未生成ならコマンドを再実行 |

## Next Step

ループ動画生成後:
→ `/videoup <collection-path>` でマスター動画を生成

## 参考リンク

- [Ultimate prompting guide for Veo 3.1 (Google Cloud Blog)](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)
- [Veo prompt guide (Google DeepMind)](https://deepmind.google/models/veo/prompt-guide/)
