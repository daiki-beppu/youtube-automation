export const dashboardPalettes = [
  {
    value: "blue",
    label: "Blue",
    levels: ["100", "300", "500", "700", "900"],
    preview: "var(--palette-blue-preview)",
  },
  {
    value: "cyan",
    label: "Cyan",
    levels: ["200", "400", "600", "800", "1000"],
    preview: "var(--palette-cyan-preview)",
  },
  {
    value: "green",
    label: "Green",
    levels: ["100", "300", "600", "800", "900"],
    preview: "var(--palette-green-preview)",
  },
  {
    value: "orange",
    label: "Orange",
    levels: ["100", "300", "600", "800", "1000"],
    preview: "var(--palette-orange-preview)",
  },
  {
    value: "purple",
    label: "Purple",
    levels: ["100", "300", "500", "600", "800"],
    preview: "var(--palette-purple-preview)",
  },
] as const

export type Palette = (typeof dashboardPalettes)[number]["value"]

export const dashboardPaletteValues = dashboardPalettes.map(
  ({ value }) => value
)

export function isDashboardPalette(value: string | null): value is Palette {
  return dashboardPaletteValues.some((palette) => palette === value)
}
