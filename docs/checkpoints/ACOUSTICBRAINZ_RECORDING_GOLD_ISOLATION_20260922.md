# AcousticBrainz recording gold source-isolation audit

## Result

The retained AcousticBrainz Discogs validation archive provides a bounded,
exact-recording-ID evaluation cohort, but no verified frozen recording-prediction
lineage is retained. The new source-isolation gate permanently abstains before
opening any AcousticBrainz genre-label column. It is not an independent artist
genre gold set and cannot be used for a public release or promotion gate.

## Exact-ID evidence

The existing counts-only overlap receipt is byte-bound as
`fd3072d430620d43b0c48ea8e53e13b3821200389fb1c76b68420dded78e763a`.
It binds the source archive SHA-256
`d5b9eaef344864cd3c4d0bf1551e29b2fbcb23f9e28d1b7180cbdfa4dee704e3`
and the exact catalog SHA-256
`100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`.

It found 71 exact recording-ID overlaps. Of those, 63 have both a matching
release group and exactly one primary artist. This is enough to identify a
small recording-level cohort if a compliant prediction snapshot is later
retained. It does not turn a recording annotation into an artist membership
judgment.

## Leakage gate

The audit accepts no caller-declared prediction lineage: a JSON declaration
cannot prove that its claimed file hashes exist or that its construction omitted
the prohibited inputs. It permanently requires a future verifier to hash a real
prediction artifact and inspect a real construction receipt for all of:

- MusicBrainz artist tags
- MusicBrainz recording and release-group genre inputs
- historical Every Noise

The supplied overlap receipt has `label_columns_read=false`. No prediction
lineage verifier is retained in custody, so the deterministic audit returned
`abstain_missing_verified_prediction_lineage`, with
`source_isolated_recording_evaluation_ready=false` and
`independent_artist_genre_gold_ready=false`. Its logical output SHA-256 is
`f99b802d0dc82ca16bb88ddd5146785a94c25c33b834a6f9c77cc2cc682a9876`;
the formatted local report file SHA-256 is
`6288290a8695cd9a95ad91d2c7a1bc08b4ff341c69d6b3677e0219e42bf049fb`.

## Read-only Wikidata-only feasibility

After freezing the 63 identities from the hash-bound credit materialization,
the audit joined their seven distinct credited artist MBIDs to the sealed
`data/public.sqlite` snapshot (SHA-256
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`).
All seven artist IDs resolved there, and every one of the 63 recording rows has
at least one direct `wikidata_p136` observation. This gives a possible frozen
prediction arm whose construction is independent of MusicBrainz genre tags:
the prediction for a frozen recording is the direct Wikidata P136 set of its
sole credited artist.

The first pass reads the two identifier fields to freeze the cohort, but does
not interpret or use source genre labels for selection. Only after that
artist/P136 cohort was fixed, the local read-only feasibility pass interpreted
the source TSV's label fields. The 63 rows contain 192 nonempty Discogs-label
occurrences and 32 distinct raw labels. Strict NFKC/casefolded,
whitespace-normalized matching to a unique current target name found only one
literal target label, `jazz`; it occurs on three rows. No target alias,
hierarchy, fuzzy, or semantic mapping was used. The corresponding frozen
Wikidata-only predictions contain literal `jazz` on zero of those three rows.

This is sufficient to prove a narrowly source-isolated positive-only recording
diagnostic can be formed once a real prediction-file/receipt verifier exists.
Its only current exact-label support is three positives, so it is far too small
for an artist-gold or promotion claim. The zero-of-three observation is a
coverage result, not a quality estimate or false-negative assertion: recording
labels do not define artist membership, and unmatched source labels remain
unmapped rather than negative.

The bounded replay is:

```sh
.venv/bin/python scripts/audit_acousticbrainz_wikidata_recording_feasibility.py \
  --source .cache/acousticbrainz-genre-dataset-discogs-validation-v1/acousticbrainz-mediaeval-discogs-validation.tsv.bz2 \
  --credit-database .cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite \
  --public-database data/public.sqlite \
  --output /tmp/acousticbrainz-wikidata-feasibility.json
```

It first hashes all three pinned inputs, freezes the identifier-only cohort and
the direct-P136 prediction set, then interprets labels only for the resulting
aggregate counts. It emits no source label or recording row. The replay's
logical output SHA-256 is
`ee2061316b7907824c6bf5702abfa464aec69a4aad2ae703e2af518d4f1294c3`;
the formatted local report file SHA-256 is
`e8101d2acc32ea35f706a81f02c31f65e1d2538be7dffc1e938678face638c87`.

## Required next artifact

Implement a verifier that opens a hash-bound pre-label exact-recording prediction
file and its construction receipt, and proves the four forbidden inputs above
are absent. Only then may the 63-row cohort support a positive-only recording
evaluation. That future result still cannot measure precision, create artist
labels, or qualify the public artist-genre promotion gate without separate
reviewed artist judgments and a negative-label policy.

## Smallest positive independent-gold route

The smallest realistic artist-level route is not this contaminated
AcousticBrainz cohort. First obtain a terms-approved, receipt-bound Discogs
sample. Use only a direct MusicBrainz artist relation whose URL ends in one
numeric Discogs artist ID; retain the exact MusicBrainz relation record hash and
the exact Discogs artist ID. From that artist ID, select by stable hash up to 50
Discogs releases that list exactly that ID as their sole credited artist. Retain
only source-native Discogs `genres` and `styles`, response hashes, and an
explicit reviewer decision mapping each source label to a target genre ID.

Each resulting artist--genre pair still needs a reviewer membership decision;
release labels do not automatically become artist memberships. Add separately
preselected, reviewer-judged non-members before measuring precision. Freeze the
candidate predictions before opening the Discogs labels, and reject any
prediction construction receipt that used MusicBrainz tags, recording/release
genres, historical Every Noise, or Discogs. This 50-release pilot is small
enough to establish whether the exact external-ID bridge and judgment protocol
work; it is not automatically large enough for promotion thresholds.
