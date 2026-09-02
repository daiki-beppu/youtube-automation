# できることから skill を探す

`yt-skills sync` で各チャンネルリポジトリに配布される skill を、カテゴリ別の「なにができるか」という 1 行要約から探せます。使う skill が決まったら、サイトの [発動条件・前提・前後工程を確認するページ](/skills) へ進み、詳細手順は `.claude/skills/<name>/SKILL.md` を参照してください。

> 個別の使い分けは各カテゴリの冒頭リンクや [`docs/workflow-cheatsheet.md`](workflow-cheatsheet.md)（workflow 系）も併せて参照。

## ワークフロー管理

コレクション制作ループ（企画 → 素材準備 → 制作 → 公開）の進行管理。詳しい使い分けは [`docs/workflow-cheatsheet.md`](workflow-cheatsheet.md) を参照。

| Skill | なにができるか |
|---|---|
| /wf-new | フラグなしで新規コレクションを立ち上げ、正規入口 `--auto` では公開後処理まで継続・再開し、`--batch` では複数企画を順次実行し、`--schedule` では定期実行を設定・確認・停止 |
| /wf-next | 既存コレクションを次の工程に 1 段進める（Phase 2-3） |
| /wf-status | 制作中コレクションの進捗を読み取り表示（実行はしない） |

## チャンネル立ち上げ

標準フローは `/setup` → `/channel-research --voice` → `/channel-strategy`（`--persona` → `--scene` → `--constraints`）→ `/wf-new`。公開前のペルソナチェーンは既存の競合 / TTP / viewer-voice 成果物を入力に完走し、自チャンネル Analytics report や任意の本格 benchmark 収集を要求しない。追加競合発掘、benchmark、`/channel-strategy --direction` による方向性再検討、branding 再反映は必要なときだけ任意後続として実行する。`/channel-research --voice` は公開後の再分析では任意で、公開後の `/channel-strategy --scene` は従来どおり Analytics report を要求する。

| Skill | なにができるか |
|---|---|
| /setup | ツール導入と GCP / OAuth 設定を wizard 形式で診断・セットアップ |

## オーディエンス・ポジショニング検証

視聴者像と訴求軸を決め、サムネ × タイトル × 音楽の整合性を担保する。

| Skill | なにができるか |
|---|---|
| /channel-strategy | チャンネル戦略を状態判定付きで実行し、`--persona` で第一ペルソナ、`--scene` で視聴シーン、`--constraints` で制作制約、`--direction` で方向性・ポジショニング・差別化を設計・見直し |
| /audit | `--alignment` で音楽・サムネ・タイトル整合、`--value-loop` で価値ループ、`--video` で動画本体、`--metadata` でローカルと YouTube のメタデータ整合を読み取り専用で監査・解析 |

## 企画・コンテンツ生成

サムネ・音源・動画など制作物の生成。`/music --generate` が `config/channel/youtube.json::music_engine` を読み、Suno UI、Vertex AI Lyria、MiniMax Music API の3経路を自動分岐する。

| Skill | なにができるか |
|---|---|
| /thumbnail | CTR 最適化サムネを生成。`--compare` で 320px 視認性検証、`--test` で Studio A/B テスト、`--iterate` で champion 還元、`--loop` で textless main から Veo / Omni ループ動画を生成 |
| /music | `--prompt` で Suno Style、`--lyric` でボーカル曲の歌詞と構成メモ、`--generate` で engine に応じた Suno UI 連続生成または Lyria 3 長尺マスター生成、`--master` で Suno 音源の DL + クロスフェードマスター化を実行 |
| /video | `--generate` で最終 MP4、`--describe` で Complete Collection 概要欄を生成 |

## 公開・運用

YouTube への公開、視聴者対応、容量整理、コミュニティ投稿。

| Skill | なにができるか |
|---|---|
| /publish | フラグなしで playlist → upload → community → pinned を状態判定付きで一括実行。各 mode の単独実行と `--clean` にも対応 |
| /reply | フラグなしで公開済みコメントへ dry-run → apply、`--live` で配信中ライブチャットの常駐 daemon を運用 |
| /short | collection 型の生成・ローカライズ投稿と release 型の JP+EN クリップ生成を設定から自動分岐 |
| /distrokid-helper | コレクション楽曲を DistroKid 配信用に整備し、Chrome 拡張向けサーバー起動まで実行 |

## 分析・振り返り

YouTube Analytics と動画本体の解析。

| Skill | なにができるか |
|---|---|
| /analytics | 収集・分析・レポート表示を一括実行。`--collect` / `--analyze` / `--report` で各段だけを実行し、`--flop` で失速原因、`--status` で登録者数・総再生回数・動画別パフォーマンスを確認 |

## ベンチマーク

競合チャンネルの最新動向を取得。

| Skill | なにができるか |
|---|---|
| /channel-research | チャンネル調査を状態判定付きで実行。`--benchmark` で競合データを収集、`--discover` で追加候補を発掘、`--voice` でコメント分析、`--market` で市場比較または収集済みデータ分析へ自動分岐し、`--thumbnail` で競合サムネイルの上位群 / 下位群から勝ちパターンを抽出 |

## 配信インフラ

24/7 ライブ配信用 VPS のプロビジョニングと運用。

| Skill | なにができるか |
|---|---|
| /streaming | YouTube ライブ配信用 Vultr VPS を Terraform で操作（構築・差し替え・死活監視） |

## リポジトリメンテ

`youtube-channels-automation` 本体のリリースと、下流チャンネルの追従。

| Skill | なにができるか |
|---|---|
| /automation | `--update` で下流チャンネルを upstream 最新版へ追従し、`--question <質問>` または自然文で配布物ローカルを根拠に読み取り専用で質問へ回答 |
| /extension | Chrome 拡張の状態判定・導入・更新と、拡張向け collection server の起動・停止 |
| /skill-feedback | スキル実行中の不具合・摩擦・改善案を append-only JSONL に構造化記録 |

---

> このカタログと下流配布対象の `.claude/skills/*/SKILL.md` の件数・名称・9カテゴリ分類は CI で照合する。新規 skill を追加・削除した場合は本ファイルも更新すること。
