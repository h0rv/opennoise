# Artist membership evaluation

`scripts/evaluate_artist_memberships.py` is the versioned gate for direct and
one-hop artist-membership predictions. It evaluates only an explicit,
bounded, SHA-256-addressed held-out judgment document. The evaluator reports
direct and one-hop macro precision, recall, F1, abstentions, and the exact
source/facet cells used in each macro. It reruns the same calculation and
fails if the normalized evaluation hash changes.

The checked-in
`tests/fixtures/artist_membership_judgments_v1.json` is deliberately small
and is marked `user_authored_fixture_calibration_not_independent_public_gold`.
It is a test/calibration artifact, not a claim about production quality. Its
only source/facet strata are public-model facets: MusicBrainz artist tags,
Wikidata `P136`, and ListenBrainz one-hop propagation. The strict schema
rejects MusicBrainz supplementary genre material and historical Every Noise
artist assignments, and it validates a deterministic SHA-256 held-out split
and the canonical judgment-record hash.

Run it against a model artifact with explicit destinations:

```sh
uv run python scripts/evaluate_artist_memberships.py data/model/phase3-public-model.json \
  --judgments tests/fixtures/artist_membership_judgments_v1.json \
  --report .cache/objective-gates/artist-membership-evaluation-v1.json \
  --database .cache/artist-membership-evaluations.sqlite \
  --object-store .cache/evaluation-objects
```

The SQLite ledger stores immutable evaluation identities. The ObjectStore
publishes the exact judgment and report bytes under content-addressed keys.
For release custody, place both the report and its exact judgment file in the
objective-gates directory. Custody verifies the report against the release
model hashes and verifies that the report binds the judgment file hash. This
additional pair is optional so old sealed releases remain compatible; when
present it must be complete. A calibration-only report never asserts that the
release has independent public quality validation.
