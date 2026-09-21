# Independent artist--genre gold set

This is the bounded workflow for the roadmap’s independent artist--genre
quality evidence. It is separate from construction and from the existing
calibration fixture. It never reads historical Every Noise labels, MusicBrainz
artist genres/tags, Wikidata `P136`, ListenBrainz candidates, or model
predictions when creating a judgment.

No cached data qualifies today: the cached MusicBrainz “external evaluation”
is explicitly source-dependent and non-gold. The checked-in fixture proves the
parser, deterministic split, custody fields, and evaluator only. It is
synthetic, diagnostic, and categorically ineligible for a production gate.

## Source and identity custody

The preferred first source is FMA metadata, identified in
[`DATA_SOURCE_RESEARCH.md`](../ingest/DATA_SOURCE_RESEARCH.md). FMA is a
separate, historical track-level tag source. Its local identifiers must be
joined only through a reviewed exact external-ID bridge, whose SHA-256 is
stored with the source snapshot. Name matching is prohibited. No audio is
downloaded or evaluated.

FMA track tags do not automatically become artist--genre membership labels.
After the exact bridge, a reviewer must make each artist-pair judgment from
the independently retained track context and record the source-record hash.
The resulting metrics are conditional on these judged pairs; they are not a
full-population precision claim.

The pinned Last.fm ArtistTags2007 archive is a quicker human-review candidate
because its rows include exact MusicBrainz artist IDs. Build a deterministic
100-question packet from the local archive with:

```sh
.venv/bin/python scripts/build_lastfm_artist_genre_review.py \
  --archive .cache/lastfm-artisttags2007/source.tar.gz \
  --output .cache/lastfm-artisttags2007/artist-genre-review-v1.json \
  --sample-size 100
```

The packet contains positive tags for review, not gold labels. Reviewers must
judge membership, and missing tags remain unknown, so the packet has no
negative labels and cannot serve as a production gate. FMA remains the formal
future route for an independently sourced gold set.

For every source snapshot, create an `independent-artist-genre-gold-v1` JSON
document with the source locator/version/payload hash, license or terms
reference, exact-review bridge hash, and an exclusion list containing all five
forbidden provenance values: `every_noise`, `musicbrainz`, `wikidata`,
`listenbrainz`, and `model_prediction`. Each judgment retains the hash of the
specific source record used to make it.

## Versioned split and gate

Before accepting model output, assign each stable judgment ID to
`sha256(id) mod 20`, record a complete disjoint training/evaluation bucket
partition, and retain only the evaluation rows in the gold document. The
evaluator consumes a separate prediction file and defaults absent pairs to
false; it never creates labels from predictions.

Run the diagnostic proof:

```sh
.venv/bin/python scripts/evaluate_independent_artist_genre_gold.py \
  --gold tests/fixtures/independent_artist_genre_gold_fixture_v1.json \
  --predictions tests/fixtures/independent_artist_genre_predictions_fixture_v1.json \
  --report .cache/objective-gates/independent-artist-genre-gold-fixture-v1.json
```

The command exits nonzero for this fixture by design. The workflow currently
has no production threshold policy: FMA tags can establish source-cited
positives but an omitted tag is not a negative. Therefore every report is
hard-blocked from release eligibility, including a future independently sourced
set with 500 rows. A later policy must first define a separately evidenced
negative sampling method, class-balance requirements, and preregistered
precision/recall thresholds; only a new revision may enable that gate.
