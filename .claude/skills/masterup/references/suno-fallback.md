# Suno fallback 経路（WebFetch + CDN curl）

suno-helper の一括ダウンロードが使えないときだけ通る経路。通常運用では読む必要はない。
Suno の公式 API ではなく UI の HTML と CDN URL パターンに依存しているため、事前告知なく壊れうる。

## Suno 依存の脆弱性と復旧手段

> **注**: suno-helper の一括ダウンロード機能により、以下の WebFetch / CDN 依存は fallback 経路に格下げされた。通常運用では suno-helper が DL を完了するため、本セクションの脆弱性は fallback 使用時にのみ該当する。

本スキルの fallback 経路は **Suno の公式 API ではなく**、UI でレンダリングされる HTML（WebFetch）と CDN URL パターン（`https://cdn1.suno.ai/{song_id}.mp3`）への curl アクセスという **非公式・非サポートな経路** に依存している。Suno 側の UI / CDN 仕様は事前告知なく変更されうるため、ある日突然 `/masterup` の Step 2 / Step 3 が壊れる可能性があることを前提に運用すること。

### どこが壊れうるか

| 経路 | 依存箇所 | 壊れた場合の症状 |
|------|----------|------------------|
| プレイリスト HTML スクレイピング | Step 2 / WebFetch | プレイリストページ DOM や `song_count` 等のメタ表記が変わり曲リスト・総曲数が取れない |
| CDN URL パターン | Step 3 / `https://cdn1.suno.ai/{song_id}.mp3` | URL 構造変更・署名要求化・ホスト変更で 403 / 404 が返る |
| プレイリスト公開可否 | Step 2 全体 | プレイリストの未ログイン公開が廃止され HTML 取得そのものが不能になる |

### 壊れた時の判定フロー

1. **Step 2 で曲リストが取れない** → Suno UI の HTML 構造変更を疑う。WebFetch 結果を生で確認し、プロンプトを更新して回避できるかを試す。回避不可なら下記フォールバックへ。
2. **Step 3 で 403 / 404 が連発** → CDN URL パターン変更を疑う。1 曲を手動で Suno UI からダウンロードして MIME / URL を確認し、`suno_download.cdn_url_template` の更新で吸収できるか判定する。吸収不可なら下記フォールバックへ。
3. いずれの場合も **silent な続行は禁止**（不完全な master.mp3 を生成しない）。ユーザーへ「Suno 経路が壊れた可能性が高い。fallback 運用に切替推奨」と明示報告し、停止する。

### フォールバック運用（手動ダウンロード → `uv run yt-generate-master` 直叩き）

`/masterup` の Step 1 / Step 5 / Step 5.5 / Step 6 / 完了時の更新は MP3 が `02-Individual-music/` に揃っていれば成立するため、Step 2 / Step 3 を **手動で代替**することで運用継続できる:

1. Suno UI から曲を 1 つずつ MP3 ダウンロード（公式に提供されている UI 経路。サブスク権利範囲内）
2. アクティブコレクションの `02-Individual-music/` に配置し、ファイル名を連番 + タイトルで揃える（例: `01-pattern-a-arrival.mp3`）
3. `uv run yt-generate-master`（または `--target-duration` / `--shuffle` などのオプション付き）を **直接実行**
4. 必要に応じて `uv run yt-finalize-master`（雨音レイヤー）→ Step 6 の `rsync` 同期を **手動で順番に実行**
5. `uv run yt-raw-master-check <コレクションディレクトリ> --apply` で `workflow-state.json` の `assets.raw_master` / `updated_at` を更新する（手動編集は不要。更新し忘れても次回の `/masterup` / `/wf-status` 起動時に Step 1.4 の突合チェックが不整合を検知・警告する）

このフォールバックは **`/masterup` が壊れていても master.mp3 を生成できる最小経路**であり、Suno 公式 API 公開までの暫定運用として機能する。

### Suno 公式 API 公開時の移行プラン（将来案 / 現行手順ではない）

この節は `yt-suno-fetch` が存在する前提の現行実行手順ではない。Suno が公式 API（プレイリスト一覧 / 楽曲メタデータ / ダウンロード URL）を公開した場合の移行方針:

1. **新規 `yt-suno-fetch` CLI を追加**（`scripts/` 配下、`yt-*` プレフィックス踏襲、`pyproject.toml::[project.scripts]` 登録）。公式 API クライアントを実装し、認証情報は `auth/suno_token.json` 等の独立ファイル + `infrastructure/secrets.py::_SECRET_REFS` 経由で解決する。
2. **本 SKILL.md の Step 2 / Step 3 を書き換え**、WebFetch + CDN curl の経路を `yt-suno-fetch` 呼び出しに置換する。skill-config の `suno_download.cdn_url_template` は deprecated として `config.default.yaml` に deprecation note を残し、しばらくは「API 障害時の緊急 fallback」として併存させる。
3. **非公式経路は別 skill `/masterup-legacy` へ退避**するか、もしくは本 SKILL.md 内で `mode: "official" | "legacy"` を切替可能にする（移行期間中の保険）。
4. 公式 API が安定し下流チャンネル全てが移行完了したら非公式経路を削除し、`suno_download.cdn_url_template` を skill-config からも除去する（破壊的変更として major version bump）。

