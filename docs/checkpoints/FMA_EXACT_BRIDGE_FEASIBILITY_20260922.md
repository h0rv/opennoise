# FMA exact artist--genre bridge feasibility checkpoint

## Decision

**No-go: no reproducible exact bridge can be built from the retained local
inputs.** No FMA metadata archive, FMA metadata sample, FMA adapter, or
reviewed FMA-to-MusicBrainz artist and target-genre bridge is present in this
checkout. An automatic name, title, URL, tag, or taxonomy-name match is not an
exact identity bridge and must not be added.

This decision concerns metadata only. It neither downloads nor evaluates FMA
audio, FMA audio features, historical Every Noise material, MusicBrainz artist
genres or tags, Wikidata, ListenBrainz, or model predictions.

## What the official FMA source provides

The FMA project's official README publishes `fma_metadata.zip`, gives its
published SHA-1 (`f0df49ffe5f2a6008d7dc83c6915b31835dfe733`), and identifies
`tracks.csv` as per-track metadata including ID, title, artist, genres, tags,
and play counts; `genres.csv` contains FMA genre names and parents. The
metadata is CC BY 4.0, while individual audio has artist-selected licensing.
The FMA loader treats `tracks.csv` as a two-level header and parses only the
track, album, and artist tag fields plus `track.genres` and
`track.genres_all` as collection-valued columns. Its collection code queries
the FMA API by the FMA-local `track_id`, `album_id`, and `artist_id` fields.
None of those primary-source schema descriptions documents a MusicBrainz
artist UUID or a target-catalog genre identifier.

Primary sources:

- [FMA README: archive, tables, checksum, and metadata license](https://github.com/mdeff/fma#data)
- [FMA `utils.py`: metadata CSV loader and parsed columns](https://github.com/mdeff/fma/blob/master/utils.py)
- [FMA `creation.py`: FMA API collection](https://github.com/mdeff/fma/blob/master/creation.py)

## Exact missing inputs

Two bridges remain independently missing:

1. A bounded, reviewer-approved mapping from an exact FMA `artist_id` to one
   MusicBrainz artist UUID. Each accepted or rejected candidate needs retained
   non-label identity evidence, its source-record hash, reviewer decision, and
   ambiguity disposition. The destination UUID is an identifier only; do not
   consult MusicBrainz genres/tags to make an FMA label or membership decision.
2. A bounded, reviewer-approved mapping from an exact FMA genre ID to the
   current model's declared genre external ID. An equal display name does not
   prove that mapping: FMA's `genres.csv` has its own parent hierarchy.

The FMA metadata payload itself is also missing locally, so its actual
two-level `tracks.csv` headers and the selected source-record bytes cannot yet
be receipt-bound. Therefore neither an adapter nor tests would be meaningful:
they would only exercise invented input rather than a bridge.

## Next acquisition, before implementation

Acquire only the official `fma_metadata.zip` (not an audio archive), retain
the original bytes and calculate SHA-256 locally, then verify the published
SHA-1 above. Extract and retain only `tracks.csv` and `genres.csv` in a
source-custody directory. Validate their headers against the official loader
before selecting a small deterministic FMA artist/genre cohort.

For that cohort, create two separate, review-only bridge receipts with the
exact FMA source IDs, target external IDs, evidence URLs or retained records,
per-record SHA-256 values, reviewer decisions, and accepted/rejected/ambiguous
counts. Only accepted pairs may then enter the existing
`independent-artist-genre-gold-v1` custody model; track tags still require a
human artist-pair judgment and absent FMA tags remain unknown, never negative.
