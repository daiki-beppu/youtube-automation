export const STOCK_TABLE_CONTRACT = {
  title: "チャンネル横断ストック",
  description: "全チャンネルの公開予約数と主要指標を比較できます。",
  ariaLabel: "チャンネル横断ストック一覧",
  columns: {
    channel: "チャンネル",
    status: "状態",
    collectedAt: "収集時刻",
    stock: "ストック",
    views: "期間再生数",
    subscribersNet: "純増登録者",
    watchTime: "総再生時間",
  },
  status: { ready: "正常", refreshFailed: "更新失敗" },
  unavailable: "未取得",
  summary: { prefix: "全チャンネル合計 公開予約", excludedSuffix: "件を除く" },
  stockCriticalThreshold: 0,
  stockWarningThreshold: 3,
} as const
