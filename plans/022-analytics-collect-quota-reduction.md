# Plan 022: analytics collect の uploads playlist 二重取得を解消し、video_listing の例外握りつぶしと TZ 境界ズレを直す

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 5394c378..HEAD -- src/youtube_automation/utils/video_listing.py src/youtube_automation/utils/strategic_analytics.py src/youtube_automation/scripts/analytics_system.py`
> 差分が出たら「Current state」の抜粋と実コードを突き合わせ、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf + bug
- **Planned at**: commit `5394c378`, 2026-07-09

## Why this matters

YouTube Data API は日次ハードクォータ（デフォルト 10,000 units）の共有資源で、この自動化基盤の全機能が奪い合う。`analytics-collect` の標準実行は uploads playlist の全ページネーション（50 本/ページ、1 ページ = 1 unit）を**最低 2 回**走らせている — 動画リストは 1 プロセス内で変わらないのに。数百本のチャンネルでは毎 collect で数〜十数 units を無駄にし、チャンネルが増えるほど効く。あわせて同ファイルに 2 つの正確性問題が同居している: (1) `get_all_channel_videos` / `get_recent_videos` が生 `Exception` を握りつぶして `[]` を返すため、認証切れやクォータ枯渇が「動画 0 本のチャンネル」として無言で分析結果に化ける。(2) naive `datetime.now()`（ローカル JST）と UTC の `publishedAt` を比較しており、「直近 N 日」フィルタの境界が 9 時間ズレる（真の境界直後 9 時間に公開された動画が漏れる）。同一ファイル中心の S 級修正なので 1 プランにまとめる。

## Current state

- `src/youtube_automation/utils/video_listing.py` — `VideoListingMixin`。`YouTubeAnalyticsCollector`（`utils/analytics_collector.py:43-`）に合成される mixin の 1 つ。**mixin には `__init__` が無い**（キャッシュ属性は遅延初期化にする必要がある）
- `src/youtube_automation/utils/strategic_analytics.py` — `get_combined_analytics`（efficient 経路）が `:50` で全動画取得し、`:56-63` に直近フィルタの**重複実装**（同じ naive TZ 比較）を持つ
- `src/youtube_automation/scripts/analytics_system.py` — collect の司令塔。`:50` で `YouTubeAnalyticsCollector()` を生成し、`:102` の `collect_basic_analytics(...)` の後、`:133` で**再度** `self.collector.get_all_channel_videos()` を呼ぶ

二重取得の実体 — `video_listing.py:46-57`（memoize なしの全ページネーション）:

```python
            while True:
                # プレイリストのアイテムを取得
                playlist_response = (
                    self.youtube_service.playlistItems()
                    .list(
                        part="snippet,contentDetails",
                        playlistId=uploads_playlist_id,
                        maxResults=50,
                        pageToken=next_page_token,
                    )
                    .execute()
                )
```

握りつぶし — `video_listing.py:81-86`（`get_recent_videos` にも `:124-126` に同型）:

```python
        except HttpError as e:
            logger.error(f"YouTube API エラー（動画リスト取得）: {e}")
            return []
        except Exception as e:
            logger.error(f"動画リスト取得エラー: {e}")
            return []
```

TZ 境界ズレ — `video_listing.py:104-116`:

```python
            cutoff_date = datetime.now() - timedelta(days=days)
            ...
                published_date = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))

                if published_date.replace(tzinfo=None) >= cutoff_date:
```

`cutoff_date` はローカル（JST）の naive 時刻、`published_date.replace(tzinfo=None)` は UTC の壁時計。JST は UTC+9 なので cutoff が実質 9 時間厳しくなる。同じパターンが `strategic_analytics.py:56-63` にもある。

再取得箇所 — `analytics_system.py:131-138`:

```python
                # 動画×日次データ（launch curve 分析用）
                try:
                    video_list = self.collector.get_all_channel_videos()
                    video_ids = [v["video_id"] for v in video_list]
