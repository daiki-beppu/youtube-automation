# Extension overlay brand colors

The draggable overlay shell stays service-neutral. Each helper owns static
`headerBackground` and `headerForeground` tokens and passes them to the shared
shell. No brand assets or colors are fetched at runtime.

Sources were verified on 2026-07-21.

| Helper | Background | Foreground | Contrast | Official source and rationale |
| --- | --- | --- | ---: | --- |
| Suno | `#101012` | `#FFFFFF` | 19.01:1 | [Suno](https://suno.com/) serves the current UI in dark mode and uses `#101012` as its base/hero endpoint; its [official favicon](https://cdn-o.suno.com/favicon-192x192.png) confirms the current visual identity. The stable UI base is used instead of reducing the favicon gradient to an arbitrary single hue. |
| DistroKid | `#0073C7` | `#FFFFFF` | 4.91:1 | The official [DistroKid logo page](https://distrokid.com/logo/) uses `#0073C7` for its primary header and provides the official black/white logo files. The page-owned blue identifies the service while preserving normal-text AA contrast. |
| Community | `#C90028` | `#FFFFFF` | 5.98:1 | [YouTube Brand Colors](https://brand.youtube/color) specifies YouTube Red `#FF0033`, Almost Black `#212121`, and White `#FFFFFF`. Official red with either official foreground is below 4.5:1, so it is darkened on the same red hue to `#C90028` for normal-text AA. |

The shared light-only theme remains in effect when the operating system uses a
dark color scheme. Header hover retains the same foreground and overlays it at
10%, so the title and minimize control retain the ratios above.
