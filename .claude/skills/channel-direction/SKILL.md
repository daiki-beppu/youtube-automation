---
name: channel-direction
description: "Use when /channel-new 後に新チャンネルの方向性を再検討・精緻化したいとき。「方向性決めたい」「チャンネルの方針」「ポジショニング」「差別化」「ブレスト」「TTP 対象を決める」など、TTP メモや seed fetch 結果、または後続の benchmark / viewer-voice 分析をもとに戦略的方向性を対話で見直す場面で使用すること。初回セットアップは /channel-new だけで完結する"
---

## Overview

`/channel-research` の分析レポート、または `/channel-new` の TTP ヒアリング・seed fetch 結果をもとに、ユーザーと対話で新チャンネルの方向性を再検討する。
データに基づいた議論を行い、決定事項をドキュメントに保存する。

**前提**: `/channel-new` が完了していること。詳細分析済みなら `docs/channel-research.md` を優先して使う。

## TTP 原則（ベンチマーク参照）

方向性議論の起点は **TTP（徹底的にパクる）**。
差別化を先に論じない。まず、競合の勝ちパターン（構造・型）から自チャンネルに転写する対象を
明示し、それを土台にしてから「自チャンネル固有の差別化」を上乗せする順序で議論する。

## Instructions

**実行場所**: リポジトリルート（チャンネルの独立リポジトリ）

### Step 1: 分析レポートの読み込みとサマリー

`docs/channel-research.md` があれば読み込み、なければ `/channel-new` の TTP メモ、seed fetch 結果、`config/channel/analytics.json::benchmark.channels` を読み込んでユーザーに要点をサマリーで提示:

- 承認済み TTP 対象の全体像（チャンネル名、登録者数、動画数、直近タイトル）
- 最も参考になるチャンネル（ロールモデル候補）
- 転写したい型（タイトル構造、サムネ構図、投稿頻度、動画尺、branding）
- 後続 `/benchmark` / `/viewer-voice` / `/channel-research` が必要な未確認事項

### Step 2: ポジショニング議論

`docs/channel-research.md` がある場合は分析レポートの「推奨事項」をベースに、ない場合は `/channel-new` の TTP メモと seed fetch 結果をベースに、ユーザーと以下を議論する。
**常にデータ根拠を示しながら**議論を進めること。

#### 議論ポイント

**順序は「TTP → 差別化」**。先に転写対象を確定し、その上に独自要素を載せる。

1. **TTP 対象選定**
   - `/channel-research` レポート、または `/channel-new` の TTP メモから転写する **構造・パターン・型** を明示
     （タイトルフォーマット / サムネ構図 / 動画尺 / 投稿頻度 / コメント語彙 等）
   - どのベンチマークの何を、どの程度パクるかをユーザーと合意

2. **ジャンル & スタイルの確定**
   - TTP 対象に基づいて競合の空白ポジションを検討
   - ユーザーの好み・得意分野とのマッチング
   - 「{genre.primary}」「{genre.style}」「{genre.context}」を確定

3. **ターゲット視聴者**
   - `/viewer-voice` 実行済みならコメント分析から見える主要な視聴者像
   - 未実行なら `/channel-new` の TTP メモと seed fetch 結果から置いた仮説
   - 狙うべきセグメント
   - 利用シーン（勉強、睡眠、作業、ゲーム等）

4. **コンテンツ戦略**
   - 動画の長さ（競合のデータを参考に `audio.target_duration_min` を決定）
   - 投稿頻度（競合の投稿間隔データを参考に）
   - テーマの幅（専門特化 vs 多様性）

5. **ビジュアルアイデンティティ**
   - サムネイルの方向性（競合分析のサムネイルパターンを参考に）
   - チャンネル全体のトーン＆マナー

6. **差別化ポイント**
   - TTP で転写した型の上に重ねる独自要素は何か（テーマ、スタイル、世界観、品質）
   - 持続可能な差別化か（一時的なトレンドではないか）

7. **チャンネル名の確定**
   - 仮名の見直し
   - SEO 観点（検索されやすさ）
   - ブランド観点（覚えやすさ、独自性）

### Step 3: 決定事項の整理

議論の結果を整理し、ユーザーに最終確認:

| 項目 | 決定内容 | データ根拠 |
|------|---------|-----------|
| チャンネル名（確定） | | |
| 短縮名（3-5文字） | | |
| リポジトリ名 | | |
| genre.primary | | 競合の空白ポジション |
| genre.style | | |
| genre.context | | |
| コアメッセージ | | 視聴者インサイト |
| 差別化ポイント | | 競合にない要素 |
| ターゲット視聴者 | | TTP メモ / コメント分析 |
| 動画の長さ（分） | | 競合の傾向 |
| 投稿頻度 | | 競合の投稿間隔 |
| 音楽エンジン（デフォルト） | suno / lyria のどちらか | ジャンル適性・API 可用性 |
| サムネイル方針 | | 競合サムネイル分析 |

