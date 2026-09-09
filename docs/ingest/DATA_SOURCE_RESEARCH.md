# Data-source research: bounded next steps

Scope: no audio files, no borrowed Every Noise coordinates, and an old-laptop
workflow that can start with a receipt-bound small sample. This is a source
decision note, not an integration or a claim that any candidate is approved.

## Recommendation

1. Finish the already sealed MusicBrainz release-group path, then add the
   MusicBrainz *derived* tag tables as a separate, weighted review signal. The
   official dump documents that `mbdump-derived` contains user tags and the
   entity-to-genre associations, while the core dump has artists, releases,
   recordings and release groups. The schema documents aggregate tag counts
   and update times. This gives the missing album/release context and tag
   specificity with exact MBIDs, no API key, snapshots twice weekly, and
   streaming import is practical. It must remain review evidence until an
   explicit source-to-claim policy is accepted; tags are not artist membership.
   [MusicBrainz download](https://musicbrainz.org/doc/MusicBrainz_Database/Download),
   [schema/tag fields](https://musicbrainz.org/doc/MusicBrainz_Database/Schema),
   [canonical release mapping](https://musicbrainz.org/doc/Canonical_MusicBrainz_data).

2. Pilot AcousticBrainz only as an optional *recording-level, CC0* feature
   enrichment keyed by recording MBID. Its published archive has basic CSV
   fields such as BPM, danceability, loudness and key, plus high/low-level JSON;
   it does not require downloading audio. It is frozen at July 2022 and the
   full files cover about 29.5 million submissions, so the only sensible first
   step is a bounded MBID-joined sample for records already in the catalog.
   It can improve descriptive filters or a separately labelled review lens,
   never establish genre membership or replace current public evidence.
   [AcousticBrainz data/download](https://acousticbrainz.org/download),
   [project status and CC0 statement](https://acousticbrainz.org/).

## Consider, but do not prioritize

- **Discogs:** useful release, credit, date, format, label and track-listing
  metadata could fill representative-album gaps. API terms impose rate,
  attribution and cache/display restrictions and distinguish CC0 from
  restricted content. Those API restrictions must not be assumed to be the
  terms of the separate monthly XML dumps: Discogs states that dump content is
  governed by the license on its dump landing page. Before any bulk decision,
  retrieve and pin that current dump-specific license; then assess each field
  independently. This is an access/policy question, not evidence that a
  dump-derived release or credit would be invalid. [API terms](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use),
  [Discogs terms note on dump license](https://support.discogs.com/hc/de/articles/360009334333-Nutzungsbedingungen).

- **ListenBrainz dumps:** retain as the best independent aggregate-listening
  candidate once its existing policy path is ready, rather than introducing a
  second listening provider. Official dumps offer public statistics plus full
  and Spark-formatted listens, with full dumps twice monthly and incremental
  dumps twice weekly. The full listen corpus is not old-laptop friendly; use a
  bounded incremental aggregate keyed to already anchored MBIDs and preserve
  privacy thresholds. [ListenBrainz dump documentation](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html).

- **TheAudioDB:** its free API advertises artist, album and song metadata, but
  it is a live service rather than a pinned bulk source and does not address
  direct-membership coverage. Treat it only as future display enrichment after
  reproducibility and terms are separately reviewed. [TheAudioDB API](https://www.theaudiodb.com/free_music_api).

- **Free Music Archive metadata:** a compact, genuinely separate tag dataset
  for an exploratory *track-level review* sample. Its official repository
  publishes `fma_metadata.zip` (342 MiB) with 106,574 track rows containing
  title, artist, genres, tags and play counts, plus a 163-row genre table with
  parent structure. It requires no audio download, but it is a historical,
  FMA-local identifier namespace with no guaranteed MusicBrainz join. Use only
  exact external-ID matches or a separately reviewed identity bridge; never
  name-match into factual membership. [FMA metadata documentation](https://github.com/mdeff/fma).

## Explicit non-recommendations

Do not use historic Every Noise output as training data, coordinate targets or
membership source. Do not use Discogs marketplace/user data. Do not download a
full AcousticBrainz or ListenBrainz corpus on the laptop merely to explore it.
