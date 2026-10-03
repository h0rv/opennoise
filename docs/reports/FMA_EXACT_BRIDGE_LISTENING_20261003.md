# Exact identities and permitted listening

The native FMA metadata snapshot has 16,916 artist rows and 109,727 track rows.
Replaying every artist and track source row to the pinned ZIP CRC and SHA256,
then matching **literal URLs and entity kinds** against a frozen MusicBrainz
artist-or-recording URL search resolves **168 native FMA artist IDs**. One
multiple-MBID conflict abstains. The remaining 16,748 artist rows, including that
conflict, stay unresolved. All 168 distinct MBIDs are present in the full
2,999,670-artist CC0 MusicBrainz core projection. No names, scheme rewriting,
artist inheritance or fuzzy joins contribute identities.

The search captured all four pages of its 320 relevant native URL entities;
this is a bounded artist/recording URL census, not a claim to reproduce every
FMA relationship in MusicBrainz. An initial broader URL query hit the provider's
500-result cap; its failed attempts remain preserved separately. There are
**zero exact recording bridges** across all 109,727 native FMA track rows.
Artist identity assertions do not turn track annotations into artist genres.
The FMA side remains CC BY 4.0 with attribution, separate from CC0 core metadata.
An independently implemented census verified the 168 resolved assertions.

A separate MusicBrainz exact recording lookup captures native URL relationships
for all 36 previously credited recording examples. Nine records have literal
provider destinations, all Spotify public links. These are optional external
links sourced from CC0 metadata; provider availability and audio permissions are
not established. No proprietary provider data, previews, media or embeds were
acquired from those links.

Actual permitted listening is now reproducible through eight native FMA small
archive excerpts. Before any audio request, a hash-seeded selection freezes
native track metadata from the 1,179 archive/size/strict-license eligible rows.
The selection admits only literal CC0, CC BY or CC BY-SA declarations, and keeps
per-track license URLs, artist/title, source page and attribution. The eight
selected IDs are 61011, 127299, 138060, 124391, 112318, 138061, 126602 and 140266.
Their MP3 files total **7,493,845 bytes**. Seventeen exact HTTP 206 range receipts
cover the native ZIP64 directory and eight local headers/compressed members;
ZIP CRCs, uncompressed lengths and audio SHA256 hashes replay offline. The
provider archive is 7,679,594,875 bytes; its **full archive SHA256 is not verified**.
The archive is not fully downloaded. Provider region is not recorded.

`verify_fma_listening_pack` replays the complete native track license CSV,
frozen selection, ZIP directory, exact member positions, decompression bounds,
CRCs, closed file inventory and exposed MP3 bytes. The static exporter emits
escaped source text, visible attribution/license/source links and native audio
controls with `preload="none"` and no autoplay. The exact source projection and
all HTML/MP3 file hashes are bound in the export manifest. The clips retain the
native 30-second excerpt scope; they are not full recordings or reviewed defining
examples. Browser duration and user-initiated play/pause validation is being
performed independently and must be recorded from its actual result.

Six focused tests cover conflicting assertions and full unresolved denominators,
endpoint/path/budget tampering, exact credits and provider host boundaries,
bounded decompression, file hash/size/symlink custody and escaped licensed static
exports. Ruff and type checks passed for these new modules and scripts.

Source assertions, permitted source listening and independent musical judgments
remain separate. No person, judgment, calibrated artist membership or overall
Every Noise parity is claimed by this evidence.
