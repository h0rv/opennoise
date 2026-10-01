# Credited music metadata examples

Implemented reusable exact-credit ranking in `opennoise.serving.metadata.artist_works`.
Scores expose exact artist credit, original album context, nonvariant recording,
dated metadata, unseen release context, and distinct title. Compatible duplicate
identities merge evidence and context deterministically; conflicting titles,
kinds, credits or variant status are rejected. This ranks bounded metadata
examples, not quintessential quality, popularity, listener consensus or genre truth.

The checked-in `data/examples/representative-music` projection contains ten
benchmark artists, including Aphex Twin and Four Tet, each with six recording
examples and six release context links. It omits tags, aliases, ratings, search
scores and media. Each recording proves its own artist credit. Release-group
links represent context from separately exact artist-credited release editions;
these are not direct group artist-credit assertions and do not establish genre
membership. MusicBrainz core metadata is CC0; the receipt includes the license URL,
projection SHA256 and original capture receipt SHA256.

Fresh clone replay after `poe sync`:

```sh
.venv/bin/python scripts/rerank_projected_artist_work_examples.py \
  data/examples/representative-music/credited-examples.json \
  --receipt data/examples/representative-music/receipt.json \
  --output .cache/representative-music-demo/representative-music.json
```

The replay verifies the receipt, exact artist identities, row kind/credits and
safe MusicBrainz URLs. It refuses existing outputs. Full original-cache replay
is available through `scripts/build_cached_artist_work_examples.py`; this checks
source-captures/query-manifest hashes against their original receipt, confines
payload paths to the cache and verifies body checksums. No network acquisition
was needed. No audio assets or playback were introduced, and published public
model representative rankings were not changed.

Validation: five focused unittest cases pass (credit exclusion, deterministic
diversity, incompatible duplicates, safe links and tampered replay). Ruff and ty
pass for the new module and both scripts. The UI agent owns optional incorporation
of this verified artifact into local discovery artist details; no deploy occurred.
