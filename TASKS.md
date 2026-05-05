# Matching Flow Improvements

- [x] Improve tag candidate scoring with a token-aware ranker.
  - Replace equal-weight raw `fuzz.ratio` scoring with normalized title/artist scoring using RapidFuzz token-aware scorers.
  - Strip feature/version noise for title identity comparisons, including `ft`, `feat`, `featuring`, `original mix`, `extended mix`, `radio edit`, and similar suffixes.
  - Weight score as title-first, artist-second; use album and duration only as small positive bonuses.
  - Do not penalize duration differences, because extended/radio/club versions can legitimately differ.

- [x] Reduce noisy candidate persistence.
  - Keep a smaller ranked shortlist per local track.
  - Persist only plausible candidates above the chosen threshold.
  - If all candidates are low confidence, keep only the top fallback candidates so review remains possible without flooding the queue.

- [x] Clear stale sibling suggestions when approving a proposal.
  - On approve, create the final link, mark the chosen suggestion approved, and delete other pending suggestions for the same `local_track_id`.
  - Preserve rejected suggestions.
  - Add backend tests covering sibling pending cleanup.

- [x] Group proposal candidates in the UI.
  - Keep the existing `/api/proposals` response shape.
  - Group client-side by `local_track_id`.
  - Show one review item per local track with ranked candidate choices.
  - Approving any candidate removes the whole group optimistically; rejecting removes only that candidate.

- [x] Clean up orphaned suggestions for already-approved tracks.
  - Add a proposal listing guard so pending suggestions are not returned when the local track already has a final link.
  - Add a maintenance cleanup path or store method to delete pending suggestions for linked tracks.
  - Verify and clean current pending suggestions joined to `final_links` by `local_track_id`.

- [ ] Validate the full matching-flow change.
  - Backend: `source .venv/bin/activate`, then `ruff check .`, `ruff format --check .`, and targeted `pytest` for matching/link tests.
  - Frontend: `npm run lint`, targeted proposal UI tests, and `npm run build`.
  - Include regression coverage for the OnlyL case so the true candidate ranks above the Gigi D'Agostino false positive.
