# MusicBrainz artist-credit refresh candidate

This is a local, non-serving candidate path for the 87 normalized releases in
`.cache/musicbrainz-catalog-expansion-v1/release-tracks.json`. It does not
open, create, or mutate a public or sealed database, and it retains no audio,
preview, artwork, genre, tag, or raw failed-response payload.

The refresher requests only exact release MusicBrainz IDs with the official
endpoint:

```text
GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits
```

It is sequential and enforces at least one second between upstream requests.
Its cache must be separate from the core hydration cache because the same
release endpoint has a different `inc` projection. Success entries retain only
the source endpoint, response SHA-256, release/recording IDs, ordered credit
members, exact artist MBIDs, source artist spelling, credited spelling, and
join phrase. No artist is matched or inferred from a name.

The candidate artifact is versioned as
`musicbrainz-artist-credit-refresh-candidate-v1`. It carries explicit release
and recording abstentions and endpoint failures. An offline replay reads only
that separate cache and makes zero upstream calls.

## 2026-09-21 bounded live attempt

After synthetic request and cache-only replay tests passed, one authorized
bounded live pass began against the exact ordered 87 release IDs. The default
network environment did not complete requests within the configured 30-second
client timeout. Two endpoint-level `request_failed` cache records were written,
with no response bodies and therefore no response hashes. The still-pending
third request was interrupted rather than turn the bounded 87-ID pass into a
long timeout run. No successful response or database was produced from the
partial attempt.

The two retained failure endpoints are:

- `release/018a6ac2-e74f-4874-9b42-7add11ba6ddf`
- `release/03118dd6-5252-489f-a934-4304a92972c1`

This is a network-environment blocker, not an assertion that either release
or its recordings lack credits. A later approved run can resume from the
failure cache only after explicitly choosing whether to retry cached failures.

An offline-only replay was still written at
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-refresh-candidate-v1.json`
with SHA-256
`c72206065ef56e83b4b47e7f1fe9a8b33e9aed246c219ab12faa94bdc9fa68ee`.
It binds all 87 exact normalized release IDs and has zero credits, 1,118
explicit abstentions (87 releases and 1,031 recordings), and 87 explicit
failures. This records cache absence and the two retained failures; it is not a
claim that MusicBrainz has no artist credits.

A single subsequent read-only diagnostic request using the identified client
outside the default sandbox returned HTTP 200 in 10.4 seconds for the first
failed release endpoint. Its 3,483-byte response had SHA-256
`fc28874178f2219374b1890a97fcf93f324d6b8a8d2182f0ca6e5cd8b6fa4452`.
This isolates the failed bounded pass to the default sandbox transport path,
rather than showing a MusicBrainz upstream outage. It was only a connectivity
check and did not restart the candidate refresh.

## 2026-09-21 escalated bounded run

One subsequently authorized run used a fresh cache directory,
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-refresh-escalated-v1`,
preserving the earlier two failed-response receipts. It completed with exit
status zero after exactly 87 fresh sequential requests, one for every selected
release ID, at the adapter's one-request-per-second floor. The fresh cache has
87 validated success entries and no failure entries.

The resulting local candidate is
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-refresh-candidate-v1-escalated.json`
with SHA-256
`f3e84ecf59d80aff6a99b74d4df039723c47f770cef8111055b6e562f1062b56`.
It contains 1,118 exact relations (87 releases and 1,031 recordings), zero
abstentions, zero failures, 1,344 ordered artist-credit members, and 87
distinct source-response hashes. It remains non-serving and does not materialize
any database.

An offline replay of that fresh cache made no upstream requests. Its artifact
SHA-256 is
`73506c90d1cd2c9858ee40371e17851710fd42fa282f10c1b4154c8cc12bd48a`;
apart from the deliberately different `cache_mode` value, its identity,
provenance, credit, abstention, and failure fields are identical to the live
candidate.

## Provenance v2 audit correction

The v1 `response_sha256` values are hashes of observed raw HTTP bytes, while
only a parsed safe payload was retained. They are therefore transport receipts,
not offline-verifiable release gates. V2 adds a required `projection_sha256`:
SHA-256 over UTF-8 JSON of `{"endpoint": endpoint, "payload": payload}` with
sorted keys, compact separators, and `ensure_ascii=False`. Cache reads recompute
and require this hash before a relation can be emitted; v1 entries are rejected
at the v2 relation boundary rather than silently reinterpreted.

The 87 successful v1 cache records were copied, without network access and
without altering the source directory, to
`artist-credit-refresh-escalated-v2`. The v2 offline artifact SHA is
`6454e5bfa4b4062e0bb7303629e0b5380af9997518ce386b896de69597496b7d`.
It retains 1,118 verified relations and zero abstentions or failures. A
tampered safe payload now fails replay with a projection SHA-256 mismatch.
