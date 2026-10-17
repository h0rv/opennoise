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
