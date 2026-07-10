# suno-helper Chrome 拡張

`/suno` が生成した `suno-prompts.json` を Suno Custom Mode に順次注入し、Generate を連続実行する個人利用向け補助拡張（WXT + React + TypeScript + Tailwind CSS / Manifest V3 / unpacked）。

> reCAPTCHA・トークン消費・速度の問題を避けるため、ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かす設計です。

## 構成

| パス                                 | 役割                                                                                                        |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `wxt.config.ts`                      | manifest を自動生成（権限 `storage` / `activeTab` / `downloads` / `debugger` は `lib/manifest.ts` が SSOT） |
| `entrypoints/background.ts`          | service worker（Download all ZIP 監視、server token 取得、downloaded POST 中継）                            |
| `entrypoints/content.ts`             | Suno UI への注入と Generate 連続実行のフロー制御                                                            |
| `entrypoints/suno-bridge.content.ts` | MAIN world fetch bridge（#948）。Suno API の生成投入 / clip status を passive 観測                          |
| `entrypoints/popup/`                 | popup の HTML / エントリ（React + Tailwind）                                                                |
| `components/`                        | popup UI（`App.tsx` / `PatternList.tsx` / `useSunoRunner.ts`）                                              |
| `lib/messaging.ts`                   | popup ⇄ content の型付き message（@webext-core/messaging）                                                  |
| `lib/clip-tracker.ts` ほか           | bridge 観測の集計（in-flight / ACK / stall。`bridge-listener` / `ack-probe` / `entry-retry`）               |
| `lib/storage.ts`                     | ローカル配信元候補 / resume state / overlay state の型付き storage（@wxt-dev/storage）                      |
| `lib/manifest.ts`                    | 最小権限定数 `MANIFEST_PERMISSIONS`                                                                         |
| `../shared/`                         | DOM 注入 / API client / origin allowlist / 契約定数（複数拡張で共有）                                       |

DOM 注入セレクタ（Style / Lyrics の placeholder、Generate ボタンのラベル、reCAPTCHA 検知）は `../shared/dom.ts` の `SELECTORS` に集約する。Suno の UI 変更で注入先が見つからなくなった場合はここを更新する。見つからない場合は **silent に続行せず停止** し、popup に理由を表示する。

## Agent 操作用 DOM signal

browser use から overlay / popup を安定して観測できるよう、操作 panel は読み取り専用の `data-suno-*` 属性を持つ。これらは表示状態の公開契約であり、runner の実行制御や server API 契約は変更しない。

| selector / 属性                                                                                 | 意味                                                                                                      |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `[data-suno-helper="control-panel"]`                                                            | 操作 panel の root                                                                                        |
| `data-suno-phase`                                                                               | `idle` / `loading` / `starting` / progress phase（`waiting-captcha` / `entry-failed` を含む）/ `adopting` |
| `data-suno-running`                                                                             | runner 実行中なら `"true"`                                                                                |
| `data-suno-error`                                                                               | status がエラーなら `"true"`                                                                              |
| `data-suno-collection-id`                                                                       | 選択中 collection id                                                                                      |
| `data-suno-entry-count`                                                                         | 読み込み済み entry 数                                                                                     |
| `data-suno-selected-entry-count`                                                                | 実行対象 entry 数                                                                                         |
| `[data-suno-control="server-url"]`                                                              | サーバー URL 入力                                                                                         |
| `[data-suno-control="collection-select"]`                                                       | collection 選択                                                                                           |
| `[data-suno-control="fetch-data"]` / `[data-suno-control="run"]` / `[data-suno-control="stop"]` | 主要操作ボタン                                                                                            |
| `[data-suno-control="resume"]` / `[data-suno-control="dismiss-resume"]`                         | 前回中断 resume バナーの再開 / 閉じる                                                                     |
| `[data-suno-control="adopt-selected-clips"]`                                                    | Suno 上の選択中 clip を採用                                                                               |
| `[data-suno-control="retry-playlist"]` / `[data-suno-control="retry-download"]`                 | playlist / download phase から再開                                                                        |
| `role="status"` + `data-suno-status`                                                            | live status。`data-suno-status="error"` は handoff / retry 判断の入口                                     |
| `[data-suno-entry-list]` / `[data-suno-entry-index]`                                            | entry 一覧。各行に `data-suno-entry-state` と `data-suno-entry-selected` が付く                           |

## 開発・ビルド・テスト

ローカル検証は CI・lockfile と同じ pnpm 11.11.0 に固定する。ambient `pnpm` の版は各環境で異なり得るため、以下の pinned command を使う。理由と両拡張共通の release 前検証は `extensions/README.md::pnpm バージョン契約` を参照する。

```bash
npx -y pnpm@11.11.0 install --frozen-lockfile  # postinstall で wxt prepare
npx -y pnpm@11.11.0 dev                                           # 開発（HMR）
npx -y pnpm@11.11.0 build                                         # 本番ビルド → .output/chrome-mv3/
npx -y pnpm@11.11.0 zip                                           # 配布用 zip
npx -y pnpm@11.11.0 compile                                       # 型チェック（tsc --noEmit）
npx -y pnpm@11.11.0 test                                          # Vitest unit
npx -y pnpm@11.11.0 exec playwright install chromium              # Playwright 初回のみ
npx -y pnpm@11.11.0 test:e2e                                      # Playwright e2e
```

