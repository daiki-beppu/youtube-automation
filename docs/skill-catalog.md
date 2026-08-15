# Skill catalog

<!-- `uv run yt-skills catalog` により生成。手で編集しないでください。 -->

PDCA 対応: 準備 = 準備する / Plan = 調べる → 決める / Do = 進める → 作る → 公開する / Check / Act = 振り返る

## 準備する

- `/automation-release` — Use when 本リポジトリの新規リリースを作成するとき。
- `/automation-update` — Use when 下流リポジトリで automation を最新リリースへ追従させるとき。
- `/channel-new` — Use when チャンネルの方向性を再検討するとき。
- `/ext-install` — Use when Chrome 拡張（suno-helper / distrokid-helper / community-helper）のインストール・更新をするとき。
- `/setup` — Use when ツール導入と GCP / OAuth の設定、新規 YouTube チャンネル開設、既存チャンネル取り込み、config 再生成、または YouTube 側設定同期を行うとき。
- `/shadcn` — Manages shadcn components and projects — adding, searching, fixing, debugging, styling, and composing UI, including chat interfaces. Provides project context, component docs, and usage examples. Applies when working with shadcn/ui, component registries, presets, --preset codes, or any project with a components.json file. Also triggers for 'shadcn init', 'create an app with --preset', or 'switch to --preset'.

## 調べる

- `/channel-research` — Use when チャンネル調査を状態判定付きで一括実行または一段だけ実行するとき。

## 決める

- `/audience-persona-design` — Use when ターゲット視聴者を第一ペルソナとして設計・見直しするとき。
- `/creative-constraints` — Use when ペルソナと視聴シーンを、音・映像・サムネ・タイトル・測定の機械検証可能なチャンネル制約へ翻訳するとき。
- `/viewing-scene` — Use when 視聴シーン（いつ・どこで・なぜ聴くか）を検証・定義するとき。

## 進める

- `/streaming` — Use when ライブ配信用 Vultr VPS・動画配信本体を Terraform で構築・運用・トラブルシュートするとき。
- `/wf-new` — Use when 新規コレクション制作を立ち上げるとき、--auto で公開後処理まで継続するとき、--batch で複数コレクションを一括企画するとき、または --schedule で定期実行を設定・確認・停止するとき。
- `/wf-next` — Use when 既存コレクション（collections/planning/）を一段進めるとき。
- `/wf-status` — Use when コレクション制作の進捗を読むだけで確認するとき（実行しない）。

## 作る

- `/loop-video` — Use when テキストなし main.png/jpg から Veo または Gemini Omni Flash でループ動画背景を生成するとき。
- `/lyria` — Use when Vertex AI Lyria 3 でマスター音源を自動生成するとき。
- `/masterup` — Use when Suno UI で生成した曲のプレイリストを一括 DL + マスター化するとき。
- `/short` — Use when collection 型（BGM テイスター）チャンネルでショートを生成・投稿するとき。
- `/short-release` — Use when release 型（楽曲リリース）チャンネルで JP+EN の 9:16 クリップを生成するとき。
- `/short-thumbnail` — Use when ショート用 9:16 サムネ作成、または short.png のループ動画化をするとき。
- `/suno` — Use when Suno UI 投入用の音楽プロンプトを生成するとき。
- `/suno-helper` — Use when Suno UI に投入する曲をブラウザで連続生成 + playlist 追加 + 一括ダウンロードしたいとき。
- `/suno-lyric` — Use when Suno ボーカル曲の歌詞を生成するとき。
- `/thumbnail` — Use when コレクションの YouTube サムネイル（thumbnail.jpg）を CTR 最適化し、textless main.png/jpg を先行生成して実フォント合成するとき。
- `/thumbnail-compare` — Use when 自チャンネルの生成済みサムネイルを競合と並べて 320px 視認性を比較検証するとき。
- `/thumbnail-iterate` — Use when 伸びた動画を起点にサムネの勝因を分解し、統制した A/B 比較で次の勝ちサムネへ更新するとき。
- `/thumbnail-test` — Use when 長尺動画で YouTube Studio のサムネイル A/B テストを単独で設計し、結果を記録するとき。
- `/video-description` — Use when YouTube 概要欄を Complete Collection 形式で自動生成するとき。
- `/videoup` — Use when 音声ファイルが揃い動画生成が必要なとき。

## 公開する

- `/comments-reply` — Use when 公開済み YouTube 動画のコメントへ自動返信するとき。
- `/community-draft` — Use when コレクションの YouTube コミュニティ投稿を JSON バッチ生成するとき。
- `/community-post` — Use when コミュニティ投稿テキスト生成から Studio 起動まで単独実行するとき。
- `/distrokid-helper` — Use when コレクションの楽曲を DistroKid 配信用に準備し、distrokid-helper Chrome 拡張へ渡すローカルサーバーを起動したいとき（30-distrokid 生成 / disc 分割 / metadata.md / ジャケット 3000×3000 新規生成 / uv run yt-collection-serve 起動）。
- `/live-chat-reply` — Use when 配信中の YouTube ライブチャットへ常駐 daemon で自動返信するとき。
- `/live-clean` — Use when live コレクションの大容量メディアを削除して容量回復するとき、または collections 配下の tmp/ 残骸を掃除するとき。
- `/pinned-comment` — Use when 新規動画へオーナー固定コメントを自動投稿するとき。
- `/playlist` — Use when プレイリストの作成・割り当て・確認をするとき。
- `/post-publish` — Use when 動画公開直後の community-post → pinned-comment → metadata-audit を承認ゲート付きで一括実行・途中再開するとき。
- `/video-upload` — Use when コレクションの動画または release 型（単曲リリース）の楽曲リリース動画が完成し、YouTubeへのアップロード自動化が必要なとき。

## 振り返る

- `/alignment-check` — Use when 音楽ムード × サムネ × タイトルの整合性を監査するとき。
- `/analytics` — Use when YouTube Analytics の収集・分析・レポート表示を一括実行または一段だけ実行するとき。
- `/channel-status` — Use when チャンネルの YouTube 統計（登録者・再生回数）を取得するとき。
- `/flop-analysis` — Use when 公開済み動画が伸びなかった原因を video_id、collection、または --since で切り分け、postmortem.md に出力するとき。
- `/metadata-audit` — Use when ローカル descriptions.md と YouTube メタデータの整合を監査するとき。
- `/skill-feedback` — Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき、または記録済み feedback を上流 issue に還流するとき。
- `/value-loop-audit` — Use when チャンネルの価値ループ（シーン定義→制約翻訳→公開前ゲート→指標還流）の整備状況を読み取り専用で横断診断するとき。
- `/video-analyze` — Use when 動画本体の中身（フック構造・シーン・BGM 展開）を Gemini で解析するとき。
