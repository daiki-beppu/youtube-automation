# `google-auth-httplib2` 移行計画書

PyPI `google-auth-httplib2 0.4.0`（2026-05-07 リリース）において、以下の deprecated 表明が追加された:

> "this library is no longer maintained. For any new usages please see provided transport layers by google-auth library."

本書は、本リポジトリ (`youtube-channels-automation`) における依存実態を記録し、将来の移行方針を確定することを目的とする。
関連 issue: **#408**（本書作成） / 関連監査: PR #375、監査レポート R-04

---

## 1. 依存実態の grep 結果

以下のコマンドで全 import を網羅的に確認した（再現可能）:

```bash
grep -rn "google_auth_httplib2" src/
grep -rn "google_auth_httplib2" tests/
grep -n "google-auth-httplib2" pyproject.toml
grep -A3 'name = "google-auth-httplib2"' uv.lock
```

| 観点 | 結果 | 根拠 |
|------|------|------|
| `src/` 配下の Python 直 import | **0 件** | `grep -rn "google_auth_httplib2" src/` で空 |
| `tests/` 配下の Python 直 import | **0 件** | `grep -rn "google_auth_httplib2" tests/` で空 |
| `pyproject.toml` 直接宣言 | **1 件（L16）** | `"google-auth-httplib2"` — 直接依存として宣言されており直 import 0 件だが、`build(..., credentials=...)` の runtime 依存が残るためオーファンではない |
| `uv.lock` 解決状況 | バージョン **0.4.0** | `name = "google-auth-httplib2" / version = "0.4.0"` — `google-api-python-client 2.198.0` の transitive dep として参照 |
| PyPI 上の最新 | **0.4.0（2026-05-07）** で deprecated 表明 | 監査レポート R-04、5.4.2 で記録済み |

重要な発見: `pyproject.toml:16` は直接依存として宣言されているが、`src/` / `tests/` に直 import が 0 件。
ただし `build(..., credentials=credentials)` が内部で `google_auth_httplib2.AuthorizedHttp` に依存しているため、直 import 0 件でもオーファンではない（runtime 依存が残る）。

---

## 2. 残置判断（2026-07-22 再監査）

### (a) transitive dep の即時撤去は不可

`google-api-python-client 2.198.0` の内部実装（`googleapiclient.discovery.build`）が引き続き `httplib2` ベースの transport を要求しているため、
`google-auth-httplib2` を除外すると `build()` 呼び出しが失敗する。
上流 (`google-api-python-client`) が non-httplib2 transport をサポートするまで、transitive dep としての残置は不可避。

### (b) `pyproject.toml:16` の直接宣言の扱いは transport 移行後に再検証（別 issue）

直接宣言 (`pyproject.toml:16`) は直 import 0 件だが、`build(..., credentials=credentials)` の runtime 依存が残るためオーファンではない。
撤去の可否は Step 2（transport 切替）完了後に依存所有形態を再検証してから判断する。本 issue では実行せず、移行計画の Step 1 として別 issue に切り出す:

- `uv sync --dry-run` で transitive 経由の動作継続を事前検証する必要がある
- 下流チャンネルリポジトリ（`youtube-channels-automation` を pin している repos）への影響テストが必要
- 関連 issue **#407**（P1: pyproject.toml 全 16 依存に上限 pin なし）との整合確認が必要

### (c) 直 import 禁止の運用方針

現状、直 import 0 件であるため「新規追加しないこと」は開発者の自主規律で担保する。
機械的な規約実行（lint ルール / 回帰テスト）は、CLAUDE.md での正式な禁止ルール化と同時に別 issue で導入する。

---

## 3. 代替候補の評価

| 候補 | 概要 | 評価 |
|------|------|------|
| `google.auth.transport.requests.Request` | `google-auth` 公式 transport。`requests` ライブラリは本リポジトリの既存依存（`pyproject.toml:27`）のため追加インストール不要 | **最有力候補**。上流 `google-api-python-client` が対応した時点でそのまま採用できる |
| `google.auth.transport.urllib3.Request` | `google-auth` 公式 transport。`urllib3` 単体を追加するだけで使える | 候補。`requests` が既にある環境では優先度は低め |
| `httpx` | order.md で例示されているが、`google-auth` 公式 transport として `google.auth.transport` 配下に `httpx` モジュールが存在しない（2026-05 時点）。採用するには自前 transport adapter の実装が必要 | **採用優先度: 低**。公式サポートが追加されるまで見送り |

移行先として最も現実的なのは `google.auth.transport.requests.Request` であり、
本リポジトリが既に `requests` を依存として保持しているため追加コストがない。

---

## 4. 将来の移行手順（参考、外部依存待ち）

各ステップは外部の動向に依存するため、スケジュールは未確定。別 issue として順次起票する。

### Step 0: 移行計画書を確定（本 issue — 完了）

本書の作成をもって issue #408 の作業完了とする。

### Step 1: `pyproject.toml:16` 直接宣言の依存所有形態を再検証（別 issue 起票、Step 2 完了後）

