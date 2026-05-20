# TASKS

## Streaming Track Relationships

### Notes

- Keep direct `final_links` as the normal local-to-streaming approval path.
- Add streaming-to-streaming relationships as a separate resolution layer for the minority of cases where several streaming tracks should use one local file.
- Keep playlist/list UI statuses limited to `linked`, `pending`, and `unlinked`.
- Accepted relationship removal, undo, full management screens, and manual relationship creation are out of scope for this version.

### Tasks

- [x] Add the relationship persistence foundation.
  - Add Alembic migration, SQLAlchemy metadata, core table views, and test factories for accepted streaming relationships and relationship suggestions.
  - Store accepted `equivalent` and `related` edges, pending suggestions, accepted suggestions, and rejected suggestions.
  - Normalize relationship pairs so duplicate reversed pairs cannot be created.
  - Add migration/schema parity tests and model tests.

- [x] Build the shared relationship resolver and conflict detector.
  - Implement equivalent-group resolution where direct `final_links` win for the exact streaming track.
  - Resolve unlinked equivalent-group members through the group's single local link.
  - Keep `related` relationships advisory only.
  - Detect equivalent acceptance conflicts when connected groups resolve to different local tracks.
  - Treat same-local conflicts as non-conflicting.
  - Add resolver tests for direct links, transitive equivalent groups, related-only groups, unlinked groups, and conflict cases.

- [x] Move M3U regeneration behind a shared background job.
  - Add an M3U regeneration job/enqueuer for affected full-sync playlist IDs.
  - Replace synchronous M3U writes in approve, reject, and break-link flows with affected-playlist enqueueing.
  - Calculate affected playlists through equivalent groups for local-link changes and through both connected groups for equivalence changes.
  - Preserve existing M3U content behavior, playlist order, and full-sync-only output.
  - Add backend tests for affected-playlist calculation and job execution.

- [x] Generate streaming-to-streaming relationship suggestions.
  - Generate candidates across active `full` and `match_only` playlist tracks.
  - Use ISRC matches for highest-confidence equivalent suggestions.
  - Use shared title/artist/album/duration scoring for fuzzy suggestions, suggesting equivalent for high-confidence matches and related for medium-confidence matches.
  - Preserve pending suggestions and suppress candidates already pending, accepted, rejected, or connected by accepted relationships.
  - Make rejection suppression group-aware by checking rejected pairs across current relationship groups.
  - Run generation after playlist sync/metadata refresh and expose a manual generation action.
  - Add backend tests for ISRC, fuzzy scoring, scope, dedupe, accepted suppression, related suppression, and group-aware rejection.

- [x] Add backend relationship queue actions.
  - Add router, schemas, store/service methods, and app registration for listing, accepting, rejecting, and generating relationship suggestions.
  - Return both track metadata, score, confidence, match method, suggested type, local-link context, and conflict state from the list API.
  - Accepting `equivalent` should create the relationship, handle no-link and one-link groups directly, and require `winning_final_link_id` for different-local conflicts.
  - Conflict acceptance should keep the chosen final link and detach losing final links without writing rejected local-to-streaming suggestions.
  - Accepting `related` should never affect link resolution or require conflict handling.
  - Regenerate OpenAPI and frontend API types after schema changes.
  - Add route tests for success, not-found, stale suggestions, conflicts, detached losing links, and M3U enqueueing.

- [x] Update existing resolution surfaces to use the resolver.
  - Playlist rows and counts should resolve equivalent-linked tracks as plain `linked`.
  - Populate `local_track_id` and `final_link_id` from the resolved link.
  - Keep pending local-link behavior unchanged for unresolved tracks.
  - Hide equivalent-resolved tracks from Missing Locally; keep related-only tracks missing.
  - Update M3U export to emit the original playlist row metadata with the resolved local file path.
  - Add backend tests for playlist rows, playlist counts, Missing Locally, and M3U equivalent rows.

- [x] Add frontend relationship data access and navigation.
  - Add typed fetch/mutation helpers, Zod validation, query keys, and invalidation for streaming relationship suggestions.
  - Add a `Streaming relationships` maintenance nav item and route.
  - Keep existing playlist status parsing constrained to `linked`, `pending`, and `unlinked`.
  - Add query and routing tests.

- [x] Build the Streaming Relationships review UI.
  - Reuse the Link Proposals visual pattern for loading, empty, error, and populated states.
  - Show score-sorted side-by-side streaming track comparisons with confidence and match-method cues.
  - Provide `Equivalent`, `Related`, `Reject`, and manual `Generate` actions.
  - Show inline winner selection only for equivalent conflicts.
  - Invalidate relationship, playlist, proposal, and Missing Locally queries after actions.
  - Add frontend tests for all states, actions, conflict winner selection, and failed mutations.

- [x] Final integration and validation.
  - Regenerate OpenAPI/types.
  - Run backend validation: `ruff check .`, `ruff format --check .`, and `pytest`.
  - Run frontend validation: `npm run lint`, `npm test`, and `npm run build`.
  - Remove any stale v1 task language about accepted relationship removal/undo screens, since management/removal is explicitly deferred.
