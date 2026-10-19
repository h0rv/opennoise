# Unsupervised artist retrieval against observed human genre votes

The frozen experiment adds a genuine unsupervised native artist index, rather than packaging previous model scores. It compares **genre-only TF-IDF cosine** with one fixed **genre+instrument TF-IDF cosine** candidate. Binary track tags are averaged over every native metadata track of each artist; gallery-only artist-document frequencies define IDF. Five unchanged artist+album component folds separate each query fold from the other four gallery folds. There is no supervised fitting, old NB/temperature output or feature-mixture search.

The [protocol](protocol.json) was committed before any IDF weights, vectors, similarities, rankings or artist-coherence metrics were computed. Identity, target availability, gallery vocabularies/document-frequency support counts and previous classification outcomes had already been inspected; that knowledge is explicitly recorded. Runtime uses deterministic sorted float64 matrices and exact positive cosine/native-ID ordering, without outcome-based rounding, clipping or tie changes.

Retained source support is 11,565 tracks, 713 native artists/components and 2,365 albums. There are 1,757 nonempty taxonomy nominations across 459 artists, with 1,024 eligible tracks in 368 artists; 164 of these artists have only one eligible track, 204 have at least two, and 345 artists have no eligible target. All disagreements remain included. The full native source and every missing/incomplete/invalid track reason remain visible. Across the five folds, judged-query counts are 76/59/75/75/83 and judged-gallery counts 292/309/293/293/285. All galleries contain 87 genre and 40 instrument literals; every judged query has a gallery-known genre feature. The minimum class support is 15 judged gallery artists. These are pre-execution support bounds, not retrieval outcomes.

Human artist targets are equal means of eligible tracks' three-vote fractional class profiles. Primary condensed judged-gallery NDCG@10 uses linear dot-product vote agreement and an ideal over **all** judged gallery artists, including those with no feature overlap. Query labels and availability never enter index construction or ranking. Full-gallery judgment coverage and conditional observed gains are reported separately; missing annotation is not a negative. All 368 judged query components remain in denominators, including zero-IDCG, empty-profile and no-overlap cases. The 204 multi-track artists are a predeclared secondary query subset, with the same galleries. Fixed paired bootstrap intervals condition on this reused cohort and fixed galleries; they are not population or retraining confirmation.

This measures coarse human-genre coherence, not pairwise listener relevance, recommendation usefulness, native artist membership truth or EveryNoise parity. Annotation independence/blinding and duplicate-audio separation across different native identities are not established. The source is **CC-BY-NC-SA-4.0, noncommercial research only**. Profiles, ranks, human ledger and index artifacts remain local; only code/contracts/restrained attributed aggregates may be committed. There is no UI/default/serving/deployment change and no acquisition. Each numeric run/replay derives five unsupervised gallery IDF indices; supervised fits remain zero. Limits are 120 seconds CPU/wall, one numerical thread, 1 GB address space and 15 MB combined new payloads.

The broader goal still lacks appropriate independent relevance data. The retained AB cohort has only 11 own-fold supported emissions; larger AB/FMA inputs remain unavailable through the previously denied routes. Parent independent source checks found direct human triplets in official CityMTag documentation but no explicit license grant, so no acquisition/use was authorized. The official [LFM-1b page](https://www.cp.jku.at/datasets/LFM-1b/) states withdrawal for licensing reasons. Ocelma 1k/360k documentation attempts timed out, with no data acquired. These are source-specific observations, not a claim that all independent free sources are unavailable.

Attribution: Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), *The MTG-Jamendo Dataset for Automatic Music Tagging*; [pinned annotation documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md), [pinned root README/license](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md). Exact source, source-serialization amendment and helper-code hashes are fixed in the protocol. Original raw/model/caller-profile studies remain unchanged. Parent and Luna protocol reviews approved implementation after this freeze; the protocol bytes remain unchanged.


## Actual fixed-comparison result

