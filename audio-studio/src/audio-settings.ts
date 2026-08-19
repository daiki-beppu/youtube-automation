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
