# Independent cultural enrichment, 2026-10-02

This bounded CC0 example extends exact Wikidata cultural-context observations
beyond the earlier electronic-focused benchmark. Its roster contains 40 extra
curated artists selected across jazz, classical, metal, folk, blues, country,
hip-hop, electronic, and regional scenes, plus the baseline Aphex Twin and Four
Tet. The roster was fixed without Every Noise memberships, coordinates, or
examples and without MusicBrainz genre associations. Its editorial coverage
intent is described in prose only; no genre-like selection labels enter the
machine-readable cohort or evidence projection.

The preserved discovery capture uses exact English labels and Wikidata P434 to
record each candidate's MusicBrainz UUID and Wikidata QID. Three candidates
(Youssou N'Dour, Kendrick Lamar, and Missy Elliott) had no exact English-label
P434 result in that response and were omitted. The claim acquisition then
queried 42 exact UUIDs for direct genre (P136), country of origin (P495), place
of formation (P740), and movement (P135) statements. The complete HTTP response
is retained, including three conflicting QID rows where Wikidata reuses a
requested MusicBrainz ID for an unrelated item. Projection replay accepts only
the individually curated QID for each requested UUID, accounts for those three
rows, and keeps the valid entity observations. Missing labels or claims do not
change identity matching.

The capture used two GET requests and 208,458 bytes across the P434 discovery
and exact-ID claim query (193,871 bytes for the exact-ID response and 14,587
bytes for discovery). The exact-ID query returned 42 intended matches and
210 direct claims. Every file is bound by a receipt. Offline replay rebuilds
the projection from the raw response, checks request coverage, identity,
property bounds, conflict accounting, and hashes. The whole pack is under 1 MB.

Reproduce the capture into a new directory with:

```sh
PYTHONPATH=src:scripts python scripts/acquire_independent_cultural_context.py \
  --acquire /tmp/independent-cultural-context
PYTHONPATH=src:scripts python scripts/acquire_independent_cultural_context.py \
  --verify data/examples/independent-cultural-context
```

The checked-in pack needs no network for replay. It supplies sparse cultural
metadata examples, not validated genre membership, musical similarity, or
complete artist coverage. Wikidata structured data is CC0; the receipt's scope
is limited to the retained Wikidata capture and direct projections.
