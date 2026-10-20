# Genre-only human-style prediction development study

Root/Luna reviewed this protocol before immutable commit and any fitting.
The fixed candidate predicts five historical human style fractions from uploader
genre frequencies, with a training Beta prior and meaningful genre TF-IDF k=10
neighbor-regression baseline. It is a new supervised task, not another score
package or parameter sweep. Previous negative instrument results are preserved.

Only development component folds0–3 participate: 558 artists/8,849 tracks,
547 complete scored artists and446 robust secondary queries. Reserved fold4
(155 artists/2,716 tracks) is skipped before BOTH genre/style extraction. It has
identity/status/counts only. The old transductive feature geometry is not reused.
No heldout prediction scores or logistic fits have been computed.

The two exact retained official files total9,080,731 bytes under CC BY-NC-SA4.0.
Sources, fitted weights, profiles, neighbors and individual outputs stay local
noncommercial research artifacts; only code/protocol/attributed aggregate evidence
may be committed. No new acquisition, reserved confirmation, public/default/UI
change, deployment or new cost is included. Protocol specifies optimizer, identity
roles, matching/gates, metrics, failure behavior, fit accounting and custody.

Attribution: Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra
(2019), The MTG-Jamendo Dataset for Automatic Music Tagging;
[annotation documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md)
and [source licensing](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md).

A metadata-only pre-fit census will be sealed before IDF/vector construction or
logistic fitting, reporting full identity roles, development-only tag availability
and per-training-fold vocabulary/DF counts. Already-seen style support is disclosed
in the protocol. The immutable protocol commit precedes all fitting; implementation and a fresh
sealed source/count census precede the first numeric run.

Protocol SHA256: `8624a347604e341943f5f91046c0a54b2ce5eae6042fbdbbe777a1c21d68430b`. No model/vector/metric outcomes were observed before freeze.
