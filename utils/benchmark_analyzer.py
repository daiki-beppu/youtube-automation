"""ベンチマーク派生指標の計算ユーティリティ

競合チャンネルの動画データから派生指標を算出する純粋関数群。
外部依存なし（標準ライブラリのみ）。
"""

import re
from datetime import date, datetime


def parse_iso_duration(iso: str) -> str:
    """ISO 8601 duration を人間が読みやすい形式に変換する。

    Args:
        iso: ISO 8601 形式の duration（例: "PT2H1M30S", "PT53S"）

    Returns:
        表示用文字列（例: "2h01m", "53s"）
    """
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso)
    if not match:
        return iso

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{seconds}s"


def compute_daily_views(video: dict, today: date | None = None) -> float:
    """公開からの日次平均再生数を算出する。

    Args:
        video: published_at (YYYY-MM-DD) と views を含む辞書
        today: 基準日（省略時は当日）

    Returns:
        日次平均再生数（小数点以下1桁）
    """
    if today is None:
        today = date.today()

    published = datetime.strptime(video["published_at"][:10], "%Y-%m-%d").date()
    days = (today - published).days
    if days <= 0:
        days = 1

    return round(video["views"] / days, 1)


def compute_engagement_rate(video: dict) -> float:
    """エンゲージメント率を算出する。

    Args:
        video: views, likes, comments を含む辞書

    Returns:
        エンゲージメント率（%、小数点以下2桁）
    """
    views = video.get("views", 0)
    if views == 0:
        return 0.0

    likes = video.get("likes", 0)
    comments = video.get("comments", 0)
    return round((likes + comments) / views * 100, 2)


def compute_posting_intervals(videos: list[dict]) -> dict:
    """投稿間隔のトレンドを分析する。

    Args:
        videos: published_at を含む辞書のリスト（新しい順）

    Returns:
        {
            "intervals_days": list[int],  # 各投稿間の日数（新しい順）
            "average_interval": float,     # 平均間隔（日）
            "trend": str                   # "accelerating" | "decelerating" | "stable"
        }
    """
    if len(videos) < 2:
        return {"intervals_days": [], "average_interval": 0, "trend": "stable"}

    dates = []
    for v in videos:
        d = datetime.strptime(v["published_at"][:10], "%Y-%m-%d").date()
        dates.append(d)

    # 新しい順 → 間隔は dates[i] - dates[i+1]
    intervals = []
    for i in range(len(dates) - 1):
        diff = (dates[i] - dates[i + 1]).days
        intervals.append(abs(diff))

    avg = round(sum(intervals) / len(intervals), 1)

    # トレンド判定: 前半 vs 後半の平均間隔
    if len(intervals) >= 4:
        mid = len(intervals) // 2
        recent_avg = sum(intervals[:mid]) / mid
        older_avg = sum(intervals[mid:]) / (len(intervals) - mid)
        diff_ratio = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0

        if diff_ratio < -0.15:
            trend = "accelerating"
        elif diff_ratio > 0.15:
            trend = "decelerating"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "intervals_days": intervals,
        "average_interval": avg,
        "trend": trend,
    }


def extract_description_keywords(description: str) -> list[str]:
    """動画説明文からキーワードを抽出する。

    ハッシュタグと主要キーワードを抽出（NLPライブラリ不使用）。

    Args:
        description: 動画説明文

    Returns:
        キーワードのリスト（重複なし、最大20個）
    """
    keywords = []

    # ハッシュタグ抽出
    hashtags = re.findall(r'#(\w+)', description)
    keywords.extend(hashtags)

    # URL を除去してからキーワード抽出
    cleaned = re.sub(r'https?://\S+', '', description)

    # 音楽ジャンル関連キーワード
    genre_patterns = [
        r'\b(celtic|fantasy|ambient|folk|medieval|relaxing|orchestral|cinematic)\b',
        r'\b(harp|flute|violin|piano|guitar|drums|whistle)\b',
        r'\b(forest|castle|tavern|ocean|village|dungeon|battle|adventure)\b',
    ]
    for pattern in genre_patterns:
        matches = re.findall(pattern, cleaned, re.IGNORECASE)
        keywords.extend(m.lower() for m in matches)

    # 重複除去、順序保持
    seen = set()
    unique = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique.append(kw_lower)

    return unique[:20]
