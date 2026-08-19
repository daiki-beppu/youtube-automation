import { useEffect, useState } from "react"
import { CloudRainIcon, SaveIcon, WandSparklesIcon } from "lucide-react"

import {
  isFinalizeAdjustmentResponse,
  type FinalizeAdjustmentResponse,
  type FinalizeLayerOverride,
  type FinalizeSettings,
} from "@/audio-settings"
import { NumberControl, ToggleControl } from "@/audio-controls"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"

const FADE_CURVES = [
  "tri",
  "qsin",
  "esin",
  "hsin",
  "log",
  "ipar",
  "qua",
  "cub",
  "squ",
  "cbr",
  "par",
  "exp",
  "iqsin",
  "ihsin",
  "dese",
  "desi",
  "losi",
  "sinc",
  "isinc",
  "nofade",
]

async function responseError(response: Response): Promise<Error> {
  try {
    const payload: unknown = await response.json()
    if (typeof payload === "object" && payload !== null && "error" in payload) {
      return new Error(String(payload.error))
    }
  } catch {
    // Fall back to the status code.
  }
  return new Error(`HTTP ${response.status}`)
}

function SelectControl({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <div className="grid gap-3 rounded-lg border p-3 sm:grid-cols-[minmax(12rem,1fr)_minmax(14rem,1.4fr)] sm:items-center">
      <Label htmlFor={`finalize-${label}`}>{label}</Label>
      <select
        id={`finalize-${label}`}
        aria-label={label}
        className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  )
}