## インストール（unpacked）

1. `npx -y pnpm@11.11.0 install --frozen-lockfile && npx -y pnpm@11.11.0 build` を実行。
2. build artifact を basename が `suno-helper` になる固定パスへコピーする:
   ```bash
   mkdir -p "$HOME/chrome-extensions/suno-helper"
   rsync -a --delete .output/chrome-mv3/ "$HOME/chrome-extensions/suno-helper/"
   ```
3. Chrome で `chrome://extensions` を開く。
4. 右上の **デベロッパーモード** を ON。
5. **パッケージ化されていない拡張機能を読み込む** → `$HOME/chrome-extensions/suno-helper` を選択。

## 使い方

1. ターミナルで collection 一覧サーバーを `suno-helper` の拡張 origin に固定して起動:
   ```bash
   uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \
     --allow-extension suno-helper
   # → http://<channel>.localhost:7873/collections と /auth/token を配信
   ```
2. Chrome で Suno の **Custom Mode** 画面を開く。
3. 拡張アイコンからポップアップを開き、**ローカル配信元** でチャンネル名つき候補を選んで **データ取得**。
4. `ready` な collection を選び、**全パターンを連続実行** を押す。
5. 各パターンで Style/Lyrics を注入 → Generate 押下 → 生成完了検知 → 次へ、を自動で繰り返す。
6. 全件完了後、対象 clip を一括選択 → playlist 追加 → More menu の **Download all** → format 選択 → ZIP ダウンロード完了監視 → `POST /collections/<id>/downloaded` で ZIP パス通知、まで実行する。サーバーは ZIP を展開し、`02-Individual-music/` と `workflow-state.json` を更新する。
7. captcha challenge は waiting-captcha 表示で解消（多くは自動 verify）を待って続行する。entry 単位の一時的な失敗は Balanced 固定の上限で自動リトライし、上限超過分はスキップして完走する（#948）。スキップされた entry は一覧表示され、**失敗分のみ再実行** で再投入できる。

### in-flight 検知と停止判断（#948）

- **in-flight カウント**: MAIN world bridge（`suno-bridge.content.ts`）が Suno API（`POST /api/generate/v2-web/` / `POST /api/feed/v3`）のレスポンスを観測し、clip status（complete/error 以外 = in-flight）で数える。「Remix ボタン disabled = 生成中」の旧 DOM プロキシは生成完了後も disabled が残り過大カウントするため fallback 専用（縮退中は popup に「bridge 未観測: DOM 計数で待機中」と表示される）
- **停止判断**: queue 空き待ちは固定 timeout ではなく stall ベース（in-flight 集合が 10 分間まったく変化しないときのみ ERROR）。run 全体を止めるのは `FatalRunError`（DOM セレクタ不在 / captcha 手動解決 timeout / queue stall / Lyrics 全注入方式失敗）のみ
- **Bearer token**: bridge が MAIN world ローカルに保持し extension 側へは渡さない。401 で破棄しページの次リクエストで自動再捕捉

## Origin / token 契約

`GET /auth/token` と `POST /collections/<id>/downloaded` は、`--allow-extension suno-helper` で解決した exact origin 以外を 403 にする。`--allow-extension` は macOS Chrome profile の `Secure Preferences` を優先し、無ければ `Preferences` を読み、`extensions.settings[*].path` が絶対パスかつ basename is `suno-helper` の unpacked extension ID から `chrome-extension://<id>` を組み立てる。

検出 0 件、複数 ID、Preferences read failure、JSON parse failure の場合だけ、Chrome の `chrome://extensions` で suno-helper の拡張 ID を確認し、手動 fallback として `--allow-origin "chrome-extension://<EXTENSION_ID>"` を指定する。`.output/chrome-mv3/` を直接ロードすると basename is `chrome-mv3` になり `--allow-extension suno-helper` では検出できないため、通常は `$HOME/chrome-extensions/suno-helper` のような固定パスをロードする。

`/auth/token` が返す token は Download all 完了通知時に `X-Serve-Token` として送るため、`--allow-extension` または fallback の `--allow-origin` なし起動では ZIP 展開・DL 完了記録は動かない。

`GET /collections` などの読み取り API と違い、downloaded POST は workflow-state と `02-Individual-music/` を更新する書き込み境界なので、origin と token の両方を必須にしている。

## ローカル配信元 selector

`yt-collection-serve` は起動時に `http://<channel>.localhost:<PORT>` 形式の URL と selector label を表示し、`GET /server-info` でも同じ情報を返す。拡張は `データ取得` 成功時にこの label と URL を保存するため、複数チャンネルのサーバーを使い分ける場合は popup の **ローカル配信元** からチャンネル名を見て選択する。

後方互換として `http://localhost:7873` も既定候補に残しているが、新規運用ではチャンネル別 hostname を使う。

## スコープ外

- Chrome Web Store への公開（unpacked + GitHub Release zip 配布のみ）
- 他ブラウザ対応 / 歌詞編集機能 / 自動ログイン
- 実 Suno アカウントを使った E2E の自動保証（手動確認・別 issue で扱う）
