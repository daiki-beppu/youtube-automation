import { useEffect, useId, useState, type ReactNode } from "react"
import { RotateCcwIcon, SaveIcon, SlidersHorizontalIcon } from "lucide-react"

import {
  type AdjustmentResponse,
  type CleanupSettings,
  isAdjustmentResponse,
  type Track,
} from "@/audio-settings"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

type PreviewGraph = {
  context: AudioContext
  muddiness: BiquadFilterNode
  harshness: BiquadFilterNode
}

const previewGraphs = new WeakMap<HTMLAudioElement, PreviewGraph>()

function applyEqPreview(
  audio: HTMLAudioElement | undefined,
  settings: CleanupSettings
) {
  if (!audio || typeof AudioContext === "undefined") return
  let graph = previewGraphs.get(audio)
  if (!graph) {
    const context = new AudioContext()
    const source = context.createMediaElementSource(audio)
    const muddiness = context.createBiquadFilter()
    const harshness = context.createBiquadFilter()
    muddiness.type = "peaking"
    harshness.type = "peaking"
    source.connect(muddiness).connect(harshness).connect(context.destination)
    graph = { context, muddiness, harshness }
    previewGraphs.set(audio, graph)
  }
  void graph.context.resume()
  graph.muddiness.frequency.value = settings.eq.muddiness_freq_hz
  graph.muddiness.gain.value = settings.eq.enabled
    ? settings.eq.muddiness_gain_db
    : 0
  graph.harshness.frequency.value = settings.eq.harshness_freq_hz
  graph.harshness.gain.value = settings.eq.enabled
    ? settings.eq.harshness_gain_db
    : 0
}

function ChangedBadge({ changed }: { changed: boolean }) {
  return changed ? <Badge variant="secondary">変更</Badge> : null
}

function ControlRow({
  label,
  changed,
  controlId,
  children,
}: {
  label: string
  changed: boolean
  controlId: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        "grid gap-3 rounded-lg border p-3 transition-colors sm:grid-cols-[minmax(12rem,1fr)_minmax(14rem,1.4fr)] sm:items-center",
        changed && "border-primary/40 bg-primary/5"
      )}
    >
      <div className="flex items-center gap-2">
        <Label htmlFor={controlId}>{label}</Label>
        <ChangedBadge changed={changed} />
      </div>
      {children}
    </div>
  )
}

function NumberControl({
  label,
  value,
  defaultValue,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  defaultValue: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  const id = useId()
  return (
    <ControlRow
      label={label}
      changed={value !== defaultValue}
      controlId={id}
    >
      <Input
        id={id}
        aria-label={label}
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(event.currentTarget.valueAsNumber)}
      />
    </ControlRow>
  )
}

function SliderControl({
  label,
  value,
  defaultValue,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  defaultValue: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  const id = useId()
  return (
    <ControlRow
      label={label}
      changed={value !== defaultValue}
      controlId={id}
    >
      <div className="grid grid-cols-[1fr_5rem] items-center gap-3">
        <Slider
          aria-label={label}
          value={[value]}
          min={min}
          max={max}
          step={step}
          onValueChange={(next) =>
            onChange(typeof next === "number" ? next : (next[0] ?? value))
          }
        />
        <Input
          id={id}
          aria-label={`${label} 数値`}
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(event.currentTarget.valueAsNumber)}
        />
      </div>
    </ControlRow>
  )
}

function ToggleControl({
  label,
  checked,
  defaultChecked,
  onChange,
}: {
  label: string
  checked: boolean
  defaultChecked: boolean
  onChange: (checked: boolean) => void
}) {
  const id = useId()
  return (
    <ControlRow
      label={label}
      changed={checked !== defaultChecked}
      controlId={id}
    >
      <Switch
        id={id}
        aria-label={label}
        checked={checked}
        onCheckedChange={onChange}
      />
    </ControlRow>
  )
}

