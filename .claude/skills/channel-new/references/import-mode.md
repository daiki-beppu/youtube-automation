# 既存チャンネル取り込みモード（取り込み Step 1〜8）

`/channel-new` 既存チャンネル取り込みモードの手順詳細。SKILL.md の「モード判別」で本モードと判定された場合に、このファイルの手順どおりに実行する。
本ファイル内の `references/...` は `.claude/skills/channel-new/references/...`（本ファイルと同じディレクトリ配下）を指す。

既に YouTube で運営中のチャンネルの情報をヒアリングし、`config/channel/*.json`（責務別分割、v2.0.0 以降）を生成して自動化システムに取り込む。

**実行場所**: `/setup` 完了後の channel repo ルート。新規開設モードと同じく、テンプレートリポジトリから clone せず今いるディレクトリを使う。

**リポジトリ準備**: `.git` がない場合は新規開設モードの Step 2（現在のディレクトリを repo 初期化）を実行する。automation パッケージ未導入・OAuth クライアント未配置など環境が未整備の場合は、新規開設モードの Step 3 と同じく `uv run yt-doctor --json` で状態を確認し、`/setup` を案内して完了させてから取り込み Step 1 前段へ進む。

## 取り込み Step 1 前段: 実績取得と方向性確認

YouTube チャンネル URL またはハンドル（例: `@channel-name`）を確認し、ベンチマーク設定を書き換えずにチャンネル実績を取得する:

```bash
uv run yt-channel-seed <URL/handle> --no-write-benchmark --json
```

JSON 結果から以下をユーザーに提示する:

- `subscribers`: 登録者数
- `total_videos`: 動画数
- `recent_titles`: 直近タイトル

固定閾値や件数による機械的な判定条件は設けず、次の観点を分けて評価する:

- `subscribers`: 現在の方向性で蓄積した視聴者基盤の規模。ただし、この値だけで成功・失敗を判定しない
- `total_videos`: 判断材料となる運用履歴の厚み。ただし、動画本数だけで継続・見直しを決めない
- `recent_titles`: 各タイトルを次の 4 観点で分類する
  - **ジャンル / 題材**: 音楽ジャンル、場所、季節、物語題材など、タイトルが明示している主題
  - **対象視聴者**: 初心者、学生、ゲーマーなど、タイトルが明示している視聴者
  - **用途**: 作業、勉強、睡眠、リラックスなど、タイトルが明示している利用目的
  - **タイトル形式**: `[用途] + [ジャンル]`、`[場所] | [用途]` など、語句の役割と並び順。固有語は役割名へ置き換えて比較する

`recent_titles` はタイトルごとに上記 4 観点の分類表を提示する。タイトル本文に根拠となる語がない観点は推測で補わず `不明` とし、明示された語から読み取れる反復、変化、混在を説明する。分類件数や多数決を結論条件には使わない。

`subscribers`、`total_videos`、`recent_titles` の全体を根拠とともに提示し、AI がその都度「既存の方向性を踏襲する / 方向性を見直す」の推奨を添える。各指標を単独の決定条件にせず、固定閾値や定型的な結論条件も設けない。CLI は YouTube API の `subscriberCount` が非公開または取得できない場合も `subscribers: 0` を出力し、実数の 0 と区別できないため、`0` を既知の視聴者基盤の規模として推奨に使わず、未知の値として判断材料不足を明記する。`recent_titles` が空の場合や、取得結果だけでは方向性を支持する根拠が不足する場合も、その不足を明示して推奨の確度を伝える。そのうえで AskUserQuestion により次のどちらで進めるか確認する:

1. **既存踏襲**: 取り込み Step 1〜8 を続行する
2. **方向性見直し**: 選択を作業メモに保持し、方向性検討へ移らず取り込み Step 1〜8 を先に完了する。取り込み完了後、Step 8 で方向性検討モードへの接続を案内する

## 取り込み Step 1: 基本情報のヒアリング

ユーザーに以下を確認する:

1. **チャンネル名**（表示名。Step 1 前段の取得結果を提示して確認する）
2. **短縮名**（3-4文字の略称、例: goa, rjn）

## 取り込み Step 2: ジャンル・世界観のヒアリング

以下を対話的に確認する:

- **ジャンル** (`genre.primary`): 「どんなジャンルのチャンネルですか？」（例: Celtic, Lo-Fi, Jazz, Ambient）
- **スタイル** (`genre.style`): 「スタイルをもう少し具体的に」（例: Fantasy, Smooth, Chill）
- **コンテキスト** (`genre.context`): 「どんな世界観・文脈ですか？」（例: RPG Adventure, Rainy Night Cafe）
- **コアメッセージ** (`channel.core_message`): 「チャンネルが届けたい価値は？」

