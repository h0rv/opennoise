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

On 2026-09-22, the creator-attributed Zenodo record
[`10.5281/zenodo.6090214`](https://doi.org/10.5281/zenodo.6090214) was also
checked as an official alternate distribution. Its HTTPS metadata and archive
HEAD request worked. It names Oscar Celma of the Music Technology Group, is in
the MTG/UPF community, and publishes the 569,202,935-byte
`lastfm-dataset-360K.tar.gz` with MD5
`635e6ed3fc873aa4ba33aba0ebce02b1`. Its stated MD5 for the inner plays TSV,
`be672526eb7c69495c27ad27803148f1`, matches the UPF page.

One local download attempt was interrupted during range resumption by the
execution environment. The resulting file failed both gzip integrity and the
published archive MD5 (`8ce899a371c05dd503a375febb251f9c`), so it was removed.
A second clean, non-resume attempt with a three-minute ceiling was terminated
by the same harness at 151,646,208 bytes. It was also removed before parsing.
Those failed transfers created no admitted source object, receipt, sample, or
aggregate. They were superseded by the verified range acquisition below. No
TLS bypass or third-party copy was used.

## Verified local-only prefix probe

That acquisition completed on 2026-09-22 through 34 disjoint 16 MiB-or-smaller
HTTPS ranges. Every response was `206` with the requested `Content-Range` and
exact byte length. The ignored local receipt is
`.cache/lastfm-360k-upf-zenodo-6090214/zenodo-record-6090214.json`
(SHA-256 `b18036154cac331fa61e016028d714561cef94aadcb18d0f50c948eb32e25474`);
the range manifest records each chunk hash. Reassembly was exactly
569,202,935 bytes and matched the published archive MD5
`635e6ed3fc873aa4ba33aba0ebce02b1`. The extracted plays TSV matched the UPF
published MD5 `be672526eb7c69495c27ad27803148f1`.

The full raw archive is retained only under that ignored local custody path.
It includes the unused `usersha1-profile.tsv` member, which contains hashed
user IDs and demographic fields. This probe never opened that member. No
profile or user data enters the derived aggregate, any model, or any public
artifact.

One local-only aggregate inspected the first 100,000 TSV rows. It retained no
user hashes, artist names, artist IDs, or pairs in its output. It found 98,748
rows with valid exact artist UUIDs, 22,166 unique exact artist UUIDs, and 702
exact overlaps with the current 1,331-artist public SQLite catalog. For a
bounded co-listen count only, it used at most the first ten source-order unique
exact artist IDs per contiguous user block: 2,033 completed user blocks,
82,777 candidate pairs, and 362 pairs supported by at least five distinct
users. The 362 count is therefore from that first-ten-per-user,
source-order-prefix diagnostic only; it is not full-dataset coverage. This is
not an artist-similarity result, graph, evaluation, model input, or serving
artifact.

The complete local aggregate report has SHA-256
`128ba8d5486fd8fbf76bc996163af90dd6fa8908509049b5896530f47fec2f90` and is
ignored at `.cache/lastfm-360k-upf-zenodo-6090214/sample-100k-aggregate.json`.
The source record states that the dataset is available for non-commercial use;
see its [license and source text](https://zenodo.org/records/6090214).

Primary source: <https://www.upf.edu/web/mtg/lastfm360k>.
