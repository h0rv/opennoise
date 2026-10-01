# Named style atlas: parity and quality audit, 2026-09-30

This is a read-only evaluation of the local named-style atlas and clean community preview. Historical names are used only as an external comparison set; they were not model inputs. This audit does not equate string overlap with taxonomy identity, listening relevance, or complete parity.

## Bound artifacts and method

- Current candidate atlas: `.cache/named-style-atlas-20260930-v3`, revision `named-source-style-atlas-v1`, display recipe `named-style-display-v3`, receipt output SHA-256 `e09925cb3c4fc1996740cc35bc677155f5fc124b3abcf161f14b7d1a3cd3cfd6`.
- The completed v3 export binds 42,863 files and 1,400,236,653 artifact bytes. Every bound byte was independently checked; artist profiles, cohorts, search and source geometry are byte-identical to the retained verified v2 export, output SHA-256 `a683830c817ba222eaf5b8b1ab83a5caffc5b0ad2a9d7d6db46fb678991396e6`.
- The original v1 draft had output SHA-256 `697d2560be8cd9c71cd4157e4faacba78032252a5810568dc4c91fe94d0298d5`. It was removed as a superseded draft before the builder learned that this audit referenced it. That artifact is unavailable; its old audit observations are preserved explicitly below, and current counts were recomputed from retained v3 bytes.
- Current evaluation-only report: `.cache/named-style-atlas-parity-audit-20260930-v3`, receipt output SHA-256 `f64a8a1b79a9c10e7ce40ca4340ee819c639b6b9bdcff19f590cdd362c472c8f`. Historical comparison was performed after construction and never entered atlas features, model fitting, geometry, or display decisions.
- Atlas receipt binds the source-profile explorer output SHA-256 `0deaa234b5637ca734b6558022ad3e1fab1573ee45f7547e37b144deff1d84a9`, feature receipt SHA-256 `00f3cd770b04368999a1685641bff00a37bdb606b68926b57d44e13603d78b1f`, feature payload SHA-256 `0c298b1241b03e642dbc7b13981f59b9008cb1fdc4e01186b5fe55e7f2c78748`, and prediction output SHA-256 `c987e91f4de32dc7d254f9d1e69ddf8185dd5bbae0503c73e9f67dcb6575d63c`.
- The clean preview receipt output SHA-256 is `6228934743a67c9408e39c3f2dc30f1198da48029be675713ab96af9c59901ec`.
- Historical comparison: vaulted Every Noise H2 snapshot dated 2023-11-19, raw object SHA-256 `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`, consistent with `docs/EVERYNOISE_PARITY.md`.
- Comparison normalization is Unicode NFC, casefold, and collapsed whitespace. It compares complete names, not aliases, partial strings, or inferred similarity. The historical set has 6,291 unique labels.

The atlas receipt reports 198,409 artists, 615,812 feature observations, 434,067 observed-artist-feature memberships, 777 credited-release-context memberships, 594,776 inferred proposals, 14,060 candidate style atoms, 3,196 positioned styles, 10,864 unpositioned styles, and 15,571 geometry edges. Every atlas style record marks `native_fact: false`; the receipt says names were not used for construction, and no historical inputs, external gold, or audio were used. Candidate labels remain research candidates.

## Name coverage (string match only)

| Comparison set | Count | Exact normalized names in 6,291-label reference | Reference coverage | Set-specific labels outside reference |
| --- | ---: | ---: | ---: | ---: |
| Retained native MusicBrainz proper genres | 697 | 697 | 11.08% | 0 |
| Candidate atlas style atoms | 14,060 | 1,621 | 25.77% | 12,439 |
| Default supported-name display | 2,226 | 986 | 15.67% | 1,240 |

All 697 native genre spellings also occur among candidate style atom names. This is spelling coverage only: atlas records explicitly do not turn a name match into a native fact or identity claim. There are 4,670 reference labels absent from the candidate set and 5,594 absent from the 697 native set. Neither percentage is a measure of semantic accuracy. The atlas expands name overlap, but the remaining mismatch is substantial and 12,439 candidate spellings have no exact counterpart in this reference.

