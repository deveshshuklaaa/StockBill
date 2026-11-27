# StockBill brand assets (logo option A, "Stacked stock")

Chosen 2026-11-22. Use these as-is; don't redraw them.

## Colours
| Token | Hex | Use |
|---|---|---|
| Brand teal | `#0F5E57` | icon tile, the "Bill" half of the wordmark on light backgrounds |
| Ink | `#10231F` | the "Stock" half of the wordmark, headings |
| Amber | `#F2B84B` | the bottom bar in the icon; the "Bill" half of the wordmark on dark backgrounds |
| Dark ground | `#0E1B19` | dark backgrounds behind the logo |

## Wordmark
- Text "Stock" + "Bill" (no space), font **Space Grotesk**, weight 600, letter-spacing -0.02em.
- Light backgrounds: "Stock" in Ink `#10231F`, "Bill" in Brand teal `#0F5E57`.
- Dark backgrounds: "Stock" in white, "Bill" in Amber `#F2B84B`.
- Render it as live text, not an image. Bundle the font locally (npm `@fontsource/space-grotesk`, weight 600); don't load it from Google Fonts, because the shop laptop may be offline.
- Sidebar lockup: 28 px icon + 10 px gap + 18 px wordmark; the shop name (from Business Profile) underneath in 12 px.

## Files
| File | Where it goes | Use |
|---|---|---|
| `stockbill-icon.svg` | `frontend/src/assets/` | the icon inside the app (sidebar, login page) |
| `favicon.svg` | `frontend/public/` | modern browsers' tab icon |
| `StockBill.ico` | `frontend/public/` (replaces the existing one) | tab icon fallback, 16/32/48 px |
| `apple-touch-icon.png` | `frontend/public/` | iPhone home screen (180 px), needed for the PWA later |
| `stockbill-icon-192.png`, `stockbill-icon-512.png` | `frontend/public/` | PWA manifest icons (later phase) |

## Rules
- Keep the icon's rounded-square tile; don't put the bars on a bare background.
- Minimum size 16 px. The icon has no text, so it stays legible.
- This is the **StockBill product** brand. Shop branding (the shop's own logo on invoices) comes from the Business Profile upload and is a separate thing.
