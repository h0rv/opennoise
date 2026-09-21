# Combined source-vault candidate replay

The `candidate-combined-database` command creates one fresh, local SQLite
candidate from the Phase 3 vault. It rehashes every manifest-bound raw object
before ingestion, then runs the 54 Wikidata SPARQL objects followed by the
seven ListenBrainz daily objects. The retained ListenBrainz joint receipt is
also rehashed and the newly generated joint artifact must match it exactly.

The command accepts only a report bound to the exact release manifest. It
writes both projector outputs to a new staging database and atomically moves
that database to a candidate path which did not exist when replay began. It
does not write the sealed vault, sealed cache, or public database.

```sh
uv run python scripts/replay_source_vault.py candidate-combined-database \
  --manifest .worktrees/phase3-public-evidence/config/releases/phase3-public-20260831/release-manifest.json \
  --report /tmp/phase3-source-vault-replay-report.json \
  --vault .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --source-manifest config/data_sources.toml \
  --candidate-database /tmp/phase3-combined-replay.sqlite \
  --replay-report /tmp/phase3-combined-replay-report.json
```

On 2026-09-21, the prerequisite verifier rehashed all 62 retained objects:
1,541,940,352 bytes, bound to manifest SHA256
`795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232`.
The 62 objects comprise 54 Wikidata objects, seven ListenBrainz daily objects,
and the sealed generated ListenBrainz joint artifact.

The interactive execution environment ended the first full combined scan
before it could publish its `/tmp` candidate receipt. Its incomplete temporary
staging directory was removed; no sealed or public database was changed. Run
the command above on a persistent local worker to obtain the final candidate
receipt. That receipt remains explicitly uncertified and non-byte-identical.
All 62 historical source-declaration hashes now replay under the retained
pre-schema serialization; current provenance, timestamps, adapter identity,
and SQLite bytes still differ.
