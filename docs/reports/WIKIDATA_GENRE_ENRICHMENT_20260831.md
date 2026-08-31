# Wikidata public genre enrichment for 2026-08-31

The checked-in query contains the exact 127 Wikidata genre QIDs present in the first public
model input catalog. QIDs select identity. Labels and aliases never select, merge, or match an
entity. The query retrieves labels and aliases in ten declared languages and direct P279
statements with rank, statement identity, reference nodes, and cited URLs.

```sh
uv run poe enrich-wikidata-public-genres -- \
  --database data/public-catalog.sqlite \
  --vault data/vault
```

The 2026-08-31 official query response had these immutable identities:

```text
query_sha256     476fe2d0f55bb70a8181fbfa599e087e4113c8cec7de942b7c1c3a41bfead0fc
artifact_sha256  6e25bf1c044594aecfb9a7ed15838ef6bb62c8d7cbe2d3daf68ec920c6c8397f
artifact_bytes   1064809
```

The shared pipeline accepted all 127 subjects, quarantined none, and completed in 0.277 seconds.
All subjects were existing exact-QID entities. It stored 2,910 name claims, including 1,823
aliases, and replaced all 127 QID canonical placeholders with source-supported labels. There were
no unresolved input QIDs. Parent targets added 41 still-unenriched placeholders outside the model
input boundary.

The response produced 174 direct P279 edges. Of those, 101 have both endpoints in the existing
P136 genre set, 80 retain at least one source reference, none are self edges, and none participate
in a directed cycle. The enrichment policy is CC0/public domain and allows normalization, local
search, display, embedding, training, and metadata export. The enriched SQLite copy was 3,989,504
bytes.

Rebuilding against the same ListenBrainz evidence produced
`/tmp/musix-release-public-model-enriched.json`. It contains 127 named genre identities and zero
QID placeholder names. Its logical output SHA256 is
`efc50be59ca4562481a975a0cdcf7ec898484cff48eba946d0a6a3453a6976bb`; its complete file SHA256 is
`86960bf72ee2016f67e23ae98959bbd3c899bc6cc003102b65b439089700e4ec`. The model build took 2.265
seconds and reported peak RSS of 312,930,304 bytes. This enrichment does not contain audio.
