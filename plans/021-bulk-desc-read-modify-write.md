# Plan 021: bulk_update_descriptions_from_md の snippet 更新を read-modify-write 化し defaultAudioLanguage 消失を止める

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 5394c378..HEAD -- src/youtube_automation/scripts/bulk_update_descriptions_from_md.py tests/test_bulk_update_descriptions_from_md.py`
> 差分が出たら「Current state」の抜粋と実コードを突き合わせ、不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED（公開済み動画のメタデータを一括で書き換えるツールの挙動変更）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5394c378`, 2026-07-09

## Why this matters

`yt-bulk-update-desc` は `collections/live/*` の descriptions.md を YouTube へ一括反映するツールで、`videos().update(part="snippet")` を使う。**YouTube Data API の仕様では `part=snippet` の update は snippet リソース全体を置換し、リクエスト body に含まれない mutable フィールドはクリアされる**。現在の実装は body を手組みで列挙しており、`defaultAudioLanguage` が入っていないため、このツールを通した全動画で音声言語設定が消える。さらに `defaultLanguage` 未設定の動画には `"en"` を注入してしまう（日本語チャンネルでは誤ラベル）。音楽アップロードでは `defaultAudioLanguage` が設定されていることが多く、back catalog 全体が blast radius。姉妹スクリプト `bulk_update_synthetic_media.py` は全く同じ理由で read-modify-write を既に実装しており、本プランはそのパターンに揃えるだけである。

## Current state

- `src/youtube_automation/scripts/bulk_update_descriptions_from_md.py` — 対象スクリプト（181 行）。`:116` で `videos().list(id=..., part="snippet")` により現 snippet を取得済み（`old_snippet`、`:124`）なのに、body 構築で使っていない
- `tests/test_bulk_update_descriptions_from_md.py` — 既存テスト。`videos().update().execute` の呼び出し回数・dry-run・UTF-16 境界を検証している（構造パターンとして流用する）

問題の body 構築 — `bulk_update_descriptions_from_md.py:156-165`:

```python
        body = {
            "id": p["video_id"],
            "snippet": {
                "title": new_title,
                "description": new_desc,
                "tags": new_tags,
                "categoryId": old_snippet.get("categoryId", "10"),
                "defaultLanguage": old_snippet.get("defaultLanguage", "en"),
            },
        }
        try:
            yt.videos().update(part="snippet", body=body).execute()
            print("   ✅ updated")
        except Exception as e:
            print(f"   ❌ update failed: {e}")
```

リポジトリ内の正しい先例 — `src/youtube_automation/scripts/bulk_update_synthetic_media.py:143-151`:

```python
def build_update_body(video_id: str, status: dict) -> dict:
    """現 status を保持したまま ``containsSyntheticMedia=True`` を立てた update body を返す.

    ``videos.update(part='status')`` は status リソース全体を置換するため、現値を
    コピーして read-only キーを除去し、``containsSyntheticMedia`` だけ差し替える。
    """
    new_status = {k: v for k, v in status.items() if k not in READONLY_STATUS_KEYS}
    new_status["containsSyntheticMedia"] = True
    return {"id": video_id, "status": new_status}
```

### API 知識（executor が知っている必要がある事実）

`videos.update` で書き換え可能な snippet のフィールドは次の 6 つだけ:
`title`, `description`, `tags`, `categoryId`, `defaultLanguage`, `defaultAudioLanguage`。
`videos().list(part="snippet")` のレスポンスにはこれ以外に `publishedAt` / `channelId` / `thumbnails` / `channelTitle` / `localized` / `liveBroadcastContent` などの read-only フィールドが混ざるため、**old_snippet の丸ごとコピーではなく mutable 6 キーの whitelist コピー**にする（synthetic_media の `READONLY_STATUS_KEYS` 方式の snippet 版）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `uv run pytest tests/test_bulk_update_descriptions_from_md.py -q` | all pass |
| 全テスト | `uv run pytest -q` | all pass |
| Lint / Format | `uv run ruff check src tests && uv run ruff format --check src tests` | exit 0 |

## Scope

**In scope**:

- `src/youtube_automation/scripts/bulk_update_descriptions_from_md.py`
- `tests/test_bulk_update_descriptions_from_md.py`
- `CHANGELOG.md`（`[Unreleased]` 追記 — src/ を触るため必須）

**Out of scope**:

- `bulk_update_synthetic_media.py` — 参照する先例であり、変更しない
- `bulk_update_short_localizations.py` — 別 part（localizations）を扱う別ツール。触らない
- descriptions.md のパース部（`:110` より前）— 本プランの欠陥と無関係
- title の UTF-16 100 units ガード（`:132-139`）— 正しく動いている

## Git workflow

- worktree 上で作業。base branch は main
- commit 例: `fix(scripts): bulk_update_desc の snippet 更新を read-modify-write 化 (#<issue>)`
- push / PR 化はオペレーター指示時のみ

## Steps

### Step 1: mutable キー whitelist で body を構築する関数を切り出す

