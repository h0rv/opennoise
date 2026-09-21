# Artist navigation audit

## Scope

This audit covers static artist search, genre artist context, artist detail,
deep links, and Back navigation. It does not cover canvas geometry, layout,
zoom, or source data.

## Result

The current path is internally consistent, and this review found no clear
correctness bug to fix.

Search returns both genres and artists from the static discovery asset. An
artist search result chooses the first directly observed genre that is present
in the atlas, then opens the artist with that genre as context. An artist
button in a genre detail panel uses the same context. The artist URL contains
both `open_focus` and `open_artist`, so a copied URL can restore the genre and
artist detail.

The detail flow keeps the artist context in `state.focus`. The visible Back
button clears `open_artist` with `history.replaceState` and restores the genre
detail. Browser history also handles a direct artist URL, a genre link from an
artist page, and a return to the prior map state through `popstate`.

## Reviewed cases

| Case | Expected behavior | Code path |
| --- | --- | --- |
| Search for a genre | Focus the genre and add one history entry. | `activateSearchMatch` calls `focus`. |
| Search for an artist | Select a directly observed genre, then show the artist. | `artistSearchContext`, `focus`, and `showArtist`. |
| Click an artist in genre detail | Keep the current genre as context and add `open_artist`. | `showArtist` with the current `state.focus`. |
| Open a copied artist URL | Restore the focused genre and artist after discovery data loads. | `canonicalizeFocusUrl`, initial `focus`, and `loadDiscovery`. |
| Click a direct genre from artist detail | Leave artist detail and focus the selected genre. | `data-open-node-id` handler and `focus`. |
| Use the visible Back action | Restore the genre panel and remove `open_artist`. | `returnToGenreDetail` and `replaceUrl`. |
| Use browser Back or Forward | Rebuild the URL state without adding another history entry. | `popstate` and `focus(..., false, ...)`. |
| Use an invalid artist or unavailable discovery asset | Show the genre detail and remove the invalid artist URL state. | `loadDiscovery` fallback and `replaceUrl`. |

The implementation correctly avoids treating an artist name as an identity
join. Search IDs come from the checked static asset, and an artist can open
only when its exact stored ID has a direct membership in the selected genre.

## Verification

The static atlas tests pass with `node --test tests/static/test_map_atlas.mjs`.
The browser QA contract test names all required artist search, deep link, and
Back checks in `tests/test_semantic_map_browser_qa.py`. All six of those
stdlib `unittest` checks pass with
`.venv/bin/python -m unittest tests.test_semantic_map_browser_qa`.

No code or test change was needed from this audit. A future browser run should
keep the existing checks for artist search, copied artist URLs, the visible
Back action, and browser history Back and Forward together because each path
uses a different history transition.
