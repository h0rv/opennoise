# Direct source claims honor display and normalization vetoes

A real direct P136 claim remained visible through `artist_genres` after an active
`display` suppression of `artist_genre_evidence:1`: one membership remained one.
The same missing claim-reference boundary affected normalization. Schema13 closes
these functional source-use gaps in the shared direct-evidence views, before
pagination, membership materialization and shared-genre relationship queries.
Suppression now removes the affected claim; release restores it without changing
stored facts. Stored source facts and model parameters remain unchanged.

The migration preserves existing rights/permission and propagated-evidence
behavior. Direct claims additionally honor matching registered snapshot/artifact
vetoes and two exact claim-reference namespaces:

- `artist_genre_evidence:<id>` addresses that exact evidence row.
- `entity_claims:<id>` addresses a generic Wikidata genre relation only when its
  artist, provenance, policy, claim type/key and typed Wikidata target match the
  direct evidence. Default `target_kind="unresolved"` is supported because the
  ordinary projector creates P136 evidence from that form. Names are never joins.

`display` affects display only, `normalize` affects normalization only, and `all`
affects both. Train/export/embed/search-only vetoes do not acquire either meaning.
Bare numbers, unknown prefixes and noncanonical numeric suffixes are not cast or
guessed as one of the independent claim tables. Existing source/entity/provenance
vetoes remain in force. Missing inventory does not become a new eligibility
requirement, and there is no new license restriction. Nine repeated captures
remain generic observations, not extra canonical votes or fallback facts.

The scope is direct evidence. Existing propagated-evidence eligibility and
persisted derived-model invalidation are separate; this fix does not claim to
retract every previously persisted model when a claim reference is suppressed.
The prior negative research results and reserved Jamendo style fold4 are untouched.

## Real inputs and evidence

The retained CC0 source cohort remains433 artists,151 source genre QIDs,
278 canonical P136 facts and287 generic source observations. Ordinary direct
navigation has580 directed co-genre links across72 artists; this is source context,
not listener relevance or a recommendation-quality claim. The two source packs
retain native SPARQL bodies. Native core credits are verified portable canonical
projections, not original MusicBrainz HTTP responses. No source acquisition,
model fitting, costs, UI/default redesign or research-data promotion participates.

The first reproduction used a retained full-catalog copy, physical source SHA256
`1389ba19789e61e801f60304c1bda494423c6f2c418d4f645e9179f91cfc9764`.
Its before proof is `/workspace/direct-claim-display-20261020/reproduction.json`
(`a3a0416f49c4359c52c9de67661581469f6bcfdab8a9de832ab1c646e81ce8cc`).
The fixed ordinary API proof is `fixed.json`
(`5cb4d5159cdf211fd32a94d3dd70a4ec24878039edc1f3c8228d5ecbcfeba004`):
the suppressed membership becomes zero, normalization remains278 under the
use-specific display veto, and release restores the membership and278-row baseline.
All287 generic observations and278 stored canonical facts remain present.

An independent raw-source oracle and guarded ordinary migration/API audit used a
separate retained catalog, source SHA256
`e3f5d00d5e73ee347caf2c3b7dc280e51a0d03ecebc321861c8394bd6287e7cf`.
These are distinct physical SQLite files representing the same verified source
facts. The audit checked35 suppression/release controls, all278 canonical IDs,
all287 generic references, display/normalize results, baseline433-artist/151-genre
API pages and related links, and16 unchanged raw-source table digests. Five active
denial probes established original-data/cache, network, research-model and fitting
boundaries; actual execution made zero forbidden operations and zero model fits.

Proof `/workspace/direct-claim-suppression-20261020/preflight/proof.json` SHA256
`671ee02c63c06e30a5745d36478633fd34957b36f771a5648809cd56651a58f0`;
independent source-oracle SHA256
`d468919e2a5d499846851487425d6febab234f4b772eb0d6771eaedc96064d17`.
The observed22.63 seconds is one guarded bounded-cohort execution, not a universal
latency claim. No new index or policy framework is needed for this cohort.

Attribution: Wikidata contributors (CC0), and MusicBrainz contributors (core CC0).
Source/capture provenance and exact receipts remain recorded by the
[complete CC0 cultural-catalog recipe](../cc0-cultural-catalog-20261019/README.md).

## Reproduction and compatibility

Run `.venv/bin/poe sync` from the repository root. The complete retained-data
regression builds both ingestion orders and exercises suppression/release without
any network access or model fitting:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.serving.public.test_direct_claim_display \
  tests.test_candidate_public_projection tests.test_db -q
```

Fresh ordinary catalog builds use schema13. To reproduce an upgrade, copy an approved schema12 catalog to a
fresh local destination and call the ordinary database initializer:

```python
from pathlib import Path
import sqlite3
from contextlib import closing
from opennoise.db import Database

original = Path("/path/to/verified-schema12-catalog.sqlite")
copy = Path("/fresh/local/catalog.sqlite")
if copy.exists():
    raise ValueError("Fresh output required")
with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source:
    with closing(sqlite3.connect(copy)) as target:
        source.backup(target)
Database(copy).initialize()
```

Use the ordinary `PublicArtistNavigationStore` and `ArtistGenreRepository`
materializer against the upgraded copy; both consume the central views. Policy
events remain append-only and releases use the ordinary latest-event behavior.
The absolute evidence paths above describe executor-local custody, not repository
inputs or future availability. If absent, rebuild the verified retained cohort
using the linked recipe and exact allowed input bytes, or report a custody blocker.

Read-only sealed candidate/binding consumers explicitly support schema12 and13
and verify that database, replay receipt and binding agree. They neither migrate
nor rewrite sealed inputs. New writers record the actual input version; the old
schema12 serialization defaults remain unchanged. Current mutable database
initialization upgrades to13. Fresh derived serving copies use the current schema
and retain separate candidate/output custody rather than relabeling old receipts.

## Checks

Forty-five focused tests pass, including the full retained corpus in both ingestion
orders, every source boundary and use-specific release, ordinary materialization,
pagination/shared-genre joins, unresolved generic relations, sibling targets,
wrong typed claims, unbound identifiers, repeated capture isolation, legacy missing
inventory, schema12→13 upgrade and byte-identical read-only schema12 verification.
Final full Poe check passed:2,362 Python tests in200.153 seconds (36 skips),
122 Node passes (44 skips), formatting, lint and types. Luna independently passed
59 focused tests and accepted the migration/compatibility delta. Log:
`/tmp/direct-claim-full-check.log`. `results.json` and this slice’s PR record
subsequent exact-head/main CI and copied-catalog verification.
