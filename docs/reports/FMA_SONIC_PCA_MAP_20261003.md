# Native FMA descriptor map candidate

A separately named descriptor map now reconstructs actual coordinates from open native input instead of treating the absent sealed legacy layout as a universal engineering blocker. It is a research candidate, **not a certified Every Noise musical map**. No Every Noise coordinates, Spotify internal features, artist names as features, audio or factual artist genres enter this fit.

The frozen declaration (`91f31dc04859203a5a56dccb1d093f414201f89f379702f62b565bf006bde246`) prescribes the original training-only normalization, all 44 native Librosa mean descriptors, centered covariance PCA, deterministic eigenvector signs, minimum five training feature positives per genre and eight hashed connected-component leave-bucket-out sensitivity fits. All covariance statistics are streamed in 128-row batches. The original Gaussian model and connected artist/album/full-feature-duplicate splits remain unchanged and their exact hashes are required.

The first complete fit used **92,270 finite known-artist training tracks**. PC1 and PC2 explain **32.0186%** of standardized training descriptor variance. Their full native feature loadings and all 44 eigenvalues are exported. These are mathematical axes; organic/mechanical, dense/atmospheric, genre similarity and independent musical interpretation remain unestablished.

The output retains all **164 native source genre definitions**: 158 have training-only source-positive descriptor centroids, six explicitly abstain below five finite training positives. No validation/test genre annotations influence the centroids. All **16,916 native FMA artist records** remain searchable: 16,109 have context coordinates from their finite native track descriptors and 807 explicitly lack a position. An artist descriptor context is not an artist genre assertion. Held-out track descriptors may be displayed through a train-fitted projection; they never fit covariance or normalization.

Full raw denominators remain **109,727 tracks**, **2,609 unlabelled tracks**, **974 tracks with unresolved source artist records** and **3,153 tracks without finite native descriptor rows**. These remain reported rather than disappearing from coverage. No FMA identity is converted to a MusicBrainz artist or recording through a name match.

Sensitivity keeps whole connected native training components together. The largest omitted bucket contains 44,336 training rows. Across the eight leave-bucket-out fits, the maximum principal angle between the candidate two-dimensional subspaces is **7.9393 degrees**. This describes deterministic source sensitivity, not a bootstrap confidence interval, audio perturbation stability or independent musical agreement. The reduced explained variance is retained separately for each omitted bucket. No held-out result selects axes, thresholds or parameters.

The fit completed in **87.23 seconds**, observed peak RSS **117,190,656 bytes**, below the declared 220 MB process bound. The candidate is approximately 3.2 MB. The minimal static SVG offers genre/artist context selection, native-ID/name search, complete paginated lists including every unpositioned identity, explicit numeric coordinates, loadings/missingness details and keyboard skip navigation. It requests no audio or external provider content.

Original fit output remains untouched at `/dev/shm/opennoise-fma-sonic-map-20261003-v1/export`. The separately named v2 view retains exactly the same coordinates (`ab73b2747ac47a6a50ef964a2f0aad8e073c5371cc6882a2992df7952b91c192`) while freezing stronger source/license replay guards and visible keyboard focus. Its receipt is `f749e21427dccaef68d0273e15e9c45ff6bbd34d418697a498639590b63f50c9`.

**Verification complete for this candidate:** four targeted numerical/train-only tests pass. A fresh full source replay independently re-fitted the declared training covariance and reproduced every native genre/artist coordinate and all eight sensitivity fits exactly. The actual single-process Chromium contract passes one test with zero skips: all 164 genre contexts and 16,916 artist contexts, unpositioned search/selection, keyboard skip focus, desktop/mobile layout and no external/media requests. Ruff and type checks pass. `/dev/shm/opennoise-fma-sonic-map-20261003-v2/validation.json` binds the exact candidate receipt, coordinate bytes, checker implementation, browser contract and logs; its SHA256 is `886907af27ef5862b5969429304a3266eb42bbf613077389c104cbe9d21f5d83`. The v2 receipt records that fresh replay was pending when the unchanged coordinate/view snapshot was created; this later independently bound verification supersedes that historical pending marker.

Reconstruct a fresh candidate:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python scripts/build_fma_sonic_map.py \
  --metadata <verified-native-FMA-metadata-projection> \
  --features <verified-native-FMA-descriptor-projection> \
  --saved-pack data/examples/fma-acoustic-baseline \
  --declaration <frozen-map-declaration.json> --output <new-output-directory>
```

Replay every native context coordinate and sensitivity fit:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python scripts/build_fma_sonic_map.py \
  --metadata <verified-native-FMA-metadata-projection> \
  --features <verified-native-FMA-descriptor-projection> \
  --saved-pack data/examples/fma-acoustic-baseline \
  --output <candidate-directory> --verify
```

The source projection, descriptor order/roles, normalization model, split ledger, declaration, coordinates, implementation snapshot and all static assets are hash-bound. Metadata, descriptors and derived source coordinates use **CC BY 4.0**, with FMA attribution: Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson, *FMA: A Dataset for Music Analysis*, ISMIR 2017, https://github.com/mdeff/fma. Repository implementation code retains its code license. The original compressed native member custody was independently audited previously; this map does not claim that the complete remote metadata/audio ZIP hashes were verified.

Needed independent evidence remains method-blind listeners' judgments of local and distant candidate pairs using permitted audio, sufficient coverage across unfamiliar source genres, treatment of abstentions and the interaction of overlapping memberships with map neighborhoods. PCA variance and stable algebraic axes do not satisfy that acceptance gate. No experimental deployment or production musical promotion is authorized by this candidate.
