# Broader native Wikidata evidence

The new separately named CC0 entity pack resolves **9,992 exact artist identities and 18,750 direct P136 statements covering 1,003 native genre QIDs**. All 1,003 have a retained native label; 998 have an English label. These are source assertions, not calibrated memberships or independent musical judgments. The factual counts, source and licensing hashes, request outcomes, and scope limits are in [the evidence JSON](WIKIDATA_ENTITY_EVIDENCE_20261003.json).

The source-only roster was frozen before the new hydration requests. It uses the retained capped native Wikidata scan, canonical P434 UUIDs, the complete separately verified CC0 MusicBrainz identity projection, unambiguous crosswalks, and SHA256 UUID selection. Exactly 10,000 artists were selected. Eight entities failed the unique exact P434 crosswalk and remain explicit quarantines; no name matching substitutes for an identifier. Each admitted projection retains its native statement ID/rank/value/qualifiers and a raw body hash/path. Full native references remain in those original raw bodies rather than being duplicated into the compact projection.

All 200 artist and 91 context API requests returned HTTP 200, with **307,604,448 original response bytes** preserved. Every request retains its actual start/end UTC time, endpoint, parameters, status, complete-body flag, and body hash/size. Context retrieval preserves native labels in 16 requested languages; it does not assert or infer a genre hierarchy. There are 4,549 distinct context QIDs and no context QIDs omitted by the 5,000 cap. A fresh official Wikidata licensing page was captured with HTTP 200, its actual time/bytes/hash, and the CC0 statement. That HTML is licensing proof and is not a model input. The previous scan's manifest, receipt, literal query and response hash are separately bound; no new transport claim is made for that reused scan.

The independently computed source coverage includes 4,787 artists with citizenship statements, 4,424 with origin statements, 2,617 with formation places, 4,464 with birthplaces, 3,405 with language-use assertions, 3,042 with formation dates and 4,767 with birthdates. These facts remain separately named. Citizenship is not regional music membership, language use is not recording language, and birth/formation dates are not a musical era classification. Native labels in multiple requested languages exist for 9,619 admitted artists.

## Reproduction and verification

The finished pack is `/dev/shm/opennoise-wikidata-entities-10000-v3`. Its projection SHA256 is `89b86d4419741856285184539175c57a4aec59c60790a4ad16e3b1c99c84fcd1`; receipt SHA256 is `7b2d96e868562614531a7620d89f72a4cdbb9398eb8fc3d70c0f4f149099e558`. It contains 587 files totaling 367,225,562 bytes. Source/licensing custody is preserved separately under `/dev/shm/opennoise-licensed-evidence-work/source-custody` and bound in the evidence JSON.

Run the offline verifier directly, without installing dependencies or fetching network data:

```sh
PYTHONPATH=src .venv/bin/python scripts/acquire_wikidata_entity_evidence.py \
  --verify --output /path/to/opennoise-wikidata-entities-10000-v3 \
  --core /path/to/musicbrainz-core-artist-identities-20261002-v1
```

Verification re-streams and hashes the complete core identity source, replays selection from the exact captured scan, derives the complete capture plan, verifies the approved closed file set and response/status admission, and reconstructs the projection from native bytes. Changed self-rehashed projections, unrelated added files, arbitrary raw paths, invalid time order, malformed UUIDs, ambiguous crosswalks and changed request selection are rejected. Eleven focused tests pass, together with Ruff formatting/lint and type checking. A separate parser independently confirmed the native counts and crosswalk denominator.

The first two finishing attempts encountered real memory limits while retaining full entity objects. Their captures remain preserved, including interrupted context bodies whose missing transport ledgers are not invented. The final pack uses hardlinks to the successful original artist captures and fresh context captures. Streaming projection/JSON hashing and raw-reference pointers kept its later observed process memory around 180 MB. A later verifier refactor preserved every canonical projection byte while replaying each fifty-entity batch incrementally: the actual complete core/source/roster/ledger/projection replay passed in 26.84 seconds with measured peak RSS of 74,852 KiB. It does not drop artist outcomes or weaken custody; a canonical-byte equality regression test covers the streamed behavior. Neither earlier source pack nor any original recovery artifact was overwritten.

## Limits and next work

The reused source query contains 20,001 raw bindings and 19,998 valid bindings after quarantine. It is capped, unordered source discovery that initially exposes 91 native genre QIDs; it is not a representative worldwide census. The frozen v3 cohort retains its originally declared cap on valid parsed statements. Its query-overflow sentinel was not among the 10,000 selected artists. Future acquisitions now cap the first 20,000 raw bindings before quarantine; v3 was replayed under its actual original plan rather than resampled or relabeled.

Broader native P136 statements obtained during entity hydration expose more genres than the initial query, but native label availability does not establish subgenre or microgenre calibration. The five absent English labels remain absent. No Every Noise labels, internal Spotify resource, commercial-only or noncommercial supplementary dataset, inferred FMA artist identity, or fabricated listener judgment enters this pack. Additional source-defined discovery cohorts, recording-level exact bridges, permitted listening evidence and independent musical review remain necessary to assess the full target.
