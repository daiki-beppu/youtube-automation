export type Track = {
  id: string
  file_name: string
  duration_seconds: number
  extension: string
  audio_url: string
}

export type TrackResponse = {
  collection_name: string
  tracks: Track[]
}

export type OrderResponse = {
  order: string[]
  shuffle_seed: number | null
  pin_first: string[]
  saved: boolean
}

export type CleanupSettings = {
  eq: {
    enabled: boolean
    muddiness_freq_hz: number
    muddiness_gain_db: number
    harshness_freq_hz: number
    harshness_gain_db: number
  }
  loudnorm: { enabled: boolean; I: number; LRA: number; TP: number }
  limiter: { enabled: boolean; limit: number }
  trim_silence: { enabled: boolean; threshold_db: number }
  tail_fade_guard: { enabled: boolean; fade_sec: number }
  volume_smoothing: boolean
}

export type AdjustmentResponse = {
  defaults: CleanupSettings
  settings: CleanupSettings
  overrides: Record<string, unknown>
}

export type MasterSettings = Pick<
  CleanupSettings,
  "eq" | "loudnorm" | "limiter"
>

export type MasterAdjustmentResponse = {
  available: boolean
  audio_url: string
  defaults: MasterSettings
  settings: MasterSettings
  has_backup: boolean
  applied?: boolean
}

export type FinalizeLayerOverride = {
  volume_db?: number
  fadein_s?: number
  fadein_curve?: string
}

export type FinalizeSettings = {
  ambient_layers: {
    dirname: string
    glob: string
    volume_db: number
    fadein_s: number
    fadein_curve: string
    layers: Record<string, FinalizeLayerOverride>
  }
  loudnorm: {
    enabled: boolean
    mode: "linear"
    I: number
    LRA: number
    TP: number
  }
  mix: {
    duration: "first" | "shortest" | "longest"
    normalize: boolean
  }
}