移行作業は本 issue とは別 issue で扱う。Suno が公式 API 公開を発表した時点で本セクションのリンクとして issue を起票すること。


### Step 2: WebFetch でプレイリスト情報を取得 (DEPRECATED -- fallback only)

> **suno-helper DL 済みの場合はスキップ**: `02-Individual-music/` ディレクトリにオーディオファイル（mp3 / m4a / wav）が既に存在する場合、suno-helper が一括ダウンロード済みと判断し、**Step 1.6 の突合ゲート完了後に Step 2-3 をスキップして Step 5 へ進む**。この経路が primary path であり、以下の WebFetch + CDN curl は suno-helper のダウンロードが使えない場合のフォールバックとしてのみ使用する。

1. 引数のプレイリストURLを WebFetch で取得
2. prompt で全曲の情報を抽出するよう指示。**プレイリスト全体の総曲数（メタ表記）も同時に取得する**:
   - プレイリスト総曲数（HTML 内の `song_count` / `songs · NN tracks` / `NN songs` 等のメタ表記。**必須**）
   - 各曲のタイトル
   - 各曲の Song ID（UUID）
   - 各曲の再生時間
3. **件数突合チェック（必須・silent な取りこぼし禁止）**:
   - WebFetch 結果から `len(songs)` を数え、ステップ 2 で取得した「プレイリスト総曲数」と突合する
   - **不一致なら処理を中断**し、ユーザーへ次のメッセージで報告する:
     > ⚠️ プレイリスト総曲数 (N) と取得件数 (M) が一致しません。WebFetch は suno.com のサーバー描画分（50 曲まで）しか見えないため、51 曲目以降は遅延読み込みで取りこぼされます。
     > 対処: (a) プレイリストを 50 曲以下に分割して再実行 / (b) 全件を手動で `02-Individual-music/` に揃えてから `uv run yt-generate-master` を直接実行
   - 総曲数のメタ表記が WebFetch から取得できなかった場合も同様に中断し、ユーザーへ「件数突合不能のため処理を停止」と報告する（silent な続行を禁止）
   - **総曲数 ≤ 50 で件数が一致した場合のみ Step 3 へ進む**
4. WebFetch の結果から曲リストをパースして Step 3 に渡す
5. Step 1.6 の突合ゲートが未実行なら、この曲リストで `yt-suno-verify-playlist` を実行してから Step 3 に進む

**取得手段のフォールバック方針**: WebFetch は suno.com のサーバー描画分（上限 50 件）しか拾えないため、本 skill は「50 曲以下のプレイリスト」を前提運用とする。50 曲超のプレイリストは現状 50 曲単位に分割して個別実行するか、手動で `02-Individual-music/` に MP3 を揃えてから `uv run yt-generate-master` を直接実行するワークフローへ切り替える（内部 API / 公式 API への移行は別 issue）。

### Step 3: MP3 ダウンロード（CDN curl）(DEPRECATED -- fallback only)

> **suno-helper DL 済みの場合はスキップ**: Step 2 と同様、`02-Individual-music/` にファイルが存在すれば本ステップはスキップ。

各曲について:
1. Song ID または Suno ショート URL（`https://suno.com/s/<slug>`）を UUID に正規化
2. UUID から CDN URL を生成: `https://cdn1.suno.ai/{song_id}.mp3`
3. `curl` でダウンロードし `02-Individual-music/` に保存
4. ファイル名: 連番 + タイトルから生成（例: `01-pattern-a-arrival.mp3`）

**Suno ショート URL の UUID 解決**:

`song_id` 欄に `https://suno.com/s/<slug>` が入っている場合は、リダイレクト先 URL から UUID を抽出してから CDN URL を組み立てる。解決できない場合は当該曲をスキップせず、原因を表示して処理を停止する（silent な欠落禁止）。

```bash
resolve_suno_song_id() {
  local input="$1"
  local uuid_re='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

  if echo "$input" | rg -qi "^${uuid_re}$"; then
    echo "$input"
    return 0
  fi

  if echo "$input" | rg -qi '^https://suno\.com/s/[^[:space:]]+$'; then
    local final_url
    final_url="$(curl -sI -L -o /dev/null -w '%{url_effective}' "$input")"
    if echo "$final_url" | rg -qio "$uuid_re"; then
      echo "$final_url" | rg -o "$uuid_re" | tail -1
      return 0
    fi
    echo "ERROR: Suno ショート URL から UUID を解決できません: $input (final_url=$final_url)" >&2
    return 1
  fi

  echo "ERROR: Song ID は UUID または https://suno.com/s/<slug> で指定してください: $input" >&2
  return 1
}
```

