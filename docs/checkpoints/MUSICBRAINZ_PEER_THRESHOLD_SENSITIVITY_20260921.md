# MusicBrainz peer threshold sensitivity

This local-only, memory-bounded replay streamed the frozen peer candidate's
abstentions and the frozen MusicBrainz direct-membership rows. It did not load
historical Every Noise features, build a full candidate, write a map, or mutate
a database.

The baseline candidate is logical hash
`15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd`, with
input hash `ddc5d06c26ca79efa2fe038eea758200bff1528d21db5f2d8927b8aed55f24de`
and settings hash `88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f`.
Its 28,508 candidate edges and 495 scoped unplaced `insufficient_direct_overlap`
seeds were read from the frozen artifact. The threshold-one settings hash is
`6ab13e5f35cf417c89308c0155eeea23a569caa6b4a9fd431abafc143b2a0810`.

Lowering only `minimum_shared_artists` from two to one admits 3,269 scoped
edges. All 495 scoped seeds gain an edge, and 487 directly touch a currently
placed seed; those links reach two current structural components. Every added
edge has exactly one shared direct artist.

The risk signal is substantial: an added-edge endpoint has degree up to 90,
and 1,772 of 3,269 edges share an artist attached to at least 10 seed genres
(maximum 91). This is a threshold sensitivity result, not a similarity
validation or publication recommendation. Keep it local pending hub controls
and an independently held-out evaluation.

A conservative local variant excludes an overlap-one edge when its sole shared
artist occurs in 10 or more seed genres. It retains 1,497 edges, connects 414
of the 495 scoped seeds, gives 405 a directly placed neighbor, reaches two
structural components, and still has maximum endpoint degree 53. It therefore
reduces, but does not remove, hub risk and is not auto-publishable.