export type FinalizeAdjustmentResponse = {
  available: boolean
  reason: string | null
  layers: string[]
  defaults: FinalizeSettings
  settings: FinalizeSettings
  has_backup: boolean
  applied?: boolean
  pass_through?: boolean
  master_reapplied?: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function isTrackResponse(value: unknown): value is TrackResponse {
  if (!isRecord(value)) return false
  return (
    typeof value.collection_name === "string" &&
    Array.isArray(value.tracks) &&
    value.tracks.every(
      (track) =>
        isRecord(track) &&
        typeof track.id === "string" &&
        typeof track.file_name === "string" &&
        typeof track.duration_seconds === "number" &&
        Number.isFinite(track.duration_seconds) &&
        typeof track.extension === "string" &&
        typeof track.audio_url === "string"
    )
  )
}

export function isOrderResponse(value: unknown): value is OrderResponse {
  return (
    isRecord(value) &&
    Array.isArray(value.order) &&
    value.order.every((item) => typeof item === "string") &&
    (value.shuffle_seed === null || Number.isSafeInteger(value.shuffle_seed)) &&
    Array.isArray(value.pin_first) &&
    value.pin_first.every((item) => typeof item === "string") &&
    typeof value.saved === "boolean"
  )
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

export function isCleanupSettings(value: unknown): value is CleanupSettings {
  if (!isRecord(value)) return false
  const eq = value.eq
  const loudnorm = value.loudnorm
  const limiter = value.limiter
  const trim = value.trim_silence
  const tail = value.tail_fade_guard
  return (
    isRecord(eq) &&
    typeof eq.enabled === "boolean" &&
    isNumber(eq.muddiness_freq_hz) &&
    isNumber(eq.muddiness_gain_db) &&
    isNumber(eq.harshness_freq_hz) &&
    isNumber(eq.harshness_gain_db) &&
    isRecord(loudnorm) &&
    typeof loudnorm.enabled === "boolean" &&
    isNumber(loudnorm.I) &&
    isNumber(loudnorm.LRA) &&
    isNumber(loudnorm.TP) &&
    isRecord(limiter) &&
    typeof limiter.enabled === "boolean" &&
    isNumber(limiter.limit) &&
    isRecord(trim) &&
    typeof trim.enabled === "boolean" &&
    isNumber(trim.threshold_db) &&
    isRecord(tail) &&
    typeof tail.enabled === "boolean" &&
    isNumber(tail.fade_sec) &&
    typeof value.volume_smoothing === "boolean"
  )
}

export function isMasterSettings(value: unknown): value is MasterSettings {
  if (!isRecord(value)) return false
  return isCleanupSettings({
    ...value,
    trim_silence: { enabled: false, threshold_db: -50 },
    tail_fade_guard: { enabled: false, fade_sec: 0 },
    volume_smoothing: false,
  })
}

export function isMasterAdjustmentResponse(
  value: unknown
): value is MasterAdjustmentResponse {
  return (
    isRecord(value) &&
    typeof value.available === "boolean" &&
    typeof value.audio_url === "string" &&
    isMasterSettings(value.defaults) &&
    isMasterSettings(value.settings) &&
    typeof value.has_backup === "boolean" &&
    (value.applied === undefined || typeof value.applied === "boolean")
  )
}

function isLayerOverrides(
  value: unknown
): value is Record<string, FinalizeLayerOverride> {
  if (!isRecord(value)) return false
  return Object.values(value).every(
    (override) =>
      isRecord(override) &&
      Object.keys(override).every((key) =>
        ["volume_db", "fadein_s", "fadein_curve"].includes(key)
      ) &&
      (override.volume_db === undefined || isNumber(override.volume_db)) &&
      (override.fadein_s === undefined || isNumber(override.fadein_s)) &&
      (override.fadein_curve === undefined ||
        typeof override.fadein_curve === "string")
  )
}

export function isFinalizeSettings(value: unknown): value is FinalizeSettings {
  if (!isRecord(value)) return false
  const ambient = value.ambient_layers
  const loudnorm = value.loudnorm
  const mix = value.mix
  return (
    isRecord(ambient) &&
    typeof ambient.dirname === "string" &&
    typeof ambient.glob === "string" &&
    isNumber(ambient.volume_db) &&
    isNumber(ambient.fadein_s) &&
    typeof ambient.fadein_curve === "string" &&
    isLayerOverrides(ambient.layers) &&
    isRecord(loudnorm) &&
    typeof loudnorm.enabled === "boolean" &&
    loudnorm.mode === "linear" &&
    isNumber(loudnorm.I) &&
    isNumber(loudnorm.LRA) &&
    isNumber(loudnorm.TP) &&
    isRecord(mix) &&
    ["first", "shortest", "longest"].includes(String(mix.duration)) &&
    typeof mix.normalize === "boolean"
  )
}

export function isFinalizeAdjustmentResponse(
  value: unknown
): value is FinalizeAdjustmentResponse {
  return (
    isRecord(value) &&
    typeof value.available === "boolean" &&
    (value.reason === null || typeof value.reason === "string") &&
    Array.isArray(value.layers) &&
    value.layers.every((layer) => typeof layer === "string") &&
    isFinalizeSettings(value.defaults) &&
    isFinalizeSettings(value.settings) &&
    typeof value.has_backup === "boolean" &&
    (value.applied === undefined || typeof value.applied === "boolean") &&
    (value.pass_through === undefined ||
      typeof value.pass_through === "boolean") &&
    (value.master_reapplied === undefined ||
      typeof value.master_reapplied === "boolean")
  )
}

export function isAdjustmentResponse(
  value: unknown
): value is AdjustmentResponse {
  return (
    isRecord(value) &&
    isCleanupSettings(value.defaults) &&
    isCleanupSettings(value.settings) &&
    isRecord(value.overrides)
  )
}