Adding instruments did **not** establish a coherence improvement. Across all 368 judged query components, condensed judged-gallery NDCG@10 was **0.667819** for genre-only and **0.659431** for genre+instrument. Candidate-minus-baseline difference: **−0.008388**, fixed paired component-bootstrap interval **[−0.018858, 0.001658]**. The 204 multi-track query subset also had a slightly worse candidate point estimate: **−0.006792**, interval **[−0.021048, 0.006702]**. Neither result supports a candidate promotion, and no setting or representation was changed afterward.

Mean vote agreement@10 (fixed denominator ten) was **0.534240** versus **0.529060**. The analytic uniform-random judged-gallery expectation was NDCG **0.319165**, agreement **0.249861**. Both feature arms exceed that observed-label random reference, but random comparison is not recommendation validation. The meaningful comparator remains the raw-genre baseline, against which adding instruments did not establish a benefit.

Judgment coverage moved in the opposite direction from the coherence point estimate: among the 3,680 full top-ten slots for judged queries, judged slots increased **1,953→2,065** and unjudged slots decreased **1,727→1,615**. These changes describe annotation availability, not improved recommendation coverage or unknown negatives. All 713 source artist outcomes per arm remain: genre-only has 710 available/3 empty profiles; genre+instrument has 711 available/2 empty profiles. No judged query was dropped, and all 368 IDCGs were defined and positive. Across all native query artists, full-slot counts are 3,656 judged/3,444 unjudged/30 missing for genre-only and 3,830/3,280/20 for the candidate.

[Checked aggregates](results.json) retain every fold, all nine fractional source-class-weighted diagnostics (positive query counts and target-mass denominators, never hard memberships), both instrument-availability strata, both bootstrap cohorts and all arm/random comparisons. They also distinguish full-native versus judged-query coverage denominators. The scalar scores do not show that sampled annotations represent each artist's full catalog or that tag/annotation sources were blinded.

## Custody and independent verification

Own source-only census was sealed before real IDF/vector/ranking execution: census seal **`224e23459e450dbfb503fc039a405edb84d95214ff9e2dd78b9f62b9d54b0d51`**, payload `fcebafc49a13fe45ff25cafe984b7571ac7497127fef96b7a86ffb2057dcb319`. The independent raw-source count-only census was separately sealed as `c697978b1710432b9ef5d52e65dc0dd8931f8b51f076d7232d657baf883207f2` before its oracle index computation. The producer uses the two pinned sources directly, not any previous model/prediction result.

Result receipt **`8a0aa9e0274e6c66faa004f131fb90c8a0b6fad1f2a1e929fcf13522154080a3`** binds the three closed payload files and the census/protocol/runtime. Current census plus result artifacts total **5,908,784 bytes** under the combined 15 MB cap. The run observed 2.002 seconds/137,621,504 peak child RSS bytes on this host. Separate exact replay passed in 2.464 seconds/152,276,992 bytes. These are individual local execution observations, not general performance guarantees. Each numerical invocation derived five unsupervised gallery indices; neither invoked supervised training.

The independent oracle imported no production code. It matched all 635 DF/IDF coordinates and all **20 normalized unit-matrix hashes exactly**, every native route/artist target, **21,570 selected full/condensed edges and their cosine scores exactly**, and all 1,426 arm outcomes. Overall/robust/fold/class point metrics and the two 2,000-draw bootstrap sets matched; largest metric error was below `9e-16`, with interval endpoints exact. Comparison receipt `/workspace/jamendo-artist-coherence-20261019/independent-production-comparison.json`: SHA256 **`2261a0e88cefbb67ccadc0d3e28448b5e4b9800b51b604c4d64e4bec378163bd`**, 1,514 bytes.

Actual relocated CLI census/run/replay used exact copied sources/protocol while original source, previous model/result/cache and oracle trees, old-model imports, networking and supervised fit calls were denied by active guards with four explicit denial probes. Production made **zero forbidden operations**, observed index-build counts **0/5/5**, and reproduced all three payloads **and both census/result receipts byte-for-byte**. This is offline recomputation from verified source copies, not a claim that sources are unnecessary. Proof `/workspace/jamendo-artist-coherence-20261019/relocated-proof/proof.json`: SHA256 **`585184707cdd984b52e48b991dea7ca53fc26c8784371f51e0e49471bec6b2e2`**, 2,281 bytes.

