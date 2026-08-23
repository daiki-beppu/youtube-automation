"""PublishedDatesScheduler.calculate_publish_at の cadence 曜日制約テスト。"""

from datetime import date, datetime
from typing import ClassVar
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from youtube_automation.configuration import ScheduleConfig
from youtube_automation.domains.uploads.collection import PublishedDatesScheduler

TZ = ZoneInfo("Asia/Tokyo")


def calculate_publish_at(
    now: datetime,
    existing_dates: set[date],
    cadence: list[str] | None = None,
    publish_time: str = "11:00",
    auto_schedule_enabled: bool = True,
) -> str | None:
    """本番 collaborator を固定時刻・既存公開日で実行するテストadapter。"""

    scheduler = PublishedDatesScheduler(
        ScheduleConfig(
            timezone=TZ,
            scheduling_enabled=auto_schedule_enabled,
            cadence=tuple(cadence or ()),
            publish_time=publish_time,
        ),
        MagicMock(),
        # now は Asia/Tokyo 付きの固定値なので、渡される tz は使わない
        now_provider=lambda _tz: now,
    )
    scheduler.get_published_dates = MagicMock(return_value=existing_dates)
    return scheduler.calculate_publish_at()


class TestCadenceScheduling:
    """cadence が正しく適用されるかのテスト"""

    CADENCE: ClassVar[list[str]] = ["tue", "thu", "sat"]

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


class TestSchedulingEnabledHeuristic:
    """解決済み ScheduleConfig から予約公開有効性を判定する観測契約。"""

    @staticmethod
    def _calculate(*, enabled: bool, cadence: tuple[str, ...] = (), publish_time: str = "10:00") -> str | None:
        scheduler = PublishedDatesScheduler(
            ScheduleConfig(scheduling_enabled=enabled, cadence=cadence, publish_time=publish_time), MagicMock()
        )
        scheduler.get_published_dates = MagicMock(return_value=set())
        return scheduler.calculate_publish_at()

    def test_explicit_true_enables(self):
        assert self._calculate(enabled=True) is not None

    def test_explicit_false_disables_even_when_cadence_present(self):
        """auto_schedule_enabled=false が明示されていればスケジュール無効（後方互換）."""
        assert self._calculate(enabled=False, cadence=("tue", "thu", "sat")) is None

    def test_cadence_alone_implies_enabled(self):
        """cadence が明示されていれば auto_schedule_enabled 未設定でも有効扱い（#647）."""
        assert self._calculate(enabled=True, cadence=("tue", "thu", "sat")) is not None

    def test_publish_time_alone_implies_enabled(self):
        """publish_time が明示されていれば auto_schedule_enabled 未設定でも有効扱い（#647）."""
        assert self._calculate(enabled=True, publish_time="20:00") is not None

    def test_empty_cadence_does_not_imply_enabled(self):
        """空 cadence はオプトインシグナルにならない."""
        assert self._calculate(enabled=False) is None

    def test_day1_time_alone_does_not_imply_enabled(self):
        """day1_time のみは過去テンプレで既定値が入っていることがあるためシグナルにしない."""
        # 旧テンプレ互換（auto_schedule_enabled なしで day1_time のみ）はスケジュール無効
        assert self._calculate(enabled=False, publish_time="20:00") is None

    def test_empty_dict_disables(self):
        assert self._calculate(enabled=False) is None
