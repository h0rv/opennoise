# Embed-authorized source names

The ordinary public-input loader previously selected raw cached genre labels and
artist, release-group and recording names even when their own source observations
were denied for embedding. Independently allowed membership evidence could thus
carry a vetoed source's text. This slice selects names through their own provenance,
embed permission and source/provenance/entity/snapshot/artifact suppression gates.
Existing absent-inventory and license semantics remain unchanged; embedding does
not become a CC0-only or export permission check.

A cached genre label is retained only when an independently eligible exact name
observation supports the same value. Otherwise the existing name preference order
selects an eligible observation. If none exists, the required genre label may be
an explicitly typed identifier string, such as `wikidata:genre:Q100`. The selected
stable key must have its own eligible canonical `wikidata_genre_qid`/Wikidata or
`musicbrainz_genre_id`/MusicBrainz observation, matching that key exactly. A different
eligible identifier cannot relabel or repair the selected identity. Without an
eligible required label, loading fails closed.

Optional metadata representatives have no identifier-label status field. When no
eligible observed name remains, the loader omits that candidate before grouping
and limits. It does not turn an identifier into an artist name or recording title.
No serialized field, source fact, qualification, stable-ID selector, graph geometry,
default, schema or serving policy changes. Raw stable-ID selection and ambiguity
remain a separate boundary; this is not full metadata certification.

## Reproduction and evidence

Run from the repository root:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.test_public_model_repository tests.test_embed_source_eligibility \
  tests.test_embed_metadata_labels -q
PYTHONPATH="$PWD/src" .venv/bin/poe check
```

The tests use explicitly synthetic qualified contracts, not real-source music
qualification, human truth or model-quality claims. Minimal fixtures now declare
the provenance of their names and identifiers; independent sibling metadata
observations preserve allowed support. A full migrated-schema `EntityProjector`
integration test separates name-source custody from allowed qualification and
artist-genre evidence, exercises append-only suppression/release, and preserves
the source facts while an unavailable required label rejects loading. Query-only
loading, own permissions, every label kind, cache poisoning, omission before bounds,
canonical QID/MBID types and exact selected-key fallback are covered.

An independent Python raw-row oracle uses the frozen preceding PR94 fixture,
without importing these new tests. Before the fix, nine of twelve expected label
controls failed. All twelve pass after the fix. Ten valid cases retain identical
source facts, qualification-derived identities/references, pairs, hierarchy and
artifact declarations; surviving candidates retain their support and references.
Three complete payloads (no events, display-only event, release) are byte-identical.
Four active filesystem/network/subprocess/SQLite-write denial probes passed, with
zero forbidden operations, model fits, acquisitions or new cost. This tests source
use correctness, not numerical modeling or newly acquired independent evidence.

Local evidence paths and hashes are recorded in `results.json`. These are current
executor-local receipts, not checked-in inputs or future custody promises. The
synthetic tests remain reproducible without them; unavailable receipts must be
reported as unavailable. No research/NC source is promoted, and prior negative
research results and reserved Jamendo style fold4 remain unchanged.

Final full Poe check passed: 2,381 Python tests in 198.400 seconds (36 skips),
122 Node passes (44 skips), formatting, lint and types. All 29 focused tests pass;
Luna accepted the exact frozen runtime. Log: `/tmp/embed-label-full-check.log`.
Subsequent exact-head and merged-main CI state is recorded by this slice's PR. No model
was built, fitted, tuned, or evaluated for music quality.
