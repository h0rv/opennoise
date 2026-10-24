# More complete listening neighborhoods

The artist catalog still contains 11,894 MusicBrainz identities. A fixed sample
of 500 previously unqueried artists adds 30,002 observed relationships within
that catalog. Artists with at least five connections increase from 4,292 to
5,895. The source now contains 149,588 undirected relationships from 2,147
successfully retrieved neighborhoods. Autechre's placeholder name is corrected
from an exact matching MusicBrainz ID in the new native responses.

The new input contains public ListenBrainz aggregate scores and MusicBrainz core
metadata under their existing CC0 scope. It contains no audio, lyrics, user
histories, private evaluation labels or private identity joins. Forty-eight
invalid rows and five repeated targets are accounted for separately. Newly
observed identities outside the existing catalog are excluded. More source
relationships do not establish musical relevance or Every Noise parity.

The raw public responses and their byte hashes are retained in
`data/examples/native-artist-neighborhoods-20261024/`. The previous public source
remains available beside the new snapshot. The producer uses only those inputs:

```sh
.venv/bin/python scripts/build_artist_neighborhood_source.py --output /tmp/opennoise-source-replay
```

The existing sparse context method remains unchanged. Spectral coordinates only
supply initial map positions; the browser measures and packs the actual labels.
The genre atlas, its source memberships, and the original public catalog remain
unchanged. Public promotion and browser checks remain separate requirements.
