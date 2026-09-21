# Phase 3 v3-to-static-map bridge audit

This is a read-only local audit. It creates no model, layout, serving database,
static export, preview, or public artifact, and does not modify the canonical
map or any historical input.

## Verified local v3 receipt

The completed local experimental projection is confined to
`/tmp/phase3-historical-v3-20260921`.

| Input or output | SHA-256 |
| --- | --- |
| v3 serving SQLite | `1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9` |
| v3 model JSON | `c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba` |
| v3 receipt JSON | `3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af` |
| receipt logical hash | `4ad4c3ba0d8347ed47a46009ec71ba461fdc898805848b3b95c9e3e5cfb83085` |
| model input logical hash | `1ce33b37b1c3de2c415d559cb8605166e51b7b81a0c704065df2cc450eba8a37` |
| model settings hash | `d27fa893459f5480e663253972191b5b90c3ab616cfaad49facc15c645ee22b0` |
| model logical hash | `a206196014c8f4374b8c2dda4d18d9217f4ff94a328baa1a308caf05f0477b12` |

Its model gate passed, but the receipt declares
`certified_database: false` and `byte_identical_database_replay: false`.
It remains a local experimental input, not an authorized public or static
release input.

## Current static-map boundary

The canonical semantic-layout artifact is
`.cache/semantic-map-layout-v3/artifact.json`, logical SHA-256
`469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`.
It is separately built from its sealed peer, hierarchy, and aggregate
co-listen inputs; it does not consume the v3 model JSON or serving SQLite.

Its immutable seed accounting is:

| Category | Count |
| --- | ---: |
| retained seed names | 6,291 |
| positioned map nodes | 2,945 |
| honest abstentions | 3,346 |

The v3 model has 603 Wikidata genre references. It is not a 6,291-seed map
and cannot replace, fill, or relabel the canonical coordinate or abstention
set.

## Checked seed bridge

The audit used the explicit v3 seed-reconciliation artifact, logical SHA-256
`ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0`,
instead of historical identifiers, coordinates, labels, memberships, or
neighbors.

| v3 Wikidata genre references | Count |
| --- | ---: |
| total | 603 |
| with one or more reconciliation candidates | 415 |
| with exactly one candidate | 347 |
| unique and non-ambiguous (`reconciled` or `public_only`) | 314 |
| unique, non-ambiguous, and already positioned | 305 |

Only the final 305 rows are eligible for a future local overlay candidate,
and only as links to existing canonical seed IDs. The 6,291-name universe,
2,945 positions, and 3,346 abstentions remain unchanged.

An independent case-folded display-name comparison found 290 of 603 v3 names
in the retained seed names, including 288 positioned names. This comparison
is diagnostic only: it is not an identity bridge and must not be used to add
or select map, model, artist, or public data.

## Artist boundary

The existing static discovery projection has 1,008 display-authorized artists
across 260 placed exact-label-bound genres. It uses direct catalog claims and
shared direct-genre peers, not artist coordinates. The local v3 model has
1,205 direct-profile artist references across 468 genres. It therefore lacks
a receipt-bound artist identity and display-authorization bridge to the
static discovery asset, and it is not an artist map.

## Next bounded task

Specify and test a local-only v3 overlay adapter contract. It must verify the
v3 receipt and all declared hashes, load the serving SQLite read-only, admit
only the 314 unique non-ambiguous reconciliation rows (and report the 305
already-positioned subset), preserve canonical seed coverage verbatim, and
emit no public/static output. A separate reviewed artist bridge is required
before any artist data can enter that candidate. Historical EveryNoise
construction remains outside this adapter's inputs.
