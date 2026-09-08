"""Read-only display of the resolved collection upload plan and quota estimate."""

from pathlib import Path

from youtube_automation.domains.uploads.quota import (
    DAILY_BUCKET_LIMITS,
    UNIT_COSTS,
    UNIT_POOL_LIMIT,
    complete_collection_quota_plan,
)


def print_collection_plan(
    collection_path: Path, publish_at: str | None, privacy_status: str, *, scheduling_disabled: bool
) -> None:
    """Render the upload plan without executing uploads or mutating quota state."""
    print(f"📋 アップロード計画: {collection_path.name}")
    print()
    print("  ── Complete Collection アップロード ──")
    print("  1. Complete Collection アップロード")
    print("  2. live/ に移動")
    print()
    if publish_at:
        print(f"  📅 公開予定: {publish_at}")
    else:
        if privacy_status == "public":
            print("  📅 公開設定: 非公開でアップロード（即時公開は行いません）")
        else:
            privacy_label = {"unlisted": "限定公開", "private": "非公開"}.get(privacy_status, privacy_status)
            print(f"  📅 公開設定: {privacy_label} ({privacy_status})")
            print("     └ config/channel/youtube.json::privacy_status を反映")
        if scheduling_disabled:
            print(
                "  ⚠️  schedule.auto_schedule_enabled が false に設定されています。"
                "予約投稿したい場合は true に変更してください"
            )
    print()
    quota_plan = complete_collection_quota_plan()
    print("  推定 YouTube API quota:")
    for method, calls in quota_plan.bucket_calls.items():
        print(f"    独立日次 bucket: {method} {calls}/{DAILY_BUCKET_LIMITS[method]} calls")
    for method, calls in quota_plan.unit_pool_calls.items():
        print(f"    unit pool: {method} {calls} × {UNIT_COSTS[method]} units")
    print(f"    unit pool 合計: {quota_plan.unit_pool_units:,}/{UNIT_POOL_LIMIT:,} units")