```

`get_all_channel_videos` の全呼び出し箇所（確認済み・これで全部）: `video_listing.py:107`（get_recent_videos 内）、`strategic_analytics.py:50` / `:251`、`analytics_system.py:133`。Protocol 宣言が `analytics_base.py:32` にある。

### 適用される規約

- 生 `Exception` catch はリポジトリ規約違反。ドメイン例外は `utils/exceptions.py`（`YouTubeAPIError.from_http_error(error, context)` が使える）
- `src/` を触るため `CHANGELOG.md` `[Unreleased]` 追記必須
- テストの autouse fixture が config singleton をリセットする（`tests/conftest.py`）。collector はプロセス毎に生成されるためキャッシュはインスタンス属性で安全

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `uv run pytest tests/test_analytics_system.py tests/test_strategic_analytics_parallel.py -q` | all pass |
| 新規テスト | `uv run pytest tests/test_video_listing.py -q` | all pass |
| 全テスト | `uv run pytest -q` | all pass |
| Lint / Format | `uv run ruff check src tests && uv run ruff format --check src tests` | exit 0 |

## Scope

**In scope**:

- `src/youtube_automation/utils/video_listing.py`
- `src/youtube_automation/utils/strategic_analytics.py`（`:56-63` の TZ 比較の統一と `:50`/`:251` のキャッシュ経由化のみ）
- `tests/test_video_listing.py`（新規）
- `CHANGELOG.md`

**Out of scope**:

- `analytics_system.py:133` の呼び出し自体 — インスタンスキャッシュ導入で自動的に 2 回目が無料になるため、**呼び出し構造は変えない**
- PERF-02 系（`_get_video_details` / `dimensions=video` クエリのサブ分析間共有）— M 級の別課題。今回は着手しない
- `analytics_base.py` の Protocol シグネチャ変更
- retention の per-video クエリ（API 仕様上バッチ不可、by design）

## Git workflow

- worktree 上で作業。base branch は main
- commit 例: `fix(analytics): 全動画リストの instance cache 導入と TZ 境界・例外握りつぶし修正 (#<issue>)`
- push / PR 化はオペレーター指示時のみ

## Steps

### Step 1: `get_all_channel_videos` にインスタンスキャッシュを入れる

`video_listing.py` の `get_all_channel_videos` 冒頭（`initialize()` 呼び出しの後）に:

```python
        cached = getattr(self, "_all_videos_cache", None)
        if cached is not None:
            return cached
```

成功 return の直前で `self._all_videos_cache = videos` を代入。**空リスト `[]` はキャッシュしない**（エラー時 `[]` の再試行余地を残す — Step 2 で例外化した後も、途中 break の空結果を恒久化しないため）。あわせて `refresh: bool = False` 引数を追加し、`True` でキャッシュを無視して再取得できるようにする（Protocol `analytics_base.py:32` はデフォルト引数の追加なので互換）。

**Verify**: `uv run pytest tests/test_analytics_system.py tests/test_strategic_analytics_parallel.py -q` → all pass

### Step 2: 例外の握りつぶしをやめる

`video_listing.py` の 2 メソッドで:

- `except Exception` 節（`:84-86`, `:124-126`）を**削除**する
- `except HttpError` 節は `raise YouTubeAPIError.from_http_error(e, "チャンネル動画リスト取得")` に変更する（`from youtube_automation.utils.exceptions import YouTubeAPIError` を追加）

呼び出し側の空リスト分岐（`strategic_analytics.py:51-52` の `if not all_videos: return ...`）は「動画 0 本の正当なチャンネル」用として残す。`analytics_system.py:132` の daily セクションは既に `try` で囲まれているため collect 全体は落ちない（確認済み — `:132` の `try:`）。

**Verify**: `uv run pytest -q` → all pass（analytics 系テストが `[]` フォールバックに依存していたら、そのテストは「エラーを無言で握りつぶす」仕様を固定していたということ — `pytest.raises(YouTubeAPIError)` へ書き換えてよい）

### Step 3: TZ 比較を aware に統一する

両ファイルの直近フィルタを次の形に:

```python
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        ...
            published_date = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))
            if published_date >= cutoff_date:
```

対象: `video_listing.py:104` + `:115`、`strategic_analytics.py:56` + `:63`。`from datetime import timezone` を追加。`.replace(tzinfo=None)` を撤去。

**Verify**: `uv run pytest -q` → all pass

### Step 4: 新規テスト + CHANGELOG

`tests/test_video_listing.py` を新規作成（構造パターン: `tests/test_strategic_analytics_parallel.py` — collector を作らずフェイク `youtube_service` を属性注入して mixin メソッドを直接叩く方式に従う）。

**Verify**: `uv run pytest tests/test_video_listing.py -q` → all pass / `uv run pytest -q` → all pass / ruff 2 コマンド exit 0

## Test plan

`tests/test_video_listing.py` に最低 5 ケース:

1. **キャッシュ**: フェイク `playlistItems().list().execute` に呼び出しカウンタを仕込み、`get_all_channel_videos()` 2 回呼びで playlist ページ取得が 1 巡分しか走らない
2. **refresh**: `get_all_channel_videos(refresh=True)` で再取得が走る
3. **空リスト非キャッシュ**: 1 回目が 0 件 → 2 回目も API を叩く
4. **例外**: `execute` が `HttpError` を raise（`googleapiclient.errors.HttpError` はフェイク resp で組める — `tests/integration/test_upload_core.py` に組み方の先例）→ `pytest.raises(YouTubeAPIError)`
5. **TZ 境界**: `published_at` が「cutoff の 4 時間後（UTC）」の動画を用意し、`get_recent_videos(days=N)` に**含まれる**こと（修正前は JST ズレで漏れるケース）。時刻固定には monkeypatch で `datetime` を差し替えず、`published_at` を `datetime.now(timezone.utc)` 相対で組み立てる（実時刻依存を避ける）

## Done criteria

- [ ] `uv run pytest -q` exit 0（新規 5 テスト含む）
- [ ] `rg -n 'except Exception' src/youtube_automation/utils/video_listing.py` → 0 件
- [ ] `rg -n 'replace\(tzinfo=None\)' src/youtube_automation/utils/video_listing.py src/youtube_automation/utils/strategic_analytics.py` → 0 件
- [ ] `rg -n '_all_videos_cache' src/youtube_automation/utils/video_listing.py` → ヒットあり
- [ ] ruff check / format --check exit 0
- [ ] `CHANGELOG.md` `[Unreleased]` に追記
- [ ] `git status` で in-scope 外の変更なし
- [ ] `plans/README.md` の 022 行を更新

## STOP conditions

- Drift check 不一致
- `get_all_channel_videos` の呼び出し箇所が「Current state」に列挙した 4 箇所以外に増えていた場合（キャッシュの生存期間の再検討が要る）
- Step 2 で `[]` フォールバックに依存するテストが 5 件を超えて壊れた場合（無言劣化が広範に仕様化されている — 影響範囲の判断をオペレーターへ）
- `YouTubeAnalyticsCollector` がプロセスをまたいで再利用される（daemon 化等の）形跡を見つけた場合

## Maintenance notes

- このキャッシュは「1 プロセス = 1 collect 実行」前提。collector を長寿命化する変更（常駐 daemon 等）が入るなら TTL か明示 invalidation が要る — その時は `refresh=True` が既にある
- レビューで見るべき点: 空リストをキャッシュしていないこと、`strategic_analytics.py` 側の直近フィルタが video_listing 側と同じ aware 比較になっていること
- 明示的に先送り: PERF-02（サブ分析間の `_get_video_details` 共有、M 級）、`get_recent_videos` と `strategic_analytics.py:54-67` の直近フィルタ重複実装の共通化（今回は挙動統一まで）
