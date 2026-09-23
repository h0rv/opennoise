# Last.fm 360K source feasibility

The UPF Music Technology Group page describes a Last.fm dataset with
17,559,530 user and artist play rows, 359,347 users, and 186,642 artists with
MusicBrainz IDs. Each play row contains a SHA-1 user value, a MusicBrainz
artist ID, an artist name, and a play count. The page lists MD5 values for the
two TSV files.

The dataset could support a local artist user-play matrix using exact artist
MBIDs. A future adapter must discard artist names and profile fields. It must
aggregate user contributions before writing results. It must not retain user
hashes in output. It could compare aggregate artist pairs with the existing
ListenBrainz daily co-listen result, but the sources measure different things.
The Last.fm file is all-time play counts per user and artist. The ListenBrainz
input is timestamped daily listening data with a fixed privacy threshold.

The dataset cannot provide artist genre labels or independent genre gold. It
is a Last.fm source and must remain separate from the existing Last.fm tag
work. The UPF page says the dataset is available for non-commercial use only.
No model, public artifact, or release input is authorized.

The official UPF page links its download to `https://ocelma.net/MusicRecommendationDataset/index.html`.
On 2026-09-22, a metadata-only HEAD request to that URL failed TLS hostname
verification because the certificate named `sni.dreamhost.com`, not
`ocelma.net`. No certificate bypass and no archive download occurred. File
size is therefore unknown.

The next safe option is to ask UPF or the dataset maintainer for a current
HTTPS mirror and checksum. If a verified source becomes available, inspect the
archive listing and a small bounded sample first. The sample must confirm the
documented TSV columns, MBID validity, compressed size, and license scope
before any adapter work.

Primary source: <https://www.upf.edu/web/mtg/lastfm360k>.
