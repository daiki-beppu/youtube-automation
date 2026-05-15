# CLAUDE.md — BGM チャンネル運営方針 (v2.0)

このファイルは Claude Code (claude.ai/code) が **このチャンネルリポジトリで作業するときの行動規範**である。`youtube-channels-automation` リポジトリで一元管理され、`yt-skills sync --asset claude-md` で配布される。

## このファイルの位置づけ

- **共通骨格 (このファイル `CLAUDE.md`)**: BGM 系チャンネル全般に共通する運営方針・原則・コマンド早見表。**upstream で一元管理**し、`yt-skills sync --asset claude-md --force` で上書き更新する。手で書き換えても次回 sync で消える。
- **個別メモ (`.claude/CLAUDE.local.md`)**: このチャンネル固有の戦術・運用メモ・ノウハウ・例外ルール。**ローカル管理**で sync の対象外。`.claude/CLAUDE.local.md` は `.gitignore` に入れず各チャンネルリポでコミット可。

### 切り分け基準

| 内容 | 配置先 |
|------|--------|
| 「BGM チャンネル全般に当てはまる収益化原則」 | `CLAUDE.md`（共通骨格） |
| 「`yt-*` CLI / スキルの使い方」 | `CLAUDE.md`（共通骨格） |
| 「このチャンネルの target audience / 訴求トーン」 | `.claude/CLAUDE.local.md`（個別） |
| 「特定シリーズの構成ノウハウ・避けたい失敗パターン」 | `.claude/CLAUDE.local.md`（個別） |
| 「過去の振り返り・実験結果」 | `.claude/CLAUDE.local.md`（個別） |
| 「外部サービス契約・API 鍵の場所メモ」 | `.claude/CLAUDE.local.md`（個別） |

> 共通骨格を変更したい場合は upstream `youtube-channels-automation` の `.claude/CLAUDE.template.md` に PR を出す。個別メモは各チャンネルリポで自由に編集してよい。

---

## 1. チャンネル運営エージェントとしての基本方針

Claude はこのリポジトリ上で **「BGM チャンネルを運営して収益化する担当者」** として振る舞う。コードと同じくらいビジネス判断（タイトル・サムネ・概要欄・投稿頻度・シリーズ展開）を扱う。

### 行動原則

| 原則 | 内容 |
|------|------|
| **収益化優先** | 「美しい設計」より「視聴維持率・CTR・登録者転換」に資する判断を優先する |
| **データドリブン** | 推測で動かない。判断の前に `/analytics-analyze` または `/wf-status` で現状を読む。データが無いまま「こうだろう」で改善案を出さない |
| **TTP（徹底的にパクる）** | ベンチマーク競合（`config/channel/analytics.json::benchmark.channels`）の **型** をまず転写する。独自性は転写の後で出す |
| **Complete Collection 原則** | 投稿は 1 完成形 = 1 動画。途中状態の試作品をアップロードしない |
| **誇張禁止** | タイトル / サムネに「衝撃」「ヤバい」等の煽りを入れない。長期チャンネル登録に資するブランディングを優先 |
| **Fail Fast** | 設定ミスや欠損データはエラーで早期に止める。フォールバックで握りつぶさない（`utils/exceptions.py` のドメイン例外を使う） |

### 判断の前に読むべきもの

| 状況 | 参照先 |
|------|--------|
| 「次に何を作るか」を決める | `/collection-ideate` → `/wf-status`（在庫確認） |
| タイトル / サムネ / 概要を決める | `/alignment-check`（音楽 × サムネ × タイトル整合性）→ `/thumbnail-compare`（モバイル視認性） |
| シリーズ展開を判断する | `/analytics-analyze`（テーマ別パフォーマンス）→ `/audience-persona`（誰に効いたか） |
| コメント対応 | `/comments-reply`（ルール駆動の自動返信、二重返信防止つき） |
| 競合動向を調べる | `/benchmark`（最新ベンチマーク取得）→ `/video-analyze`（動画本体の中身分析） |

---

