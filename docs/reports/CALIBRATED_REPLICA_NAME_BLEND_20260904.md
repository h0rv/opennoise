# Calibrated replica: rejected name blend

Artifact: `calibrated-replica-v1` SHA-256
`7af9443b08737b3e7b422c776753b9e9419d8db2fdd77d7e960cb1afaa90a831`.

Inputs were H2 map SHA-256 `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`
and H3 membership SHA-256 `863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20`.
The artifact is generated locally under `.cache/` and is intentionally not tracked.

The deterministic split has 5,027 train genres and 1,264 untouched holdout genres. The grid chose
only from train coordinate neighborhoods:

| Setting | Selected value |
| --- | --- |
| Artist weight | 1.0 |
| Name weight | 0.0 |
| Artist degree cutoff | 16 |
| k | 20 |
| Train recall@20 | 0.0212950 |
| Holdout recall@20 | 0.0164161 |
| Holdout lift over artist-only | 0.0 |

The grid tested artist weights 0, 0.25, 0.5, 0.75, and 1; degree cutoffs 4, 8, and 16; and k of
10 and 20. Name candidates used character-trigram TF-IDF, capped to document frequency 64 and a
deterministic top 64 candidates per genre. The complete run took 15.9 seconds on this laptop.

Result: reject the name blend. It did not beat H3 artist-only similarity on the untouched holdout.
The coordinate-free production artifact was not modified. Spectral embedding options were not
selected by this H2 calibration experiment.
