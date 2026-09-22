# MusicBrainz direct custody peer graph

The local graph records artist co-membership from the portable proper-genre custody receipt. It uses no tags, release rows, historical assignments, H3 data, or Last.fm data. The graph does not claim that an artist or release is musically representative, and it is not approved for serving or publication.

The builder verifies the custody object before it reads claims. The command also pins the receipt file bytes to SHA-256 `41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615`. It writes a SQLite database and a typed receipt under `.cache/musicbrainz-direct-custody-peer-graph-v1/`.

## Scoring

Each artist receives weight `1 + ln((N + 1) / (df + 1))`, where `N` is the number of custody seeds and `df` is the number of seeds containing that artist. A pair's IDF weighted Jaccard score is the sum of shared artist weights divided by the sum of both seed weights minus the shared weights. The builder sorts artist IDs before using `math.fsum` for score sums. It also stores shared artist count and ordinary binary Jaccard.

The database stores every pair with at least one shared artist. Pairs that share one artist are explicit abstentions. Pairs that share two or more artists are canonical symmetric candidates. The directional neighbor table keeps up to ten candidate peers per seed, ranked by IDF weighted Jaccard, shared artist count, then peer ID. A seed with no shared artists remains in the node table as isolated.

## Results

The graph contains 697 seed nodes, 387,435 custody claims, 198,409 artist MBIDs, and 387,435 distinct seed and artist pairs. The artist-sharing pass visits 468,523 seed pairs. It finds 38,084 pairs with nonzero overlap. Of these, 20,178 meet the two-artist threshold and 17,906 abstain at one shared artist. Two seeds have no overlapping artists. The graph has 6,119 directional neighbor rows.

For example, `item1` ranks `item48` first with 1,090 shared artists, raw Jaccard `0.069044`, and IDF weighted Jaccard `0.065808`. `item1` ranks `item20` second with 947 shared artists, raw Jaccard `0.065550`, and IDF weighted Jaccard `0.061291`. These are source co-membership counts and scores, not judgments of genre similarity.

The 11 custody seeds that are absent from the current atlas have no admitted peers under the two-artist rule. Ten have one or more one-overlap abstentions, and one has no overlap. In the earlier unthresholded graph, eight had at least two placed peers, two had one placed peer, and one had none. Those counts do not support placing them with this graph's current threshold.

The SQLite file is 57,384,960 bytes. Its SHA-256 is `1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69`. The receipt file SHA-256 is `a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`, and its embedded output hash is `3b9b98511f350e21f2b17366d799d81b88f99a99339456a27789c42fdc0c5ffc`.

The build command is:

```sh
uv run python scripts/build_musicbrainz_direct_custody_peer_graph.py \
  --custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --receipt-output .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json
```

The command refuses to replace existing outputs. The database remains local research data and does not change `dist`, serving inputs, or deployment.