#### `/channel-setup` への引き継ぎ項目（必須・issue #567）

下記は `/channel-setup` 側で `config/skills/*.yaml` / `config/channel/*.json` に
転記される項目。**ここで決め切らない項目があると下流 skill がチャンネル
方向性を AI に手書きさせる素地になる**。必ず table と同じ厳密さで合意する。

| 項目 | 決定内容 | 転記先 |
|---|---|---|
| Suno `genre_line`（音楽方向性の英語直訳） | | `config/skills/suno.yaml::genre_line` |
| Suno `exclude_styles`（排除する音楽要素）| | `config/skills/suno.yaml::exclude_styles` |
| TTP 対象サムネ（competitor 名 + 代表 video_id ×3）| | `config/skills/thumbnail.yaml::image_generation.gemini.reference_images.default` |
| ブランド背景色 | | `config/skills/thumbnail.yaml::image_generation.gemini.brand_background` |
| サムネ構図ルール（キャラサイズ / NG ポーズ 等）| | `config/skills/thumbnail.yaml::image_generation.gemini.composition_rules.*` |
| テーマ → アクティビティ・シーン対応表 | | `config/channel/content.json::title.theme_scenes` |
| 動画の長さ（分・固定 / 範囲）| | `config/channel/audio.json::audio.target_duration_min` / `target_duration_max` |
| 1 コレクションあたりの楽曲数（track 戦略）| | `config/skills/collection-ideate.yaml`（または masterup 側）|

### Step 4: 方向性ドキュメント保存

決定事項を `docs/channel/channel-direction.md` に保存。
ディレクトリが存在しなければ `mkdir -p docs/channel` で作成してから書き出す。

雛形:

```markdown
# チャンネル方向性

## 基本情報
- チャンネル名: {name}
- 短縮名: {short}
- ジャンル: {primary} / {style} / {context}
- コアメッセージ: {core_message}

## ポジショニング
- 差別化ポイント: ...
- ターゲット視聴者: ...
- 主な利用シーン: ...

## コンテンツ戦略
- 動画の長さ: {target_duration_min}分
- 投稿頻度: ...
- テーマの幅: ...

## ビジュアルアイデンティティ
- サムネイル方針: ...
- トーン＆マナー: ...
- ブランド背景色: ...
- TTP 対象サムネ:
  - `data/thumbnail_compare/benchmark/<channel>-<vid1>.jpg`
  - `data/thumbnail_compare/benchmark/<channel>-<vid2>.jpg`
  - `data/thumbnail_compare/benchmark/<channel>-<vid3>.jpg`

## 音楽設定（Suno / Lyria 共通）
- `genre_line`（英語直訳）: ...
- `exclude_styles`: ...
- 1 コレクションあたりの楽曲数（track 戦略）: ...

## 決定の根拠
[各決定のデータ根拠をまとめる]
```

### Step 5: 次フェーズへの案内

「方向性が更新されました。config を再生成・再反映する場合は `/channel-setup`、制作に進む場合は `/wf-new` を実行してください。」

リポジトリ名が変更された場合、ユーザーにリポジトリのリネームを案内する。

#### リネーム時の venv 復旧手順

リポジトリ／ディレクトリをリネームすると、`.venv/bin/*` の shebang に旧パスが
焼き込まれたままになる（`uv sync` だけでは shebang は更新されない）。
`uv run yt-*` が `bad interpreter` で落ちるため、リネーム後は **必ず venv を作り直す**:

```bash
rm -rf .venv
uv sync
```

`uv sync --reinstall --refresh` でも代替可能だが、`rm -rf .venv && uv sync` が
最短かつ確実。リネーム直後と、`.venv` 配下を別マシン間で移動した直後に実行する。

## 障害時ガイダンス

方向性決定は対話ベースで、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ/設定の不在 | 参照先のローカルファイルが見つからない | 該当ファイルを用意するか前段スキルを先に実行（外部サービスに依存しないため API 障害・quota の影響は受けない） |

## Cross References

- `/channel-new` → 前提: TTP 対象確認 / seed fetch / 承認済み benchmark.channels 反映 / 初回 config / persona / branding
- `/channel-research` → 任意: ベンチマーク詳細分析
- `/benchmark` → 任意: 承認済み TTP 対象の動画データ収集
- `/viewer-voice` → 任意: コメント収集と視聴者インサイト分析
- `/channel-setup` → 任意: config 再生成 / branding 再反映
- `/wf-new` → 初回コレクション制作
