# tayk

YouTube チャンネル運営を自動化するツールキット (旧 `youtube-channels-automation`、ADR-0007 で `tayk` に rebrand)。Python から TypeScript(bun) へ MCP tool 中心設計で 0 ベース再設計中 (epic #727)。既存 Python コードの移植ではなく、skill に蓄積されたワークフロー知識を型付き MCP tool に結晶化するスクラップ&ビルド。本ファイルは実装詳細ではなく、本プロジェクト固有の用語の正書を定める **グロッサリ**である。

## 配布・移行

**tayk**:
本ツールの公開ブランド = npm package 名 = bin 名。下流からの canonical 起動は `bunx tayk <cmd>`。
_Avoid_: youtube-channels-automation, yt-automation, yt (旧 bin 名)

**cutover**:
`feat/ts-rewrite` を Python 一掃済みの状態で main へ **merge commit** で統合し `tayk@0.1.0` を publish する単一イベント (#790)。これ以降 main は TS。

**dogfood**:
cutover 前に first-party 2 リポ (soulful-grooves / deepfocus365) で各コレクション 1 本のフルライフサイクルを実走させる受け入れ検証 (epic マイルストーン M2)。期間ではなく完走で判定する。
_Avoid_: ベータ, トライアル, 試運転

**critical regression**:
cutover をブロックする欠陥。**3 種のみ** — ①誤公開・誤メタデータ ②データ破壊 (analytics 履歴 / collection 成果物) ③auth 破壊。これ以外は cutover をブロックしない bug として issue 化する。
_Avoid_: 重大バグ (範囲が曖昧)

**first-party (下流)**:
運営者自身が保有する 5 リポ前後のチャンネルリポジトリ。dogfood の対象。
_Avoid_: 「第三者 consumer は存在しない」の根拠として使うこと (external user が実在する。ADR-0015)

**external user**:
`uv add git+https://` で Python 版を導入し skills 経由で運用する数十人規模の第三者コミュニティ。first-party ではないため dogfood 対象外だが、cutover の告知義務・移行コスト判断に影響する (ADR-0015)。
_Avoid_: 第三者 consumer なし (ADR-0007 起案時の旧前提。2026-06-25 の ADR-0015 で更新済み)

## 計画の 2 軸

**Phase**:
実行順の見出し (1B / 2 / 3)。「いつ書くか」を表す。Tier とは直交する。

**Tier**:
マイルストーンゲート所属のバッジ。**[T1]** = dogfood ブロッカー (全完了で M1) / **[T2]** = cutover ブロッカー (合格は smoke のみ) / **[T3]** = port せず削除。「どのゲートに属すか」を表す。
_Avoid_: 優先度, priority (Tier は priority ではなくゲート所属)

## 設定・データ形式

**config format**:
`packages/core` が読み書きするファイルはすべて JSON。YAML パーサー依存を持たない。takt / CI / lefthook 等の外部ツール所有ファイルは各ツールの規約に従う (YAML 等)。
_Avoid_: YAML / JSONC / JSON5 を core が読み書きするファイルに使うこと

**skill config**:
チャンネル固有のスキル挙動パラメータ。`config/skills/<skill>.json` のフルファイル 1 本。default + override の deep merge は行わず、zod schema の `.default()` が省略キーを補完する。
_Avoid_: config.default.yaml, deep merge (Python 版の旧方式)

## アーキテクチャ

**MCP tool**:
tayk が expose する型付き操作。agent (Claude Code / Codex 等) が直接呼ぶ第一級インターフェース。2 層で構成される — workflow tool (粗粒度) と primitive tool (細粒度)。ベンチマーク: [html2pptx.app](https://html2pptx.app/) の Skill + MCP tool + REST 3 層。
_Avoid_: API endpoint, command (MCP tool は MCP protocol で expose される typed operation)

**workflow tool**:
人間の GO/NO-GO 判断ゲートで区切られた粗粒度の MCP tool。`collection.plan` (分析→企画) / `collection.produce` (音源→動画→サムネ) / `collection.publish` (upload→公開後運用) の 3 本。tool 内部で状態管理し、resume 可能。
_Avoid_: orchestrator, pipeline (workflow tool は MCP tool の一種であり、別レイヤーではない)

**primitive tool**:
単一操作を行う細粒度の MCP tool。`audio.master` / `thumbnail.generate` / `analytics.collect` 等。workflow tool が内部で呼ぶほか、agent が直接呼んで細かい制御もできる。

**knowledge codec**:
skill が MCP tool 化後に担う役割。「いつ・どの MCP tool を・どう使うか」のドメイン知識パッケージ。MCP tool の description (WHAT) に対し、knowledge codec は WHEN/HOW を提供する。60+ skill → 5 本に集約: `collection-lifecycle` / `channel-management` / `analytics` / `content-quality` / `distribution`。cutover 時点で下流へ配布する操作面は codec 5 本のみで、旧個別 skill は配布しない (2026-07-03 決定)。旧 skill は codec の設計材料として扱う。
_Avoid_: skill guide, routing layer (knowledge codec は知識の bundled 提供であり、単なるルーティングではない)

**adapter**:
core の MCP tool を各プロトコルへ橋渡しする薄いラッパ。MCP adapter (primary) と CLI adapter (`tayk <cmd>`) がある。
_Avoid_: thin client, thin wrapper (同一概念。canonical は adapter)

**tracer**:
アーキテクチャ規約を確定させるために最初に end-to-end で通す垂直スライス。0 ベース再設計では `collection.plan` (分析→企画を MCP tool + libSQL + CLI adapter で実装) が該当。旧 tracer は `tayk skills list` (#732/#842)。
_Avoid_: PoC (PoC は撤退判定用の別物 #730)

## 動画生成

**renderer**:
collection の映像を生成するバックエンド。`"remotion"`（React コンポーネント → Chromium フレームキャプチャ → ffmpeg エンコード）と `"ffmpeg"`（ffmpeg CLI 直接実行）の 2 種。`config/skills/videoup.json` の `renderer` key で切り替える (ADR-0018)。
_Avoid_: encoder, transcoder (renderer は映像合成 + エンコードの全工程を指す。エンコードだけではない)

## コンテンツ制作

**collection**:
1 本の YouTube 動画としてまとめられる楽曲群とその成果物一式。`collections/planning/<slug>/` で制作し、公開後 `collections/live/` へ移動する。
_Avoid_: アルバム, プレイリスト (collection は YouTube 動画単位の制作物であり、音楽配信のアルバムや YouTube playlist とは別概念)

**collection lifecycle**:
collection の制作フロー。人間の GO/NO-GO ゲートで 3 区間に分かれる:
`分析 → 企画 →[GO/NO-GO]→ サムネ生成 →[GO/NO-GO]→ 音源生成 → MIX/マスタリング → 動画生成 → upload → 公開後運用`。
ゲート 1 (企画後): 「作る / 作らない」。ゲート 2 (サムネ後): 「出す / 出さない」。各区間が workflow tool (`collection.plan` / `collection.produce` / `collection.publish`) に対応する。
_Avoid_: pipeline, workflow (lifecycle は collection 固有の制作工程を指す。汎用の概念ではない)

**master（マスター音源）**:
collection 内の個別トラックをクロスフェード結合した最終音声ファイル (`master.mp3` / `master.wav`)。`generate-master` で結合し `finalize-master` で正規化する 2 段階で生成される。この音声が videoup で動画の音声トラックになる。

## Chrome 拡張

**yield guard (歩留まりガードレール)**:
suno-helper が担う、Suno 生成曲の品質最低ラインを保証する仕組み。feed v3 の `metadata.duration` で尺を検知し、閾値外（短すぎ / 長すぎ）の曲を NG 判定して同一プロンプトで自動再生成する (ADR-0020)。masterup-pairs のキュレーション（ペア選択 + stock 退避）とは別責務 — yield guard は「壊れた曲を弾く」、キュレーションは「良い曲を選ぶ」。
_Avoid_: フィルタ, バリデーション (yield guard は検知 + 自動再生成のループを含む。単なるフィルタではない)

**community-helper**:
YouTube Studio Web のコミュニティ投稿画面に対して DOM 注入を行う Chrome 拡張。`yt-collection-serve` から投稿データ (テキスト + スケジュール日時 + 画像) を取得し、Studio の DOM に自動入力する。suno-helper / distrokid-helper と同列の `extensions/community-helper/` に配置する。
_Avoid_: studio-helper (Studio 全般ではなくコミュニティ投稿専用), community-post-helper (冗長)

**helper extension shell**:
first-party Chrome helper 拡張が共有する構造的な外枠。対象サイト固有の自動化機能を同一にすることではなく、開発ゲート、manifest 管理、server 連携、popup/background/content の責務境界、エラー表示の考え方を揃えるための基準を指す。
_Avoid_: feature parity, UI parity

## マルチチャンネル運用

**channel registry**:
運営者が所有する全 first-party チャンネルリポのパス一覧。`~/.config/tayk/channels.json` に JSON 配列で格納する。各エントリはチャンネルリポの絶対パスのみを持ち、表示名等のメタデータは各リポの `config/channel/meta.json` から動的に解決する（二重管理の回避）。dashboard が消費する。
_Avoid_: channel list, channel config (config は `config/channel/*.json` のこと)

**dashboard**:
全 first-party チャンネルの analytics スナップショットを一覧表示するローカル Web UI。データ収集は行わずビューア専用 — SSOT は各チャンネルの `data/analytics_data_*.json`（将来は local store）。channel registry で対象チャンネルを解決する。
_Avoid_: analytics dashboard (analytics は収集+分析を含意する。dashboard は表示のみ)

## データ

**local store**:
チャンネルリポごとに `<CHANNEL_DIR>/data/local.db` に置く libSQL (Turso) embedded DB。時系列データ (analytics / コスト / 投票 / ベンチマーク) とコレクション状態を保持する SSOT (ADR-0017)。チャンネル設定 (`config/channel/*.json`) は含まない — 設定の SSOT は JSON ファイル。
_Avoid_: database, SQLite (実体は libSQL。SQLite 互換だが区別する)
