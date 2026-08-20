import { useEffect, useRef, useState } from "react"
import {
  AudioWaveformIcon,
  RotateCcwIcon,
  SaveIcon,
  WandSparklesIcon,
} from "lucide-react"

import {
  isMasterAdjustmentResponse,
  type MasterAdjustmentResponse,
  type MasterSettings,
} from "@/audio-settings"
import { NumberControl, SliderControl, ToggleControl } from "@/audio-controls"
import { applyEqPreview } from "@/audio-preview"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"

async function responseError(response: Response): Promise<Error> {
  try {
    const payload: unknown = await response.json()
    if (typeof payload === "object" && payload !== null && "error" in payload) {
      return new Error(String(payload.error))
    }
  } catch {
    // Fall back to the HTTP status below.
  }
  return new Error(`HTTP ${response.status}`)
}

export function MasterPanel() {
  const [data, setData] = useState<MasterAdjustmentResponse | null>(null)
  const [settings, setSettings] = useState<MasterSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState("master 調整値を読み込んでいます")
  const [working, setWorking] = useState(false)
  const [revision, setRevision] = useState(0)
  const audio = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetch("/api/master/adjustments", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw await responseError(response)
        const payload: unknown = await response.json()
        if (!isMasterAdjustmentResponse(payload))
          throw new Error("invalid master response")
        setData(payload)
        setSettings(payload.settings)
        setStatus(payload.has_backup ? "調整原本を退避済みです" : "未適用です")
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "unknown error")
        }
      })
    return () => controller.abort()
  }, [])

  function update(next: MasterSettings, preview = false) {
    setSettings(next)
    setStatus("未保存の変更があります")
    if (preview) applyEqPreview(audio.current ?? undefined, next)
  }

  async function persist(): Promise<MasterAdjustmentResponse> {
    if (!settings) throw new Error("master settings are unavailable")
    const response = await fetch("/api/master/adjustments", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    })
    if (!response.ok) throw await responseError(response)
    const payload: unknown = await response.json()
    if (!isMasterAdjustmentResponse(payload))
      throw new Error("invalid master response")
    setData(payload)
    setSettings(payload.settings)
    return payload
  }

  async function save() {
    setWorking(true)
    setError(null)
    try {
      await persist()
      setStatus("master 調整値を保存しました")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "unknown error")
    } finally {
      setWorking(false)
    }
  }

  async function apply() {
    setWorking(true)
    setError(null)
    setStatus("原本から master を再出力しています")
    try {
      await persist()
      const response = await fetch("/api/master/apply", { method: "POST" })
      if (!response.ok) throw await responseError(response)
      const payload: unknown = await response.json()
      if (!isMasterAdjustmentResponse(payload) || payload.applied !== true) {
        throw new Error("invalid master apply response")
      }
      setData(payload)
      setSettings(payload.settings)
      setRevision(Date.now())
      setStatus("原本から master.mp3 を再出力しました")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "unknown error")
      setStatus("master を再出力できませんでした")
    } finally {
      setWorking(false)
    }
  }

  if (error && !settings) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Master セクションを読み込めませんでした</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }
  if (!data || !settings) return <Skeleton className="h-96 w-full" />

  const defaults = data.defaults
  return (
    <Card role="region" aria-label="master.mp3 全体調整">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AudioWaveformIcon aria-hidden="true" />
          Master 全体調整
        </CardTitle>
        <CardDescription>
          Web Audio の EQ preview は ffmpeg
          の出力と完全には一致しません。適用は常に退避原本から行います。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        {!data.available ? (
          <Alert variant="destructive">
            <AlertTitle>master.mp3 がありません</AlertTitle>
            <AlertDescription>
              先に master 音源を生成してください。
            </AlertDescription>
          </Alert>
        ) : (
          <audio
            ref={audio}
            className="w-full min-w-0"
            controls
            preload="metadata"
            src={`${data.audio_url}?revision=${revision}`}
            aria-label="master.mp3 を再生"
          />
        )}

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Master 調整に失敗しました</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <section className="grid gap-3" aria-labelledby="master-eq-heading">
          <h3 id="master-eq-heading" className="font-semibold">
            Master EQ（リアルタイムプレビュー）
          </h3>
          <ToggleControl
            label="Master EQ enabled"
            checked={settings.eq.enabled}
            defaultChecked={defaults.eq.enabled}
            onChange={(enabled) =>
              update({ ...settings, eq: { ...settings.eq, enabled } }, true)
            }
          />
          <SliderControl
            label="Master muddiness frequency (Hz)"
            value={settings.eq.muddiness_freq_hz}
            defaultValue={defaults.eq.muddiness_freq_hz}
            min={20}
            max={20000}
            step={10}
            onChange={(muddiness_freq_hz) =>
              update(
                { ...settings, eq: { ...settings.eq, muddiness_freq_hz } },
                true
              )
            }
          />
          <SliderControl
            label="Master muddiness gain (dB)"
            value={settings.eq.muddiness_gain_db}
            defaultValue={defaults.eq.muddiness_gain_db}
            min={-24}
            max={24}
            step={0.5}
            onChange={(muddiness_gain_db) =>
              update(
                { ...settings, eq: { ...settings.eq, muddiness_gain_db } },
                true
              )
            }
          />
          <SliderControl
            label="Master harshness frequency (Hz)"
            value={settings.eq.harshness_freq_hz}
            defaultValue={defaults.eq.harshness_freq_hz}
            min={20}
            max={20000}
            step={10}
            onChange={(harshness_freq_hz) =>
              update(
                { ...settings, eq: { ...settings.eq, harshness_freq_hz } },
                true
              )
            }
          />
          <SliderControl
            label="Master harshness gain (dB)"
            value={settings.eq.harshness_gain_db}
            defaultValue={defaults.eq.harshness_gain_db}
            min={-24}
            max={24}
            step={0.5}
            onChange={(harshness_gain_db) =>
              update(
                { ...settings, eq: { ...settings.eq, harshness_gain_db } },
                true
              )
            }
          />
        </section>

        <Separator />
        <section
          className="grid gap-3"
          aria-labelledby="master-dynamics-heading"
        >
          <h3 id="master-dynamics-heading" className="font-semibold">
            Master loudness / limiter
          </h3>
          <ToggleControl
            label="Master loudnorm enabled"
            checked={settings.loudnorm.enabled}
            defaultChecked={defaults.loudnorm.enabled}
            onChange={(enabled) =>
              update({
                ...settings,
                loudnorm: { ...settings.loudnorm, enabled },
              })
            }
          />
          <NumberControl
            label="Master loudnorm I (LUFS)"
            value={settings.loudnorm.I}
            defaultValue={defaults.loudnorm.I}
            min={-70}
            max={-5}
            step={0.5}
            onChange={(I) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, I } })
            }
          />
          <NumberControl
            label="Master loudnorm LRA"
            value={settings.loudnorm.LRA}
            defaultValue={defaults.loudnorm.LRA}
            min={1}
            max={50}
            step={0.5}
            onChange={(LRA) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, LRA } })
            }
          />
          <NumberControl
            label="Master loudnorm TP (dB)"
            value={settings.loudnorm.TP}
            defaultValue={defaults.loudnorm.TP}
            min={-9}
            max={0}
            step={0.1}
            onChange={(TP) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, TP } })
            }
          />
          <ToggleControl
            label="Master limiter enabled"
            checked={settings.limiter.enabled}
            defaultChecked={defaults.limiter.enabled}
            onChange={(enabled) =>
              update({ ...settings, limiter: { ...settings.limiter, enabled } })
            }
          />
          <NumberControl
            label="Master limiter limit"
            value={settings.limiter.limit}
            defaultValue={defaults.limiter.limit}
            min={0.01}
            max={1}
            step={0.01}
            onChange={(limit) =>
              update({ ...settings, limiter: { ...settings.limiter, limit } })
            }
          />
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-sm text-muted-foreground" role="status">
            {status}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => update(defaults, true)}
              disabled={working}
            >
              <RotateCcwIcon aria-hidden="true" />
              既定値に戻す
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void save()}
              disabled={working}
            >
              <SaveIcon aria-hidden="true" />
              設定を保存
            </Button>
            <Button
              type="button"
              onClick={() => void apply()}
              disabled={working || !data.available}
            >
              <WandSparklesIcon aria-hidden="true" />
              {working ? "処理中…" : "原本から再出力"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
