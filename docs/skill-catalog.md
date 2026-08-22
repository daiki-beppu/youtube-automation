# Skill catalog

<!-- `uv run yt-skills catalog` により生成。手で編集しないでください。 -->

PDCA 対応: 準備 = 準備する / Plan = 調べる → 決める / Do = 進める → 作る → 公開する / Check / Act = 振り返る

## 準備する

- `/automation` — Use when 下流リポジトリで automation を最新リリースへ追従させるとき、またはツールキットの仕様・skill・CLIについて質問するとき。
- `/automation-release` — Use when 本リポジトリの新規リリースを作成するとき。
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

- `/hallmark` — Anti-AI-slop design skill for greenfield pages, audits, redesigns, and design extraction from URLs or screenshots. Use when the user asks to build a new app or landing page, wants to redesign something, invokes Hallmark by name, or uses audit/redesign/study.
- `/music` — Use when 音楽制作を状態判定付きで一括実行または一段だけ実行するとき。
- `/short` — Use when collection 型（BGM テイスター）または release 型（楽曲リリース）のチャンネルでショートを生成するとき。
- `/thumbnail` — Use when コレクションの YouTube サムネイル（thumbnail.jpg）を CTR 最適化し、textless main.png/jpg を先行生成して実フォント合成するとき、`--compare` で生成済み候補を競合と 320px 比較するとき、`--test` で Studio の A/B テストを設計・記録するとき、`--iterate` で伸びた動画の勝因を次のサムネへ還元するとき、または `--loop` で textless main.png/jpg から Veo / Gemini Omni Flash / MiniMax H3 のループ動画背景を生成するとき。
- `/video` — Use when 音源と画像からマスター動画と YouTube 概要欄を作るとき。

## 公開する

- `/distrokid-helper` — Use when コレクションの楽曲を DistroKid 配信用に準備し、distrokid-helper Chrome 拡張へ渡すローカルサーバーを起動したいとき（30-distrokid 生成 / disc 分割 / metadata.md / ジャケット 3000×3000 新規生成 / uv run yt-collection-serve 起動）。
- `/publish` — Use when 完成した動画を公開工程へ進めるとき。
- `/reply` — Use when 公開済み YouTube 動画のコメントへ返信するとき、または --live で配信中のライブチャットへ常駐 daemon で自動返信するとき。

## 振り返る

- `/analytics` — Use when YouTube Analytics の収集・分析・レポート表示を一括実行または一段だけ実行するとき。
- `/audit` — Use when 整合性・動画本体・公開後メタデータ・価値ループの監査を一括実行または一段だけ実行するとき。
- `/skill-feedback` — Use when 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を構造化記録するとき、または記録済み feedback を上流 issue に還流するとき。
