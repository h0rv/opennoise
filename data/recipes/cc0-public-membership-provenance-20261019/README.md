# Source-qualified public membership exports

The old ordinary adapter exported all 40 real P136 claims after an `all` source suppression even though existing artist navigation correctly showed zero. Its raw `MIN` identifier CTEs and `genres.name` could also borrow restricted metadata after exact artist identity reuse. The v2 adapter selects each claim and each emitted identifier/name through their own CC0, public-domain, export-allowed provenance, snapshot and artifact chain. Source, provenance, entity, snapshot and artifact `all`/`export` suppressions apply before export. Optional aggregate inputs use the same source/snapshot/artifact eligibility boundary and retain their privacy thresholds.

Exact identities must be canonical, typed and unique in both directions. The existing production artist resolver checks historical generic aliases, conflicts and wrong kinds. Hidden, denied, unreceipted or suppressed identity observations can **veto** an unsafe join; they never supply exported values or custody. Ambiguous catalog rows require explicit reconciliation, not filtering one owner away. A deterministic qualified source name may be used; raw catalog defaults are never fallback names. If no qualified name exists, an authorized canonical genre ID supplies an explicit identity label.

Claim suppression references have an explicit v2 contract: `artist_genre_evidence:<positive-id>` addresses an exact evidence row; `entity_claims:<positive-id>` addresses a generic P136 relation linked by artist, provenance, policy, relation/key and exact target namespace/QID. Its optional target-kind spelling does not change that linkage. Bare numeric, unknown-namespace and noncanonical active `all`/`export` claim refs fail closed. No schema migration or guessed cross-table numeric identity is involved.

## Available real inputs and outcomes

The source database is a fresh SQLite backup of the merged [exact artist replay](../cc0-exact-artist-identity-20261019/README.md), preserving all 352 artists, 87 release groups and 1,031 recordings. Only inventory metadata was appended: the genuine retained independent Wikidata raw response and manifest were registered against their existing provenance. Claims and identities were unchanged. MusicBrainz custody remains verified portable core projections, **not retained original HTTP bodies**. Wikidata custody includes native SPARQL bytes replayed by the existing verifier. All inputs are retained CC0 metadata; no research-only source, new acquisition or model participates.

The fixed scope is all seven exact core/cultural artist overlaps, 40 P136 pairs and 35 genre QIDs, from 42 requested/matched cultural artists. The other 35 cultural identities are unjoined; 345 native artists have no observed P136 evidence. The ordinary CLI exports **40 rows, seven artists, 35 genres, 42 independently bound ID observations and one raw source artifact**. No qualified genre-name observation exists here: all 35 labels are authorized QIDs. This repairs an export boundary; it adds no musical relevance, inferred membership or listening recommendation claim.

An appended source `all` suppression keeps all 40 stored claims, makes navigation displayable claims zero, and causes the complete adapter CLI to reject without publishing any approved output directory. An independently guarded release restores 40 rows and the exact same model-input payload. Tests also cover independent metadata denial/revocation, authorized metadata artifacts, private conflicting identities, namespaced claim suppression, ambiguity, URI filenames, real WAL refusal and physical-byte pins. See [results.json](results.json) for all source, implementation, output and independent-evidence hashes.

## Reproduce offline

Use `.venv/bin/poe sync`, explicit `PYTHONPATH="$PWD/src"`, and the checked-in inputs from the exact artist recipe. First regenerate its fresh two-order catalog with the existing `scripts/replay_cc0_artist_identity.py` command. Copy `musicbrainz-first.sqlite` with SQLite backup into a **fresh** adapter input file; retain the original replay directory and its pins unchanged. Register the captured Wikidata artifact in that copied database as follows (replace only the two local example paths):

