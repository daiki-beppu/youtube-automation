import type { OverlayBrandColors } from "@youtube-automation/ui";

/** AA-safe darkening of official YouTube Red, verified 2026-07-21. */
export const YOUTUBE_OVERLAY_BRAND = {
  headerBackground: "#C90028",
  headerForeground: "#FFFFFF",
} as const satisfies OverlayBrandColors;
