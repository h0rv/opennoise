# MusicBrainz direct seed H3 holdout

`scripts/evaluate_musicbrainz_direct_seed_h3_holdout.py` compares a verified,
local-only, reconciliation-safe MusicBrainz proper-genre custody object with
the current static-discovery seed IDs and the retained Every Noise/H3 semantic
artifact. It is an identity/coverage smoke test, not a quality evaluation,
model input, custody artifact, publication gate, or release claim.

The custody object is verified before the evaluator opens the historical
artifact. Joins are only exact retained seed IDs: a custody claim `seed_id` can
join a public `node_id`, and a historical `enao-legacy:<seed_id>`. Name,
alias, MusicBrainz genre-ID, artist, and inferred joins are not allowed.

The historical result is positive-only. A historical membership count above
zero is an observed-positive presence signal. A zero count or an absent
historical identity is recorded as an abstention. Because the retained H3
artifact has observed memberships for nearly all 6,291 seed IDs, positive
presence is nearly tautological and cannot validate direct artist-genre
correctness or the usefulness of the lift. The receipt intentionally reports
no precision, false positives, recall, quality threshold, or publication result.

Run it only after the custody object has already been verified locally:

```sh
.venv/bin/python scripts/evaluate_musicbrainz_direct_seed_h3_holdout.py \
  --custody-receipt /path/to/musicbrainz-direct-proper-genre-custody.json \
  --custody-object-store /path/to/custody-object-store \
  --public-static-discovery dist/assets/static-discovery.<hash>.json \
  --historical-semantic .cache/historical-signal-final/historical-signal-semantic-v1.json \
  --output /tmp/musicbrainz-direct-seed-h3-holdout.json
```

The September 22 direct gate measured 697 reconciliation-safe seed IDs. The
current public discovery has 344 seed IDs, but the relevant comparison is the
exact seed-ID intersection, not subtraction: the independently measured split
is 274 shared, 423 direct-only, and 70 public-only. A receipt from the script
must reproduce those counts from its supplied sealed candidate and current
static asset before treating the 423 as the evaluated cohort. Even then it
only proves cohort identity and historical seed presence; an exact artist-MBID
holdout or independently judged gold set is still required to evaluate quality.

## Preliminary receipt (2026-09-22)

The verified local custody receipt `cf91b9840cf53111c0efe1435467f36404b02dc871f65afd39c8dce7a159ad1b`
was evaluated against static-discovery bytes
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`
and historical semantic bytes
`4f910231f6c098c1b75471071e7706a819b1617a0253ec574a09289751ddbb57`.
The temporary receipt logical hash was
`6be45ecbf38bd555c387856a7bd899fa39f813d44eb45ae51a18efadc4195a8a`.

It replayed 697 reconciliation-safe direct seed IDs, 344 current public seed
IDs, 274 shared IDs, 423 direct-only IDs, and 70 public-only IDs. All 423
direct-only IDs had an exact historical seed identity with a positive H3
membership count; there were zero zero-count and zero missing-identity
abstentions. This is expected given the retained H3 artifact has positive
presence for 6,289 of 6,291 seed IDs. It confirms neither artist--genre claim
correctness nor that the 423-seed lift is useful beyond labels.

The final tracked custody receipt hash is
`a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9`.
The final H3 identity-smoke report hash is
`f6738cea3736774343f0bba72eca0a03d101f56b09b52ed198c7c535ed4c3ddd`.

## Exact artist and genre positive recovery

`scripts/evaluate_musicbrainz_direct_artist_genre_h3_positive_recovery.py`
checks exact `(seed_id, MusicBrainz artist MBID)` pairs only. It verifies the
direct custody object first. It then verifies the bridge and H3 hashes. The
H3 genre key is a one-to-one source ID crosswalk, not a genre name or alias.

The report is positive-only. H3 pairs absent from the direct set are not
negative evidence. The result does not measure precision and cannot approve a
release. Its soundness depends on the verified source-ID crosswalk and the
accepted Spotify-to-MusicBrainz bridge being unique.
