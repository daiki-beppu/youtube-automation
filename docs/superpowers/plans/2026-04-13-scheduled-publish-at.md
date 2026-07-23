# scheduled_publish_at フィールド追加 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analytics 出力の各動画エントリに `scheduled_publish_at`（予約公開日時）を追加し、アップロード日と公開日を区別可能にする

**Architecture:** `ChannelAnalyticsMixin.collect_basic_analytics()` で `video_data` dict 構築後に、`collections/live/` の `upload_tracking.json` を走査して `video_id` → `publish_at` マッピングを構築し注入する。新規ヘルパー `_build_publish_at_map()` を1つ追加するだけの最小変更。

**Tech Stack:** Python, YouTube Analytics API（既存）, json（標準ライブラリ）

**Spec:** `docs/superpowers/specs/2026-04-13-scheduled-publish-at-design.md`

---

### Task 1: `_build_publish_at_map()` のテストを書く

**Files:**
- Create: `tests/test_publish_at_map.py`

- [ ] **Step 1: テストファイル作成**

```python
"""_build_publish_at_map() のユニットテスト"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.utils.channel_config import ChannelConfig


@pytest.fixture(autouse=True)
def reset_singletons():
    ChannelConfig.reset()
    yield
    ChannelConfig.reset()


@pytest.fixture
def live_dir(tmp_path):
    """upload_tracking.json を持つ模擬 collections/live/ を構築"""
    live = tmp_path / "collections" / "live"

    # コレクション A: 正常な tracking
    col_a = live / "20260326-rjn-cafe-collection" / "20-documentation"
    col_a.mkdir(parents=True)
    (col_a / "upload_tracking.json").write_text(json.dumps({
        "schema_version": 3,
        "collection_name": "20260326-rjn-cafe-collection",
        "status": "completed",
        "complete_collection": {
            "video_id": "ABC123",
            "video_url": "https://www.youtube.com/watch?v=ABC123",
            "upload_time": "2026-03-25T08:00:00.000000",
            "publish_at": "2026-03-26T11:00:00+09:00",
            "status": "completed"
        }
    }))

    # コレクション B: 正常な tracking（別タイムゾーン）
    col_b = live / "20260402-rjn-ember-collection" / "20-documentation"
    col_b.mkdir(parents=True)
    (col_b / "upload_tracking.json").write_text(json.dumps({
        "schema_version": 3,
        "collection_name": "20260402-rjn-ember-collection",
        "status": "completed",
        "complete_collection": {
            "video_id": "DEF456",
            "video_url": "https://www.youtube.com/watch?v=DEF456",
            "upload_time": "2026-04-01T10:00:00.000000",
            "publish_at": "2026-04-02T02:00:00-04:00",
            "status": "completed"
        }
    }))

    # コレクション C: tracking なし（planning 段階）
    col_c = live / "20260410-rjn-wip-collection" / "20-documentation"
    col_c.mkdir(parents=True)

    # コレクション D: 壊れた JSON
    col_d = live / "20260411-rjn-broken-collection" / "20-documentation"
    col_d.mkdir(parents=True)
    (col_d / "upload_tracking.json").write_text("not json")

    return tmp_path


def _make_mixin(channel_dir):
    """ChannelAnalyticsMixin だけをインスタンス化するヘルパー"""
    from youtube_automation.domains.analytics.mixins.channel_analytics import ChannelAnalyticsMixin
    obj = object.__new__(ChannelAnalyticsMixin)
    return obj


class TestBuildPublishAtMap:
    def test_returns_mapping_for_valid_tracking(self, live_dir):
        mixin = _make_mixin(live_dir)
        with patch.object(ChannelConfig, 'channel_dir', return_value=live_dir):
            result = mixin._build_publish_at_map()

        assert result == {
            "ABC123": "2026-03-26T11:00:00+09:00",
            "DEF456": "2026-04-02T02:00:00-04:00",
        }

    def test_skips_missing_tracking(self, live_dir):
        """tracking ファイルがないコレクションは無視"""
        mixin = _make_mixin(live_dir)
        with patch.object(ChannelConfig, 'channel_dir', return_value=live_dir):
            result = mixin._build_publish_at_map()

        assert "WIP_ID" not in result

    def test_skips_broken_json(self, live_dir):
        """壊れた JSON は無視してクラッシュしない"""
        mixin = _make_mixin(live_dir)
        with patch.object(ChannelConfig, 'channel_dir', return_value=live_dir):
            result = mixin._build_publish_at_map()

        # 壊れた分はスキップされ、正常な2件だけ返る
        assert len(result) == 2

    def test_empty_when_no_live_dir(self, tmp_path):
        """collections/live/ が存在しない場合は空 dict"""
        mixin = _make_mixin(tmp_path)
        with patch.object(ChannelConfig, 'channel_dir', return_value=tmp_path):
            result = mixin._build_publish_at_map()

        assert result == {}
```

