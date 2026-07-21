import type { OverlayBrandColors } from "@youtube-automation/ui";

/** User-approved Suno overlay identity colors. */
export const SUNO_OVERLAY_BRAND = {
  headerBackground: "oklch(0.753 0.2067 57.6 / 96.4%)",
  headerForeground: "oklch(0.205 0 0)",
  primary: "oklch(0.753 0.2067 57.6 / 96.4%)",
  primaryForeground: "oklch(0.205 0 0)",
} as const satisfies OverlayBrandColors;
