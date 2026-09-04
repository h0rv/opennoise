# Historical signal semantic hierarchy candidate

The candidate is stored outside version control at
`.cache/historical-signal-semantic-candidate/historical-signal-semantic-v1.json`.
It covers all 6,291 retained genres from the sealed H3 membership database.

Broad-family seeds are assigned from each genre's own explicit lexical head.  Only unseeded genres
propagate a family over weighted H3 neighbors when one family has at least 60% of available support;
the rest remain explicitly `Other / unplaced`.  The lower hierarchy is then graph-only inside each
family: induced H3 graph regions are bounded to 96 members, then split to microgenres of at most 24.
Names never affect the H3 kNN graph, edge weights, layout, or lower-level clustering.

The final in-process deterministic build reports complete hierarchy coverage, 13 umbrellas, 83
subcommunities, 448 microgenres, and weighted union-H3 edge retention of 0.689795697233,
0.411728252332, and 0.286746510700 respectively.  The largest microgenre has 24 members and each
overview region is no larger than 3,000 members.  The model build executes an independent rerun
before writing; the focused cross-hash-seed unit test also passes.

The coarse nodes use `graph_and_genre_name_derived` provenance.  Subcommunity and microgenre nodes
retain `graph_derived_h3_similarity` provenance, conditioned on their already-selected display
family.  The report is a display taxonomy evaluation, not a claim that name families are musical
ground truth.
