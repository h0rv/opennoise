# MusicBrainz catalog import

The catalog import uses the official MusicBrainz JSON dumps dated 2026-08-29.
It imports release group and recording metadata without importing the release
dump. The release dump is about 22.5 GB, so the laptop task does not download or
read it.

The release group archive is 1,187,679,180 bytes. Its verified SHA256 is
`a1a45e5f6f0f642e8a63455188cddc449bd248da68f1f5a1109a9183fd0a82fa`.
The recording archive is 33,572,648 bytes. Its verified SHA256 is
`680ab1cc3df8502d9635728a87eece24b367d6a142906eb01a4b24be7dd735d8`.
The manifest pins both values and stores each archive by its hash in an ignored
local vault.

## Bounded run

The release group job scanned all 4,486,319 records and selected source IDs
whose SHA256 starts with `00`. The exact partition is one part in 256. The job
accepted 17,484 records, quarantined 3 records, and found no duplicates. The
three rejected records had an artist credit join phrase longer than the declared
100 character input bound. The first run took 622.94 seconds.

The recording job scanned all 154,137 records and selected source IDs whose
SHA256 starts with `0`. The exact partition is one part in 16. The job accepted
9,359 records, quarantined no records, and found no duplicates. The first run
took 25.63 seconds.

The combined SQLite database uses 145 MiB. The two verified source objects use
about 1.2 GiB. SQLite returned `ok` from `PRAGMA integrity_check`, and
`PRAGMA foreign_key_check` returned no rows. Peak memory was not measured.

A replay reused each completed attempt and did not parse either archive again.
Each replay returned in about 0.013 seconds with the same counters.

## Stored catalog data

The bounded database contains 17,484 release groups, 9,359 recordings, 25,065
artists, and 704 genres. Exact MusicBrainz identifiers connect all three entity
kinds. The database also contains 640 ISRC identifiers.

Artist credits preserve order, credited names, and join phrases. The database
contains 22,180 credits, 26,643 ordered credit members, and 26,843 links from a
release group or recording to a credit. The projector creates an artist only
from an exact MusicBrainz artist ID. It never matches an artist by name.

Direct source evidence links 6,391 release groups to genres through 17,913
observations. It links 562 recordings to genres through 931 observations. The
pipeline does not infer a recording genre from an artist or release group.

## Rights and model use

MusicBrainz core metadata is CC0, while genre associations are supplementary
data under CC BY NC SA 3.0. The two sources therefore use the local research
policy. The policy permits local normalization, search, display, embedding, and
training. It denies metadata export, raw export, and redistribution.

Public model builds must continue to use sources whose policies permit export.
The model repository reads recording candidates only through the policy filtered
genre view, and it also requires active permission for embedding. Active source,
entity, and provenance suppressions remain effective.

## Content limits

The adapters parse only the fields used for catalog identity, names, dates,
types, exact artist credits, exact identifiers, and direct genre evidence. They
discard upstream duration and video fields. They do not expose cover, preview,
stream, media, acoustic feature, player, or audio fields.

Each expanded JSON record is capped at 2 MiB. Archive size, record count,
decompression ratio, nesting depth, timeout, and checkpoint interval are also
bounded. The parser streams the compressed archive and does not load the dump
into memory.
