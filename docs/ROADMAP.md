# Roadmap

## Stable baseline commits

The following commits are review points. New work should keep its own delete path so a reviewer can return to one of these states.

| Commit | Baseline |
| --- | --- |
| `9eb0b20` | The first working Musix map application. |
| `1bd95af` | The first research directions. |
| `c0cd34c` | The exploration and layout experiment contracts. |
| `ecd54db` | The album genre evidence contracts. |
| `b905f6d` | The stable map selection and browser navigation flow. |
| `d8e3045` | The Every Noise reconstruction method and evaluation boundary. |
| `e9a6ab6` | The historical genre discovery import. |

## Active workstreams

| Workstream | Owner | Status | Delete path |
| --- | --- | --- | --- |
| Application and final integration | `/root` | Active | Revert uncommitted integration changes and return to `b905f6d`. |
| Public Every Noise data import | `/root/everynoise_ingest` | Complete | Revert `e9a6ab6`. Do not change the pinned raw artifacts. |
| Reconstruction methods and evaluation | `/root/everynoise_methodology` | Complete | Revert `d8e3045`. |
| Genre entry experience | `/root/python_app` | In review | Remove `src/musix/genre_entry.py`. Revert the related app, route, model, template, style, and app test changes. |
| Open artist-to-genre membership | `/root/membership_pipeline` | In review | Remove migration 0004, `src/musix/membership.py`, `scripts/evaluate_membership.py`, `tests/test_membership.py`, the membership fixtures, and the Poe evaluation task; then restore schema version 3 and remove migration 0004 from schema tests. |
| Python review and release checks | `/root/python_final_review` | Active | Remove review notes or focused test additions. Application behavior should not depend on review tools. |
| Semantic renderer and product map | `/root/renderer_terra` | Active, isolated | Remove the Cytoscape static assets and semantic-map template/script/style changes. The published model and taxonomy DAG remain intact. |

## Completed research

The stack, prior art, data policy, visualization options, album evidence, and historical Every Noise method now have written reviews. `docs/EVERY_NOISE_REPRODUCTION.md` separates disclosed facts, observed output, testable inferences, and unknown details. It also defines an open pipeline based on MusicBrainz, Wikidata, ListenBrainz, and optional open audio sources.

The pinned final Every Noise map contains 6,291 genres and dated coordinates through November 19, 2023. The historical method review found public support for artist overlap, audio similarity, bounciness, organism, human review, representative playlists, and automatic updates. Exact weights, cutoffs, scaling, layout adjustment, and update rules remain unknown.

## Pending user decisions

The user has not selected the following product behavior. Implementation work must keep each choice replaceable.

| Choice | Options still open |
| --- | --- |
| Historical map route | Use the tall historical layout only at `/classic`, or make it the default map. |
| Default modern layout | Use a vertical map, a two dimensional embedding, a graph layout, a tiled map, or another representation. |
| Genre click behavior | Enter the genre, open a side panel, or focus the map in place. |
| Listening path | Use external links, playable samples, both, or neither until source policy is settled. |
| Defining albums | Use direct evidence counts, a transparent weighted score, pairwise user judgments, editorial choices, or a staged mix. |
| Membership production evidence | Select which fixed source keys and evidence kinds qualify; every run currently requires an explicit manifest. |
| Album credit propagation | Keep full evidence value for every primary credited artist, divide among credited artists, or use another declared allocation. |
| Similarity representation | Select the feature vocabulary and explicit feature weights before weighted Jaccard or cosine is published. |
| Evaluation truth set | Select a versioned, licensed positive-claim set and a negative-claim protocol; current metrics demonstrate contracts on synthetic known positives. |
| Membership run invalidation | Register membership runs as generic derived outputs before production materialization so one run can be withdrawn without suppressing its inputs. |

## Near term work

First, finish the public data import with source hashes and dated observations. Second, expose the genre path from artists to albums or tracks, then to a sample or external link, and then to neighboring genres. Third, compare open artist overlap neighbors with the historical pages where archived evidence exists. Fourth, publish measured layout candidates without replacing the historical source coordinates.

## Explicit non-goals

The current work will not claim that inferred weights reproduce Spotify's private system. It will not train a final model, scrape private accounts, or treat missing archived artists as evidence that an artist did not belong to a genre. It will not merge historical observations with open reconstruction results into one unexplained score. It will not decide the pending product choices without user review.

The artist membership baseline does not use historical Every Noise observations as training truth, perform fuzzy API identity matches, infer negatives from absent claims, normalize against the current cohort, or silently truncate a run. The local MusicBrainz fixture demonstrates direct adapter projection with a provenance-bound source key. Wikidata artist claims remain pending a typed, identity-resolved adapter instead of being guessed from the existing album-only fixture.
