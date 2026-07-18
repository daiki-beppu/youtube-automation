# suno-helper Chrome 拡張

`/suno` が生成した `suno-prompts.json` を Suno の Advanced タブに順次注入し、Generate を連続実行する個人利用向け補助拡張（WXT + React + TypeScript + Tailwind CSS / Manifest V3 / unpacked）。

> reCAPTCHA・トークン消費・速度の問題を避けるため、ヘッドレス／DevTools 経由ではなく **既ログイン状態の本物の Chrome セッション** 上で動かす設計です。

## 構成

| パス | 役割 |
| --- | --- |
| `wxt.config.ts` | manifest を自動生成（権限 `storage` / `activeTab` / `downloads` / `debugger` は `lib/manifest.ts` が SSOT） |
| `entrypoints/background.ts` | service worker（Download all ZIP 監視、server token 取得、downloaded POST 中継） |
| `entrypoints/content.ts` | Suno UI への注入と Generate 連続実行のフロー制御 |
| `entrypoints/suno-bridge.content.ts` | MAIN world fetch bridge（#948）。Suno API の生成投入 / clip status を passive 観測 |
| `entrypoints/popup/` | popup の HTML / エントリ（React + Tailwind） |
| `components/` | popup UI（`App.tsx` / `PatternList.tsx` / `useSunoRunner.ts`） |
| `lib/messaging.ts` | popup ⇄ content の型付き message（@webext-core/messaging） |
| `lib/clip-tracker.ts` ほか | bridge 観測の集計（in-flight / ACK / stall。`bridge-listener` / `ack-probe` / `entry-retry`） |
| `lib/storage.ts` | 選択中ローカル配信元 / resume state / overlay state の型付き storage（@wxt-dev/storage） |
| `lib/manifest.ts` | 最小権限定数 `MANIFEST_PERMISSIONS` |
| `../shared/` | DOM 注入 / API client / origin allowlist / 契約定数（複数拡張で共有） |

DOM 注入セレクタ（Style / Lyrics の placeholder、Generate ボタンのラベル、reCAPTCHA 検知）は `../shared/dom.ts` の `SELECTORS` に集約する。Suno の UI 変更で注入先が見つからなくなった場合はここを更新する。見つからない場合は **silent に続行せず停止** し、popup に理由を表示する。

## Agent 操作用 DOM signal

browser use から overlay / popup を安定して観測できるよう、操作 panel は読み取り専用の `data-suno-*` 属性を持つ。これらは表示状態の公開契約であり、runner の実行制御や server API 契約は変更しない。

| selector / 属性 | 意味 |
| --- | --- |
| `[data-suno-helper="control-panel"]` | 操作 panel の root |
| `data-suno-phase` | `idle` / `loading` / `starting` / progress phase（`waiting-captcha` / `entry-failed` を含む）/ `adopting` |
| `data-suno-running` | runner 実行中なら `"true"` |
| `data-suno-error` | status がエラーなら `"true"` |
| `data-suno-collection-id` | 選択中 collection id |
| `data-suno-entry-count` | 読み込み済み entry 数 |
| `data-suno-selected-entry-count` | 実行対象 entry 数 |
| `[data-suno-control="server-source-trigger"]` | ローカル配信元の動的検出を開始し、候補 listbox を開く |
| `role="option"` | 動的検出したローカル配信元の選択 |
| `[data-suno-control="collection-select"]` | collection 選択 |
| `[data-suno-control="run"]` / `[data-suno-control="stop"]` | 主要操作ボタン |
| `[data-suno-control="resume"]` / `[data-suno-control="dismiss-resume"]` | 前回中断 resume バナーの再開 / 閉じる |
| `[data-suno-control="adopt-selected-clips"]` | Suno 上の選択中 clip を採用 |
| `[data-suno-control="retry-playlist"]` / `[data-suno-control="retry-download"]` | playlist / download phase から再開 |
| `role="status"` + `data-suno-status` | live status。`data-suno-status="error"` は handoff / retry 判断の入口 |
| `[data-suno-entry-list]` / `[data-suno-entry-index]` | entry 一覧。各行に `data-suno-entry-state` と `data-suno-entry-selected` が付く |

## 開発・ビルド・テスト

ローカル検証は CI・lockfile と同じ Nix extensions shell の Node 24 / pnpm 11.12.0 に固定する。ambient `pnpm` の版は各環境で異なり得るため、リポジトリ root から以下のコマンドを使う。理由と両拡張共通の release 前検証は `extensions/README.md::pnpm バージョン契約` を参照する。

```bash
nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile  # postinstall で wxt prepare
nix develop .#extensions --command pnpm -C extensions/suno-helper dev                         # 開発（HMR）
nix develop .#extensions --command pnpm -C extensions/suno-helper build                       # 本番ビルド → .output/chrome-mv3/
nix develop .#extensions --command pnpm -C extensions/suno-helper zip                         # 配布用 zip
nix develop .#extensions --command pnpm -C extensions/suno-helper compile                     # 型チェック（tsc --noEmit）
nix develop .#extensions --command pnpm -C extensions/suno-helper test                        # Vitest unit
nix develop .#extensions --command pnpm -C extensions/suno-helper exec playwright install --with-deps chromium  # Playwright 初回のみ（CI と同じ browser + system dependencies）
nix develop .#extensions --command pnpm -C extensions/suno-helper test:e2e                    # Playwright e2e
```

`compile` は `wxt prepare` の後に固定版 TypeScript 7.0.2 の `tsc --noEmit` を実行する型検査レーンで、成果物を生成する WXT の `build` / `zip` とは別である。TypeScript 5.9.3 との比較で確認した 6.7〜8.3 倍の高速化は `wxt prepare` を除外した型検査部分だけの結果であり、build / zip 全体の性能を示さない。計測条件と生値は [共通の性能比較記録](../../docs/investigations/2026-07-18-2016-typescript7-compile-benchmark.md) を参照する。

