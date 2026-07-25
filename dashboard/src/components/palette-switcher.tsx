import type { CSSProperties } from "react"

import { useTheme } from "@/components/theme-provider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { dashboardPalettes, isDashboardPalette } from "@/lib/dashboard-palettes"
import { cn } from "@/lib/utils"

export function PaletteSwitcher() {
  const { palette, setPalette } = useTheme()
  const selectedPalette =
    dashboardPalettes.find((option) => option.value === palette) ??
    dashboardPalettes[0]

  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        aria-label="カラーパレット"
        value={[palette]}
        onValueChange={(values) => {
          const nextPalette = values[0]
          if (nextPalette && isDashboardPalette(nextPalette)) {
            setPalette(nextPalette)
          }
        }}
        variant="palette"
        size="sm"
        className="w-full flex-wrap justify-start"
      >
        {dashboardPalettes.map((option) => (
          <ToggleGroupItem
            key={option.value}
            value={option.value}
            aria-label={option.label}
            className="flex-1 sm:flex-none"
            style={
              {
                "--palette-option": option.preview,
              } as CSSProperties
            }
          >
            <span
              aria-hidden="true"
              className="size-2.5 rounded-full bg-[var(--palette-option)] ring-1 ring-foreground/15"
            />
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <div
        role="img"
        aria-label={`${selectedPalette.label} の5段階配色。1〜3系列では ${selectedPalette.levels[0]}、${selectedPalette.levels[2]}、${selectedPalette.levels[4]} を使用`}
        className="grid grid-cols-5 overflow-hidden rounded-md border"
      >
        {selectedPalette.levels.map((level, index) => (
          <div key={level} className="flex min-w-0 flex-col">
            <span
              data-testid={`palette-swatch-${index + 1}`}
              aria-hidden="true"
              className="h-8"
              style={{ backgroundColor: `var(--chart-${index + 1})` }}
            />
            <span
              className={cn(
                "bg-card px-1 py-1 text-center text-xs",
                index % 2 === 0 ? "font-semibold" : "text-muted-foreground"
              )}
            >
              {level}
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        太字の3色は1〜3系列、5色すべては4〜5系列の比較に使用します。
      </p>
    </div>
  )
}
