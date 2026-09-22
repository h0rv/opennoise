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

## Measured temporary receipt (2026-09-22)

The verified local custody receipt `cf91b9840cf53111c0efe1435467f36404b02dc871f65afd39c8dce7a159ad1b`
was evaluated against static-discovery bytes
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`
and historical semantic bytes
`4f910231f6c098c1b75471071e7706a819b1617a0253ec574a09289751ddbb57`.
The receipt logical hash is
`6be45ecbf38bd555c387856a7bd899fa39f813d44eb45ae51a18efadc4195a8a`.

It replayed 697 reconciliation-safe direct seed IDs, 344 current public seed
IDs, 274 shared IDs, 423 direct-only IDs, and 70 public-only IDs. All 423
direct-only IDs had an exact historical seed identity with a positive H3
membership count; there were zero zero-count and zero missing-identity
abstentions. This is expected given the retained H3 artifact has positive
presence for 6,289 of 6,291 seed IDs. It confirms neither artist--genre claim
correctness nor that the 423-seed lift is useful beyond labels.
