# suno-helper Chrome 拡張

`/suno` が生成した `suno-prompts.json` を Suno Custom Mode に順次注入し、Generate を連続実行する個人利用向け補助拡張（Manifest V3 / unpacked）。

> reCAPTCHA・トークン消費・速度の問題を避けるため、ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かす設計です。

## 構成

| ファイル | 役割 |
|---|---|
| `manifest.json` | Manifest V3 定義（permissions / content script / popup） |
| `constants.js` | popup ⇄ content の契約文字列（メッセージ種別・storage キー） |
| `popup.html` / `popup.css` / `popup.js` | ポップアップ UI（URL 入力・取得・連続実行・停止・進捗） |
| `content.js` | Suno UI への Style/Lyrics 注入と Generate 連続実行 |
| `background.js` | service worker（ライフサイクルログのみ） |

## インストール（unpacked）

1. Chrome で `chrome://extensions` を開く。
2. 右上の **デベロッパーモード** を ON。
3. **パッケージ化されていない拡張機能を読み込む** → この `extensions/suno-helper/` ディレクトリを選択。

## 使い方

1. ターミナルでサーバーを起動:
   ```bash
   uv run yt-suno-serve collections/planning/<theme>
   # → http://localhost:7873/prompts.json で配信
   ```
2. Chrome で Suno の **Custom Mode** 画面を開く。
3. 拡張アイコンからポップアップを開き、**サーバー URL**（既定 `http://localhost:7873`）を入れて **データ取得**。
4. パターン一覧が出たら **全パターンを連続実行** を押す。
5. 各パターンで Style/Lyrics を注入 → Generate 押下 → 生成完了検知 → 次へ、を自動で繰り返す。
6. reCAPTCHA / エラー検知時は自動停止し、ポップアップに警告を表示する。手動で解決後に再度 **連続実行** で続行できる。

## CORS

サーバー（`yt-suno-serve`）は CORS を `chrome-extension://` オリジンのみ許可する。`--allow-origin chrome-extension://<id>` で特定拡張 ID に固定もできる。

## DOM セレクタの保守

Suno の UI 変更で注入先が見つからなくなった場合は `content.js` 冒頭の `SELECTORS` を更新する。`textarea` の placeholder（Style / Lyrics）と Generate ボタンのラベルを判定に使っている。見つからない場合は **silent に続行せず停止** し、ポップアップに理由を表示する。

## スコープ外

- Chrome Web Store への公開（unpacked 個人利用のみ）
- 他ブラウザ対応 / 歌詞編集機能 / 自動ログイン / 生成曲の自動 DL（`masterup` の責務）
