# suno-helper Chrome 拡張

`/suno` が生成した `suno-prompts.json` を Suno Custom Mode に順次注入し、Generate を連続実行する個人利用向け補助拡張（WXT + React + TypeScript + Tailwind CSS / Manifest V3 / unpacked）。

> reCAPTCHA・トークン消費・速度の問題を避けるため、ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かす設計です。

## 構成

| パス                        | 役割                                                                                   |
| --------------------------- | -------------------------------------------------------------------------------------- |
| `wxt.config.ts`             | manifest を自動生成（最小権限 `["storage","activeTab"]` は `lib/manifest.ts` が SSOT） |
| `entrypoints/background.ts` | service worker（ライフサイクルログのみ）                                               |
| `entrypoints/content.ts`    | Suno UI への注入と Generate 連続実行のフロー制御                                       |
| `entrypoints/popup/`        | popup の HTML / エントリ（React + Tailwind）                                           |
| `components/`               | popup UI（`App.tsx` / `PatternList.tsx` / `useSunoRunner.ts`）                         |
| `lib/messaging.ts`          | popup ⇄ content の型付き message（@webext-core/messaging）                             |
| `lib/storage.ts`            | サーバー URL の型付き storage（@wxt-dev/storage）                                      |
| `lib/manifest.ts`           | 最小権限定数 `MANIFEST_PERMISSIONS`                                                    |
| `../shared/`                | DOM 注入 / API client / origin allowlist / 契約定数（複数拡張で共有）                  |

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
   uv run yt-collection-serve collections/planning/<theme>
   # → http://localhost:7873/suno/prompts.json で配信
   ```
2. Chrome で Suno の **Custom Mode** 画面を開く。
3. 拡張アイコンからポップアップを開き、**サーバー URL**（既定 `http://localhost:7873`）を入れて **データ取得**。
4. パターン一覧が出たら **全パターンを連続実行** を押す。
5. 各パターンで Style/Lyrics を注入 → Generate 押下 → 生成完了検知 → 次へ、を自動で繰り返す。
6. reCAPTCHA / エラー検知時は自動停止し、ポップアップに警告を表示する。手動で解決後に再度 **連続実行** で続行できる。

## CORS

サーバー（`yt-collection-serve`）は CORS を `chrome-extension://` オリジンのみ許可する。`--allow-origin chrome-extension://<id>` で特定拡張 ID に固定もできる。判定ロジックは `../shared/origin.ts`（サーバー側 `collection_serve.py::is_origin_allowed` と対の契約）。

## スコープ外

- Chrome Web Store への公開（unpacked + GitHub Release zip 配布のみ）
- 他ブラウザ対応 / 歌詞編集機能 / 自動ログイン / 生成曲の自動 DL（`masterup` の責務）
