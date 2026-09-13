# Local external membership evaluation

`scripts/evaluate_public_memberships_externally.py` compares an already
selected public serving model with the local-only MusicBrainz research
database. It is a post-seal research diagnostic. It does not build the public
model, alter ranking or layout, or contribute to any exportable release.

The evaluator opens both SQLite files read-only and fails closed unless the
public database has an exportable, derived `public-graph` model and does not
contain the MusicBrainz research source key. It binds both file hashes, the
selected model hashes, and a deterministic replay hash in its Pydantic report.

Artist identity is an exact MusicBrainz artist identifier. Genre identity is
unique exact NFKC/casefold/whitespace-normalized label equality. It deliberately
does not use aliases, taxonomy, semantic mapping, or fuzzy matching.

Run the task with explicit local destinations:

```sh
OPENNOISE_CERTIFIED_PUBLIC_DATABASE=.cache/musicbrainz-20-catalog/public.sqlite \
OPENNOISE_MUSICBRAINZ_RESEARCH_DATABASE=.cache/musicbrainz-v3-research/musicbrainz-v3.sqlite \
OPENNOISE_PUBLIC_MEMBERSHIP_EXTERNAL_EVALUATION_REPORT=.cache/musicbrainz-v3-research/public-membership-external-evaluation-v1.json \
uv run poe evaluate-public-memberships-externally
```

Or call the script directly. The default tag-weight sensitivity thresholds are
1, 3, and 5; repeated `--threshold` arguments replace those defaults and must
be distinct, positive, and ascending.

## Current local run

The retained local report is
`.cache/musicbrainz-v3-research/public-membership-external-evaluation-v1.json`.
It is ignored by Git and must not be bundled with a public release. Its current
evaluation hash is `c8b90c9767a3c8bb4fbebdcd0284aa502ef5a9f90e5934f48f71ba385d364e90`.
It binds certified public DB hash
`31b342e11a03fcfabca6a8e639f96e9250ef7cfb06b4e615608a6445e9b15b7c`,
public model output
`e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b`, and
research DB hash
`2fc3a7371bb272e19d1eedc0f7102a909381ce759fe56fbad1e34aaa8a331dd3`.

At tag weight >= 1, the matched direct profile had micro precision/recall/F1
of 0.644/0.552/0.594 (macro 0.628/0.559/0.553); one-hop had
0.065/0.213/0.099 (macro 0.087/0.165/0.097). Matched-prediction coverage was
315/4,434 direct and 1,703/22,091 one-hop. The report carries per-genre
support, confidence bins/Brier/ECE, weighted-reference recall, and deterministic
false-positive/false-negative samples for every threshold.

MusicBrainz tags are noisy, community-supplied, incomplete reference evidence,
not gold labels. Both sides also depend on MusicBrainz identifiers. The
comparison universe is the union of observed predictions and observed tags, so
its true-negative field is not a meaningful specificity denominator. Public
scores are ranking scores rather than claimed probabilities, and the calibration
output is descriptive only.
