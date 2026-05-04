# E16 — Frontend: Tailwind and Catppuccin cleanup

- [x] Add shared UI primitives for repeated actions, badges/pills, empty states, and status messages
- [x] Centralize tone and status class mappings around Catppuccin Mocha `ctp-*` Tailwind classes
- [x] Replace repeated action button class strings in `App.tsx` and playlist components with the shared button primitive
- [x] Consolidate playlist and proposal filter chips into one reusable filter chip component
- [x] Move proposal queue UI out of `App.tsx` into focused feature components
- [x] Move sidebar, topbar, and playlist sync configuration UI out of `App.tsx` into focused components
- [x] Replace hardcoded Catppuccin RGB values with CSS variables or theme-backed Tailwind classes where practical
- [x] Keep inline styles only for genuinely dynamic values such as progress width or computed SVG stroke offset
- [x] Review arbitrary Tailwind values and convert repeated radii, shadows, and typography patterns into shared component styles
- [ ] Replace hand-written generic SVG icons with a consistent icon approach, preferably `lucide-react`
- [ ] Add or update frontend tests for shared UI primitives, reusable filter chips, and extracted proposal/config components
- [ ] Run relevant frontend validation: `npm run lint`, `npm test`, and `npm run build`