- [ ] **Step 2: テスト実行 — 失敗を確認**

Run: `cd /Users/mba/02-yt/automation && uv run pytest tests/test_publish_at_map.py -v`
Expected: FAIL — `AttributeError: 'ChannelAnalyticsMixin' object has no attribute '_build_publish_at_map'`

---

### Task 2: `_build_publish_at_map()` を実装する

**Files:**
- Modify: `src/youtube_automation/domains/analytics/mixins/channel_analytics.py:5-11` (imports)
- Modify: `src/youtube_automation/domains/analytics/mixins/channel_analytics.py:68` (新メソッド追加)

- [ ] **Step 1: import を追加**

`channel_analytics.py` の先頭 import ブロックに追加:

```python
import json
from pathlib import Path
```

既存の import:
```python
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict
```

変更後:
```python
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict
```

- [ ] **Step 2: `_build_publish_at_map()` メソッドを追加**

`ChannelAnalyticsMixin` クラス内、`collect_basic_analytics()` メソッドの直前（L69 付近）に追加:

```python
    def _build_publish_at_map(self) -> dict[str, str]:
        """collections/live/ の upload_tracking.json から video_id → publish_at マップを構築。"""
        from youtube_automation.utils.channel_config import ChannelConfig

        publish_map: dict[str, str] = {}
        live_dir = ChannelConfig.channel_dir() / 'collections' / 'live'
        if not live_dir.exists():
            return publish_map
        for collection_dir in live_dir.iterdir():
            if not collection_dir.is_dir():
                continue
            tracking = collection_dir / '20-documentation' / 'upload_tracking.json'
            if not tracking.exists():
                continue
            try:
                data = json.loads(tracking.read_text())
                cc = data.get('complete_collection', {})
                vid = cc.get('video_id')
                pub = cc.get('publish_at')
                if vid and pub:
                    publish_map[vid] = pub
            except (json.JSONDecodeError, OSError):
                continue
        return publish_map
```

Note: `ChannelConfig` は循環 import を避けるため関数内 import にする。

- [ ] **Step 3: テスト実行 — パスを確認**

Run: `cd /Users/mba/02-yt/automation && uv run pytest tests/test_publish_at_map.py -v`
Expected: 4 passed

- [ ] **Step 4: コミット**

```bash
cd /Users/mba/02-yt/automation
git add tests/test_publish_at_map.py src/youtube_automation/domains/analytics/mixins/channel_analytics.py
git commit -m "feat: _build_publish_at_map() で upload_tracking から予約公開日を収集"
```

---

### Task 3: `collect_basic_analytics()` に注入ロジックを追加

**Files:**
- Modify: `src/youtube_automation/domains/analytics/mixins/channel_analytics.py:106-107` (video_data 構築直後)
- Modify: `tests/test_analytics_system.py` (既存テストの更新)

- [ ] **Step 1: 注入テストを追加**

`tests/test_publish_at_map.py` に追加:

