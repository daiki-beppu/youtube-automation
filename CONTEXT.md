# tayk

YouTube チャンネル運営を自動化するツールキット (旧 `youtube-channels-automation`、ADR-0007 で `tayk` に rebrand)。Python から TypeScript(bun) へ big-bang 移行中 (epic #727)。本ファイルは実装詳細ではなく、本プロジェクト固有の用語の正書を定める **グロッサリ**である。

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
本ツールを消費する 5 リポ前後のチャンネルリポジトリ。すべて運営者自身のもので第三者 consumer は存在しない (rebrand / 載せ替えコストの判断前提)。

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

**service**:
`packages/core/src/<feature>/service.ts` の単一エントリ関数。input schema を受け `Result` を返す。重い外部依存 (googleapis / sharp 等) を内包してよい唯一の層 (ADR-0002/0003)。

**adapter**:
core の service を各プロトコルへ橋渡しする薄いラッパ。CLI adapter (`packages/cli/src/commands/<feature>/`) と MCP adapter (将来) があり、registry を介して service を呼ぶ。schema や重い依存を再宣言しない。
_Avoid_: thin client, thin wrapper (同一概念。canonical は adapter)

**registry**:
feature 名 → {description, schema, service, deps} の data map。**core が所有**し (`packages/core/src/registry.ts`)、CLI / MCP は import して各自のプロトコルへ変換する (ADR-0004)。cli ↔ mcp は相互 import しない。

**DepsMap**:
service が要求しうる重い依存の型対応表。`config` (ChannelConfig) / `yt` (YouTube Data API client) / `ytAnalytics` (YouTube Analytics API client) を持つ。各 service は `deps` 配列で必要なキーだけを宣言し、`Pick<DepsMap, D>` で compile-time 検査される (ADR-0004 §2)。CLI adapter の `resolveDeps()` が entry.deps を見て lazy に構築する (#993)。
_Avoid_: dependency injection container (DepsMap は DI container ではなく typed data map)

**tracer**:
アーキテクチャ規約を確定させるために最初に end-to-end で通す垂直スライス。本プロジェクトでは `tayk skills list` (旧 `yt-skills list`、#732/#842) が該当。
_Avoid_: PoC (PoC は撤退判定用の別物 #730)

## 動画生成

**renderer**:
collection の映像を生成するバックエンド。`"remotion"`（React コンポーネント → Chromium フレームキャプチャ → ffmpeg エンコード）と `"ffmpeg"`（ffmpeg CLI 直接実行）の 2 種。`config/skills/videoup.json` の `renderer` key で切り替える (ADR-0010)。
_Avoid_: encoder, transcoder (renderer は映像合成 + エンコードの全工程を指す。エンコードだけではない)

## コンテンツ制作

**collection**:
1 本の YouTube 動画としてまとめられる楽曲群とその成果物一式。`collections/planning/<slug>/` で制作し、公開後 `collections/live/` へ移動する。ライフサイクルは 企画 → 音源 → videoup → upload → 公開 → analytics-collect → playlist 反映。
_Avoid_: アルバム, プレイリスト (collection は YouTube 動画単位の制作物であり、音楽配信のアルバムや YouTube playlist とは別概念)

**master（マスター音源）**:
collection 内の個別トラックをクロスフェード結合した最終音声ファイル (`master.mp3` / `master.wav`)。`generate-master` で結合し `finalize-master` で正規化する 2 段階で生成される。この音声が videoup で動画の音声トラックになる。

## Chrome 拡張

**community-helper**:
YouTube Studio Web のコミュニティ投稿画面に対して DOM 注入を行う Chrome 拡張。`yt-collection-serve` から投稿データ (テキスト + スケジュール日時 + 画像) を取得し、Studio の DOM に自動入力する。suno-helper / distrokid-helper と同列の `extensions/community-helper/` に配置する。
_Avoid_: studio-helper (Studio 全般ではなくコミュニティ投稿専用), community-post-helper (冗長)

## マルチチャンネル運用

**channel registry**:
運営者が所有する全 first-party チャンネルリポのパス一覧。`~/.config/tayk/channels.json` に JSON 配列で格納する。各エントリはチャンネルリポの絶対パスのみを持ち、表示名等のメタデータは各リポの `config/channel/meta.json` から動的に解決する（二重管理の回避）。dashboard が消費する。
_Avoid_: channel list, channel config (config は `config/channel/*.json` のこと)

**dashboard**:
全 first-party チャンネルの analytics スナップショットを一覧表示するローカル Web UI。データ収集は行わずビューア専用 — SSOT は各チャンネルの `data/analytics_data_*.json`（将来は local store）。channel registry で対象チャンネルを解決する。
_Avoid_: analytics dashboard (analytics は収集+分析を含意する。dashboard は表示のみ)

## データ

**local store**:
チャンネルリポごとに `<CHANNEL_DIR>/data/local.db` に置く libSQL (Turso) embedded DB。時系列データ (analytics / コスト / 投票 / ベンチマーク) とコレクション状態を保持する SSOT (ADR-0009)。チャンネル設定 (`config/channel/*.json`) は含まない — 設定の SSOT は JSON ファイル。
_Avoid_: database, SQLite (実体は libSQL。SQLite 互換だが区別する)
