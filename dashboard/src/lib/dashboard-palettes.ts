export const dashboardPalettes = [
  {
    value: "blue",
    label: "Blue",
    levels: ["100", "300", "500", "700", "900"],
    preview: "var(--palette-blue-preview)",
  },
  {
    value: "light-blue",
    label: "Light Blue",
    levels: ["200", "400", "600", "800", "1000"],
    preview: "var(--palette-light-blue-preview)",
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
    value: "lime",
    label: "Lime",
    levels: ["100", "500", "700", "900", "1100"],
    preview: "var(--palette-lime-preview)",
  },
  {
    value: "yellow",
    label: "Yellow",
    levels: ["200", "500", "700", "900", "1100"],
    preview: "var(--palette-yellow-preview)",
  },
  {
    value: "orange",
    label: "Orange",
    levels: ["100", "300", "600", "800", "1000"],
    preview: "var(--palette-orange-preview)",
  },
  {
    value: "red",
    label: "Red",
    levels: ["100", "300", "500", "800", "1000"],
    preview: "var(--palette-red-preview)",
  },
  {
    value: "magenta",
    label: "Magenta",
    levels: ["100", "300", "500", "700", "900"],
    preview: "var(--palette-magenta-preview)",
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
