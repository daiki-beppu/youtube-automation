# distrokid-helper Chrome 拡張

DistroKid の楽曲登録フォーム (`distrokid.com/new`) に、静的プロファイル（言語 / メインジャンル / サブジャンル / ソングライター 3 分割 / AI 開示）と、コレクション由来の動的データ（アルバム名 / 曲ファイル / ジャケット / リリース日）を自動入力する個人利用向け補助拡張（WXT / Manifest V3 / unpacked）。

データ供給源は `yt-collection-serve` の `GET /distrokid/release.json` / `GET /distrokid/assets/<path>`。

> **送信はしません。** 「続ける」等の送信系操作は拡張から一切行いません（規約遵守）。注入後はユーザーが目視確認し、手動で続行してください。

## スタック

WXT + React + TypeScript + Tailwind CSS + [@webext-core/messaging](https://webext-core.aklinker1.io/messaging/) + [@wxt-dev/storage](https://wxt.dev/storage.html) + Vitest + Playwright。

## ディレクトリ構成

| パス                        | 役割                                                                                           |
| --------------------------- | ---------------------------------------------------------------------------------------------- |
| `wxt.config.ts`             | Manifest V3 定義（最小権限 `storage` / `activeTab`、`host_permissions` は distrokid.com 限定） |
| `entrypoints/background.ts` | service worker（ライフサイクルログのみ）                                                       |
| `entrypoints/content.ts`    | `distrokid.com/new` での DOM 注入（テキスト + popup から受け取った File）                      |
| `entrypoints/popup/`        | popup UI（React）。URL 入力 / データ取得 / レビュー / 一括入力 / 停止 / 進捗                   |
| `components/`               | popup プレゼンテーション部品                                                                   |
| `lib/api.ts`                | `/distrokid/release.json` / assets の fetch client（`ReleaseUnavailableError`）                |
| `lib/asset-transfer.ts`     | popup で fetch した asset を content へ渡すための base64 直列化（CORS 回避）                   |
| `lib/distrokid-injector.ts` | React 互換ネイティブイベント注入 + `DataTransfer` ファイル注入 + セレクタ契約                  |
| `lib/messaging.ts`          | popup ↔ content の型付き channel（`PHASES` 進捗契約）                                         |
| `lib/storage.ts`            | サーバー URL 永続化（既定 `http://localhost:7873`）                                            |
| `lib/types.ts`              | `/distrokid/release.json` の JSON 契約型                                                       |
| `tests/`                    | Vitest unit + Playwright e2e                                                                   |

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

### dir mode（コレクション選択 UI、#934）

複数の disc（アルバム）を管理しているチャンネルには dir mode を使う。

1. コレクションルートを指定してサーバーを起動:
   ```bash
   uv run yt-collection-serve <collections_root> --playlist-capture-root <channel_root>
   # 例: uv run yt-collection-serve collections/ --playlist-capture-root .
   # → GET /distrokid/collections でコレクション一覧を配信
   ```
2. Chrome で `distrokid.com/new` を開く。
3. 拡張ポップアップで **サーバー URL** を確認し **データ取得**（または URL blur 後に自動取得）。
4. popup に **コレクション選択** のドロップダウンが表示される。未配信の disc のみ列挙される。
5. disc を選んで **データ取得** → レビューを確認して **フォーム一括入力**。
6. 目視確認 → **「続ける」を手動押下** → マスタリング選択 → 完了。
7. フィル完了後、拡張が自動的に `POST /distrokid/releases` で配信済み記録を送信し、ドロップダウンから当該 disc が消える。

**配信済み記録の保存先**: `<channel_root>/config/distrokid-releases.json`（`"<collection_id>/<disc>"` キー）。フィルしたが実際には配信しなかった場合は、該当キーを手で削除して「未配信」状態に戻す。

**POST 失敗時**: フィル成功の表示を覆さず、warning メッセージを表示するのみ（補助機能のため）。

### 単一ファイル mode（後方互換）

単一の disc だけを管理している場合や、旧形式でサーバーを起動した場合は従来の動作を引き続き使える。

1. コレクションのディレクトリを指定してサーバーを起動:
   ```bash
   uv run yt-collection-serve collections/planning/<theme>
   # → http://localhost:7873/distrokid/release.json で配信
   ```
   対象チャンネルは `config/channel/distrokid.json` を `enabled: true` + profile 付きにしておく
   （`enabled: false` / 未配置だと `/distrokid/*` が 404 になり、popup がガイダンスを表示する）。
2. Chrome で `distrokid.com/new` を開く。
3. 拡張ポップアップで **サーバー URL**（既定 `http://localhost:7873`）を入力し **データ取得**。
   コレクション選択 UI は表示されない（単一 mode のため）。
4. レビュー表示を確認して **フォーム一括入力**。プロファイル + 動的データがフォームに注入される。
5. 目視確認 → **「続ける」を手動押下** → マスタリング選択 → 完了。

## テスト

```bash
pnpm test                              # Vitest（API client / DOM 注入 / messaging / storage）
pnpm exec playwright install chromium  # 初回のみ
pnpm test:e2e                          # Playwright（distrokid.com/new モックへの注入スモーク）
```

## DOM セレクタの保守

注入先は **id ベース + label 隣接ベース**のセレクタ（`lib/distrokid-injector.ts` の `PROFILE_SELECTORS` / `ALBUM_SELECTORS` / `RELEASE_DATE_SELECTOR` / `FILE_SELECTORS` / `TRACK_FIELD_SELECTORS` / `AI_DISCLOSURE_SELECTORS` / `AI_MODAL_SELECTORS`）で解決する（#813 で実 DOM 検証に基づき name 属性ベースから刷新）。要点:

- **静的プロファイル**（言語 / メイン・サブジャンル）は SELECT の id（`#language` / `#genrePrimary` / `#genreSecondary`）。
- **track 系**は DOM order と index で解決する。タイトルは `[name^="title_"]` を列挙して得た uuid（`resolveTrackUuids`）、songwriter は 3 分割欄 `songwriter_real_name_{first,middle,last}<N>`（1-indexed）、曲ファイルは `#js-track-upload-<N>`。全 track を index 順に注入する（先頭のみではない）。
- **アルバム名**（`#albumTitleInput`）はアルバム時のみ存在するため、要素不在なら skip（シングルモード対応）。
- **ジャケット**は hidden file input `#artwork`。
- **AI 開示**（#877 で実機 DOM 再検証）は **SweetAlert2 modal フロー**で注入する。各 track の gate radio `ai_gate_<uuid>`（value=0「いいえ」/ value=1「はい」）のうち、**1st track の「はい (value=1)」を click すると `.ai-credits-swal-modal`（SweetAlert2）が mount する**。`disabled`（`enabled: false`）の track は全 uuid を「いいえ (value=0)」に確定して終了し、modal は開かない。modal 内では `resolveTrackUuids` で解決した 1st track の uuid を使い、`ai_lyrics_<uuid>` / `ai_music_<uuid>` checkbox、`.distroAiRecordingScope[value="full"|"partial"]` radio、partial 選択時のみ `ai_partial_audio_type_<uuid>` radio（value=vocals/instruments）、`ai_artist_persona_<uuid>_0` radio（value=0「人間」/ value=1「AI ペルソナ」）、`#ai-apply-all-1`（Apply to all songs）checkbox を設定する。**`#ai-apply-all-1` を入れて「保存する」ボタン（`button.swal2-confirm.ai-modal-btn-save`、送信系ではなく modal を閉じるだけ）を click すると、その設定が release 内の全 track（25 tracks 含む）へ伝播する**ため、modal は 1st track 分の **1 回だけ**開閉し 2nd 以降の gate は操作しない。100% AI 楽曲（Suno 等）は `recording_scope: "full"` / `partial_audio_type: null` で part 系 radio に触れない（`partial_audio_type` は `!= null` の loose equality で評価するため `undefined` でも `FieldNotFoundError` を出さない、#877）。
  - **mount/unmount 待ち**: modal の出現は `waitForElement`、消滅は `waitForRemoval` で待つ **async 注入**で、`injectAiDisclosure` / `InjectSession.finish` も async。制限時間 `AI_MODAL_WAIT_TIMEOUT_MS` を超えたら silent skip せず `ModalTimeoutError` で **fail-loud** に停止し popup へ伝播する。
  - **設計の変更経緯**: PR #813 では `#ai-yes` / `#ai-modal` / `[name^="ai_lyrics_"]` / `#ai-apply-all-1` / `#ai-save` を想定し、#866 では「モーダルは存在せず inline 展開・apply_to_all/save 無し」と判断していたが、**#877 の実機検証で再び SweetAlert2 modal フロー（`.ai-credits-swal-modal` / `#ai-apply-all-1` / `button.swal2-confirm.ai-modal-btn-save` が実在）であることが判明**したため、gate を `AI_DISCLOSURE_SELECTORS.gateByUuid`、modal 内フィールドを `AI_MODAL_SELECTORS.{modal,lyricsByUuid,musicByUuid,recordingScope,partialAudioTypeByUuid,artistPersonaByUuid,applyAll,saveButton}` に再刷新した。実 DOM が変われば `tests/distrokid-injector.test.ts` と `tests/e2e/inject.spec.ts` のセレクタ固定テストで検知できる。

テキスト/SELECT 解決時は `extensions/shared/visibility.ts::isVisible` で hidden 要素（type=hidden の `#artistName` 等）を排除する。注入先が見つからない場合は **silent skip せず `FieldNotFoundError` で停止** し、popup にエラーを表示する。セレクタを更新する際は、実 DOM 構造をミラーしたモックフォーム `tests/e2e/fixtures/distrokid-new.html` も合わせて更新する。

## リリース日（release_date）の契約（#932）

リリース日の供給元はコレクションの `workflow-state.json::planning.publish_target_at`。`yt-collection-serve` が ISO 8601 形式（`"2026-03-22T08:00:00+09:00"` のような full datetime、または `"2026-03-22"` のような date のみ）を `YYYY-MM-DD` へ正規化し、`GET /distrokid/release.json` の `release.release_date` として配信する（`publish_target_at` 未設定時は `null` で、注入はスキップされフォームは空のまま）。

注入先の `#release-date-dp` は `<input type="date">` であり `YYYY-MM-DD` 以外を受け付けないため、serve 側で正規化を完結させる。拡張側（`injectReleaseDate`）は受け取った `YYYY-MM-DD` 文字列をそのまま注入する。

`#release-date-dp` が DOM に存在しない場合（DistroKid の契約プランがリリース日指定非対応）は、`FieldNotFoundError` を投げず `console.warn` + skip し、フィル全体は続行する。

## CORS と asset の取得経路

サーバー（`yt-collection-serve`）は CORS をデフォルトで `chrome-extension://` オリジンと helper サイト web origin（`https://distrokid.com` / `https://www.distrokid.com`）に許可する（#896）。`--allow-origin <origin>` で単一 origin の完全一致に固定もできる。

このため `release.json` と asset（曲 / ジャケット）の **fetch はすべて popup（`chrome-extension://` origin）で行う**。#896 でサーバーが `distrokid.com` origin もデフォルト許可したが、distrokid-helper 拡張本体を content script fetch へ書き換えるのは #896 のスコープ外（別 issue）であり、現状の popup fetch 構成を維持する。popup で取得した File を `lib/asset-transfer.ts` の base64 直列化で content へ転送し、content 側で File に復元して `<input type=file>` に注入する。`host_permissions` を `distrokid.com` 限定に保ったまま（要件 #2）asset 注入を成立させるための構成。

## スコープ外

- 「続ける」ボタンの自動押下 / マスタリング画面・有料オプションの自動操作（規約遵守・誤課金回避）
- Chrome Web Store への公開（unpacked 個人利用のみ）
- Firefox / Safari 等の他ブラウザ対応
- DistroKid 以外の配信サービス（TuneCore / CD Baby / The Orchard）