build 後は `.output/chrome-mv3/manifest.json`、zip 後は `.output/suno-helper-<package.json の version>-chrome.zip` を確認する。期待名 zip が唯一の 1 件であることを含む release 前検証は、リポジトリ root で `bash .claude/skills/automation-release/references/verify-extensions.sh suno-helper` を実行する。

## インストール（unpacked）

1. リポジトリ root で `nix develop .#extensions --command pnpm -C extensions/suno-helper install --frozen-lockfile && nix develop .#extensions --command pnpm -C extensions/suno-helper build` を実行。
2. build artifact を basename が `suno-helper` になる固定パスへコピーする:
   ```bash
   mkdir -p "$HOME/chrome-extensions/suno-helper"
   rsync -a --delete extensions/suno-helper/.output/chrome-mv3/ "$HOME/chrome-extensions/suno-helper/"
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
2. Chrome で Suno の **Advanced** タブを選択する。
3. 拡張アイコンからポップアップを開き、**ローカル配信元** で動的検出されたチャンネル名つき候補を選ぶ。初回表示・配信元選択・collection 選択の各タイミングで一覧と prompts が自動取得される。
4. `ready` な collection を選び、prompts の自動取得後に **異常値の曲を再生成する** を選んでから **全パターンを連続実行** を押す。既定の ON は duration guard NG の entry を最大 2 回再生成する。OFF は追加生成せず、NG を警告表示したうえで生成済み全 clip を playlist / download 候補に残す。
5. 各パターンで Style/Lyrics を注入 → Generate 押下 → 生成完了検知 → 次へ、を自動で繰り返す。
6. 全件完了後、対象 clip を一括選択 → playlist 追加 → More menu の **Download all** → format 選択 → ZIP ダウンロード完了監視 → `POST /collections/<id>/downloaded` で ZIP パス通知、まで実行する。サーバーは ZIP を展開し、`02-Individual-music/` と `workflow-state.json` を更新する。
7. captcha challenge は waiting-captcha 表示で解消（多くは自動 verify）を待って続行する。entry 単位の一時的な失敗は Balanced 固定の上限で自動リトライし、上限超過分はスキップして完走する（#948）。スキップされた entry は一覧表示され、**失敗分のみ再実行** で再投入できる。

**異常値の曲を再生成する** を OFF にした run は、duration guard の閾値外 clip も歯抜けにせず playlist と ZIP に含める。popup の status / console warning で NG を確認し、完了後に対象 playlist を試聴して採否を手動判断する。popup を閉じて再表示した場合も選択は復元される。entry phase の ERROR / STOPPED は resume バナー、playlist / download phase の中断は **Playlist から再開** / **Download から再開** を使い、いずれも元 run の選択と警告を引き継ぐ。

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

`yt-collection-serve` は起動時に `http://<channel>.localhost:<PORT>` 形式の URL と selector label を表示し、固定 registry `http://localhost:7872/.well-known/yt-collection-serve` へ heartbeat 登録する。拡張は初回表示と selector を開く操作時に registry を読み、`GET /server-info` で検証できた稼働中サーバーだけを動的検出する。選択肢は更新完了後に開くため、停止済み候補を先に表示しない。例: `yt-collection-serve collections/planning --port 49152`。既定の `http://youtube-automation.localhost:7873` はサーバー停止中でも常に表示される。過去の候補一覧は保存せず、選択中 URL だけを保存する。

### discovery / storage schema v1

server は `Content-Type: application/json`、`Origin` なしで `{"instance_id":"fixture-instance","server_info":{"channel_name":"Fixture Channel","channel_short":"fixture","hostname":"fixture.localhost","port":49152,"base_url":"http://fixture.localhost:49152","label":"Fixture Channel"}}` を registry へ POST する。GET の完全な schema v1 応答は次の形になる。

```json
{
  "schema_version": 1,
  "ttl_seconds": 30,
  "servers": [
    {
      "instance_id": "fixture-instance",
      "expires_at": 130.0,
      "server_info": {
        "channel_name": "Fixture Channel",
        "channel_short": "fixture",
        "hostname": "fixture.localhost",
        "port": 49152,
        "base_url": "http://fixture.localhost:49152",
        "label": "Fixture Channel"
      }
    }
  ]
}
```

`schema_version` は互換性番号、`ttl_seconds` は生存期間、`servers` は `base_url` 順の登録配列。`instance_id` はプロセス識別子、`expires_at` は Unix time の失効時刻、`server_info` の各 field はチャンネル名・短縮名・loopback host/port/base URL・表示 label である。同一 ID の heartbeat POST は expiry を更新し、正常終了時の `{"instance_id":"fixture-instance"}` DELETE は即時削除、異常終了時は TTL 境界で失効する。

POST/DELETE は JSON 以外を 415、`Origin` 付き要求を 403、不正 schema を 400、16384 bytes 超の body を 413、128 文字超の ID を 400、128 件超の登録を 429 にして状態を変更しない。未知 path は 404、未対応 method は 405。storage は `chrome.storage.local["sunoServerUrl"]` に選択中 URL 文字列だけを保持し、旧候補配列 key `chrome.storage.local["ytCollectionServeSources"]` は更新時に削除して再作成しない。

## スコープ外

- Chrome Web Store への公開（unpacked + GitHub Release zip 配布のみ）
- 他ブラウザ対応 / 歌詞編集機能 / 自動ログイン
- 実 Suno アカウントを使った E2E の自動保証（手動確認・別 issue で扱う）