## Source support and label noise

Counting distinct exact artist IDs with a matching `artist_tag` feature (one artist counted once per normalized value) yields this candidate-atom stratification:

| Distinct artist-tag support | Candidate atoms | Exact historical-name matches |
| --- | ---: | ---: |
| 0 | 55 | 1 |
| 1 | 10,196 | 451 |
| 2–4 | 1,999 | 288 |
| 5–9 | 591 | 146 |
| 10–49 | 720 | 321 |
| 50+ | 499 | 414 |

The v3 namespace counts were independently recomputed from the complete immutable feature cache and matched every one of the 14,060 exported style rows. The corpus contains 387,435 distinct artist-genre pairs, 154,908 artist-tag pairs, 605 credited release-genre pairs and 777 credited release-tag pairs. Namespace counts can overlap within one artist and style. Exactly 1,810 atoms have at least five distinct artist-tag sources; 12,250 have fewer than five or none. This is a triage split, not a truth threshold. A name match does not rescue a weakly supported label, and frequent user tags can still be noisy.

The superseded v1 audit note reported support-bin counts 2,916 / 8,059 / 1,585 / 449 / 765 / 286 and 1,500 atoms at support five or above. Those historical audit outputs are retained here for traceability, but are inconsistent with the independently checked full feature-cache namespace projection and must not be reused as current corpus support.

Default display has 1,447 exact dictionary-name matches and 779 repeated source candidates, totaling 2,226 searchable styles and 1,934 positioned styles. Another 11,834 raw candidates remain explicitly searchable. Repeated candidates require at least five distinct source artists and pass a versioned display screen; this does not validate musical semantics. Reviewed rank, label/company, event, nationality, occupation, status and technical labels are excluded from the default view without removing raw observations or memberships. Dictionary spelling alone does not override an explicit nonstyle display exclusion.

The original draft audit recorded 128 punctuation-leading labels, 28 quote-edge labels and 184 broad metadata-word matches. Those are historical review-queue observations rather than current support-bin evidence. Examples include `!hyperfocus`, `"air with heart"`, and `"alt rock"`; raw candidate names are retained. Geometry does not validate a label: `!hyperfocus` remains positioned in the raw tier. Browser review also identified repeated nonstyles including `top 100`, `milane records`, `sxsw`, `komponist`, `violinist`, `lithuanian`, `covid-19`, `death by murder`, `27 club`, `fixme`, and `model`; the v3 default display screen now excludes these exact cases while retaining their source evidence. Musical forms such as `finnish string quartet` and `festival trap` are preserved by focused tests.

Recommended browse/evidence presentation:

1. Keep direct native artist/release proper-genre facts as their own evidence class; never promote a candidate because its spelling matches a dictionary entry.
2. Show source-observed artist and release tags with separate distinct-artist and distinct-release support. A provisional “repeated source tag” view may start at five distinct artist IDs, with an explicit unreviewed label and no truth implication.
3. Keep inferred proposals in a separate section with their score and source cues. They must not be blended into observed tags or source facts.
4. Add a conservative review queue for quote/punctuation edges, sentence-like text, personal/status/role/format terms, and source fragments. Suppress or canonicalize only through a versioned reviewed display overlay; preserve each original source value and its evidence.

## Fixed artist audit

Each row was looked up by exact MusicBrainz UUID in the atlas artist shard, not by display name. `native genres` are the exact preview source `genre_ids` resolved against its retained 697-name dictionary. Membership counts distinguish directly observed artist features, credited release context, and inferred proposal roles; all style memberships are candidate atlas memberships and are not native facts. Top proposals are the first three sorted by proposal score, not reviewed recommendations.

