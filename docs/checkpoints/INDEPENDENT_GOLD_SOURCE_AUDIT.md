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
| AcousticBrainz feature dump | The archive is keyed by exact MusicBrainz recording IDs and contains low and high level acoustic features. | No-go. Audio-derived features are outside the default pipeline, and features alone are not independent genre judgments. |
| AcousticBrainz Genre Dataset annotations | Separate TSV archives have exact MusicBrainz recording IDs, release-group IDs, and genre/subgenre labels from Discogs, Last.fm, and Tagtraum. The smallest validation archive is 4.0 MB compressed. | Diagnostic only, not approved as independent gold. MetaBrainz later imported tags from these same archives into MusicBrainz, a retained model candidate. The exact recording-to-artist join and reviewed genre bridge are also missing. |

The Last.fm documentation is at
[artist.getTopTags](https://www.last.fm/api/show/artist.getTopTags) and
[the API terms](https://www.last.fm/api/tos). The Discogs evidence is in the
[genre and style guidelines](https://support.discogs.com/hc/en-us/articles/360005055213-Database-Guidelines-9-Genres-Styles).
The AcousticBrainz feature evidence is in its [data documentation](https://acousticbrainz.org/data)
and [download documentation](https://acousticbrainz.org/download). The separate
[AcousticBrainz Genre Dataset format](https://mtg.github.io/acousticbrainz-genre-dataset/data/)
and [Zenodo deposit](https://zenodo.org/records/2553414) document the annotation-only
TSV files. The dataset authors state that Discogs labels came from release
metadata and Last.fm and Tagtraum labels from community tags. The audio-derived
feature archives are separate and are not needed for an annotation pilot.
The [MetaBrainz genre-matching project](https://github.com/metabrainz/genre-matching)
states that in 2021 it submitted almost six million genre tags for over 1.3
million MusicBrainz recordings from the same Discogs, Last.fm, and Tagtraum
annotations. It explicitly used both training and validation TSV files. This
creates a leakage risk for any candidate trained or evaluated using MusicBrainz
tags, even if a validation recording was absent from our current local catalog.

Last.fm is the only candidate that currently has a documented direct
MusicBrainz artist input and a returned artist tag result. It still cannot be
called gold without a pinned response artifact and a policy that says which
tags count as a positive label. Its tags are community annotations, and an
absent tag is not a negative label.

The AcousticBrainz Genre Dataset is a small, pinned, offline diagnostic pilot,
but not an approved production gold source under the current policy. Its
public annotation archives are distinct from the AcousticBrainz feature dump.
An exact recording-to-artist join could measure overlap and expose failure
cases, but would not remove the historical MusicBrainz leakage risk. A recording
label is not automatically an artist membership judgment, and a missing label
is not a negative. Keep all annotations out of model construction and the
public release. The larger Zenodo music knowledge graph is not suitable as independent
gold without a field-level provenance audit: it combines MusicBrainz tables
already used in construction with Last.fm listening records, and its only
download is a 3.1 GB ZIP. Its
[deposit](https://zenodo.org/records/20394102) and
[pipeline README](https://github.com/rhermosoUZ/EARS-data-project) describe
those inputs.