`build(..., credentials=credentials)` が `google_auth_httplib2.AuthorizedHttp` に依存している現状では、
`pyproject.toml:16` の直接宣言は transitive 依存を明示的に固定する意味を持つ（オーファンではない）。
Step 2（transport 切替）が完了し、runtime 依存が解消されたタイミングで以下を確認する:

```bash
# Step 2 完了後に実行: build(..., credentials=...) 経由で runtime 依存チェーンを確認
uv sync --dry-run
uv run python -c "
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
# ダミー credentials で build() の transport 解決パスを通す
# non-httplib2 transport に切り替わっていれば ImportError は発生しない
creds = Credentials(token='dummy')
try:
    build('youtube', 'v3', credentials=creds, cache_discovery=False)
    print('OK: build(..., credentials=...) が google_auth_httplib2 なしで完了')
except ImportError as e:
    raise SystemExit(f'FAIL: transport が google_auth_httplib2 を要求しています: {e}')
except Exception as e:
    # 認証エラー・HTTP エラーは transport 解決後の失敗なので問題なし
    print(f'OK: transport 解決が完了（認証エラーは想定内）: {type(e).__name__}')
"
```

runtime 依存が解消されていれば `pyproject.toml:16` の宣言はオーファンになるため、
その時点で別 issue を起票して `"google-auth-httplib2"` 行の撤去を検討する。

### Step 2: `googleapiclient.discovery.build` の transport 切替（外部依存待ち）

`google-api-python-client` 側が non-httplib2 transport を正式にサポートした時点で対応を実施する（別 issue）。

> **注意**: 現時点では `build(..., credentials=credentials)` は内部で `google_auth_httplib2.AuthorizedHttp` に依存している。
> 移行手順・参考実装は、上流が non-httplib2 transport を正式サポートした際に上流の公式ドキュメントを参照して別 issue で確定すること。

### Step 3: transitive dep からの除去確認（別 issue — Step 2 完了後）

`uv.lock` から `google-auth-httplib2` が完全に除外されていることを確認する:

```bash
grep "google-auth-httplib2" uv.lock  # 0 件であることを確認
```

---

## 5. 監視ポイント

| 項目 | 確認先 | 推奨頻度 |
|------|--------|---------|
| `google-api-python-client` の httplib2 廃止予告 | [CHANGELOG](https://github.com/googleapis/google-api-python-client/blob/main/CHANGELOG.md) | メジャーバージョンリリース時 |
| `google-auth-httplib2` 0.5+ のリリース動向 | [PyPI](https://pypi.org/project/google-auth-httplib2/) | 四半期ごと |
| PyPI deprecated 表明文字列の更新 | PyPI `google-auth-httplib2` のトップページ | 半期ごと |
| `google.auth.transport` への `httpx` サポート追加 | [google-auth-library-python CHANGELOG](https://github.com/googleapis/google-auth-library-python/blob/main/CHANGELOG.md) | 半期ごと |

---

## 6. 関連 issue / PR / 監査レポート

| 種別 | 識別子 | 内容 |
|------|--------|------|
| Issue | **#408** | 本書作成（P1: google-auth-httplib2 deprecated 表明への対応） |
| Issue | **#407** | P1: pyproject.toml 全 16 依存に上限 pin なし（`google-auth-httplib2<1` 追加は #407 の責務） |
| PR | **#375** | 運用リスク監査（P1-16）— 本 issue の起点 |
| 監査レポート | R-04（`docs/audits/2026-05-18-skills-operational-risk-audit/raw/09-data-deps-deprecation.md:509`） | `google-auth-httplib2` 表明を CHANGELOG / docs に追記し、新規 import 禁止ルールを CLAUDE.md に明示する勧告。CLAUDE.md 追記・CHANGELOG 追記は本 issue のスコープ外（別 issue で対応） |

---

## 7. スコープ外（本 issue に含まれない作業）

| 項目 | 除外理由 |
|------|---------|
| `pyproject.toml:16` の `google-auth-httplib2` 直接宣言を撤去 | Step 1/2 参照。`build(...)` の runtime 依存が残るため撤去不可。Step 2（transport 切替）完了後に依存所有形態を再検証し、撤去の可否を判断する |
| `pyproject.toml` に `google-auth-httplib2<1` 上限 pin を追加 | 別 issue **#407** の責務 |
| `googleapiclient` → `google-auth` + transport の実コード移行 | Step 2 参照。上流対応待ち |
| `CLAUDE.md` に直 import 禁止ルールを追記 | 監査 R-04 が勧告するが、本 issue の明示要求（grep + 移行計画）から直接導出できない。別 issue で対応 |
| `CHANGELOG.md` に `### Deprecated` を追記 | 同上。リリース運用は `/automation-release` が CHANGELOG を扱う |
| 回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` の追加 | 現状 0 件で規約化の前提が整っていない。CLAUDE.md ルール確定後に別 issue で導入 |
