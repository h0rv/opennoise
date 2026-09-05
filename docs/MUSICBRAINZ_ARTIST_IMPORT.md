# MusicBrainz artist import

The completed import used the official MusicBrainz artist JSON dump dated
2026-08-29. The source archive is 1,695,597,804 bytes, and its verified SHA256
is `396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d`.
MusicBrainz publishes the core data under CC0. The source manifest records the
mixed terms that apply to the full JSON dump, so derived fields remain subject
to the stored source policy.

The job scanned all 2,970,393 artist records. It selected records whose source
ID SHA256 starts with `0`, which is exactly one sixteenth of the hash space. The
job accepted 185,779 artists, quarantined no records, and found no duplicate
source objects. The observed selection rate was 6.254358 percent.

The final SQLite database is `data/musicbrainz-final.sqlite`. It is ignored by
Git and uses 619 MiB. The verified source object is stored in the ignored
content addressed vault at `data/source-cache/raw/sha256/396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d`
and uses 1.6 GiB.

The database contains 185,779 artists, 310,962 names, 203,404 identifiers,
185,779 source objects, 185,779 provenance records, and 185,779 search
documents. SQLite reported `ok` for `PRAGMA integrity_check`, and
`PRAGMA foreign_key_check` returned no rows.

The first completed run took 1,281.069 seconds, which is about 21 minutes and
21 seconds. Peak memory was not measured because `/usr/bin/time` is not
installed on the laptop. The parser caps each expanded JSON record at 64 MiB.
The largest record observed during preflight was 51,092,053 bytes.

A second run reused the completed attempt. It returned the same counters
without parsing the archive again. The command still spent about five seconds
checking the 1.6 GiB vault object's SHA256 before it returned.

The release group archive is 1,187,679,180 bytes. The release archive is
22,491,260,204 bytes, so the release import was not started on this laptop. The
recording archive is 33,572,648 bytes, but this branch does not claim support
for its record shape. The next import should add and test those source adapters
before it downloads either archive.

## Positive genre and tag evidence

Adapter version 4 projects positive counts from each artist record's
official MusicBrainz `genres` array. At most 128 unique genre identities are
accepted per artist. Repeated identities or a larger array quarantine the whole
record instead of choosing a count or silently truncating it. Zero, missing, and
negative counts do not become positive evidence.

The same adapter parses the broader supplementary `tags` array, bounded at 512
normalized unique names per artist. Whitespace-only, punctuation-only, and
malformed tag entries are dropped from the tag facet. Case/punctuation-normalized
duplicates are merged deterministically, retaining the first spelling and the
maximum count. If the bounded unique-name limit is exceeded, the tag facet is
dropped while core artist and curated genre fields remain available. Tags have
no MusicBrainz UUID, so they use deterministic name-derived identities under the
`musicbrainz_tag_name` identifier type and remain separate from UUID-backed
genres. Positive tag counts are stored in the same append-only
`artist_genre_evidence` table with method `musicbrainz_artist_tag`; curated
genres retain method `musicbrainz_artist_genre`.

Genre entities are resolved only through the MusicBrainz genre UUID. The
projector records the raw positive count in `artist_genre_evidence` with method
`musicbrainz_artist_genre`; downstream jobs read the policy-filtered
`normalizable_artist_genre_evidence` view. The JSON artifact mixes core CC0 data
with supplementary CC-BY-NC-SA-3.0 fields, so the manifest deliberately applies
the restrictive `restricted_research` policy to the whole projection.

MusicBrainz identifies tags and genre associations as supplementary data. Its
official license page permits noncommercial use with attribution and requires
derivative works to use the same CC-BY-NC-SA-3.0 license. The official download
page confirms that genre associations require derived data and that
`mbdump-derived.tar.bz2` uses that license. See the
[MusicBrainz data license](https://musicbrainz.org/doc/About/Data_License) and
[official dump license table](https://musicbrainz.org/doc/MusicBrainz_Database/Download).

The manifest therefore exposes two explicit modes. The ordinary mixed-artifact
source permits normalization and local display but denies embedding, training,
and export. `musicbrainz_json_artist_research_20260829` permits local
noncommercial embedding and training, is marked `local_only`, and still denies
all export and redistribution. Any later publication of an output derived from
this research mode needs a separate review, MusicBrainz attribution, a
noncommercial use decision, and CC-BY-NC-SA-3.0 ShareAlike output terms. The
default public/exportable model must use CC0-compatible inputs such as Wikidata
and ListenBrainz instead.

The measured 185,779-artist run above used adapter version 2 and therefore
contains identity data only. It must not be reported as having genre evidence.
The version 4 fixture run accepts one artist, one positive genre claim with raw
count 4, and positive tag claims while ignoring zero, missing, and negative
counts. A real version 4 partition rerun remains pending.