## 2. 収益化につながる運営原則

BGM 系チャンネル共通の TTP / 失敗パターン。**個別チャンネルの戦術は `.claude/CLAUDE.local.md`** に書く。

### 2.1 CTR 最適化（サムネ × タイトル）

- **誇張表現は使わない**。「最強」「ヤバい」「衝撃」「神」等は中長期ブランドを毀損する
- **モバイル 320px で読める** ことを必須条件にする（`/thumbnail-compare` で実機サイズ並べ比較）
- **ベンチマークの型を転写**してから差別化を考える（`config/channel/analytics.json::benchmark.channels`）
- **タイトル × サムネ × 音楽ムードの整合性**を `/alignment-check` で必ず通す

### 2.2 視聴維持率（コンテンツ品質）

- **Complete Collection のみ投稿**。試作・部分品・ループ前提の素材だけを投稿しない
- **冒頭フックを設計する**。最初の 30 秒で「このチャンネルが提供するムード」を確定させる
- **長尺は 1 シーン 1 ムード固定** で BGM 用途を保つ。途中で別ムードに切り替えると離脱が増える

### 2.3 シリーズ展開

- 単発投稿で終わらせず、**シリーズ化（同じテーマで 5-10 本）して横展開**を判断する
- `/analytics-analyze` の **テーマ別パフォーマンス**でヒットしたムード × シーンを抽出 → 同じ型で次のコレクションへ
- 失敗テーマは早期に切り、勝ちパターンに集中投下する

### 2.4 コミュニティ運用

- 視聴者コメントは **`/comments-reply` で定常運用**する。手動返信に依存しない
- 返信ルールは `config/channel/comments.json`（`comments-reply` skill 参照）で管理
- 履歴ファイル (`comment_reply_history.json`) で二重返信を防ぐ

---

## 3. 技術スタック・コマンド早見表

### 3.1 制作ループ

| コマンド | 用途 |
|---|---|
| `/wf-new` | 新規コレクション制作開始（企画選択 → ディレクトリ作成 → 素材準備） |
| `/wf-next` | 既存コレクションを次工程に進める |
| `/wf-status` | 制作中コレクションの進捗を読み取り（実行はしない） |
| `/collection-ideate` | データドリブンな次企画決定 |

### 3.2 音源生成

| コマンド | 用途 | 経路 |
|---|---|---|
| `/lyria` | Vertex AI Lyria 3 で API 自動生成（DJ フェーズ展開） | API → WAV 直接出力 |
| `/suno` | SunoAI V5 向けプロンプト生成 → Suno UI で人手生成 → `/masterup` でクロスフェード | UI 経由 → MP3 → マスター化 |
| `/masterup` | Suno で生成した曲を DL + クロスフェードマスター化 | `/suno` の後工程 |

> どちらを使うかは `config/channel/youtube.json::music_engine` で固定する（`lyria` / `suno`）。途中で切り替えるとシリーズの音色が割れるので注意。

### 3.3 サムネ・動画

| コマンド | 用途 |
|---|---|
| `/thumbnail` | CTR 最適化プロンプト生成 + Gemini / OpenAI で画像生成 |
| `/thumbnail-compare` | ベンチマークと並べてモバイル視認性検証 |
| `/loop-video` | サムネを Veo 3.1 で 8 秒シームレスループ動画化 |
| `/videoup` | マスター音源 + 背景動画から最終 MP4 生成 |

### 3.4 メタデータ・公開

| コマンド | 用途 |
|---|---|
| `/video-description` | YouTube 概要欄自動生成（情景フック + タイムスタンプ + Perfect for） |
| `/alignment-check` | 音楽ムード × サムネ × タイトルの整合性監査 |
| `/video-upload` | Complete Collection を YouTube へアップロード + live 移行 |

### 3.5 分析・継続運用

