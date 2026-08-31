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

## Active workstreams

| Workstream | Owner | Status | Delete path |
| --- | --- | --- | --- |
| Application and final integration | `/root` | Active | Revert uncommitted integration changes and return to `b905f6d`. |
| Public Every Noise data import | `/root/everynoise_ingest` | Active | Remove `genre_discovery.py`, migration 0003, and `tests/test_genre_discovery.py`. Revert the adapter, bootstrap, database, migration smoke, database test, schema test, and Every Noise adapter test changes. Do not change the pinned raw artifacts. |
| Reconstruction methods and evaluation | `/root/everynoise_methodology` | Active | Remove `src/musix/reconstruction.py`, `scripts/evaluate_reconstruction.py`, `tests/test_reconstruction.py`, and its entry in `docs/EXPERIMENTS.md`. |
| Python review and release checks | `/root/python_final_review` | Active | Remove review notes or focused test additions. Application behavior should not depend on review tools. |

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

## Near term work

First, finish the public data import with source hashes and dated observations. Second, expose the genre path from artists to albums or tracks, then to a sample or external link, and then to neighboring genres. Third, compare open artist overlap neighbors with the historical pages where archived evidence exists. Fourth, publish measured layout candidates without replacing the historical source coordinates.

## Explicit non-goals

The current work will not claim that inferred weights reproduce Spotify's private system. It will not train a final model, scrape private accounts, or treat missing archived artists as evidence that an artist did not belong to a genre. It will not merge historical observations with open reconstruction results into one unexplained score. It will not decide the pending product choices without user review.
