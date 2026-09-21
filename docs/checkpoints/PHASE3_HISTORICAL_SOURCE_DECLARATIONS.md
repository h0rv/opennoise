# Phase 3 historical source declarations

All 62 Phase 3 `source_manifest_sha256` values are reproducible without a raw
data scan. The release used the `DownloadSource` serialization before the later
`export_raw` and `redistribute` default fields existed. Those two fields made
the current declaration hash differ despite equivalent historical fields.

The historical Wikidata declarations are reconstructed from the exact release
snapshot, artifact digest, byte size, and the retained Phase 3 Wikidata
constructor. The seven ListenBrainz daily declarations come from the current
pinned declarations with the pre-schema serialization. The generated joint
declaration is reconstructed from those seven declarations and its sealed
snapshot and artifact values.

```sh
uv run python scripts/replay_source_vault.py verify-historical-declarations \
  --manifest config/releases/phase3-public-20260831/release-manifest.json \
  --source-manifest config/data_sources.toml \
  --replay-report /tmp/phase3-historical-declarations.json
```

On 2026-09-21 the command verified all 62 declarations against manifest SHA256
`795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232`.
This proves declaration identity only. It does not certify a rebuilt database
or make its SQLite bytes historical.