**入力値のサニタイズ（必須）**:
- **Song ID**: UUID v4 形式（`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`、hex + hyphen のみ）であることを検証する。正規表現: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`（case-insensitive）。不一致なら当該曲をスキップし警告を出す（シェルインジェクション防止）
- **ファイル名 slug**: タイトルから生成するファイル名は英数字・ハイフン・アンダースコアのみ許可し、それ以外の文字は `-` に置換する（`tr -cs 'a-zA-Z0-9_-' '-'`）。先頭・末尾の `-` は除去する

```bash
# song_id の UUID 正規化・検証（各曲ループ内で実行）
song_id="$(resolve_suno_song_id "$song_id")" || exit 1

if ! echo "$song_id" | rg -qi '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; then
  echo "SKIP: invalid song_id format: $song_id"
  continue
fi

curl -fSL \
  --retry "${RETRY_COUNT:-3}" --retry-delay "${RETRY_DELAY:-2}" \
  -w '\n[DL] %{filename_effective}: HTTP %{http_code}, type=%{content_type}, %{size_download} bytes, %{speed_download} B/s\n' \
  -o "02-Individual-music/{filename}.mp3" \
  "https://cdn1.suno.ai/{song_id}.mp3"
```

`RETRY_COUNT` / `RETRY_DELAY` は skill-config の `suno_download.retry_count` / `suno_download.retry_delay_seconds` から読み込む（既定 3 / 2）。

**各フラグの意味**:
- `-f` (`--fail`): HTTP 4xx/5xx でゼロバイトファイルを残さず即座に失敗扱いにする
- `-S`: `-f` と組み合わせてエラー詳細を stderr に出力
- `--retry N --retry-delay N`: 一時的な CDN エラー時にリトライ（skill-config で調整可能）
- `-w`: ダウンロード結果（HTTP status, Content-Type, サイズ, 速度）をログ出力

**Content-Type 検証**: `-w` 出力の `%{content_type}` が `audio/mpeg` でない場合（例: `text/html` — CDN がエラーページを返した）、そのファイルは破損扱いとして検証失敗リストに追加する。

**ダウンロード後の検証（全曲完了後に一括実行）**:

```bash
failed=()
for f in 02-Individual-music/*.mp3; do
  size=$(stat -f%z "$f" 2>/dev/null || echo 0)
  if [ "$size" -lt 10000 ]; then
    echo "⚠️  $f: サイズが異常に小さい (${size} bytes) — 部分ダウンロードの可能性"
    failed+=("$f")
    continue
  fi
  duration=$(afinfo "$f" 2>/dev/null | grep "estimated duration" | awk '{print $3}')
  if [ -z "$duration" ] || [ "$(echo "$duration < 5" | bc)" -eq 1 ]; then
    echo "⚠️  $f: 再生時間が異常 (${duration:-N/A} 秒) — ファイル破損の可能性"
    failed+=("$f")
  fi
done
if [ ${#failed[@]} -gt 0 ]; then
  echo "❌ ${#failed[@]} ファイルの検証に失敗:"
  printf '  - %s\n' "${failed[@]}"
  echo "→ 手動で Suno UI から再ダウンロードするか、Song ID を確認して curl を再実行してください"
else
  echo "✅ 全ファイル検証 OK"
fi
```

**期待ファイルとの突合チェック（必須）**:

ダウンロード・検証ループの後、Step 2 で取得した曲リスト（期待トラック一覧）と `02-Individual-music/` の実ファイルを突合する:

```bash
# expected_files: Step 2 の曲リストから生成したファイル名配列
# actual_files: 02-Individual-music/*.mp3 の basename 配列
missing=()
for expected in "${expected_files[@]}"; do
  if [[ ! -f "02-Individual-music/$expected" ]]; then
    missing+=("$expected")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "MISSING ${#missing[@]} files (expected from playlist but not on disk):"
  printf '  - %s\n' "${missing[@]}"
fi
```

期待ファイルが 1 件でも欠けている場合は検証失敗として扱い、Step 5 へ進まない。

**検証が失敗した場合**: 該当ファイルを削除し、curl を再実行する。3 回リトライしても失敗する場合は CDN 障害の可能性が高いため、手動で Suno UI からダウンロードして `02-Individual-music/` に配置するフォールバックに切り替える。

**注意**: CDN URL は public だが永続性は不明。生成後なるべく早めにダウンロードすること。1ファイル約2-3MB。