## 取り込み Step 3: コンテンツ設定のヒアリング

以下を確認する:

1. **音楽エンジン**: Suno / Lyria（`music_engine` に入れる値は `suno` / `lyria` のどちらか。`both` は config 契約外のため選択肢にしない）
2. **動画尺** (`audio.target_duration_min` / `audio.target_duration_max`): 既存動画の標準尺を確認し、固定尺なら min/max を同値にする
3. **タイトルテンプレート**: 既存動画のタイトルパターンを確認し、`{style} {theme} Music - {activity} BGM [{duration_display}]` 形式で提案
4. **タグ** (`tags.base`): ジャンルに適した YouTube 検索タグを 10 個程度提案
5. **テーマ別タグ** (`tags.themes`): 6-10 テーマのタグ群を提案
6. **説明文設定**:
   - `descriptions.opening`: `{style} {primary} music inspired by ...` 形式
   - `descriptions.perfect_for`: 4 項目（例: Study & Focus, Relaxation, Creative Work, Sleep）
   - `descriptions.hashtags`: 5 個程度
7. **Suno 設定**（音楽エンジンが Suno の場合）: `config/skills/suno.yaml` で `workspace_name` / `genre_line` / `exclude_styles` を上書き（ない場合は skill default を使用）

## 取り込み Step 4: config 生成

`references/config-template/*.json`（責務別 5 ファイル: meta / content / youtube / analytics / audio）をベースに、ヒアリング結果で各ファイルの全フィールドを埋めて `config/channel/*.json` を生成する。動画尺は `references/config-template/audio.json` に反映する。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。

## 取り込み Step 5: ディレクトリ構造の確認・補完

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。
既存リポジトリに不足しているディレクトリがあれば作成する。

## 取り込み Step 6: 検証

JSON 構文検証・config ロードテスト（`uv run yt-doctor --json` の `channel_config.status` 判定）は **`references/verification.md`** を参照。

## 取り込み Step 7: OAuth 認証と channel_id 取得

`auth/token.json` がない場合、OAuth 認証と channel_id 自動取得を実行。
`config/channel/meta.json::channel.channel_id` が未設定の場合は、認証済みチャンネル ID を必ず取得して保存する。
手順は **`references/verification.md`**（「OAuth 認証」「channel_id の自動取得」）を参照。

## 取り込み Step 8: 次ステップ案内

config 生成・認証完了後、以下を案内:

1. **ブランディング素材**: 未作成の場合は `references/verification.md`（「ブランディング素材生成」）を参照
2. **ベンチマーク設定**: 競合チャンネルを追加したい場合は `config/channel/analytics.json` の `benchmark.channels` を追加し `/benchmark` で収集
3. **ペルソナ定義**: `/viewer-voice` → `/audience-persona-design` → `/viewing-scene` の順で実行
4. **データ収集・分析**: `/analytics-collect` → `/analytics-analyze` で現状のパフォーマンスを把握
5. **コレクション制作**: `/wf-new` で最初のコレクション制作を開始

Step 1 前段で「方向性見直し」が選ばれていた場合は、上記に加えて `/channel-new` の方向性検討モードへの接続を案内する。ただし、`references/direction-mode.md` の前提は新規開設モードの完了であり、既存チャンネル取り込みモードの完了だけでは満たさないため、方向性検討モードへ直行する案内はしない。新規開設モードを完了して前提を満たしたうえで、TTP メモ（`docs/channel/ttp-seed-confirmation.md` と `docs/channel/competitor-branding-snapshot.json`）または分析レポート（`docs/channel-research.md`）を入力として準備してから方向性検討モードを実行するよう案内する。入力がなければ、`references/direction-mode.md` の Step D1 に従い、新規開設モードで TTP メモを作成するか、必要に応じて `/benchmark` / `/viewer-voice` / `/channel-research` を先に実行し、入力を準備するまで方向性検討を停止する旨も明記する。

取り込みモードは、`config/channel/*.json` の生成、`uv run yt-doctor --json` の `channel_config.status` が `ok`、OAuth 認証、`channel_id` の `config/channel/meta.json::channel.channel_id` 保存、次ステップ案内まで到達した時点で完了扱いにできる。新規開設モードの `benchmark.channels`、`ttp-seed-confirmation.md`、branding snapshot、`ttp_wf_new_readiness` は取り込みモードの必須完了条件ではない。
