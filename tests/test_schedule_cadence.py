"""_calculate_publish_at の cadence 曜日制約テスト

collection_uploader のインポート依存（schedule パッケージ等）を回避するため、
テスト対象メソッドを直接抽出してテストする。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")

# collection_uploader.py から _calculate_publish_at のロジックを再現
# 本体と同期を保つため、テスト失敗時は本体の変更を確認すること
WEEKDAY_MAP = {
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
    "sun": 7,
}


def calculate_publish_at(
    now: datetime,
    existing_dates: set[date],
    cadence: list[str] | None = None,
    publish_time: str = "11:00",
    auto_schedule_enabled: bool = True,
) -> str | None:
    """_calculate_publish_at のスタンドアロン版（テスト用）

    本体: agents/collection_uploader.py CollectionUploader._calculate_publish_at
    """
    if not auto_schedule_enabled:
        return None

    hour, minute = map(int, publish_time.split(":"))

    allowed_weekdays = {WEEKDAY_MAP[d.lower()] for d in cadence} if cadence else set(range(1, 8))

    publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if publish_dt <= now:
        publish_dt += timedelta(days=1)

    max_slide = 30
    for _ in range(max_slide):
        if publish_dt.isoweekday() in allowed_weekdays and publish_dt.date() not in existing_dates:
            break
        publish_dt += timedelta(days=1)

    return publish_dt.isoformat()


class TestCadenceScheduling:
    """cadence が正しく適用されるかのテスト"""

    CADENCE = ["tue", "thu", "sat"]

    def test_skips_non_cadence_day(self):
        """木曜 14:00 → 公開時刻過ぎ → 金曜スキップ → 土曜に公開"""
        now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=TZ)  # 木曜
        result = calculate_publish_at(now, set(), cadence=self.CADENCE)
        dt = datetime.fromisoformat(result)
        assert dt.isoweekday() == 6  # 土曜
        assert dt.date() == date(2026, 3, 28)

    def test_same_day_before_publish_time(self):
        """当日 cadence 曜日で公開時刻前なら当日に公開"""
        now = datetime(2026, 3, 26, 9, 0, 0, tzinfo=TZ)  # 木曜 09:00
        result = calculate_publish_at(now, set(), cadence=self.CADENCE)
        dt = datetime.fromisoformat(result)
        assert dt.isoweekday() == 4  # 木曜
        assert dt.date() == date(2026, 3, 26)

    def test_same_day_non_cadence_before_publish_time(self):
        """当日が cadence 外なら次の cadence 曜日まで飛ぶ"""
        now = datetime(2026, 3, 25, 9, 0, 0, tzinfo=TZ)  # 水曜 09:00
        result = calculate_publish_at(now, set(), cadence=self.CADENCE)
        dt = datetime.fromisoformat(result)
        assert dt.isoweekday() == 4  # 木曜
        assert dt.date() == date(2026, 3, 26)

    def test_skips_existing_date(self):
        """cadence 曜日でも既存公開日があればスキップ"""
        now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=TZ)  # 木曜
        existing = {date(2026, 3, 28)}  # 土曜に既に公開済み
        result = calculate_publish_at(now, existing, cadence=self.CADENCE)
        dt = datetime.fromisoformat(result)
        assert dt.isoweekday() == 2  # 火曜
        assert dt.date() == date(2026, 3, 31)

    def test_no_cadence_allows_any_day(self):
        """cadence 未設定なら全曜日許可（従来動作）"""
        now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=TZ)  # 木曜
        result = calculate_publish_at(now, set(), cadence=None)
        dt = datetime.fromisoformat(result)
        assert dt.date() == date(2026, 3, 27)  # 翌日（金曜）

    def test_auto_schedule_disabled_returns_none(self):
        """auto_schedule_enabled=false なら None"""
        now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=TZ)
        result = calculate_publish_at(now, set(), auto_schedule_enabled=False)
        assert result is None

    def test_publish_time_respected(self):
        """公開時刻が正しく設定される"""
        now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=TZ)
        result = calculate_publish_at(now, set(), cadence=self.CADENCE, publish_time="11:00")
        dt = datetime.fromisoformat(result)
        assert dt.hour == 11
        assert dt.minute == 0

    def test_consecutive_scheduling(self):
        """連続スケジュールで Tue→Thu→Sat パターンが維持される"""
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=TZ)  # 日曜
        existing = set()
        weekdays = []

        for _ in range(6):
            result = calculate_publish_at(now, existing, cadence=self.CADENCE)
            dt = datetime.fromisoformat(result)
            weekdays.append(dt.isoweekday())
            existing.add(dt.date())

        assert all(w in (2, 4, 6) for w in weekdays), f"Non-cadence days: {weekdays}"
        assert weekdays == [2, 4, 6, 2, 4, 6]

    def test_bug_regression_friday_not_scheduled(self):
        """回帰テスト: 木曜の後に金曜(3/27)ではなく土曜(3/28)になること"""
        # 実際のバグ: 2026-03-26 木曜 14:24 に実行 → 3/27 金曜にスケジュールされた
        now = datetime(2026, 3, 26, 14, 24, 0, tzinfo=TZ)
        existing = {date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 26)}
        result = calculate_publish_at(now, existing, cadence=self.CADENCE)
        dt = datetime.fromisoformat(result)
        assert dt.date() == date(2026, 3, 28), f"Expected Sat 3/28, got {dt.date()} ({dt.strftime('%A')})"
        assert dt.isoweekday() == 6  # 土曜
