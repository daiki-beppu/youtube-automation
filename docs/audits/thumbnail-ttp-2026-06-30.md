# Thumbnail TTP Audit (2026-06-30)

Related issues: #520, #521, #522. This report records the local inventory available in this checkout, but it does not close #520 or #522 because several required downstream roots were not present and the all-channel stock operation table remains incomplete.

Scope scanned: local first-party channel roots under `/Users/mba/02-yt` that contain `config/skills/thumbnail.yaml`.

Not present in this checkout scan: `bobble`, `neta`, `yt-studio`, `libecity`.

## Config Audit

| Channel | `reference_images.default` | `generation_mode` | Diff prompt appears delta-only | Effective stock reuse | `/thumbnail-compare` operation |
|---|---|---:|---|---|---|
| `deepfocus365` | `collections/live/20260520-df365-limitless-concentration-zone-collection/10-assets/main.png` | `two_phase` | N/A | enabled by default, but no reusable `thumbnail_candidate` stock found | skill requires pre-approval compare; no channel override disables it |
| `rjn` | `docs/benchmarks/thumbnails/jazzgak_TgrZPdKOYdU.jpg` | `single_step` | yes, substitutions only | enabled by default, but no reusable `thumbnail_candidate` stock found | skill requires pre-approval compare; no channel override disables it |
| `soulful-grooves` | 3 own-winner references under `assets/reference/own-winners/` | inherited `single_step` | N/A, style lock is config-driven | enabled by default, but no reusable `thumbnail_candidate` stock found | skill requires pre-approval compare; no channel override disables it |
| `youtube-abyss` | 3 SI benchmark references under `docs/benchmarks/thumbnails/` | inherited `single_step` | yes, short theme variation | enabled by default; 3 reusable `thumbnail_candidate` stock files found | skill requires pre-approval compare; no channel override disables it |
| `youtube-veluvia` | branding template + 3 Chillora benchmark references | inherited `single_step` | yes, short theme variation | enabled by default, but no reusable `thumbnail_candidate` stock found | skill requires pre-approval compare; no channel override disables it |

## Stock Inventory

`image_generation.gemini.reference_images.stock.enabled` is inherited as `true` unless a channel override disables it. Default reuse filters to `source_role: "thumbnail_candidate"`.

| Channel | Stock image files | `thumbnail_candidate` reusable files | Main finding |
|---|---:|---:|---|
| `deepfocus365` | 30 | 0 | Stock archive exists, but all image metadata is `ideate_preview`; default reuse will fall back to benchmark/default refs. |
| `rjn` | 18 | 0 | Same as above. |
| `soulful-grooves` | 41 | 0 | Same as above; many other stock assets are music b-sides and are outside thumbnail reuse. |
| `youtube-abyss` | 17 | 3 | Reuse is active for a small subset. |
| `youtube-veluvia` | 2 | 0 | Stock archive exists, but no default-reusable thumbnail candidates. |

## Live Collection Inventory

| Channel | Live collections | Thumbnail/main image files found | TTP status |
|---|---:|---:|---|
| `deepfocus365` | 57 | 115 | Requires visual per-collection QA before regeneration decisions. |
| `rjn` | 60 | 113 | Requires visual per-collection QA before regeneration decisions. |
| `soulful-grooves` | 29 | 58 | Requires visual per-collection QA before regeneration decisions. |
| `youtube-abyss` | 5 | 11 | Requires visual per-collection QA before regeneration decisions. |
| `youtube-veluvia` | 8 | 16 | Requires visual per-collection QA before regeneration decisions. |

## Findings

1. `deepfocus365` intentionally uses `two_phase`, so it is outside the default `single_step` TTP mode. The config comments document the reason: channel-specific vehicle/private-jet template and text overlay phase.
2. `youtube-abyss` explicitly sets `image_generation.provider: codex`; no provider drift was found in the local scan.
3. Stock reuse is configured on by default, but most archived stock images are `source_role: "ideate_preview"`. With the default `thumbnail_candidate` filter, those files are archived but not reused. Decision: keep `ideate_preview` archive-only and keep the `thumbnail_candidate` filter unchanged. Reusing ideation previews would mix lower-confidence exploratory assets into final thumbnail prompts, so only final rejected `/thumbnail` candidates should become reusable stock.
4. No local evidence of `/thumbnail-compare` being disabled was found. The shared thumbnail skill requires it before approval, so this remains an operating-procedure check rather than a per-channel config gap.

## Follow-Ups

- #520 should stay open: required channel roots `bobble`, `neta`, `yt-studio`, and `libecity` were not present in this checkout and need a restored local scan or another evidence source.
- #521 should stay deferred until a visual QA pass is run over the listed live collections; no image regeneration was performed in this automation PR.
- #522 should stay open: this report records local inventory and the stock reuse decision for scanned roots only; the full all-channel stock operation table remains incomplete until missing roots are scanned.