```python
from pathlib import Path
import hashlib
import sqlite3

original = Path(".cache/exact-artist-replay/musicbrainz-first.sqlite")
database = Path(".cache/export-v2-input.sqlite")
if database.exists():
    raise ValueError("fresh database copy required")
pack = Path("data/examples/independent-cultural-context")
raw = pack / "raw/batch-00.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
if sha(raw) != "df1cf4e12a947ff18df1a7bcfb1cfda68e8c30b17e197275f07d4b336f772f19":
    raise ValueError("retained raw source changed")
if (
    sha(pack / "manifest.json")
    != "62f5318c2a8404f88874a9e3558e485099b606f772a052873a010a848e14d7e2"
):
    raise ValueError("retained manifest changed")
with sqlite3.connect(original) as source, sqlite3.connect(database) as c:
    source.backup(c)
    sid, pid, snapshot, observed = c.execute(
        "SELECT DISTINCT p.source_id,p.policy_id,p.snapshot_ref,p.observed_at "
        "FROM provenance_records p JOIN data_sources s ON s.id=p.source_id "
        "WHERE s.source_key='wikidata_cultural_exact_artist'"
    ).fetchone()
    ss = c.execute(
        "INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,"
        "manifest_sha256,acquired_at,policy_id) VALUES(?,?,'single_artifact',?,?,?)",
        (sid, snapshot, sha(pack / "manifest.json"), observed, pid),
    ).lastrowid
    c.execute(
        "INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,"
        "byte_size,sha256,vault_key,policy_id) VALUES(?,'raw/batch-00.json',"
        "'Retained raw Wikidata response','application/json',?,?,?,?)",
        (ss, raw.stat().st_size, sha(raw), sha(raw), pid),
    )
```

Freeze the copied database's actual SHA256 externally, then invoke the existing adapter CLI with that pin and the checked recipe policy pin:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python scripts/adapt_public_artist_membership_input.py \
  --database .cache/export-v2-input.sqlite --database-sha256 <ACTUAL_SHA256> \
  --policy data/recipes/cc0-public-membership-provenance-20261019/policy.json \
  --policy-sha256 0b39262b6244edf1835ecb3c968aefa5ff4ccca108c71a319563a915f4d08f65 \
  --output .cache/export-v2-approved
```

`--output` requires external database/policy pins and a fresh directory; it atomically publishes `approved-input.json` and `receipt.json`. Historical `--approved-input`/`--receipt` spelling remains supported with exclusive fresh files and failure cleanup, without claiming atomic two-path publication. Inputs and outputs cannot alias; mixed modes fail before writes. The CLI caps CPU/wall at 120 seconds, address space at 1 GB, numerical threads at one and combined output at 32 MB. Database SHA256 must bind a checkpointed single file: existing WAL/SHM/journal sidecars are rejected, and reads use a resolved escaped immutable SQLite URI and a read transaction.

The current executor's input database pin is `a1b67cef…`, approved logical pin `e503282f…` and receipt logical pin `e76e443a…`. These are observations, not assumptions of future cache custody. Source packs and native projection files are checked in; SQLite builds and local audit artifacts are not. Rebuild them from those exact inputs if missing, or report the missing custody rather than fabricate receipts.

## Version transition and independent verification

The historical [v1 configuration](../../../config/public_artist_membership_adapter_v1.json) is unchanged. New certification uses [v2 configuration](../../../config/public_artist_membership_adapter_v2.json) or the explicitly scoped [recipe policy](policy.json). **Old v1 policies/receipts cannot be relabeled or re-certified as v2.** Rebuild approved input and receipt from an eligible source database; missing rights/provenance/inventory must be recovered through verified ingestion. Existing released public-artifact readers and the membership source-policy serialization are unchanged. Metadata selectors can admit explicit additional providers only within already declared direct source families. Unsupported providers are omitted; their names/IDs do not inherit claim eligibility.

The receipt binds selected claims and every used ID/name to its own source policy, snapshot, artifact and field/value. All used supported metadata artifacts also occur in the deduplicated public input artifact list. Receipt policy hashes cover those metadata bindings; normal replay recomputes the entire derivation against the exact physical database.

An independent stdlib SQL oracle, without production imports, matched all 40 native P136 pairs, 35 authorized QID labels, 42 metadata chains and every logical hash. The actual copied-input CLI passed five active denial probes covering Python/SQLite original-path reads, network, research models and fitting, with zero production forbidden operations. Independent suppression/release CLI runs rejected the suppressed catalog without output and restored the exact model input after release. Final proof/oracle/suppression pins are recorded in the results. Luna's final runtime review was clear; focused checks passed with one unavailable historical-release skip. The clean final full check and exact-head/main CI outcomes are tracked by the PR; no future success is assumed here.

Attribution: MusicBrainz and Wikidata contributors. [MusicBrainz core data rights](https://musicbrainz.org/doc/About/Data_License), [Wikidata structured-data rights](https://www.wikidata.org/wiki/Wikidata:Licensing). No UI, defaults, deployment, research promotion, new acquisition or external cost ($0). Prior negative Jamendo instrument results and the reserved fold-4 style targets remain unchanged.