export function FinalizePanel({ onApplied }: { onApplied: () => void }) {
  const [data, setData] = useState<FinalizeAdjustmentResponse | null>(null)
  const [settings, setSettings] = useState<FinalizeSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState("ambient 設定を読み込んでいます")
  const [working, setWorking] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void fetch("/api/finalize/adjustments", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw await responseError(response)
        const payload: unknown = await response.json()
        if (!isFinalizeAdjustmentResponse(payload)) {
          throw new Error("invalid finalize response")
        }
        setData(payload)
        setSettings(payload.settings)
        setStatus(
          payload.has_backup ? "finalize 原本を退避済みです" : "未適用です"
        )
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "unknown error")
        }
      })
    return () => controller.abort()
  }, [])

  function update(next: FinalizeSettings) {
    setSettings(next)
    setStatus("未保存の変更があります")
  }

  function updateLayer(filename: string, override: FinalizeLayerOverride) {
    if (!settings) return
    update({
      ...settings,
      ambient_layers: {
        ...settings.ambient_layers,
        layers: { ...settings.ambient_layers.layers, [filename]: override },
      },
    })
  }

  function inheritLayerField(
    filename: string,
    field: keyof FinalizeLayerOverride
  ) {
    if (!settings) return
    const layers = { ...settings.ambient_layers.layers }
    const override = { ...(layers[filename] ?? {}) }
    delete override[field]
    if (Object.keys(override).length === 0) delete layers[filename]
    else layers[filename] = override
    update({
      ...settings,
      ambient_layers: { ...settings.ambient_layers, layers },
    })
  }

  async function persist(): Promise<FinalizeAdjustmentResponse> {
    if (!settings) throw new Error("finalize settings are unavailable")
    const response = await fetch("/api/finalize/adjustments", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    })
    if (!response.ok) throw await responseError(response)
    const payload: unknown = await response.json()
    if (!isFinalizeAdjustmentResponse(payload)) {
      throw new Error("invalid finalize response")
    }
    setData(payload)
    setSettings(payload.settings)
    return payload
  }

  async function save() {
    setWorking(true)
    setError(null)
    try {
      await persist()
      setStatus("ambient 設定を保存しました")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "unknown error")
    } finally {
      setWorking(false)
    }
  }

  async function apply() {
    setWorking(true)
    setError(null)
    setStatus("finalize 原本から ambient layer を再出力しています")
    try {
      const saved = await persist()
      if (!saved.available) {
        setStatus(saved.reason ?? "ambient layer を適用できません")
        return
      }
      const response = await fetch("/api/finalize/apply", { method: "POST" })
      if (!response.ok) throw await responseError(response)
      const payload: unknown = await response.json()
      if (!isFinalizeAdjustmentResponse(payload) || payload.applied !== true) {
        throw new Error("invalid finalize apply response")
      }
      setData(payload)
      setSettings(payload.settings)
      setStatus(
        payload.master_reapplied
          ? "ambient と master 全体調整を原本から再出力しました"
          : "ambient layer を原本から再出力しました"
      )
      onApplied()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "unknown error")
      setStatus("ambient layer を再出力できませんでした")
    } finally {
      setWorking(false)
    }
  }

  if (error && !settings) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Ambient layer 設定を読み込めませんでした</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }
  if (!data || !settings) return <Skeleton className="h-96 w-full" />

  return (
    <section className="grid gap-5" aria-labelledby="ambient-finalize-heading">
      <div>
        <h3
          id="ambient-finalize-heading"
          className="flex items-center gap-2 font-semibold"
        >
          <CloudRainIcon aria-hidden="true" />
          Ambient layer finalize
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          finalize 原本へ layer を重ね、その後に保存済みの master
          全体調整を再適用します。
        </p>
      </div>

      {!data.available ? (
        <Alert>
          <AlertTitle>Ambient layer 適用 controls は無効です</AlertTitle>
          <AlertDescription>{data.reason}</AlertDescription>
        </Alert>
      ) : null}

      {data.layers.length > 0 ? (
        <div className="flex flex-wrap gap-2" aria-label="対象 ambient layers">
          {data.layers.map((layer) => (
            <Badge key={layer} variant="secondary">
              {layer}
            </Badge>
          ))}
        </div>
      ) : null}

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Ambient finalize に失敗しました</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="ambient-dirname">Layer directory</Label>
            <Input
              id="ambient-dirname"
              disabled={working}
              value={settings.ambient_layers.dirname}
              onChange={(event) =>
                update({
                  ...settings,
                  ambient_layers: {
                    ...settings.ambient_layers,
                    dirname: event.currentTarget.value,
                  },
                })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ambient-glob">Layer glob</Label>
            <Input
              id="ambient-glob"
              disabled={working}
              value={settings.ambient_layers.glob}
              onChange={(event) =>
                update({
                  ...settings,
                  ambient_layers: {
                    ...settings.ambient_layers,
                    glob: event.currentTarget.value,
                  },
                })
              }
            />
          </div>
        </div>
        <fieldset
          disabled={!data.available || working}
          className="grid gap-5 disabled:opacity-60"
        >
          <NumberControl
            label="Ambient volume (dB)"
            value={settings.ambient_layers.volume_db}
            defaultValue={data.defaults.ambient_layers.volume_db}
            min={-60}
            max={12}
            step={0.5}
            onChange={(volume_db) =>
              update({
                ...settings,
                ambient_layers: { ...settings.ambient_layers, volume_db },
              })
            }
          />
          <NumberControl
            label="Ambient fade-in (seconds)"
            value={settings.ambient_layers.fadein_s}
            defaultValue={data.defaults.ambient_layers.fadein_s}
            min={0}
            max={60}
            step={0.1}
            onChange={(fadein_s) =>
              update({
                ...settings,
                ambient_layers: { ...settings.ambient_layers, fadein_s },
              })
            }
          />
          <SelectControl
            label="Ambient fade-in curve"
            value={settings.ambient_layers.fadein_curve}
            options={FADE_CURVES}
            onChange={(fadein_curve) =>
              update({
                ...settings,
                ambient_layers: { ...settings.ambient_layers, fadein_curve },
              })
            }
          />

          {data.layers.map((layer) => {
            const override = settings.ambient_layers.layers[layer] ?? {}
            return (
              <div
                key={layer}
                className="grid gap-3 rounded-lg border border-dashed p-3"
              >
                <p className="font-medium">{layer} override</p>
                <NumberControl
                  label={`${layer} volume (dB)`}
                  value={
                    override.volume_db ?? settings.ambient_layers.volume_db
                  }
                  defaultValue={settings.ambient_layers.volume_db}
                  min={-60}
                  max={12}
                  step={0.5}
                  onChange={(volume_db) =>
                    updateLayer(layer, { ...override, volume_db })
                  }
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={override.volume_db === undefined}
                  onClick={() => inheritLayerField(layer, "volume_db")}
                >
                  {layer} volume は共通値を使う
                </Button>
                <NumberControl
                  label={`${layer} fade-in (seconds)`}
                  value={override.fadein_s ?? settings.ambient_layers.fadein_s}
                  defaultValue={settings.ambient_layers.fadein_s}
                  min={0}
                  max={60}
                  step={0.1}
                  onChange={(fadein_s) =>
                    updateLayer(layer, { ...override, fadein_s })
                  }
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={override.fadein_s === undefined}
                  onClick={() => inheritLayerField(layer, "fadein_s")}
                >
                  {layer} fade-in は共通値を使う
                </Button>
                <SelectControl
                  label={`${layer} fade-in curve`}
                  value={
                    override.fadein_curve ??
                    settings.ambient_layers.fadein_curve
                  }
                  options={FADE_CURVES}
                  onChange={(fadein_curve) =>
                    updateLayer(layer, { ...override, fadein_curve })
                  }
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={override.fadein_curve === undefined}
                  onClick={() => inheritLayerField(layer, "fadein_curve")}
                >
                  {layer} curve は共通値を使う
                </Button>
              </div>
            )
          })}

          <Separator />
          <ToggleControl
            label="Finalize loudnorm enabled"
            checked={settings.loudnorm.enabled}
            defaultChecked={data.defaults.loudnorm.enabled}
            onChange={(enabled) =>
              update({
                ...settings,
                loudnorm: { ...settings.loudnorm, enabled },
              })
            }
          />
          <NumberControl
            label="Finalize loudnorm I (LUFS)"
            value={settings.loudnorm.I}
            defaultValue={data.defaults.loudnorm.I}
            min={-70}
            max={-5}
            step={0.5}
            onChange={(I) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, I } })
            }
          />
          <NumberControl
            label="Finalize loudnorm LRA"
            value={settings.loudnorm.LRA}
            defaultValue={data.defaults.loudnorm.LRA}
            min={1}
            max={50}
            step={0.5}
            onChange={(LRA) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, LRA } })
            }
          />
          <NumberControl
            label="Finalize loudnorm TP (dB)"
            value={settings.loudnorm.TP}
            defaultValue={data.defaults.loudnorm.TP}
            min={-9}
            max={0}
            step={0.1}
            onChange={(TP) =>
              update({ ...settings, loudnorm: { ...settings.loudnorm, TP } })
            }
          />
          <SelectControl
            label="Mix duration"
            value={settings.mix.duration}
            options={["first", "shortest", "longest"]}
            onChange={(duration) =>
              update({
                ...settings,
                mix: {
                  ...settings.mix,
                  duration: duration as FinalizeSettings["mix"]["duration"],
                },
              })
            }
          />
          <ToggleControl
            label="Mix normalize"
            checked={settings.mix.normalize}
            defaultChecked={data.defaults.mix.normalize}
            onChange={(normalize) =>
              update({ ...settings, mix: { ...settings.mix, normalize } })
            }
          />
        </fieldset>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-sm text-muted-foreground" role="status">
            {status}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={working}
              onClick={() => void save()}
            >
              <SaveIcon aria-hidden="true" />
              Ambient 設定を保存
            </Button>
            <Button
              type="button"
              disabled={!data.available || working}
              onClick={() => void apply()}
            >
              <WandSparklesIcon aria-hidden="true" />
              {working ? "処理中…" : "Ambient を原本から再出力"}
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
