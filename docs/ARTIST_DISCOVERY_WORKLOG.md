# Artist discovery checkpoint

Status: implemented and locally verified. This file tracks the UI change and cleanup audit.

## Scope

- Search placed genres and artists in the static, display-authorized discovery asset.
- Give a genre its artist list and a selected artist a genre-scoped peer list.
- Keep artist and genre selection in a shareable URL with working Back navigation.
- Label peers as shared direct-genre evidence, not learned similarity.
- Preserve the static Pages delivery path; no backend or audio.

## Acceptance

- Search can open a genre or artist by keyboard and pointer.
- Selecting an artist shows only artists directly observed in that genre.
- A direct artist URL restores the same selected genre and artist.
- Static export, browser interaction checks, Ruff, ty, and focused tests pass.

## Cleanup boundary

The active static path is `src/opennoise/deployment/semantic_pages.py`,
`src/opennoise/static/map-atlas.mjs`, and `src/opennoise/static/map-renderer.js`.
`src/opennoise/evidence/reconstruction.py`, `src/opennoise/serving/map/layouts.py`,
and `src/opennoise/evidence/album_genres.py` still have active importers; they are
not disposable experiments. The only other worktree contains unique raw objects,
so it was preserved. No source caches or historical evaluation artifacts were
removed.

## Current limit

The public discovery asset has direct artist observations for 260 placed genres
and 1,008 artists. Its genre-scoped artist peers are ranked by shared direct
genre memberships. They are not a learned artist similarity model, and this is
not yet a two-dimensional artist map. The model pipeline and serving path are
still separate; public UI data is the validated static projection.

## Verification

The Python suite passed 640 tests with 3 skips. Ruff, ty, Node atlas tests,
focused deployment tests, and `git diff --check` passed. The static Pages
certification gate regenerated `dist` and passed its local Chromium interaction
checks, including search, genre-to-artist navigation, deep links, and Back.
Browser screenshots and the report are generated in `artifacts/semantic-map/`.
