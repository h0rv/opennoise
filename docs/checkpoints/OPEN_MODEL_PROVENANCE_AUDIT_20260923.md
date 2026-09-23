# Open model provenance audit

This audit checks the release bytes in `dist`, the current semantic layout input, and the local Phase 3 v3 overlay. It does not deploy or rebuild any artifact.

Every Noise may supply retained genre names and stable IDs. Its coordinates, artist memberships, neighbors, and other similarity output must be evaluation-only.

## Results

| Artifact | Result | Evidence |
| --- | --- | --- |
| Certified static atlas in `dist` | Pass for direct historical value flow | The release manifest, promotion receipt, layout bytes, atlas bytes, and discovery bytes agree on their pinned hashes. The atlas and discovery JSON have no historical field or string. |
| Static discovery v2 | Pass for direct historical value flow | It contains only direct catalog observations from the eight `wikidata_phase3_artists_*` source partitions. The public database has zero historical artist, relation, and track observation rows. |
| `semantic-map-layout-v3` construction | Pass at its direct input boundary, with indirect upstream attestation | The builder reads the peer index, peer manifold, hierarchy artifact, and co-listen artifact and cache. It rejects a hierarchy or co-listen artifact that declares historical construction input. The layout records `historical_inputs_read_for_construction: false`. |
| Local Phase 3 v3 overlay | No direct historical value flow found. End-to-end names-only provenance is unproven. | The overlay is local-only and does not write a layout or static payload. It reads only canonical seed IDs and placed state from the layout. Its separate historical candidate binding covers the Phase 3 Wikidata and ListenBrainz declaration replay, not Every Noise. The pinned upstream candidate construction is outside this audit's executable release path. |

## Static release chain

`poe build` runs `scripts/certify_static_pages.py`. The script reads the sealed layout and public database, replays the public discovery v2 promotion, exports a temporary directory, runs browser certification, and then installs `dist`. The deploy mode also pins the layout and database paths and SHA-256 values. See `scripts/certify_static_pages.py:51`, `scripts/certify_static_pages.py:111`, and `scripts/certify_static_pages.py:275`.

| Item | SHA-256 |
| --- | --- |
| Semantic layout file | `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972` |
| Semantic layout logical output | `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38` |
| Semantic atlas asset | `730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac` |
| Static discovery v2 asset | `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c` |

The semantic exporter projects coordinates, names, hierarchy IDs, labels, and structural edges from the verified layout. See `src/opennoise/deployment/semantic_pages.py:562`. It does not open an Every Noise source. The v2 discovery exporter pins the exact atlas, public database, and reviewed direct-discovery chain. See `src/opennoise/deployment/public_static_discovery_v2.py:177` and `src/opennoise/deployment/public_static_discovery_v2.py:254`. Its base query selects only `direct_source_claim` rows with active export and display permission. See `src/opennoise/deployment/static_discovery.py:267`.

## Semantic layout chain

The layout builder reads names and peer scores from the peer index, then combines peer, hierarchy, and co-listen structural edges. See `src/opennoise/ml/semantic_layout/builder.py:149` and `src/opennoise/ml/semantic_layout/builder.py:1116`. The hierarchy and co-listen loaders reject artifacts that declare historical construction input. See `src/opennoise/ml/semantic_layout/builder.py:183` and `src/opennoise/ml/semantic_layout/builder.py:219`.

The Every Noise name boundary is implemented in `src/opennoise/taxonomy/seeds/universe.py:167`. It reads only the source ID, content hash, item ID, external ID, and name. The test at `tests/taxonomy/seeds/test_universe.py:100` changes coordinates, representative data, memberships, neighbors, and audio-shaped fields, then requires an unchanged result.

This is not a complete byte-level proof. The seed artifact still records the full Every Noise source content hash, and the consumed peer index records a path and hash for a separate historical evaluation receipt in its metadata. The layout builder does not use that receipt as a feature, but its current contract does not require a field-level transitive provenance manifest for every upstream artifact.

## Local Phase 3 v3 overlay

The local overlay sets `export_allowed: false`, `static_output_written: false`, and `artist_integration_included: false`. See `src/opennoise/serving/local/v3_map_overlay.py:131`. It states that it reads only canonical seed IDs and placed or unplaced state, not coordinates, artist profiles, historical artifacts, or a static export destination. See `src/opennoise/serving/local/v3_map_overlay.py:279`.

Its `historical_candidate_binding_sha256` is easy to misread. It binds the local candidate to the historical declaration replay for 62 Phase 3 source objects. Those objects are Wikidata and ListenBrainz inputs, as enforced in `src/opennoise/pipeline/historical_candidate_binding.py:145` and `src/opennoise/pipeline/historical_candidate_binding.py:239`. It is not an Every Noise feature input.

The terminal v3 evaluator fixes and verifies the candidate before it opens the held historical signal. See `src/opennoise/checkpoints/v3_terminal_historical_evaluation.py:174`. It also marks the signal evaluation-only. However, its own source says that its historical token scan cannot prove how upstream sources were collected. See `src/opennoise/checkpoints/v3_terminal_historical_evaluation.py:354`.

## Required gate before any local v3 promotion

Add a transitive construction receipt for each promoted artifact. It should list every source artifact and the allowed fields read from it. For Every Noise, the only construction input should be a verified name and identity projection with the stable item ID, external ID, and genre name. The raw snapshot may remain isolated for evaluation. The promotion gate should reject downstream consumption of its coordinates, artist memberships, neighbor or similarity rows, representative fields, ranks, and every other historical output. It should verify the field list from the sealed inputs, rather than relying only on Boolean attestations or the absence of historical tokens in the final model.

`scripts/verify_names_only_construction_boundary.py` now checks the current H2 name projection against the peer index and semantic layout inventory. It reads only stable IDs and names from the peer index and layout. It proves that the current local layout uses the same 6,291 seed identities and names as the typed projection. It does not prove that the upstream peer-edge producer used no forbidden Every Noise fields. A transitive producer receipt remains required before promotion.

## Checks run

The focused name-boundary, semantic-layout, and static-discovery-v2 tests passed. The checked release hashes also replayed against `dist` and the promotion receipt. The test process emitted existing SQLite resource warnings after success. No deployment ran.
