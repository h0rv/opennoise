# Exact CC0 artist identity joins

An ordinary ingestion-order bug split MusicBrainz recording-credit artists from Wikidata genre evidence. With MusicBrainz first, the old generic entity projector looked up only QID, created a second artist and attached the same P434 MBID to it. Other artist paths selected the first matching identifier row. This patch resolves all typed exact artist identifiers together across the generic entity projector, native artist projector, recording-credit projector and retained native-credit materializer.

The shared resolver is read-only. One canonical MBID, consistent QID and a unique artist entity can be reused; repeated source observations on that entity remain legitimate. Ambiguous entities, wrong-kind or foreign-kind typed identifiers, multiple MBIDs and conflicting QIDs fail before artist mutation or roll back in the owning ordinary transaction. Names and unrelated provider IDs are not matching signals. Existing split entities are not merged, redirected or silently repaired; they need separate explicit reconciliation. Each new identifier, name and claim retains its independent source provenance/policy. The native artist dump’s historical `source_id` in the exact `musicbrainz` namespace remains preserved and accepts only a canonical lowercase UUID. New artist observations also append a typed artist MBID with the same provenance. Legacy and typed rows participate jointly in ambiguity/conflict checks; a generic identifier resolving to a wrong-kind entity fails closed.

## Real retained sources and result

The checked-in MusicBrainz portable source `13921b94…` contains 87 verified safe cached projections, native core hydration and exact ordered release/recording credits. Its preserved historical response hashes do **not** imply original HTTP bodies are retained. The source remains CC0 core metadata only: no tags, genres, media or inferred release-group credits. Its original catalog is physically pinned at `100af6ec…` (3,072,000 bytes). The replay uses existing validated hydration/credit materializers, preserving release-level credits at release level.

The independent cultural pack is checked-in Wikidata CC0 data with native raw SPARQL bodies. All 42 requested artists matched that pack; exactly seven match one of the core catalog's 352 artist MBIDs. All 40 artist/P136 pairs across 35 genre QIDs replay from raw `batch-00.json` SHA256 `df1cf4e12a947ff18df1a7bcfb1cfda68e8c30b17e197275f07d4b336f772f19`. The other 35 cultural identities remain explicitly unjoined. No names or fuzzy matches enter this boundary.

A clearly derived common `EntityProjection` bridge registers a **separate Wikidata CC0 policy/source** and binds its provenance to the raw response hash and original observation time. Transformed common projections are never labeled original upstream bytes. The truthy capture did not retain ranks, statement IDs or references: stored relation rank is explicitly `null`, statement ID is absent and references empty. `RelationClaim` now accepts explicit null while retaining its old default for compatibility; `ValueClaim` and existing Wikidata parsing are unchanged. Supplied preferred ranks still round-trip.

| Build order | Artists | Release groups | Recordings | P136 pairs | Credited entities joining P136 |
|---|---:|---:|---:|---:|---:|
| Before: MusicBrainz then Wikidata | 359 | 87 | 1,031 | 40 | 0 |
| Before: Wikidata then MusicBrainz | 352 | 87 | 1,031 | 40 | 87 |
| Fixed: either order | 352 | 87 | 1,031 | 40 | 87 |

The pre-fix in-memory transaction observation binds the unmodified main `c46d2dc` projector SHA `478cad74…`: seven MBIDs each resolved to two artists in the failing order. The diagnostic used then-current common projection defaults; it is identity-only evidence, not a claim about unobserved source ranks or a published catalog. An initial shared-editable-import setup error was explicitly marked invalid locally; only the subsequent hard-guarded root-main observation is included in [results.json](results.json).

The fixed builds have identical normalized native-ID/claim/ordered-credit graph SHA256 `b726a1c3094b1b5cb77621eb8f465095624a715354d568710679e42ad01cc038`. SQL surrogate IDs, insertion order, bookkeeping times and physical database bytes may differ. Existing display-policy-filtered artist navigation returns four directed shared-direct-genre edges (two unordered pairs), preserving all 352 query artists. Only seven have observed P136 evidence; 345 lack it. These are transparent source metadata relationships, **not music recommendations, artist membership truth or listener relevance**. The patch does not construct a hierarchy or infer genres from native credits.

## Offline reproduction

From this checkout, first run `.venv/bin/poe sync`, then:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python scripts/replay_cc0_artist_identity.py \
  --core-source data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256/13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba.json \
  --core-source-sha256 13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba \
  --cultural-pack data/examples/independent-cultural-context \
  --cultural-receipt-sha256 df9763aef5b3f5801cc9ef999ecd34b24b97c588dc25679a2adaf8432461cfa5 \
  --output .cache/cc0-exact-artist-identity-reproduction
```

The output must be fresh. It contains `musicbrainz-first.sqlite`, `wikidata-first.sqlite` and `report.json`. Sources may be copied/relocated with identical pins; source symlinks, changed raw bodies, mismatched pins and overlapping/existing outputs fail closed. The CLI bounds CPU/wall to 120 seconds, address space to 1 GB, numerical threads to one, inputs to 2 MB per declared source pack and combined outputs to 32 MB. It acquires nothing and does not fit models. Use explicit `PYTHONPATH` to avoid a shared editable environment importing a different worktree. All paths in local evidence are current-executor observations, not assumed future cache custody.

The earlier reviewed nullable-rank build at `.cache/cc0-exact-artist-identity-20261019-final` took 4.668 seconds with Linux child peak RSS 92,028 KiB. This single execution is engineering evidence, not a universal latency claim. The final legacy-compatible replay at `.cache/cc0-exact-artist-identity-20261019-legacy-final` retained the same normalized graph; it was not separately timed. Its physical database/report pins and source/helper hashes appear in [results.json](results.json).

## Independent checks and limits

The independent raw-source/core oracle reconstructed every retained safe projection and all 1,118 native credit relations. Across the two producer and two relocated databases it matched **5,376 ordered credit tuples and 160 P136 pairs**, all seven QID/MBID joins, source-policy/raw-hash custody, complete 352/87/1,031 counts, the 87 credit joins and every artist's existing navigation count. The guarded actual copied-input CLI denied original entire data/cache trees, actual research-model paths/imports, network and supervised fit calls. Four active denial probes passed, production attempted zero forbidden operations and the normalized graph reproduced exactly. Physical SQLite bytes are not claimed identical across runs. Final comparison/proof hashes are recorded in the checked results.

The first full check exposed three native dump pipeline failures: that adapter emits historical `source_id`, which the initial typed-only resolver rejected. Strict legacy artist compatibility now preserves those observations and adds typed aliases; 28 focused identity, real-source and actual source-pipeline tests pass. Luna’s corrected runtime review is clear and independently reran 27 focused tests before the final additional conflict regression. The corrected full check is in progress. The complete final check and exact-head/main CI outcomes are tracked by the PR, with no preemptive success claim here. Only this production identity boundary changed: prior negative Jamendo instrument results, reserved fold-4 style labels, research-only licenses and serving defaults remain unchanged. The separate export-adapter suppression/metadata-eligibility gap is a next slice, not silently addressed here.

Attribution: MusicBrainz and Wikidata contributors. See [MusicBrainz core data license](https://musicbrainz.org/doc/About/Data_License) and [Wikidata structured-data licensing](https://www.wikidata.org/wiki/Wikidata:Licensing). The code and replay add no acquisition or external cost ($0).
