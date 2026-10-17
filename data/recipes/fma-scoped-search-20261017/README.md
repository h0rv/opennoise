# Search within native catalog context

The current catalog supported global title, artist-name and native-ID search,
but typing on a genre, artist or album page dropped the selected entity.
Finding a recording in Experimental required browsing 128 pages or manually
checking global search results. This change keeps the selected source context
while searching its complete recordings.

The existing search control offers this genre's, artist's or album's tracks on
its corresponding page. The query and result page remain in the URL. Selecting
a global search scope deliberately leaves the context; clearing the query
restores ordinary browsing. Matching uses the existing title/artist/native-ID
semantics and preserves source order. Results state both matches and the full
source cohort denominator. Source artist association and source album IDs are
not artist classifications, album genres or a release sequence.

No new search index or metadata is exported. Artist/album profiles already
contain complete recording IDs. A genre search loads its existing membership
pages in batches of at most four, only for a nonblank query. Complete page
identity, cardinality and ordered unique IDs are checked before results can be
shown or a membership list cached. Navigation interrupts further batches;
already-started requests may finish but cannot render stale results. Failed
pages are evicted for Retry. Empty-query browsing retains its normal paginated
loads. The existing global title index is shared and reused; visible result
records retain exact native source evidence and reconstructed metadata URLs.

Actual retained scope sizes include Experimental genre 38 (25,493 tracks),
Kosta T artist 15891 (804), album 17509 (314), and artist 8613 whose source artist
record is missing (22). The largest genre's complete membership is 171,029 bytes
across 128 existing files. This is a one-time search load, not an initial browsing
cost. The current actual corpus has no missing titles and no null-artist tracks;
those boundaries are tested with explicitly synthetic fixtures.

This implements a discovery interaction criterion from the parity roadmap. It
does not expand source coverage, improve the frozen model, establish musical
relevance or merge the separate listening artifacts. No fitting against examined
holdouts, new source/audio acquisition, credentials, paid services or public
research deployment is part of this work. The finished listening packages remain
unchanged with zero actual responses out of twelve planned responses.

## Verified delivery

Implementation: `47ab8ad6310abebf224f628f5e5dfd7363c14449`.
The final actual browser audit passed 36 frozen search/page cases, covering all
four independently enumerated scopes. For example, `#genre=38&q=live` returns
458 of 25,493 source recordings. Text matching does not establish that a track
is a live performance. Exact IDs, outsider duplicate titles, first/last result
pages, history, reload, explicit global handoff, map compatibility and 320/390px
layouts passed. A separate browser check cleared each of the three context
queries and immediately typed with real keyboard input; focus stayed in the
search box and the new query worked. Initial failure evidence is retained.

Interrupted genre loading launched at most its current four-request batch;
late results did not overwrite the new route. A failed membership page could
be repaired and retried without reload or partial results. No external or media
requests occurred. Four synthetic contracts additionally exercise null and
missing-title fixtures, malformed membership/index/track cache recovery and
matching semantics. Independent source review cleared the final source.

All 7,545 JSON data files and all 13 descriptor-map files remain byte-identical
to the compact baseline. The closed final export has 7,563 files and occupies
33,998,075 bytes including its receipt, within the unchanged 40 MB bound. Only
display code and output inventory receipts changed; there is no new data index.
Both finished participant ZIPs still match their recorded hashes.

The standalone archive `/workspace/OpenNoise-scoped-track-search-20261017.zip`
has 7,564 members and 11,153,241 bytes; SHA256
`aac92fadf4377776da731b53227084a8dccacd8e2cfaeea2216c60bdef322b0a`.
Every file passed byte-for-byte archive round-trip verification. Extract it,
serve its `site` folder with `python3 -m http.server 8000 --bind 127.0.0.1`,
then open the local address. A repository, build environment or external service
is unnecessary for browsing.

The final display refresh uses the existing `refresh_fma_static_display`
function with the receipt-pinned compact baseline. The exact wrapper is
`/workspace/opennoise-scoped-search-run-20261017/refresh-final-bounded.py`;
120-second CPU/wall and 1-GiB address-space guards remain unchanged. Its final
output is `site-final` under that directory; the earlier `site` remains as
pre-focus-fix evidence. The source/catalog/model is never refitted or recaptured.

Evidence locations:

- Run, resource bounds and checks: `/workspace/opennoise-scoped-search-run-20261017`.
- Groundtruth and exact data audit: `/workspace/opennoise-scoped-search-independent-20261017`.
- Final browser evidence: `/workspace/opennoise-scoped-search-browser-20261017/final`.
- Independent source review: `/workspace/opennoise-scoped-search-review-20261017`.

An environment disconnect notification at 15:51 UTC did not interrupt execution;
the worktree remained available and a preservation snapshot was saved. No work
was discarded or restarted because of the notification.