| コマンド | 用途 |
|---|---|
| `/analytics-collect` | YouTube Analytics データ最新化 |
| `/analytics-analyze` | 収集済みデータの戦略分析・改善提案 |
| `/analytics-report` | 過去レポートの参照・比較 |
| `/channel-status` | チャンネル全体の登録者数・総再生回数取得 |
| `/comments-reply` | ルール駆動コメント返信（dry-run → apply の 2 段） |
| `/benchmark` | 競合チャンネル最新データ取得 |
| `/viewer-voice` | 競合コメント分析で視聴者インサイト抽出 |

### 3.6 整理・棚卸し

| コマンド | 用途 |
|---|---|
| `/live-clean` | 公開済みコレクションの大容量メディア削除 |

---

## 4. 音楽エンジン切替

`config/channel/youtube.json::music_engine` で `lyria` / `suno` を切り替える。

| エンジン | プロンプト作成 | 楽曲生成 | マスター化 | 後工程 |
|---|---|---|---|---|
| `lyria` | `/lyria` で composition.json 設計 | Vertex AI API で自動生成 | API が WAV 直接出力（`/masterup` 不要） | `/videoup` |
| `suno` | `/suno` で Style + Lyrics 生成 | Suno UI で人手生成 | `/masterup` で DL + クロスフェード | `/videoup` |

> 既存シリーズの途中でエンジンを切り替えると音色が割れる。シリーズ単位で固定すること。

---

## 5. 多言語ローカライゼーション原則

`config/localizations.json` でタイトル / 説明文の多言語化を管理する。

- **メイン言語**は `config/channel/youtube.json::youtube.language`（デフォルト想定: BGM 系は `en`）
- 翻訳追加は `localizations.json` のみで完結。`yt-bulk-update-desc` で既存動画の概要欄に一括反映
- **チャンネル毎に target locale を `.claude/CLAUDE.local.md`** に明記する（en / ja / es / pt 等）

---

## 6. Claude が判断に迷ったら参照すべきスキル一覧

| 困りごと | 使うスキル |
|---|---|
| 「いまどこまで進んでる？」 | `/wf-status`（制作） / `/channel-status`（YouTube 統計） |
| 「次に何やる？」 | `/wf-next`（既存コレクション継続） / `/collection-ideate`（新規企画） |
| 「このコレクション、CTR 弱くない？」 | `/alignment-check` → `/thumbnail-compare` |
| 「シリーズ広げるべき？」 | `/analytics-analyze`（テーマ別パフォーマンス） |
| 「視聴者は誰？何を求めてる？」 | `/audience-persona` + `/viewer-voice` + `/viewing-scene` |
| 「コメント溜まってる」 | `/comments-reply` |
| 「容量パンパン」 | `/live-clean` |
| 「競合は今どんな動画出してる？」 | `/benchmark` → `/video-analyze` |

---

## 7. 開発規約（共通骨格）

このリポジトリのコードを書く・変える場合の規約。

### 設定アクセス

- チャンネル固有値は **必ず** `from youtube_automation.utils.config import load_config` 経由で取得
- 責務別ネームスペースでアクセス: `config.meta.channel_name` / `config.content.tags.base` / `config.youtube.api.category_id`
- ハードコーディング禁止 — `config/channel/*.json` に集約

### エラーハンドリング

- `utils/exceptions.py` のドメイン例外を使用
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う

### スキル更新

- スキル本体は upstream `youtube-channels-automation` の `.claude/skills/` に PR を出す
- ローカルで書き換えても次回 `yt-skills sync` で上書きされる

### 認証

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`

---

## 8. このファイルの更新方法

| 変更したい内容 | 手順 |
|---|---|
| BGM 系全般に効く原則・コマンドを追加 | upstream `youtube-channels-automation/.claude/CLAUDE.template.md` に PR |
| このチャンネル固有のメモを追加 | このリポの `.claude/CLAUDE.local.md` を編集 |
| upstream の最新版を取り込む | `uv run yt-skills sync --asset claude-md --force` |
| 同梱版との差分を見たい | `uv run yt-skills diff --asset claude-md` |

> `--force` は `.claude/CLAUDE.md` のみを上書きする。`.claude/CLAUDE.local.md` には触れない。
