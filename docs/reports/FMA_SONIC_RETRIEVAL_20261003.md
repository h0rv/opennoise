# Native FMA acoustic retrieval experiment

The frozen experiment selects 240 exact native FMA validation identities from
7,332 eligible known-artist queries before inspecting descriptors or scores.
Training-only normalization uses 92,270 finite tracks from 5,467 connected
artist/album/full-descriptor-duplicate components. Retrieval excludes the query
component and ranks ten training neighbors by standardized Euclidean distance,
with exact native-ID tie ordering. No audio, artist names, Every Noise targets or
proprietary Spotify features enter the fit.

All 240 queries remain in the evaluation: 236 have observed source annotations,
four have unknown targets, four lack feature rows and one fails the frozen
descriptor support gate. Missing labels never become negative musical labels.
Across 529 observed positives, acoustic neighbors recover 278 (52.55%), training
annotation-frequency neighbors 293 (55.39%), and fixed-hash neighbors 225
(42.53%). Acoustic neighbors overlap at least one observed label for 180 queries,
versus 151 for annotation frequency and 155 for fixed hash. This experiment
does not establish musical relevance or superiority over the frequency arm.

The queries reuse previously reported validation data. They are a descriptive
frozen experiment, not untouched confirmation or a basis for post-hoc tuning.
Native FMA identities are not MusicBrainz recordings; exact listening bridges
and independent judgments remain separate requirements.

A fresh source/component/fit replay completed successfully after replacing
large per-query distance copies with exact 1,024-row batches. The complete query
output and training normalization are byte-identical to the preserved original
fit. Eight targeted tests cover training-only fitting, component exclusion,
abstention, unknown labels, identity guards, numeric overflow, frozen-policy
tampering before descriptor access and ties across batch boundaries;
Ruff and type checks pass. The accompanying JSON binds the frozen declaration,
source receipt, implementation and outputs. Earlier failed replay attempts and
the complete original pack remain preserved.

Metadata, descriptors and derived native results retain FMA's CC BY 4.0
attribution: Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier
Bresson, *FMA: A Dataset for Music Analysis*, ISMIR 2017,
https://github.com/mdeff/fma. This experiment does not verify complete remote
archive hashes or grant rights to arbitrary audio.
