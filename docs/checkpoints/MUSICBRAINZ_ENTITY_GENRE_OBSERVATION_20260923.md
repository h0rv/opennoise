# MusicBrainz entity genre observation checkpoint

The new `musicbrainz-entity-genre-observation-v1` adapter is local research
only. It creates native observations for recordings, releases, and release
groups. It does not read artist credits, and every report hard-codes false for
serving, export, and artist membership propagation.

The bounded source capture is
`musicbrainz_ws2_entity_genre_research_20260923`, with local capture label
`20260923-local-entity-genre-query-001`. The label is not an official
MusicBrainz database snapshot, archive checksum, or proof of upstream
provenance. Each receipt pins a locally retained response byte sequence to its
exact request URL and SHA-256 value. The exact receipts are tracked as
`BOUNDED_ENTITY_GENRE_RECEIPTS` in the adapter. The raw responses remain in
the ignored local cache at `.cache/musicbrainz-entity-genre-observation-v1`.

| Entity kind | MBID | Response SHA-256 |
| --- | --- | --- |
| Recording | `00526a18-e31d-4b1f-bc6a-c6c7e318694d` | `255555b3b19de92d58e286d1816c773de82d05a8a1f0ed1dbee1809e759c8818` |
| Recording | `0065d575-27e6-4151-a489-4ecc4afb9974` | `206926c81e0f0517c0f238573f54d058d505e912b43968f268293c5679229cd9` |
| Recording | `0078b7fc-f0cd-4496-ad71-0235f955fa3b` | `d4081e97cfe0b812e34a8cd7530c06982d819b2ed0b80ed5d85d086b5870f0f8` |
| Recording | `008d0bdd-e3e1-469a-9531-2cb5ef8eb109` | `7cdc71c5e932b7730f59cf013b45aa0050ed7b65c0c86c6f1e7402c68e0018a1` |
| Release | `018a6ac2-e74f-4874-9b42-7add11ba6ddf` | `c3382e3557824db78b6cbcbe084919a8f37eb9c2abf1fa7652c0c06ca7c56cfa` |
| Release | `03118dd6-5252-489f-a934-4304a92972c1` | `224cc8fcfb4dbbebccbccd08af735e5de8350c6e73ea53ccceb1843a6c12f934` |
| Release | `03288a74-b855-4274-a5ec-e48e72d6451b` | `be018bcfd894f8a693ba8eb0941edb98bb6c6b21950516a14db00d7026e2d37d` |
| Release group | `005909de-978b-3450-a820-c89b7dae787a` | `62324163ec202cb59b5f2b27e215a6848836d75c41865bea80ddfda8dfcf5015` |
| Release group | `02adb8a7-496c-3a9a-a324-662df73fdba5` | `645e49770763e2ae9c41bb676eecd63da2d5ebcb4a60a2c43e465814bbc0e6b5` |
| Release group | `04de5d0b-1e38-4890-93a3-34bc5fdda4dc` | `2ff0fb21faebc332c2d2e703cb21516692192f70d168af022fe3b3f14616396d` |

The capture used these selected catalog MBIDs and MusicBrainz WS/2 JSON entity
endpoints. Recording and release-group requests used `inc=genres+tags`.
Release requests used `inc=genres+tags+release-groups`, so each release fact
retains its exact parent group. The following command was run once for each
selected entity, sequentially, with the descriptive User-Agent shown and at
least 1.1 seconds between completed requests. The ten final response bytes
replayed to a report with 18 proper-genre observations and 56 positive-count
tag observations. Its logical SHA-256 is
`1ced27b9349efe6276890beb871bf447b66bd86269476925895dcdc0ab03d3bd`.

```sh
curl --fail --silent --show-error --location \
  --user-agent 'opennoise/0.1 (local-research@example.invalid)' \
  'https://musicbrainz.org/ws/2/KIND/MBID?fmt=json&inc=genres%2Btags' \
  -o .cache/musicbrainz-entity-genre-observation-v1/responses/KIND-MBID.json
sleep 1.1
```

For a release, replace the final query value with
`genres%2Btags%2Brelease-groups`. `KIND` is `release-group` for a release
group. The table supplies every exact `KIND` and `MBID`, and the adapter
constant supplies the exact final URLs. The rate limit was applied to the ten
final retained responses. Three preliminary release responses without
`release-groups` were discarded because they did not preserve a required parent
release-group ID.

Run `./.venv/bin/python scripts/build_musicbrainz_entity_genre_observation.py`
only after restoring the ten response files at their listed paths. The script
checks every response against the tracked receipt before parsing, creates only
`.cache/musicbrainz-entity-genre-observation-v1/report.json`, and refuses an
existing target, a symlink target, or a target outside its cache root.

The bounded report is a source observation sample. It does not measure source
coverage, rank labels, label artists, or turn a release-group observation into
a recording or release fact.