| Artist | Exact MusicBrainz ID | Native genre facts | observed artist features | release context | inferred proposals | Top three inferred proposals |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Aphex Twin | `f22942a1-6f70-4f48-866e-238cb2308fbd` | 15 | 27 | 72 | 3 | edm; deep house; melodic techno |
| Four Tet | `3bcff06f-675a-451f-9075-99e8657047e8` | 12 | 17 | 52 | 3 | breakbeat; melodic techno; lo-fi |
| Boards of Canada | `69158f97-4c07-4c4e-baf8-4e4ab1ed666e` | 6 | 12 | 58 | 3 | lo-fi; hip hop; chillwave |
| Autechre | `410c9baf-5469-44f6-9852-826524b80c61` | 7 | 15 | 35 | 3 | noise; house; drum and bass |
| Burial (UK dubstep identity) | `9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6` | 6 | 11 | 52 | 3 | electronica; drum and bass; pop |
| Squarepusher | `4d86ad4e-28d8-4e9f-8cf4-735c57060fdc` | 4 | 6 | 31 | 3 | electronica; house; dubstep |
| Floating Points | `69d9c5ba-7bba-4cb7-ab32-8ccc48ad4f97` | 5 | 7 | 29 | 3 | edm; melodic techno; pop |
| Caribou | `735e3514-a8ae-401f-af3b-6300df1b8d2c` | 4 | 6 | 50 | 3 | lo-fi; indie pop; edm |
| Brian Eno | `ff95eb47-41c4-4f7f-a104-cdc30f02e872` | 7 | 8 | 82 | 3 | indie rock; psychedelic rock; noise |
| Jon Hopkins | `0b0c25f4-f31c-46a5-a4fb-ccbf53d663bd` | 5 | 8 | 39 | 3 | edm; deep house; hip hop |

These ten rows were independently reread from retained v3 artist shards and exactly match the prior audit's role counts and proposal values. The ten exact IDs all have native facts, artist-observed features, release-context features, and proposal records. This demonstrates entity and feature coverage for this fixed cohort, not broad precision or sufficient fine-grained relevance. Generic or surprising proposals (for example Aphex Twin → “edm” and “deep house”; Brian Eno → “noise”) remain a quality issue. V3 now includes a standalone static atlas with support tiers, paginated source/inferred cohorts, raw source evidence and exact-ID artist search; browser interaction evidence is tracked separately and does not validate those suggestions or establish semantic genre parity.

## Prioritized next improvements

1. **Clean vocabulary without destroying evidence:** quantify fragment, quotation, punctuation, personal-tag, role, and format noise by namespace and source cohort; publish a reversible reviewed display overlay while preserving raw labels. Avoid padding toward historical-name parity.
2. **Expose evidence separation:** a future atlas UI should show source native facts, observed artist tags, release-context tags, and inferred proposals distinctly, with distinct source counts, provenance links, and an unreviewed/candidate state. Exact-name dictionary matches are hints only.
3. **Evaluate candidate quality beyond coverage:** take a stratified human review sample across support tiers, namespaces, and geometry states; report precision/acceptability and inter-reviewer agreement. Keep the 6,291-name exact overlap as a dated external diagnostic, not training input or a target.
4. **Reduce proposal fragmentation:** assess near-duplicate aliases and generic umbrella labels with source cooccurrence and exact evidence, then merge only reviewed display variants. Track how many artist identities and useful distinctions a merge affects.
5. **Broaden relevance evaluation:** preserve the fixed ten-artist cohort but add predeclared artists across styles and holdout examples; compare proposed labels and memberships to independent expert judgments or listening studies. Existing historical strings cannot establish sonic relevance.
6. **Treat artifact scale as follow-up work:** the complete 14,060-style atlas and 198,409-artist corpus binds 1,400,236,653 bytes. Browse data, compact search, exact-ID shards and role cohorts load independently. Further packaging can reduce transfer costs; this checkpoint does not authorize public release or public serving.

The research receipts remain local-only with public export and public serving unauthorized. No producer, model, UI, or artifact was changed by this audit.
