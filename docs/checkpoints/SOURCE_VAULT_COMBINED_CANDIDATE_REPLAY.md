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

## 2026-09-21 controlled-run postmortem

One persistent-session run was allowed. It rehashed the 62-object receipt in
6.6 seconds and replayed all 54 Wikidata objects in 16.5 seconds. Its only
progress marker then entered the ListenBrainz stage. The operator stopped that
same session at a 15-minute cap after it stopped producing output; the tool
reported interrupt exit status 1, and the shell did not reach its exit-file
write. This is an operator timeout, not an application error receipt.

The retained staging database is
`/tmp/.phase3-combined-replay-20260921.sqlite.combined-s6skf54n/phase3-combined-replay-20260921.sqlite`.
It is 148,897,792 bytes with SHA-256
`f318b74175b74dca5d04752354a4618d02b537460f94b9bf4b5a3f970e5ddc6a`.
Read-only `PRAGMA integrity_check` returned `ok`; its schema version is 12.
It must not be promoted or treated as a candidate because the atomic publish
and replay receipt never occurred.

The database nevertheless records a completed aggregate transaction at
17:49:47Z: 30,469,708 listens, 993,589 artist-MBID listens, 79,673 artists,
40,782 user windows, 8,420,452 candidate pairs, 30,903 emitted pairs, and one
quarantine. Its recorded aggregation elapsed time is 323,475 ms with peak RSS
379,846,656 bytes. Two separately retained interrupted ListenBrainz staging
databases show the same 30,903 pairs and nearly identical profiles (324,332 ms
and 375,394,304-byte peak RSS). The expensive joint aggregation therefore
completed normally; the missing progress marker and publication occurred after
the aggregate transaction, most plausibly at the async runtime/session cleanup
boundary rather than in the aggregation algorithm.

Before another full scan, isolate that boundary with a fixture-sized test or a
local invocation that records milestones immediately after the awaited
multi-artifact call, joint-receipt comparison, SQLite checkpoint, and atomic
rename. In particular, test whether the `asyncio.run`/`asyncio.to_thread`
shutdown path returns after a completed aggregate. Do not retry the 1.5 GB
vault scan until that bounded diagnostic distinguishes runtime cleanup from
post-aggregate verification or publication.

The combined command now emits those four post-aggregate milestones. Its
fixture asserts the complete sequence through publication, so a future bounded
run can identify the first missing boundary without inferring it from a silent
staging database. The retained evidence also isolated the bridge itself: the
source-vault path now calls the verified-download persistence routine directly
instead of wrapping it in `asyncio.run` and `asyncio.to_thread`; a fixture
asserts that direct path returns after persistence. This does not change
aggregate parsing, SQLite contents, or candidate certification policy.

All 62 historical source-declaration hashes replay under the retained
pre-schema serialization; current provenance, timestamps, adapter identity,
and SQLite bytes still differ. A future receipt remains explicitly
uncertified and non-byte-identical.