モジュールレベルに定数と純粋関数を追加する（テスト容易性のため main 内へ inline しない）:

```python
MUTABLE_SNIPPET_KEYS = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")


def build_snippet_update_body(video_id: str, old_snippet: dict, title: str, description: str, tags: list) -> dict:
    """現 snippet の mutable キーを保持したまま title/description/tags を差し替えた update body を返す.

    ``videos.update(part='snippet')`` は snippet リソース全体を置換するため、
    body に含まれない mutable フィールド（defaultAudioLanguage 等）は消える。
    bulk_update_synthetic_media.build_update_body と同じ read-modify-write 方式。
    """
    new_snippet = {k: old_snippet[k] for k in MUTABLE_SNIPPET_KEYS if k in old_snippet}
    new_snippet["title"] = title
    new_snippet["description"] = description
    new_snippet["tags"] = tags
    new_snippet.setdefault("categoryId", "10")
    return {"id": video_id, "snippet": new_snippet}
```

要点: `defaultLanguage` は**存在するときだけ**引き継ぐ（無い動画に `"en"` を注入する現行挙動を廃止）。`categoryId` の `"10"`（音楽）fallback は現行挙動を維持。

**Verify**: `uv run ruff check src/youtube_automation/scripts/bulk_update_descriptions_from_md.py` → exit 0

### Step 2: main ループから新関数を使う

`:156-165` の手組み body を `body = build_snippet_update_body(p["video_id"], old_snippet, new_title, new_desc, new_tags)` に置き換える。あわせて `:169` の `except Exception` を `except HttpError` に狭める（`from googleapiclient.errors import HttpError` を追加。1 本の失敗で残りのバッチを止めない print-and-continue 挙動は維持）。

**Verify**: `uv run pytest tests/test_bulk_update_descriptions_from_md.py -q` → all pass（既存テストが body 形状を握っていれば期待値を新形状に更新してよい — それがこの修正の本体）

### Step 3: 回帰テストを追加

`tests/test_bulk_update_descriptions_from_md.py` に既存テストと同じフェイク構造で追加:

1. old_snippet に `defaultAudioLanguage: "ja"` がある → update body の snippet に `defaultAudioLanguage == "ja"` が含まれる
2. old_snippet に `defaultLanguage` が**ない** → body の snippet に `defaultLanguage` キーが**存在しない**（`"en"` 注入の再発防止）
3. old_snippet の read-only キー（例 `publishedAt`, `thumbnails`）が body に**含まれない**
4. `build_snippet_update_body` 単体: title/description/tags が引数の値で上書きされる

**Verify**: `uv run pytest tests/test_bulk_update_descriptions_from_md.py -q` → all pass（新規 4 ケース含む）

### Step 4: CHANGELOG 追記 + 全体検証

`CHANGELOG.md` `[Unreleased]` の Fixed に「bulk_update_desc が snippet 全置換で defaultAudioLanguage を消していた問題を read-modify-write 化で修正」を追記。

**Verify**: `uv run pytest -q` → all pass / `uv run ruff check src tests && uv run ruff format --check src tests` → exit 0

## Test plan

（Step 3 に統合。構造パターンは同ファイルの既存テスト — `videos().update` をモックし body を捕捉して assert する方式 — に従う）

## Done criteria

- [ ] `uv run pytest -q` exit 0（新規 4 テスト含む）
- [ ] `rg -n 'defaultAudioLanguage' src/youtube_automation/scripts/bulk_update_descriptions_from_md.py` が MUTABLE_SNIPPET_KEYS 定義でヒットする
- [ ] `rg -n '"defaultLanguage": old_snippet.get' src/youtube_automation/scripts/` が 0 件（"en" fallback の消滅）
- [ ] `uv run ruff check src tests` / `uv run ruff format --check src tests` exit 0
- [ ] `CHANGELOG.md` `[Unreleased]` に追記
- [ ] `git status` で in-scope 外の変更なし
- [ ] `plans/README.md` の 021 行を更新

## STOP conditions

- Drift check 不一致（特に body 構築部 `:156-165` が既に変更されている場合）
- 既存テストが body の旧形状（`defaultLanguage: "en"` fallback 等）を**仕様として**固定しており、その変更が他のテスト・スキル記述（`.claude/skills/video-description/` 等）と連動している形跡を見つけた場合 — 影響範囲の判断はオペレーターに戻す
- `videos().list` の取得 part が snippet 以外に変わっていた場合

## Maintenance notes

- レビューで見るべき点: whitelist が mutable 6 キー**ちょうど**であること（read-only キーを送ると API はエラーにはしないが、意図しないフィールドを「保持しているつもり」になる事故のもと）
- 将来 `part` を増やす（status 等を同時更新する）変更が入る場合、synthetic_media 側の `READONLY_STATUS_KEYS` との共通化を検討する
- 明示的に先送り: 実 YouTube への統合テスト（このツールは operator が dry-run → 実行の 2 段で使う運用ガードが既にある）