export function CleanupPanel({
  track,
  audio,
}: {
  track: Track
  audio: HTMLAudioElement | undefined
}) {
  const [data, setData] = useState<AdjustmentResponse | null>(null)
  const [settings, setSettings] = useState<CleanupSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void fetch(`/api/tracks/${track.id}/adjustments`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload: unknown = await response.json()
        if (!isAdjustmentResponse(payload)) {
          throw new Error("invalid adjustment response")
        }
        setData(payload)
        setSettings(payload.settings)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "unknown error")
        }
      })
    return () => controller.abort()
  }, [track.id])

  function update(next: CleanupSettings, preview = false) {
    setSettings(next)
    setSaved(false)
    if (preview) applyEqPreview(audio, next)
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    setError(null)
    try {
      const response = await fetch(`/api/tracks/${track.id}/adjustments`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload: unknown = await response.json()
      if (!isAdjustmentResponse(payload)) {
        throw new Error("invalid adjustment response")
      }
      setData(payload)
      setSettings(payload.settings)
      setSaved(true)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "unknown error")
    } finally {
      setSaving(false)
    }
  }

  if (error && !settings) {
    return (
      <Alert variant="destructive">
        <AlertTitle>調整値を読み込めませんでした</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }
  if (!data || !settings) return <Skeleton className="h-96 w-full" />

  const defaults = data.defaults
  const changedCount = JSON.stringify(settings) === JSON.stringify(defaults) ? 0 : 1

  return (
    <Card role="region" aria-label={`${track.file_name} の cleanup 調整`}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SlidersHorizontalIcon aria-hidden="true" />
          {track.file_name}
        </CardTitle>
        <CardDescription>
          Web Audio の EQ は即時プレビューです。ffmpeg の equalizer
          と完全には一致しません。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>保存できませんでした</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <section className="grid gap-3" aria-labelledby="eq-heading">
          <h3 id="eq-heading" className="font-semibold">
            EQ（リアルタイムプレビュー）
          </h3>
          <ToggleControl
            label="EQ enabled"
            checked={settings.eq.enabled}
            defaultChecked={defaults.eq.enabled}
            onChange={(enabled) =>
              update({ ...settings, eq: { ...settings.eq, enabled } }, true)
            }
          />
          <SliderControl
            label="Muddiness frequency (Hz)"
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
            label="Muddiness gain (dB)"
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
            label="Harshness frequency (Hz)"
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
            label="Harshness gain (dB)"
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
        <section className="grid gap-3" aria-labelledby="dynamics-heading">
          <h3 id="dynamics-heading" className="font-semibold">
            Loudness / dynamics
          </h3>
          <ToggleControl
            label="Loudnorm enabled"
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
            label="Loudnorm I (LUFS)"
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
            label="Loudnorm LRA"
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
            label="Loudnorm TP (dB)"
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
            label="Limiter enabled"
            checked={settings.limiter.enabled}
            defaultChecked={defaults.limiter.enabled}
            onChange={(enabled) =>
              update({
                ...settings,
                limiter: { ...settings.limiter, enabled },
              })
            }
          />
          <NumberControl
            label="Limiter limit"
            value={settings.limiter.limit}
            defaultValue={defaults.limiter.limit}
            min={0.01}
            max={1}
            step={0.01}
            onChange={(limit) =>
              update({ ...settings, limiter: { ...settings.limiter, limit } })
            }
          />
          <ToggleControl
            label="Volume smoothing"
            checked={settings.volume_smoothing}
            defaultChecked={defaults.volume_smoothing}
            onChange={(volume_smoothing) =>
              update({ ...settings, volume_smoothing })
            }
          />
        </section>

        <Separator />
        <section className="grid gap-3" aria-labelledby="edges-heading">
          <h3 id="edges-heading" className="font-semibold">
            Trim / tail
          </h3>
          <ToggleControl
            label="Trim silence enabled"
            checked={settings.trim_silence.enabled}
            defaultChecked={defaults.trim_silence.enabled}
            onChange={(enabled) =>
              update({
                ...settings,
                trim_silence: { ...settings.trim_silence, enabled },
              })
            }
          />
          <NumberControl
            label="Silence threshold (dB)"
            value={settings.trim_silence.threshold_db}
            defaultValue={defaults.trim_silence.threshold_db}
            min={-100}
            max={0}
            step={1}
            onChange={(threshold_db) =>
              update({
                ...settings,
                trim_silence: { ...settings.trim_silence, threshold_db },
              })
            }
          />
          <ToggleControl
            label="Tail fade guard enabled"
            checked={settings.tail_fade_guard.enabled}
            defaultChecked={defaults.tail_fade_guard.enabled}
            onChange={(enabled) =>
              update({
                ...settings,
                tail_fade_guard: { ...settings.tail_fade_guard, enabled },
              })
            }
          />
          <NumberControl
            label="Tail fade (seconds)"
            value={settings.tail_fade_guard.fade_sec}
            defaultValue={defaults.tail_fade_guard.fade_sec}
            min={0}
            max={60}
            step={0.1}
            onChange={(fade_sec) =>
              update({
                ...settings,
                tail_fade_guard: { ...settings.tail_fade_guard, fade_sec },
              })
            }
          />
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="text-sm text-muted-foreground" aria-live="polite">
            {saved
              ? "保存しました"
              : changedCount
                ? "既定値からの変更があります"
                : "すべて既定値です"}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => update(defaults, true)}
            >
              <RotateCcwIcon aria-hidden="true" />
              既定値に戻す
            </Button>
            <Button type="button" disabled={saving} onClick={() => void save()}>
              <SaveIcon aria-hidden="true" />
              {saving ? "保存中…" : "差分を保存"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