```python
class TestCollectBasicAnalyticsIntegration:
    """collect_basic_analytics() が scheduled_publish_at を注入することを検証"""

    def test_injects_scheduled_publish_at(self, live_dir):
        """video_data に scheduled_publish_at が追加される"""
        with patch.object(ChannelConfig, 'channel_dir', return_value=live_dir), \
             patch('youtube_automation.domains.analytics.mixins.channel_analytics.ChannelAnalyticsMixin.get_channel_analytics') as mock_ch, \
             patch('youtube_automation.domains.analytics.mixins.channel_analytics.ChannelAnalyticsMixin.get_strategic_video_analytics') as mock_strat, \
             patch.object(ChannelAnalyticsMixin, 'initialize'):

            mock_ch.return_value = {"period": "test", "daily_metrics": []}
            mock_strat.return_value = {
                'mode': 'efficient',
                'top_videos': [
                    {'video_id': 'ABC123', 'title': 'Cafe', 'published_at': '2026-03-25T08:00:00Z'},
                    {'video_id': 'XYZ789', 'title': 'Unknown', 'published_at': '2026-04-01T00:00:00Z'},
                ],
                'recent_videos': [],
                'summary': {},
            }

            from youtube_automation.domains.analytics.mixins.channel_analytics import ChannelAnalyticsMixin
            mixin = object.__new__(ChannelAnalyticsMixin)
            result = mixin.collect_basic_analytics("2026-03-14", "2026-04-13", depth="basic")

            video_data = result['video_analytics']
            # マッチする動画: publish_at が入る
            assert video_data['ABC123']['scheduled_publish_at'] == "2026-03-26T11:00:00+09:00"
            # マッチしない動画: None
            assert video_data['XYZ789']['scheduled_publish_at'] is None
```

- [ ] **Step 2: テスト実行 — 失敗を確認**

Run: `cd /Users/mba/02-yt/automation && uv run pytest tests/test_publish_at_map.py::TestCollectBasicAnalyticsIntegration -v`
Expected: FAIL — `KeyError: 'scheduled_publish_at'`

- [ ] **Step 3: `collect_basic_analytics()` に注入コードを追加**

`channel_analytics.py` の `video_data` dict 構築直後（現在の L106-107 付近）:

```python
            # 動画データをキー化
            video_data = {}
            for video in video_analytics:
                video_id = video.get('video_id')
                if video_id:
                    video_data[video_id] = video
```

この直後に追加:

```python
            # upload_tracking から予約公開日時を注入
            publish_at_map = self._build_publish_at_map()
            for vid, entry in video_data.items():
                entry['scheduled_publish_at'] = publish_at_map.get(vid)
```

- [ ] **Step 4: テスト実行 — 全パスを確認**

Run: `cd /Users/mba/02-yt/automation && uv run pytest tests/test_publish_at_map.py -v`
Expected: 5 passed

- [ ] **Step 5: 既存テストが壊れていないことを確認**

Run: `cd /Users/mba/02-yt/automation && uv run pytest tests/test_analytics_system.py -v`
Expected: 全テスト PASS

- [ ] **Step 6: コミット**

```bash
cd /Users/mba/02-yt/automation
git add src/youtube_automation/domains/analytics/mixins/channel_analytics.py tests/test_publish_at_map.py
git commit -m "feat: collect_basic_analytics() に scheduled_publish_at 注入を追加"
```

---

### Task 4: E2E 検証

- [ ] **Step 1: rjn リポジトリでパッケージを更新**

```bash
cd /Users/mba/02-yt/rjn
uv lock --upgrade-package youtube-channels-automation && uv sync
```

- [ ] **Step 2: analytics 収集を実行**

```bash
cd /Users/mba/02-yt/rjn
uv run yt-analytics --days 30
```

- [ ] **Step 3: 出力 JSON を検証**

最新の `data/analytics_data_*.json` を開き:
1. `video_analytics` 内の各エントリに `scheduled_publish_at` キーが存在する
2. `upload_tracking.json` がある動画: ISO 8601 + TZ 文字列（例: `"2026-03-26T11:00:00+09:00"`）
3. マッチしない動画: `null`
4. 既存フィールド（`published_at`, `views`, `title` 等）が正常

- [ ] **Step 4: 確認後コミット（rjn 側の lock 更新）**

```bash
cd /Users/mba/02-yt/rjn
git add uv.lock
git commit -m "chore: youtube-channels-automation パッケージ更新（scheduled_publish_at 対応）"
```
