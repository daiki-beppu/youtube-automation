# C-1: 依存ライブラリの健全性 — 監査データ

調査日: 2026-05-18
担当: dig.part-c-deps-deprecation
対象リビジョン: HEAD（worktree `20260518T0905-372-issue-372-chore-skills-sukiru`）

---

## 6.1 pyproject.toml 依存棚卸し

### 6.1.1 `[project.dependencies]`（main 依存）

出典: `pyproject.toml:13-28`

| パッケージ | 制約 | uv.lock 解決 | PyPI latest stable (2026-05-18 確認) | 遅延 | 備考 |
|---|---|---|---|---|---|
| `google-api-python-client` | （無制約） | 2.193.0 | 2.196.0（2026-01-13 last_serial） | パッチ 3 | 健全 |
| `google-auth-oauthlib` | （無制約） | 1.3.0 | **1.4.0（2026-05-07 リリース）** | マイナー 1 つ遅延 | 健全 |
| `google-auth-httplib2` | （無制約） | 0.3.0 | **0.4.0（2026-05-07）／⚠️ PyPI で deprecated 表明** | パッチ程度 | **要対応**（後述 6.3） |
| `google-genai` | （無制約） | 1.69.0 | **2.4.0（メジャー乖離）** | **メジャー 1 つ遅延** | **要評価**（後述 6.2） |
| `openai` | （無制約） | 2.33.0 | 2.37.0 | パッチ 4 | 健全 |
| `Pillow` | （無制約） | 12.1.1 | 12.2.0 | パッチ 1 | 健全 |
| `python-dotenv` | （無制約） | 1.2.2 | 1.2.2（2026-03-01） | 同等 | 健全 |
| `pandas` | （無制約） | 3.0.1 | 3.0.3 | パッチ 2 | 健全 |
| `matplotlib` | （無制約） | 3.10.8 | 3.10.9 | パッチ 1 | 健全 |
| `japanize-matplotlib` | （無制約） | 1.1.3 | 1.1.3（2020-10-21 リリース、以降 4 年超更新なし） | 同等 | **メンテ停滞**（後述 6.3） |
| `seaborn` | （無制約） | 0.13.2 | 0.13.2（2024-01-25） | 同等 | やや停滞、現役 |
| `schedule` | （無制約） | 1.2.2 | 1.2.2（2024-06-18） | 同等 | 現役 |
| `pyyaml` | （無制約） | 6.0.3 | 6.0.3 | 同等 | 健全 |
| `requests` | （無制約） | 2.33.0 | 2.34.2 | パッチ 1 | 健全 |

### 6.1.2 `[project.optional-dependencies]`

出典: `pyproject.toml:33-35`

| グループ | パッケージ | 制約 | uv.lock 解決 | PyPI latest |
|---|---|---|---|---|
| `dev` | `pytest` | 無制約 | 9.0.2 | 9.0.3 |
| `dev` | `ruff` | 無制約 | 0.15.8 | 0.15.13 |
| `veo` | （空配列） | — | — | — |

`[project.optional-dependencies] veo = []` は `# google-genai, Pillow moved to main dependencies` とコメントが付いており、空の extras を残している。`pip install 'youtube-channels-automation[veo]'` を打っても何もインストールされない。**dead extras**（残骸）。

---

## 6.2 pin の妥当性

### 6.2.1 全依存が pin なし

全 16 件の依存（main 14 + dev 2）に対し、`==` / `>=` / `~=` / 上限指定 (`<X`) のいずれも **一切付与されていない**。

```
"google-api-python-client",
"google-auth-oauthlib",
...
```

→ PyPI で破壊的変更（例: `pandas` 4.x、`openai` 3.x）がリリースされた瞬間に下流チャンネルリポジトリの `uv add` / `pip install` がランタイム不整合を引き起こすリスク。`uv.lock` をコミット済み（`git ls-files` で `uv.lock` 確認済み）だが、下流が uv ではなく pip でインストールする場合に lockfile は使われない。

### 6.2.2 メジャー乖延ありの依存に上限を切るべき候補

- `google-genai`: 1.69.0 → 2.4.0 のメジャーアップで SDK API 互換性が崩れている可能性高。`google.genai` 直 import 箇所（`src/youtube_automation/utils/genai_client.py:23`, `src/youtube_automation/utils/veo_generator.py:36`, `src/youtube_automation/utils/image_provider/gemini.py:36`, `src/youtube_automation/scripts/video_analyze.py:29`, `src/youtube_automation/scripts/benchmark_collector.py:538`, `src/youtube_automation/utils/video_analyzer.py:27`）で `types.GenerateVideosConfig` / `types.Image.from_file` などを使用。SDK 2.x で型インポートパスが変わっている可能性があるため、当面 `google-genai>=1.60,<2` 等の上限指定を検討する価値あり
- `pandas`: 2.x → 3.x で `DataFrame.append` 等の API が削除されている。コード側は 3.0.1 を解決しているので追従済みだが、下流環境次第で爆発する

### 6.2.3 hard pin の有無

