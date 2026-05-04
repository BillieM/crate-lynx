# E15 — Frontend: link proposals view

- [x] Add a frontend API client method for listing link proposals with optional confidence-band filtering
- [x] Add frontend API client methods for approving and rejecting link proposals
- [x] Create the link proposals routed view and wire it into the app navigation
- [x] Render proposals grouped by confidence band: High, Medium, and Low
- [ ] Build proposal cards with confidence bar, local track column, streaming track column, match method badge, and score
- [ ] Add confidence-band filter chips that update the proposals query
- [ ] Implement optimistic approve and reject mutations with TanStack Query cache updates
- [ ] Add loading, empty, and error states for the proposals view
- [ ] Add frontend tests for grouped rendering, band filtering, and optimistic approve/reject behavior
- [ ] Run relevant frontend validation: `npm run lint`, `npm test`, and `npm run build`
