# suno-helper Chrome 拡張

`/suno` が生成した `suno-prompts.json` を Suno Custom Mode に順次注入し、Generate を連続実行する個人利用向け補助拡張（WXT + React + TypeScript + Tailwind CSS / Manifest V3 / unpacked）。

> reCAPTCHA・トークン消費・速度の問題を避けるため、ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かす設計です。

## 構成

| パス                                 | 役割                                                                                          |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| `wxt.config.ts`                      | manifest を自動生成（最小権限 `["storage","activeTab"]` は `lib/manifest.ts` が SSOT）        |
| `entrypoints/background.ts`          | service worker（ライフサイクルログのみ）                                                      |
| `entrypoints/content.ts`             | Suno UI への注入と Generate 連続実行のフロー制御                                              |
| `entrypoints/suno-bridge.content.ts` | MAIN world fetch bridge（#948）。Suno API の生成投入 / clip status を passive 観測            |
| `entrypoints/popup/`                 | popup の HTML / エントリ（React + Tailwind）                                                  |
| `components/`                        | popup UI（`App.tsx` / `PatternList.tsx` / `useSunoRunner.ts`）                                |
| `lib/messaging.ts`                   | popup ⇄ content の型付き message（@webext-core/messaging）                                    |
| `lib/clip-tracker.ts` ほか           | bridge 観測の集計（in-flight / ACK / stall。`bridge-listener` / `ack-probe` / `entry-retry`） |
| `lib/storage.ts`                     | サーバー URL の型付き storage（@wxt-dev/storage）                                             |
| `lib/manifest.ts`                    | 最小権限定数 `MANIFEST_PERMISSIONS`                                                           |
| `../shared/`                         | DOM 注入 / API client / origin allowlist / 契約定数（複数拡張で共有）                         |

DOM 注入セレクタ（Style / Lyrics の placeholder、Generate ボタンのラベル、reCAPTCHA 検知）は `../shared/dom.ts` の `SELECTORS` に集約する。Suno の UI 変更で注入先が見つからなくなった場合はここを更新する。見つからない場合は **silent に続行せず停止** し、popup に理由を表示する。

## 開発・ビルド・テスト

```bash
pnpm install            # 依存インストール（postinstall で wxt prepare）
pnpm dev                # 開発（HMR）
pnpm build              # 本番ビルド → .output/chrome-mv3/
pnpm compile            # 型チェック（tsc --noEmit）
pnpm test               # Vitest unit
pnpm test:e2e           # Playwright e2e（初回 pnpm exec playwright install chromium）
```

## インストール（unpacked）

1. `pnpm install && pnpm build` を実行。
2. Chrome で `chrome://extensions` を開く。
3. 右上の **デベロッパーモード** を ON。
4. **パッケージ化されていない拡張機能を読み込む** → この拡張の `.output/chrome-mv3/` ディレクトリを選択。

## 使い方

1. ターミナルでサーバーを起動:
   ```bash
   tayk collection-serve collections/planning/<theme>
   # → http://localhost:7873/suno/prompts.json で配信
   ```
2. Chrome で Suno の **Custom Mode** 画面を開く。
3. 拡張アイコンからポップアップを開き、**サーバー URL**（既定 `http://localhost:7873`）を入れて **データ取得**。
4. パターン一覧が出たら **全パターンを連続実行** を押す。
5. 各パターンで Style/Lyrics を注入 → Generate 押下 → 生成完了検知 → 次へ、を自動で繰り返す。
6. captcha challenge は waiting-captcha 表示で解消（多くは自動 verify）を待って続行する。entry 単位の一時的な失敗は preset 連動で自動リトライし、上限超過分はスキップして完走する（#948）。スキップされた entry は一覧表示され、**失敗分のみ再実行** で再投入できる（完走時に playlist 追加が実行される）。

### in-flight 検知と停止判断（#948）

- **in-flight カウント**: MAIN world bridge（`suno-bridge.content.ts`）が Suno API（`POST /api/generate/v2-web/` / `GET /api/feed/v2`）のレスポンスを観測し、clip status（complete/error 以外 = in-flight）で数える。「Remix ボタン disabled = 生成中」の旧 DOM プロキシは生成完了後も disabled が残り過大カウントするため fallback 専用（縮退中は popup に「bridge 未観測: DOM 計数で待機中」と表示される）
- **停止判断**: queue 空き待ちは固定 timeout ではなく stall ベース（in-flight 集合が 10 分間まったく変化しないときのみ ERROR）。run 全体を止めるのは `FatalRunError`（DOM セレクタ不在 / captcha 手動解決 timeout / queue stall）のみ
- **Bearer token**: bridge が MAIN world ローカルに保持し extension 側へは渡さない。401 で破棄しページの次リクエストで自動再捕捉

## CORS

サーバー（`tayk collection-serve`）は CORS をデフォルトで `chrome-extension://` オリジンと helper サイト web origin（`https://suno.com` / `https://www.suno.com`）に許可する。overlay 化（#892）後は content script の fetch が `https://suno.com` origin になるため、引数なし起動でそのまま通る（#896）。判定ロジックは `../shared/origin.ts` と TS collection-serve service の対の契約。

## スコープ外

- Chrome Web Store への公開（unpacked + GitHub Release zip 配布のみ）
- 他ブラウザ対応 / 歌詞編集機能 / 自動ログイン / 生成曲の自動 DL（`masterup` の責務）
