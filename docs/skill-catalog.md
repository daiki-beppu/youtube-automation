# Skill catalog

<!-- `uv run yt-skills catalog` により生成。手で編集しないでください。 -->

PDCA 対応: 準備 = 準備する / Plan = 調べる → 決める / Do = 進める → 作る → 公開する / Check / Act = 振り返る

## 準備する

- `/automation-release` — Use when 本リポジトリの新規リリースを作成するとき。
- `/automation-update` — Use when 下流リポジトリで automation を最新リリースへ追従させるとき。
- `/extension` — Use when Chrome 拡張（suno-helper / distrokid-helper / community-helper）の導入・更新、または拡張向け collection server の起動・停止を行うとき。
- `/setup` — Use when ツール導入と GCP / OAuth の設定、新規 YouTube チャンネル開設、既存チャンネル取り込み、config 再生成、または YouTube 側設定同期を行うとき。
- `/shadcn` — Manages shadcn components and projects — adding, searching, fixing, debugging, styling, and composing UI, including chat interfaces. Provides project context, component docs, and usage examples. Applies when working with shadcn/ui, component registries, presets, --preset codes, or any project with a components.json file. Also triggers for 'shadcn init', 'create an app with --preset', or 'switch to --preset'.

## 調べる

- `/channel-research` — Use when チャンネル調査を状態判定付きで一括実行または一段だけ実行するとき。

## 決める

- `/channel-strategy` — Use when チャンネル戦略を状態判定付きで一括実行または一段だけ実行するとき。

## 進める

- `/streaming` — Use when ライブ配信用 Vultr VPS・動画配信本体を Terraform で構築・運用・トラブルシュートするとき。
- `/wf-new` — Use when 新規コレクション制作を立ち上げるとき、--auto で公開後処理まで継続するとき、--batch で複数コレクションを一括企画するとき、または --schedule で定期実行を設定・確認・停止するとき。
- `/wf-next` — Use when 既存コレクション（collections/planning/）を一段進めるとき。
- `/wf-status` — Use when コレクション制作の進捗を読むだけで確認するとき（実行しない）。

## 作る

- `/lyria` — Use when Vertex AI Lyria 3 でマスター音源を自動生成するとき。
- `/masterup` — Use when Suno UI で生成した曲のプレイリストを一括 DL + マスター化するとき。
- `/music` — Use when 音楽制作を状態判定付きで一括実行または一段だけ実行するとき。
- `/short` — Use when collection 型（BGM テイスター）または release 型（楽曲リリース）のチャンネルでショートを生成するとき。
- `/suno-helper` — Use when Suno UI に投入する曲をブラウザで連続生成 + playlist 追加 + 一括ダウンロードしたいとき。
- `/thumbnail` — Use when コレクションの YouTube サムネイル（thumbnail.jpg）を CTR 最適化し、textless main.png/jpg を先行生成して実フォント合成するとき、`--compare` で生成済み候補を競合と 320px 比較するとき、`--test` で Studio の A/B テストを設計・記録するとき、`--iterate` で伸びた動画の勝因を次のサムネへ還元するとき、または `--loop` で textless main.png/jpg から Veo / Gemini Omni Flash のループ動画背景を生成するとき。
- `/video` — Use when 音源と画像からマスター動画を生成するとき。
- `/video-description` — Use when YouTube 概要欄を Complete Collection 形式で自動生成するとき。

## 公開する

- `/comments-reply` — Use when 公開済み YouTube 動画のコメントへ自動返信するとき。
- `/community-draft` — Use when コレクションの YouTube コミュニティ投稿を JSON バッチ生成するとき。
- `/community-post` — Use when コミュニティ投稿テキスト生成から Studio 起動まで単独実行するとき。
- `/distrokid-helper` — Use when コレクションの楽曲を DistroKid 配信用に準備し、distrokid-helper Chrome 拡張へ渡すローカルサーバーを起動したいとき（30-distrokid 生成 / disc 分割 / metadata.md / ジャケット 3000×3000 新規生成 / uv run yt-collection-serve 起動）。
- `/live-chat-reply` — Use when 配信中の YouTube ライブチャットへ常駐 daemon で自動返信するとき。
- `/live-clean` — Use when live コレクションの大容量メディアを削除して容量回復するとき、または collections 配下の tmp/ 残骸を掃除するとき。
- `/pinned-comment` — Use when 新規動画へオーナー固定コメントを自動投稿するとき。
- `/post-publish` — Use when 動画公開直後の community-post → pinned-comment → metadata-audit を承認ゲート付きで一括実行・途中再開するとき。
- `/publish` — Use when 完成した動画を公開工程へ進めるとき。

## 振り返る

- `/alignment-check` — Use when 音楽ムード × サムネ × タイトルの整合性を監査するとき。
- `/analytics` — Use when YouTube Analytics の収集・分析・レポート表示を一括実行または一段だけ実行するとき。
- `/channel-status` — Use when チャンネルの YouTube 統計（登録者・再生回数）を取得するとき。
- `/flop-analysis` — Use when 公開済み動画が伸びなかった原因を video_id、collection、または --since で切り分け、postmortem.md に出力するとき。
- `/metadata-audit` — Use when ローカル descriptions.md と YouTube メタデータの整合を監査するとき。
- `/skill-feedback` — Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき、または記録済み feedback を上流 issue に還流するとき。
- `/value-loop-audit` — Use when チャンネルの価値ループ（シーン定義→制約翻訳→公開前ゲート→指標還流）の整備状況を読み取り専用で横断診断するとき。
- `/video-analyze` — Use when 動画本体の中身（フック構造・シーン・BGM 展開）を Gemini で解析するとき。
