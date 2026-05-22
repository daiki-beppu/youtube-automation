# Skill Catalog

`yt-skills sync` で配布される skill の一覧です。各行は「なにができるか」が 1 行で分かる粒度にそろえています。

## ワークフロー全体管理

| Skill | なにができるか |
|---|---|
| /wf-new | 新規コレクションの企画選択からディレクトリ作成と素材準備までを立ち上げる |
| /wf-next | 制作中コレクションの次工程を進める |
| /wf-status | コレクション制作の進捗を読み取り専用で確認する |

## チャンネル立ち上げ

| Skill | なにができるか |
|---|---|
| /channel-new | 新規チャンネル用リポジトリ作成から初期セットアップの入口を担う |
| /channel-research | 競合チャンネルのベンチマークデータを分析して方向性判断の材料を作る |
| /channel-direction | 競合分析結果をもとにチャンネルの方向性とポジショニングを決める |
| /channel-setup | 新規チャンネルの設定生成や既存チャンネルの YouTube 設定反映を行う |
| /channel-import | 既存 YouTube チャンネルを自動化用設定に取り込む |
| /channel-status | チャンネル全体の登録者数や動画別パフォーマンスを取得する |
| /discover-competitors | ニッチキーワードから競合候補チャンネルを自動発掘する |
| /onboard | GCP と OAuth の API セットアップを診断しながら進める |

## オーディエンス・ポジショニング検証

| Skill | なにができるか |
|---|---|
| /viewer-voice | 競合コメント分析から視聴者インサイトを抽出する |
| /audience-persona | ターゲット視聴者ペルソナを定義する |
| /viewing-scene | 視聴シーンと用途を検証して注力先を定める |
| /alignment-check | 音楽ムードとサムネとタイトル訴求の整合性を監査する |
| /thumbnail-compare | サムネイルを競合と並べて視認性を比較検証する |

## 企画・コンテンツ生成

| Skill | なにができるか |
|---|---|
| /collection-ideate | 次に作るコレクション候補をデータに基づいて提案する |
| /thumbnail | コレクション用サムネイル画像を生成する |
| /lyria | Vertex AI Lyria 3 で長尺マスター音源を自動生成する |
| /suno | Suno UI に投入する音楽プロンプトを生成する |
| /masterup | Suno で作った楽曲群をダウンロードしてマスター音源化する |
| /loop-video | サムネイル画像からシームレスなループ背景動画を作る |
| /videoup | 音声素材とビジュアル素材から動画ファイルを生成する |

## ショート動画

| Skill | なにができるか |
|---|---|
| /short | collection 型チャンネル向けのショート動画を生成して投稿する |
| /short-release | release 型チャンネル向けの縦型ショートを生成して投稿する |
| /short-thumbnail | ショート用の 9:16 サムネイルやループ素材を作る |

## 公開・運用

| Skill | なにができるか |
|---|---|
| /video-description | YouTube 概要欄や投稿用メタデータ文面を生成する |
| /video-upload | Complete Collection のアップロードと live 移行を実行する |
| /playlist | プレイリストの作成と動画割り当てと状態確認を行う |
| /comments-reply | ルールに沿って YouTube コメントへ自動返信する |
| /metadata-audit | ローカル記述と YouTube 上のメタデータ差分を監査する |
| /live-clean | 公開済みコレクションの不要メディアを削除して容量を回復する |
| /community-draft | YouTube コミュニティ投稿の下書きを生成する |
| /community-post | コミュニティ投稿文を作成して投稿準備まで進める |

## 分析・振り返り

| Skill | なにができるか |
|---|---|
| /analytics-collect | YouTube Analytics データを収集して最新化する |
| /analytics-analyze | 収集済み Analytics データを分析して改善提案を出す |
| /analytics-report | 既存の Analytics レポートを表示して比較する |
| /postmortem | 伸び悩んだ動画の原因を仮説検証で切り分ける |
| /video-analyze | YouTube 動画本体を解析して構成や演出の特徴を抽出する |

## ベンチマーク

| Skill | なにができるか |
|---|---|
| /benchmark | 競合チャンネルの最新動画データを取得して更新する |

## 配信インフラ

| Skill | なにができるか |
|---|---|
| /streaming | YouTube ライブ配信用 VPS の構築と運用を行う |

## メタ運用・リリース

| Skill | なにができるか |
|---|---|
| /automation-release | このリポジトリ本体のリリース準備と公開を進める |
| /automation-update | 下流チャンネルリポジトリの automation 依存を最新版へ追従させる |

> 各説明は `.claude/skills/<name>/SKILL.md` の frontmatter をもとに要約しています。
