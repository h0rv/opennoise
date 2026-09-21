# Independent gold source audit

## Result

No independent public source is ready to produce an exact artist and genre
gold set for the current model. The Free Music Archive (FMA) metadata is a
good independent candidate, but it has its own artist and genre identifiers.
The official description does not provide MusicBrainz artist identifiers or
OpenNoise genre identifiers. A download of the 342 MiB archive would not
close this join gap, so this audit did not download it.

The existing gold workflow therefore remains blocked from production use. The
checked in fixture is synthetic, and the existing MusicBrainz, Wikidata, and
ListenBrainz inputs are excluded by the gold policy because they are used by
construction or are derived from construction inputs.

## Evidence checked

The repository describes FMA as a separate historical metadata source in
[`DATA_SOURCE_RESEARCH.md`](../ingest/DATA_SOURCE_RESEARCH.md). The official
FMA repository says that `tracks.csv` has track IDs, titles, artist fields,
genres, tags, and play counts for 106,574 tracks. It says that `genres.csv`
has 163 genre IDs, names, and parent IDs. It does not list a MusicBrainz ID
field in either table.

The FMA creation code confirms that the archive is built from FMA API
`track_id`, `album_id`, and `artist_id` values. Its artist download uses the
FMA `artist_id` range. The code does not add a MusicBrainz crosswalk.

Sources:

- [FMA README](https://github.com/mdeff/fma#data)
- [FMA metadata creation code](https://github.com/mdeff/fma/blob/master/creation.py)
- [FMA API helper](https://github.com/mdeff/fma/blob/master/utils.py)
- [FMA metadata archive](https://os.unil.cloud.switch.ch/fma/fma_metadata.zip)

The local model uses MusicBrainz artist UUIDs, as shown by the artist ID type
and the public membership evaluator. The local taxonomy also uses source
specific genre IDs. There is no FMA adapter, FMA snapshot, or reviewed FMA
artist or genre bridge in the repository.

## Exact join assessment

The FMA labels are usable at the FMA identity level. A track row can be
grouped by its exact FMA `artist_id`, and its exact FMA genre IDs can be
retained with the track row hash. This uses metadata only and does not require
audio.

The result cannot yet be joined to the model exactly. Two independent bridges
are missing:

1. An FMA artist ID to a MusicBrainz artist UUID bridge is missing. FMA names,
   URLs, or title and artist text must not be used as an automatic join.
2. An FMA genre ID to the model's genre ID bridge is missing. A same name
   comparison is also not an exact genre join, because FMA has its own parent
   hierarchy and labels.

A human reviewed bridge could make a bounded study possible, but it must retain
the two source IDs, the evidence URL or record used for the decision, the
reviewer decision, and hashes for the source records. Rows without an explicit
identity decision must be excluded. A bridge created from normalized names
alone would not satisfy the gold policy.

## Recommended next step

Do not fetch the full archive yet. First obtain a small, legally retained FMA
metadata sample or the archive central directory, and verify the actual CSV
headers against the official schema. Then select a bounded set of FMA artists
and test whether a reviewer can establish both bridges using explicit external
identifiers. Record the result as a bridge receipt with counts for accepted,
rejected, and ambiguous rows.

Proceed only if the bridge has enough exact pairs for the preregistered gold
split. The gold document should retain the FMA artist and genre IDs as source
identities, map them to the model IDs only through the reviewed bridge, and
store a hash of every source record used for a judgment. Missing FMA genre tags
cannot be treated as negative labels, so a separate negative sampling rule is
still required before any precision or recall gate can be enabled.

If the small bridge test produces no explicit IDs, the honest outcome is a
no-go for FMA. At that point, the project needs a different public source that
publishes both stable artist IDs and genre labels with a documented crosswalk
to the model IDs. No such source is currently retained in this repository.

## Other public candidates

The following sources were checked as possible replacements for FMA. None is
ready to serve as a production gold source.

| Source | Exact identity and labels | Decision |
| --- | --- | --- |
| Last.fm artist API | `artist.getTopTags` accepts a MusicBrainz artist ID and returns popularity ordered tags. The API needs a key, has rate limits, and its terms limit stored data to 100 MB unless Last.fm grants permission. | Conditional pilot only. It has the best exact artist join, but it is a live API rather than a pinned public snapshot. A receipt bound cache, terms approval, tag to genre policy, and a negative sampling rule are required. |
| Discogs database | Discogs assigns its own artist and release IDs and documents release genres and styles. The official genre guidance does not document a MusicBrainz artist crosswalk. Dump terms also need a separate review. | No-go for an exact MusicBrainz join. It could support a reviewed release level study after an explicit identity bridge, but that is the same unresolved bridge problem as FMA. |
| AcousticBrainz | The archive is keyed by exact MusicBrainz recording IDs and contains low and high level acoustic features. The official data page describes features, not artist genre labels. | No-go for artist genre gold. It is metadata and exact ID compatible, but it has no independent genre judgments. |

The Last.fm documentation is at
[artist.getTopTags](https://www.last.fm/api/show/artist.getTopTags) and
[the API terms](https://www.last.fm/api/tos). The Discogs evidence is in the
[genre and style guidelines](https://support.discogs.com/hc/en-us/articles/360005055213-Database-Guidelines-9-Genres-Styles).
The AcousticBrainz evidence is in its [data documentation](https://acousticbrainz.org/data)
and [download documentation](https://acousticbrainz.org/download).

Last.fm is the only candidate that currently has a documented direct
MusicBrainz artist input and a returned artist tag result. It still cannot be
called gold without a pinned response artifact and a policy that says which
tags count as a positive label. Its tags are community annotations, and an
absent tag is not a negative label. The next low cost research step is a small
Last.fm request pilot against already known MusicBrainz artist UUIDs, subject
to a confirmed API key and terms review. This does not justify a bulk download
or a production gate.
