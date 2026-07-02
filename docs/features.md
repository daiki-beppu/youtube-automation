# 全 skill カタログ

`yt-skills sync` で各チャンネルリポジトリに配布される Claude Code skill の一覧（全 **48 個**）。各行は「なにができるか」（what）の 1 行要約。発動トリガーや詳細手順は `.claude/skills/<name>/SKILL.md` を参照。

> 個別の使い分けは各カテゴリの冒頭リンクや [`docs/workflow-cheatsheet.md`](workflow-cheatsheet.md)（workflow 系）も併せて参照。

## ワークフロー管理

コレクション制作ループ（企画 → 素材準備 → 制作 → 公開）の進行管理。詳しい使い分けは [`docs/workflow-cheatsheet.md`](workflow-cheatsheet.md) を参照。

| Skill | なにができるか |
|---|---|
| /wf-new | 新規コレクションの企画選択・ディレクトリ作成・素材準備（Phase 1） |
| /wf-next | 既存コレクションを次の工程に 1 段進める（Phase 2-3） |
| /wf-status | 制作中コレクションの進捗を読み取り表示（実行はしない） |
| /collection-ideate | データドリブンに次の企画候補を提案 |

## チャンネル立ち上げ

標準フローは `/setup` → `/channel-new` → `/wf-new`。追加競合発掘、benchmark、viewer voice、方向性再検討、branding 再反映は必要なときだけ任意後続として実行する。

| Skill | なにができるか |
|---|---|
| /setup | ツール導入と GCP / OAuth 設定を wizard 形式で診断・セットアップ |
| /channel-new | TTP 対象確認、seed confirmation artifacts、config、簡易ペルソナ、初回 branding まで進める |
| /discover-competitors | 任意: ニッチキーワードから追加競合候補を YouTube Data API で自動発掘 |
| /channel-research | 任意: benchmark / viewer-voice 済みデータを徹底分析 |
| /channel-direction | 任意: TTP seed confirmation または分析結果から方向性・ポジショニングを対話で再検討 |
| /channel-setup | 任意: config 再生成と YouTube 側設定（branding / status / localizations）の push |
| /channel-import | 既存 YouTube チャンネルを自動化システムに取り込み |
| /channel-status | 登録者数・総再生回数・動画別パフォーマンスを YouTube API から取得 |

## オーディエンス・ポジショニング検証

視聴者像と訴求軸を決め、サムネ × タイトル × 音楽の整合性を担保する。

| Skill | なにができるか |
|---|---|
| /viewer-voice | 競合コメント収集で視聴者インサイトを抽出 |
| /audience-persona-design | ターゲット視聴者のペルソナを定義 |
| /viewing-scene | 視聴シーン（いつ・どこで・なぜ聴くか）を検証・定義 |
| /alignment-check | 音楽ムード × サムネ × タイトル訴求の整合性を監査 |
| /thumbnail-compare | サムネをベンチマーク競合と並べてモバイル視認性（320px）を検証 |

## 企画・コンテンツ生成

サムネ・音源・動画など制作物の生成。`config/channel/youtube.json::music_engine` により `/lyria` 経路と `/suno` + `/masterup` 経路を切り替える。

| Skill | なにができるか |
|---|---|
| /thumbnail | CTR 最適化プロンプトでサムネイル画像を生成（Gemini / OpenAI） |
| /lyria | Vertex AI Lyria 3 で長尺マスター音源を自動生成（API 完結） |
| /suno | Suno UI 用プロンプト（Style + Lyrics）を生成 |
| /suno-lyric | Suno のボーカル曲向けに歌詞と構成メモを生成 |
| /suno-helper | suno-helper Chrome 拡張で Suno UI への連続生成 + playlist 一括追加を運用 |
| /masterup | Suno で生成した楽曲を DL + クロスフェードマスター化 |
| /loop-video | 静止画から 8 秒シームレスループ動画を生成（Veo 3.1） |
| /videoup | マスター音源 + 背景画像 / 動画から最終 MP4 を合成 |
| /short-thumbnail | ショート用 9:16 縦型サムネ生成 + ループ動画化（Veo） |

## 公開・運用

YouTube への公開、視聴者対応、容量整理、コミュニティ投稿。

| Skill | なにができるか |
|---|---|
| /video-description | YouTube 概要欄を自動生成（情景フック + タイムスタンプ + Perfect for） |
| /video-upload | Complete Collection を YouTube へアップロード + live 移行 |
| /playlist | プレイリストの作成・動画割当・状態確認（`playlists.json` 駆動） |
| /comments-reply | ルール駆動コメント自動返信（dry-run → apply、二重返信防止） |
| /pinned-comment | オーナー固定コメント自動投稿（preflight で削除済み/private を skip、dry-run → apply、二重投稿防止） |
| /metadata-audit | ローカル descriptions.md と YouTube 上メタデータの整合性監査 |
| /live-clean | live コレクションの大容量メディアを削除してディスク回復 |
| /community-draft | コミュニティ投稿の下書きを type 別に生成 + クリップボードコピー |
| /community-post | 動画公開と連動した固定テンプレ投稿（Studio 起動まで） |
| /short | BGM テイスター（collection 型）チャンネル用 9:16 ショートを生成・投稿 |
| /short-release | 楽曲リリース（release 型）チャンネル用 JP+EN クリップショート生成 |
| /distrokid-helper | コレクション楽曲を DistroKid 配信用に整備し、Chrome 拡張向けサーバー起動まで実行 |

## 分析・振り返り

YouTube Analytics と動画本体の解析。

| Skill | なにができるか |
|---|---|
| /analytics-collect | YouTube Analytics データの収集・最新化 |
| /analytics-analyze | 収集済みデータを詳細分析し戦略的改善提案を生成 |
| /analytics-report | 過去レポートの表示・比較 |
| /postmortem | 伸びなかった動画の原因を仮説 → 検証で切り分け |
| /video-analyze | Gemini で YouTube 動画本体を直接解析（フック・BGM・シーン・サムネ整合性） |

## ベンチマーク

競合チャンネルの最新動向を取得。

| Skill | なにができるか |
|---|---|
| /benchmark | 競合チャンネルの最新動画データを取得し `docs/benchmarks/*.md` を更新 |

## 配信インフラ

24/7 ライブ配信用 VPS のプロビジョニングと運用。

| Skill | なにができるか |
|---|---|
| /streaming | YouTube ライブ配信用 Vultr VPS を Terraform で操作（構築・差し替え・死活監視） |

## リポジトリメンテ

`youtube-channels-automation` 本体のリリースと、下流チャンネルの追従。

| Skill | なにができるか |
|---|---|
| /automation-release | 本リポジトリの新規リリースを作成（prepare → publish の 2 フェーズ） |
| /automation-update | 下流チャンネルを upstream 最新版に追従（pin bump + `yt-skills sync` + 動作確認） |
| /ext-install | Chrome 拡張（suno-helper / distrokid-helper）の初回インストールまたは更新ガイド |

---

> このカタログの整合性は CI で担保していない。新規 skill を追加・削除した場合は本ファイルも更新すること。`ls .claude/skills/ | wc -l` の結果と本ファイルの行数（`| /` 始まり）が一致することを確認する。
