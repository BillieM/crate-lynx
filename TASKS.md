# E09 — Shell redesign to match mockup

- [x] Delete `SectionView`, `AppShell`, `ShellNavLink`, `appRoutes`, and the full-screen grid layout from `App.tsx` — keep only `lerp`, `getProgressColor`, `asRgb`, `mixColors`, and the color/type helpers
- [x] Implement the fixed-height app container: `640px`, `border-radius: 12px`, `overflow: hidden`, flex row, `border: 1px solid surface0`, Catppuccin Mocha `base` background
- [x] Build the sidebar (220px, `mantle` background, flex column, `border-right: surface0`):
  - Logo/brand header: icon + "MUSEBRIDGE" wordmark in `mauve`, with `surface0` bottom border
  - Inline search bar below logo (not in topbar): `surface0` background, `subtext0` placeholder text
  - Maintenance section with section label and three nav items: Link proposals (yellow badge 14), Unidentified (red badge 3), Missing locally (overlay badge 28)
  - YouTube Music section with section label and five per-playlist nav items, each with a progress bubble
  - Local Library section with section label and an All tracks nav item (mauve badge 312)
- [x] Redesign the progress bubble as a compact sidebar fraction (e.g. `5/62`), right-aligned in the nav item, coloured via the existing lerp helper — remove the large decorative bubble card entirely
- [x] Build the topbar (44px, `mantle` background, `border-bottom: surface0`, flex row, space-between):
  - Left: section icon + title text + context pill (pill-info / pill-pending / pill-lib)
  - Right: action buttons rendered from a per-view config (e.g. Sync + Export M3U for playlist views, empty for maintenance views)
- [x] Wire view switching: each nav item click activates the matching view div and updates the topbar title/pill/actions — no React Router needed, replicate the `showView` pattern from the mockup using React state
- [x] Add stub view shells (empty `<div>` with an id) for: `proposals`, `unidentified`, `missing`, `playlist` (Late Night Drive), `playlist2`–`playlist5`, `library` — content filled by E10–E12
- [x] Move `SearchPanel` into the sidebar search bar slot; keep the existing debounce + TanStack Query fetch logic, drop the full-screen dropdown styling in favour of the compact sidebar context
- [ ] Verify the Catppuccin Mocha palette is applied throughout: no grays, no default Tailwind colours — every element maps to a named Catppuccin token
