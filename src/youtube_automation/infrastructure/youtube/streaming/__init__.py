"""帯域モニタリング用の定数集中モジュール（Issue #110）。

CLI / レポート / テストはここで定義された定数を import して使うこと。
重複定義を禁ずる。
"""

from __future__ import annotations

# Vultr プラン (vc2-1c-2gb) の月間帯域上限。2 TB を GB 換算した値。
MONTHLY_QUOTA_GB: int = 2048

# アラート閾値の比率。80% 到達でアラート (= 1638.4 GB)。
THRESHOLD_RATIO: float = 0.80

# 想定ビットレート (Mbps)。映像 + 音声 (192 kbps) の合算想定値。
THEORETICAL_BITRATE_MBPS: int = 4

# 1 日あたりの想定配信時間 (時間)。24/7 連続配信。
THEORETICAL_HOURS_PER_DAY: int = 24

# 24/7 連続配信では YouTube ライブアーカイブ生成を期待しない。
ARCHIVES_EXPECTED: bool = False
