# Catalog lineage restore

The taxonomy artifact `45eea…` is bound to public catalog hash
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.
Do not point it at a later hydrated catalog. Restore the sealed snapshot to a
new path, verify it, and pass that path explicitly to taxonomy expansion.

```bash
uv run python scripts/restore_catalog_snapshot.py \
  --source <retained-sealed-public-catalog.sqlite> \
  --destination .cache/catalog-snapshots/sha256/240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc.sqlite \
  --expected-taxonomy-catalog-sha256 240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc \
  --receipt .cache/catalog-snapshots/sha256/240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc.restore-receipt.json
```

The command checks the source before writing, copies through a sibling
temporary file, verifies the destination hash, then runs SQLite integrity and
foreign-key checks. The receipt records source and destination paths, hashes,
byte size, and expected taxonomy catalog hash.

The restored snapshot generated public taxonomy expansion logical hash
`e1a7d82a7c15008f5f7f0b0afff62a14d48ed284212b3f2dd0b91ff164133271` and
the full evidence frontier logical hash
`8b17de7f4ad31ee8f49b1e36b006ff5f35e32510ab26533943d751ff5f775194`.