Twelve focused tests cover gallery-only DF/vocabulary, all-track TF denominators, one global block normalization, exact native-ID ties, positive-only edges, component exclusion, human-free index inputs, fractional track-average targets, linear gain/full ideal, zero IDCG, exact random expectation, unknown annotation accounting, fractional weighted diagnostics, paired bootstrap, physical whitespace/type/inventory guards, caps and pre-index support failure.

Full `poe check` passed: 2,255 Python tests in 160.097 seconds (36 skips), 166 Node tests (122 passes, 44 skips, zero failures), and format/lint/type checks. All twelve focused tests passed; independent Luna final review was clear and reran those tests. Runtime/source hashes remained the audited `3a310f1f…` / `527147c9…`. Full log: `/tmp/opennoise-jamendo-artist-coherence-check.log`.

## Reproduce

Use Python 3.13 and `poe sync`. Sources remain local noncommercial research files; restore the exact pinned bytes under honest custody if these paths are unavailable. No acquisition is performed by the CLI, and no old model/result path is needed. All destinations must be fresh. From the repository root:

```bash
.venv/bin/python - <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root = Path('.cache/jamendo-artist-coherence-reproduction')
common = [
    '--metadata', '/workspace/jamendo-human-genre-20261019/source/autotagging-test.tsv',
    '--human', '/workspace/jamendo-human-genre-20261019/source/music-classification-annotations-raw.tsv',
    '--protocol', 'data/recipes/jamendo-artist-coherence-20261019/protocol.json',
    '--protocol-sha256', 'ac14d662222fc5241b38598cc2dd74f762d4910f2699c795c1be408356c6e25c',
]
def stage(name, extra):
    command = [sys.executable, 'scripts/run_jamendo_artist_coherence.py', name, *common, *extra]
    return json.loads(subprocess.check_output(command, text=True))

census = stage('census', ['--output', str(root / 'census')])
# The complete source/support census is physically sealed BEFORE real index execution.
extra = ['--census', str(root / 'census'), '--census-sha256', census]
result = stage('run', [*extra, '--output', str(root / 'results')])
print(stage('replay', [*extra, '--output', str(root / 'results'), '--result-sha256', result]))
PY
```

The CLI sets resource bounds before numerical imports. Closed file inventories, physical byte/hash bindings, type-sensitive canonical replay, source/runtime changes and overlapping/existing output paths fail closed. Support gates are replayed before indexing; a failed gate produces explicit no-evaluation output, not a changed class/fold/query policy.

The acquisition restrictions above apply to this fixed experiment and the named denied/unlicensed/withdrawn routes. They do not revoke separate standing authorization for an independently licensed new dataset. The next substantive recommendation-quality dependency remains appropriate independently licensed listener relevance/artist-pair judgments and native identity support, not another favorable label-proxy metric or post-hoc feature mixture. Exact-head and merge/main CI status belongs to the associated pull request.


## Separate post-freeze source feasibility

After this protocol freeze, the parent's independent next-slice check identified [official DEAM documentation](https://cvml.unige.ch/databases/DEAM/) describing explicit BY-NC nonprofit research terms, 1,802 songs with human arousal/valence annotations, artist/genre metadata and 601.5 MB openSMILE features. Its single ordinary HEAD request for official `metadata.zip` at 2026-10-19 21:54:17 UTC failed at proxy CONNECT with `403 Forbidden`; zero body bytes, no redirect or retry, and no annotation/feature values acquired. That host attempt stopped without an alternative route. This separate feasibility request did not change the frozen Jamendo comparison or its zero new source-acquisition accounting. Its receipt/hash is preserved in checked aggregates. It illustrates a precise access dependency for one independently licensed source, not a global ban or a claim that all free sources are unavailable.
