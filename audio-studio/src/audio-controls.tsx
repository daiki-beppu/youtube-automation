import { useId, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

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

export function NumberControl({
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
    <ControlRow label={label} changed={value !== defaultValue} controlId={id}>
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

export function SliderControl({
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
    <ControlRow label={label} changed={value !== defaultValue} controlId={id}>
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

export function ToggleControl({
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