`==` による hard pin は **ゼロ件**。security update を取れない過剰 pin は無い。これは健全方向（ただし 6.2.1 の上限不在とのトレードオフ）。

---

## 6.3 deprecated / archived dependency

### 6.3.1 `google-auth-httplib2`（PyPI で deprecated 表明）

出典: PyPI `google-auth-httplib2 0.4.0` ページ（2026-05-07 リリース）

> "this library is no longer maintained. For any new usages please see provided transport layers by google-auth library."

このリポジトリは `google-api-python-client` 経由で必要としているため即時撤去不可だが、**新規 import 禁止 + Google 公式の移行ガイドに従う計画を立てるべき**。codebase 直 import は無し（`grep "google_auth_httplib2"` で 0 件）。`googleapiclient.discovery.build` の内部依存。

### 6.3.2 `japanize-matplotlib`（最終リリース 2020-10-21、4 年超停滞）

出典: PyPI `japanize-matplotlib 1.1.3` リリースページ

リリース履歴: 1.1.3 (2020-10-21) で停止。GitHub リポジトリ uehara1414 もアクティブな更新なし。

実コード使用箇所:

```
src/youtube_automation/utils/launch_curve_plotter.py
src/youtube_automation/utils/channel_trend.py
src/youtube_automation/utils/theme_performance.py
```
（grep で確認）

matplotlib 3.10.x 以降のフォント解決と齟齬が出始める可能性があり、代替として `matplotlib.font_manager` で日本語フォントを直接登録する方法が現代的。**P2: 中長期的に置き換え検討**。

### 6.3.3 archived の有無

`schedule` (1.2.2, 2024-06-18) / `seaborn` (0.13.2, 2024-01-25) は更新頻度が低いが PyPI / GitHub では archived 表明なし。現役扱い。

---

## 6.4 lockfile 運用

### 6.4.1 `uv.lock` の存在と再現性

`uv.lock` は git 管理下（`git ls-files | grep lock` で確認済み）、`version = 1`、`requires-python = ">=3.11"` を宣言（uv.lock:1-3）。1687 行で 60 程度のパッケージを解決。

`flake.lock` も commit 済み（nix 利用者向け）。

`requirements.txt` / `requirements.lock` / `Pipfile.lock` 等は存在せず、pip 利用者は実質 PyPI 最新を引く運用。

### 6.4.2 下流再現性ギャップ

下流チャンネルリポジトリは `uv add git+https://github.com/daiki-beppu/youtube-automation` でインストールする（`src/youtube_automation/cli/skills_sync.py:3-4` モジュール docstring に記載）。

**問題**: `uv add` した時点で `uv.lock` は **チャンネルリポジトリ側の lock** に展開される。本リポジトリの `uv.lock` は単なる開発時 lock であり、下流に伝播しない。`pyproject.toml` の依存に上限指定が無いため、下流が `uv add` した日次のタイミング次第で異なる依存バージョンが解決される。

---

## 6.5 Python バージョン制約

### 6.5.1 宣言

- `pyproject.toml:9`: `requires-python = ">=3.11"`
- `pyproject.toml:107`: `[tool.ruff] target-version = "py311"`
- `.python-version`: `3.11`
- `uv.lock:3`: `requires-python = ">=3.11"`

3 箇所で 3.11 が一致しており、整合性は取れている。

### 6.5.2 実装側の Python 3.11+ syntax 使用状況

- `from __future__ import annotations` 使用ファイル: **88 件**（grep で確認）。3.10 互換性を残す形
- `match`/`case` (3.10+) 使用: 0 件確認（grep で match/case パターン 0 件）
- `typing.Self` / `typing.override` (3.11+ / 3.12+) 使用: 0 件
- `typing.ParamSpec` / `TypeVarTuple` (3.10+): 0 件
- 旧式 `Dict` / `List` / `Optional` from `typing`: 多数（`src/youtube_automation/agents/youtube_auto_uploader.py:20` 等）残存

実 syntax は 3.10 互換レベルで書かれている。`requires-python = ">=3.11"` は **過剰制約**の可能性あり、`>=3.10` に下げても動く見込み（ただし pandas 3.x が py3.10 を切っている可能性があるので uv.lock の transitive 解決と要突合せ）。

---

## まとめ（依存健全性 severity）

| ID | 内容 | severity |
|---|---|---|
| 6.1 | 直接依存にメジャー遅延あり (`google-genai` 1.69 → 2.4) | **P1** |
| 6.2.1 | 全依存に version 上限なし → 下流で破壊的アップデート被弾の余地 | **P1** |
| 6.2.2 | `[project.optional-dependencies] veo = []` の dead extras 残骸 | P3 |
| 6.3.1 | `google-auth-httplib2` は PyPI で deprecated 表明済み | **P1** |
| 6.3.2 | `japanize-matplotlib` 4 年超更新停止 | P2 |
| 6.4.2 | `uv.lock` は下流に伝播しないため再現性ギャップあり | P2 |
| 6.5.2 | `requires-python = ">=3.11"` が実 syntax より過剰制約の可能性 | P3 |

調査不可項目: なし（全項目データ取得済み）。
