# Last.fm ArtistTags2007 static-genre review packet

This local-only packet is the next independent-gold review stage. It creates
100 deterministic, **unreviewed** questions from the pinned Last.fm 2007
archive and the deployed public static-discovery v2 asset. It reads no audio,
model predictions, historical Every Noise data, public database, or release
output; it does not write `dist` or a public artifact.

The archive pin is SHA-256
`b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f`.
The static-asset byte pin is SHA-256
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`;
its separately verified v2 logical payload hash is
`c117658577413e8047503486077e3b50ebe31056340a9025897fa8645c716c22`.

## Candidate rule

An emitted row requires all of the following:

1. A well-formed Last.fm source row with a positive count and exact
   MusicBrainz artist UUID.
2. That UUID occurs exactly in the pinned v2 static asset.
3. The raw Last.fm tag exactly equals a current v2 catalog genre name. This
   is literal, case-sensitive candidate selection only.

Rows are ranked by the SHA-256-derived stable question ID and the first 100
are retained. Only one question per `(musicbrainz_artist_id,
catalog_genre_id)` is retained; the lowest source-row ordinal is the stable
representative. The packet retains that source row’s ordinal and SHA-256.

Each row is `unreviewed_abstain`, has no membership value, and explicitly says
that no tag-to-genre approval or negative label has occurred. A literal match
is not a semantic bridge and must never be promoted automatically. An absent
Last.fm tag is unknown, not a negative.

The real pinned run has 8,619 unique exact-artist/literal-genre candidate pairs
over 1,126 static MBIDs. Its 100 rows cover 39 catalog genre IDs, with at most
six questions for a single genre. This breadth is an observed deterministic
packet property, not a quality metric.

The demonstrated packet at `/tmp/lastfm-static-genre-review-v1.json` has file
SHA-256 `7525c4f3c422d8f69561b124ea33334d500c47314cf08b8be308772149979c20`
and its embedded, canonical logical `output_sha256` is
`8f40a0761573a8e23e60ca7b0c2a0f1843ba1e9eedd9814182f7b4ac4e23edc1`.

Run it with:

```sh
.venv/bin/python scripts/build_lastfm_static_genre_review.py \
  --archive .cache/lastfm-artisttags2007/source.tar.gz \
  --static-discovery dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json \
  --output .cache/lastfm-artisttags2007/static-genre-review-v1.json \
  --sample-size 100
```

This packet is not an independent gold set, a positive label source, a
negative source, a precision estimate, or a release gate. A later reviewed
bridge and independently evidenced judgments are required before the existing
gold evaluator can consume any row.
