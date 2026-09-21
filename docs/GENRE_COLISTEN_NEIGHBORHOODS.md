# Co-listen genre neighborhoods

`scripts/build_genre_colisten_neighborhoods.py` is a no-environment-variable checkpoint. It locates the shared `.cache` beside Git's common directory, so main and linked worktrees use the same sealed inputs and durable output.

Construction reads exactly two receipt-bound SQLite artifacts: the evidence graph and the privacy-thresholded aggregate ListenBrainz co-listen sidecar. It verifies each receipt's logical hash, each database's bytes, the sidecar's graph-receipt binding, integrity, and all 6,291 stable seeds before querying. It never reads historical artifacts, audio, raw listens, or listener identifiers.

Artist memberships stay in two non-interchangeable channels: `artist_direct` and `reviewed_alias_context`. `release_group_support` is deliberately absent. Each channel deduplicates `(artist, seed)` first. For an artist with `d` memberships, it assigns each seed `1/d` of that artist's membership mass. Each canonical artist-pair/window contributes `log1p(distinct_user_count)` times endpoint membership mass to both ordered genre directions. Windows are aggregate evidence, not sums of distinct people.

The train score is ordered NPMI: `PMI(g,h) / -log P(g,h)`, with probabilities formed from the complete ordered weighted joint and its induced marginals. The cache retains raw mass, window support, canonical artist-pair support, unshrunk NPMI, and `NPMI * raw_mass / (raw_mass + 3)` separately. A predeclared minimum of two windows and raw mass 0.05 prevents one-offs from becoming peers. This checkpoint does not blend Jaccard, cosine, or PPMI full-graph baselines.

The split hashes the canonical artist pair before any window is used; every repeated window remains together. Heldout reporting is positive-only: it gives all heldout genre-pair positives, scoreable positives, overlap coverage, and top-k recovery. Missing data is never a negative or precision denominator.

The SQLite cache has a row for every `(channel, stable_seed)` with `observed`, `abstained`, or `isolated` state, plus at most 50 ranked `peer_not_parent_child` rows per seed/channel. The query API requires `certify_neighborhood_cache`, which replays the artifact and byte-binds the cache before `neighbors_for_seed` serves a bounded page. Peer rows are intentionally not child-to-parent claims.

`quality-diagnostics.json` is evaluation-only. It samples diverse supplied label text (IDM, post-punk, jazz, hip hop/trap, K-pop/J-pop, metal, regional styles and microgenres), reports top peers and support, cross-umbrella text leakage, degree/disconnected counts over all 6,291 seeds, and explicitly records that a peer is not a parent relation. Its labels never affect model construction.
