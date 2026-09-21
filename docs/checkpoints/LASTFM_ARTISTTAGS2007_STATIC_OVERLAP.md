# Last.fm ArtistTags2007 static overlap

The local evaluator reads the archived Last.fm ArtistTags2007 tarball and one
static discovery JSON file. It does not read a public database, audio, model
input, training data, or candidate membership input. It writes a local research
report and does not change the static discovery file or any public output.

The archive is pinned to SHA-256
`b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f`.
The source documentation describes the archive as 952,810 artist tag rows for
20,907 MusicBrainz artists with positive raw tag counts. See the [source
description](https://musicmachinery.substack.com/p/lastfm-artisttags2007).

The evaluator uses only `Lastfm-ArtistTags2007/ArtistTags.dat`. Each accepted
row must have four `<sep>` fields, a lowercase UUID MusicBrainz artist ID, and
a positive integer count. It reports malformed, invalid UTF-8, invalid ID,
invalid count, nonpositive count, and duplicate artist-tag rows separately.
A duplicate artist-tag row is rejected instead of being added to another raw
count.

Artist matching uses the MusicBrainz ID from a static discovery URL. Genre
matching compares the raw Last.fm tag and static discovery catalog genre name
as literal strings. The evaluator does not case-fold, normalize aliases, use a
taxonomy relation, or use fuzzy matching.

The positive set is split by the SHA-256 hash of the exact `(MBID, tag)` pair.
One fifth is held out. The report gives results at raw tag count thresholds 1,
2, 5, and 10. Each threshold reports the source positives, held-out positives,
artist-ID coverage, literal genre-name coverage, scoreable positives, and
exact pair overlap. Missing Last.fm tags are unknown. They are never treated
as negative examples, so the report has no precision, false-positive, or
specificity claim.

Run the checkpoint with:

```bash
uv run poe evaluate-lastfm-artisttags2007-overlap --archive .cache/lastfm-artisttags2007/source.tar.gz --static-discovery .cache/semantic-map-layout-v3-certification/site/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json --output .cache/lastfm-artisttags2007/static-overlap-v1.json
```

The checked local run used static discovery hash
`b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8`.
It parsed 952,707 accepted positives and rejected 103 duplicate artist-tag
rows. At thresholds 1, 2, 5, and 10, the exact held-out pair overlaps were
205, 204, 191, and 173. The corresponding scoreable positive overlap recalls
were 12.87%, 13.09%, 16.84%, and 23.28%.

The results describe overlap with a 2007 community tag snapshot. They do not
show that a public membership is correct, and they cannot authorize a public
release or a model change.
