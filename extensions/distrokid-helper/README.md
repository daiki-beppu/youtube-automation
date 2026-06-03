# distrokid-helper Chrome 拡張

DistroKid の楽曲登録フォーム (`distrokid.com/new`) に、静的プロファイル（言語 / メインジャンル / サブジャンル / ソングライター 3 分割 / AI 開示）と、コレクション由来の動的データ（アルバム名 / 曲ファイル / ジャケット / リリース日）を自動入力する個人利用向け補助拡張（WXT / Manifest V3 / unpacked）。

データ供給源は `yt-collection-serve` の `GET /distrokid/release.json` / `GET /distrokid/assets/<path>`。

> **送信はしません。** 「続ける」等の送信系操作は拡張から一切行いません（規約遵守）。注入後はユーザーが目視確認し、手動で続行してください。

## スタック

WXT + React + TypeScript + Tailwind CSS + [@webext-core/messaging](https://webext-core.aklinker1.io/messaging/) + [@wxt-dev/storage](https://wxt.dev/storage.html) + Vitest + Playwright。

## ディレクトリ構成

| パス | 役割 |
|---|---|
| `wxt.config.ts` | Manifest V3 定義（最小権限 `storage` / `activeTab`、`host_permissions` は distrokid.com 限定） |
| `entrypoints/background.ts` | service worker（ライフサイクルログのみ） |
| `entrypoints/content.ts` | `distrokid.com/new` での DOM 注入（テキスト + popup から受け取った File） |
| `entrypoints/popup/` | popup UI（React）。URL 入力 / データ取得 / レビュー / 一括入力 / 停止 / 進捗 |
| `components/` | popup プレゼンテーション部品 |
| `lib/api.ts` | `/distrokid/release.json` / assets の fetch client（`ReleaseUnavailableError`） |
| `lib/asset-transfer.ts` | popup で fetch した asset を content へ渡すための base64 直列化（CORS 回避） |
| `lib/distrokid-injector.ts` | React 互換ネイティブイベント注入 + `DataTransfer` ファイル注入 + セレクタ契約 |
| `lib/messaging.ts` | popup ↔ content の型付き channel（`PHASES` 進捗契約） |
| `lib/storage.ts` | サーバー URL 永続化（既定 `http://localhost:7873`） |
| `lib/types.ts` | `/distrokid/release.json` の JSON 契約型 |
| `tests/` | Vitest unit + Playwright e2e |

## 開発フロー

依存インストール（pnpm）:

```bash
pnpm install
```

開発（HMR 付き、Chrome を自動起動）:

```bash
pnpm dev
```

## ビルド

```bash
pnpm build      # .output/chrome-mv3/ に Manifest V3 拡張を生成
pnpm zip        # 配布用 zip を生成
```

型チェック（WXT 型生成 + tsc）:

```bash
pnpm compile
```

## unpacked ロード

1. `pnpm build` で `.output/chrome-mv3/` を生成する。
2. Chrome で `chrome://extensions` を開く。
3. 右上の **デベロッパーモード** を ON。
4. **パッケージ化されていない拡張機能を読み込む** → `.output/chrome-mv3/` を選択。

## 使い方

1. コレクション完成後、サーバーを起動:
   ```bash
   uv run yt-collection-serve collections/planning/<theme>
   # → http://localhost:7873/distrokid/release.json で配信
   ```
   対象チャンネルは `config/channel/distrokid.json` を `enabled: true` + profile 付きにしておく
   （`enabled: false` / 未配置だと `/distrokid/*` が 404 になり、popup がガイダンスを表示する）。
2. Chrome で `distrokid.com/new` を開く。
3. 拡張ポップアップで **サーバー URL**（既定 `http://localhost:7873`）を入力し **データ取得**。
4. レビュー表示を確認して **フォーム一括入力**。プロファイル + 動的データがフォームに注入される。
5. 目視確認 → **「続ける」を手動押下** → マスタリング選択 → 完了。

## テスト

```bash
pnpm test                              # Vitest（API client / DOM 注入 / messaging / storage）
pnpm exec playwright install chromium  # 初回のみ
pnpm test:e2e                          # Playwright（distrokid.com/new モックへの注入スモーク）
```

## DOM セレクタの保守

注入先は **id ベース + label 隣接ベース**のセレクタ（`lib/distrokid-injector.ts` の `PROFILE_SELECTORS` / `ALBUM_SELECTORS` / `RELEASE_DATE_SELECTOR` / `FILE_SELECTORS` / `TRACK_FIELD_SELECTORS` / `AI_DISCLOSURE_SELECTORS`）で解決する（#813 で実 DOM 検証に基づき name 属性ベースから刷新）。要点:

- **静的プロファイル**（言語 / メイン・サブジャンル）は SELECT の id（`#language` / `#genrePrimary` / `#genreSecondary`）。
- **track 系**は DOM order と index で解決する。タイトルは `[name^="title_"]` を列挙して得た uuid（`resolveTrackUuids`）、songwriter は 3 分割欄 `songwriter_real_name_{first,middle,last}<N>`（1-indexed）、曲ファイルは `#js-track-upload-<N>`。全 track を index 順に注入する（先頭のみではない）。
- **アルバム名**（`#albumTitleInput`）はアルバム時のみ存在するため、要素不在なら skip（シングルモード対応）。
- **ジャケット**は hidden file input `#artwork`。
- **AI 開示モーダル**（Suno 楽曲は通過必須）は「はい」radio を選択した後、`MutationObserver` でモーダル（`#ai-modal`）の展開を待ってから checkbox を注入する（polling しない）。歌詞 `ai_lyrics_` / 作曲 `ai_music_` / apply-all `ai-apply-all-` は属性で、「音声すべて / 音声の一部」は name 属性が無いためモーダル内 checkbox の DOM order（`input[type="checkbox"]` の 3・4 番目）で識別する。確定は「保存する」ボタン（モーダル内 commit。wizard 進行ではない）。
  - **暫定**: 「音声すべて / 音声の一部」の DOM order 依存は実機の安定識別子が未確定なため（#813 スコープ外）の暫定実装。`tests/distrokid-injector.test.ts` の `injectAiDisclosure` テストが `[歌詞, 作曲, 音声すべて, 音声の一部, apply-all]` の order 前提を fixture 上に固定しており、実機 DOM が変われば検知できる。実機の name / `data-testid` / label テキスト等の安定識別子が判明し次第、order 依存から属性ベースへ差し替える。

テキスト/SELECT 解決時は `extensions/shared/visibility.ts::isVisible` で hidden 要素（type=hidden の `#artistName` 等）を排除する。注入先が見つからない場合は **silent skip せず `FieldNotFoundError` で停止** し、popup にエラーを表示する。セレクタを更新する際は、実 DOM 構造をミラーしたモックフォーム `tests/e2e/fixtures/distrokid-new.html` も合わせて更新する。

## CORS と asset の取得経路

サーバー（`yt-collection-serve`）は CORS を `chrome-extension://` オリジンのみ許可する。`--allow-origin chrome-extension://<id>` で特定拡張 ID に固定もできる。

このため `release.json` と asset（曲 / ジャケット）の **fetch はすべて popup（`chrome-extension://` origin）で行う**。content script の fetch はページ origin（`distrokid.com`）で CORS 評価され遮断されるため、popup で取得した File を `lib/asset-transfer.ts` の base64 直列化で content へ転送し、content 側で File に復元して `<input type=file>` に注入する。`host_permissions` を `distrokid.com` 限定に保ったまま（要件 #2）asset 注入を成立させるための構成。

## スコープ外

- 「続ける」ボタンの自動押下 / マスタリング画面・有料オプションの自動操作（規約遵守・誤課金回避）
- Chrome Web Store への公開（unpacked 個人利用のみ）
- Firefox / Safari 等の他ブラウザ対応
- DistroKid 以外の配信サービス（TuneCore / CD Baby / The Orchard）
