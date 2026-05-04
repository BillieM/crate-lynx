# Compact Minimal UI

Design constraints for every task:
- Keep the UI comfortably compact, not spreadsheet-dense.
- Preserve existing routes, API behavior, and user workflows.
- Use built-in Tailwind utilities and existing Catppuccin Mocha `ctp-*` theme classes.
- Prefer shared primitives and shared class maps over one-off component styling.
- Keep typography, spacing, radii, borders, focus states, disabled states, and loading states consistent across the app.

- [x] Establish compact shared UI styles in `app-ui/src/styles/componentClasses.ts`, reducing repeated oversized radii, padding, shadows, pills, panels, buttons, and row styles into reusable Tailwind/Catppuccin class groups
- [x] Slim down the app shell by reducing sidebar header height, search field padding, section gaps, nav row height, badge size, topbar height, icon frames, and action button sizing while preserving current navigation behavior
- [x] Replace the oversized playlist overview hero with a compact header band that keeps playlist title, sync time, linked/pending/unlinked counts, coverage, artwork, and sync errors visible without dominating the viewport
- [x] Make playlist filters smaller and more space-efficient while preserving filter counts, selected states, keyboard accessibility, and Catppuccin status colors
- [x] Convert playlist track cards into compact rows using the existing row-card model, reducing padding and duplicated information while keeping status, title, artist, album, duration, and actions easy to scan
- [ ] Apply the compact design system to proposal cards, empty states, loading states, status messages, and popovers so secondary views match the playlist screen
- [ ] Review arbitrary Tailwind values across touched frontend components and replace repeated sizing, spacing, radius, shadow, and typography patterns with shared styles where practical
- [ ] Verify desktop and narrower viewport layouts for clipping, overlap, excessive whitespace, readable text, stable controls, and consistent Catppuccin Mocha theming
- [ ] Update affected frontend tests for changed structure, labels, accessible states, or shared primitive behavior
- [ ] Run frontend validation: `npm run lint`, `npm test`, and `npm run build`
