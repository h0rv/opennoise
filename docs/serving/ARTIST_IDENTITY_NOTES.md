# Native artist notes

The listening catalog now includes 4,340 retained MusicBrainz disambiguation
notes. A native artist page shows its source note beneath the name. Search and
list results show notes only for names shared by multiple native IDs.

There are 31 repeated native names covering 62 IDs. Source notes are available
for 53 of those IDs. In 22 groups, every ID has a different note. For example,
Alice Cooper's band and solo artist keep their separate IDs and source notes.
Missing notes stay absent. A note is source text, including occasional editorial
notes, rather than a biography written by OpenNoise or a verified genre label.

The projection reads only the two already-public capture packets and the pinned
native snapshot. It requires the exact native MBID, matching normalized name,
matching capture reference and a finite positive numeric score. It excludes
self rows. A note must be one exact nonempty comment across all admitted
observations. Conflicting values abstain without a majority vote. The maximum
length is 500 characters, and ASCII controls 0 through 31 and 127 are excluded.
The actual retained maximum is 118 characters.

The artifact, input contract and promotion pin the source hashes, counts and
policy. Every build replays the notes from the original response bytes. The
MusicBrainz core comment field remains within the previously accepted CC0
source scope. No new acquisition, artist merge or private evaluation input is
used.

Notes belong to native MBIDs. Atlas global search can show a native note beside
its Connections result. An atlas artist does not inherit a note through a name
match. Search membership, ordering, source genres, connection scores, Suggested
orders and map positions stay unchanged. The native details and genre suggestion
files and all non-native JSON remain exact to release 7894182.

The browser gate checks Alice Cooper, Felt, missing notes, long and Unicode text,
phone layouts, source links, keyboard/history and complete offline navigation.
A local response fixture also verifies that HTML-looking note text remains text.
No recommendation-quality or Every Noise parity increase follows from this work.
