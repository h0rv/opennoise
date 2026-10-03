# Independent artist listening request

We need real independent musical judgments. No reviewers have been assigned and
no musical ratings have been received. Please recruit willing listeners who did
not build or tune these models; each item needs two independent submissions.
The prepared request below has not been sent to anyone.

Start with the existing eight licensed FMA excerpt pilot in
`musical-review-packet/fma-permitted-listening/`. Use its listening page and blank
forms to check access, attribution, rating clarity, familiarity, uncertainty and
recusal. This is a separate workflow pilot: its FMA identities and judgments must
not be attached to the artist study by name matching.

The follow-on is frozen under
`/dev/shm/opennoise-exact-artist-musical-review-v1/public/`. It contains all 1,991
exact MusicBrainz artist UUIDs from the source experiment's confirmation cohort.
The first 1,000 are an identity-hash-ordered batch; another 991 remain in the
denominator. No artist was removed for rare labels, absent supported seeds or
method abstentions. The cohort was prepared after inspecting the source
experiment, but before any musical judgments. It is not fresh source-model
confirmation or a representative sample of all music.

Use `review-form.csv`: it includes artist names, candidate genre labels and
metadata links. Fill only your assigned blank reviewer slot. Judge each candidate
independently; several overlapping genres may fit the same artist. Rate fit from
0 (poor fit) through 4 (strong fit), familiarity from 0 (unfamiliar) through 3
(very familiar), and uncertainty from 0 (low) through 3 (high). Record conflicts
or recusal, inaccessible material, uncertain artist identity, and insufficient
representative material rather than guessing. Source assertions are not answers.

Listen through lawful, permission-supported references and record the reference,
permission/access basis, provider, territory and date. Prefer multiple exact
recordings spanning the artist's work before making an artist-level judgment.
**The present 1,991-artist cohort has no verified recording-link overlap with the
bounded recording pack and no verified permitted listening references.** Every
MusicBrainz artist link is metadata only. The public forms are ready, but they
cannot presently support a listening-based completion claim. The coordinator
must obtain suitable exact-identity listening references or record abstentions.

Methods and scores are withheld from reviewer items. The private coordinator key
compares four frozen source-completion arms and an untuned unconditional training
prior, all using the same full observed-seed inputs. Reviewers should not inspect
model output or source genre annotations until their judgments are submitted.
Genre prompts are proposals, not claimed facts or musical confidence estimates.

The concise request to participants is:

> Please independently review the eight permitted excerpt pilot first. If the
> workflow works and you are willing, help judge candidate genre fit for an
> assigned portion of the frozen first-1,000-artist batch. Each item needs two
> independent reviews. Record lawful listening references, access, familiarity,
> conflicts and uncertainty; abstain when material or expertise is insufficient.
> Do not consult model scores or treat database genre assertions as truth.

The coordinator assigns actual consenting reviewers and resolves listening
permissions; those are genuine external dependencies. Its keys and assignments
remain under `coordinator-private/`, outside public Git and public static exports.
The public manifest SHA256 is
`31f9d721b0862b85b88c0ab43db613ab65952814323c50d997e8d6e20373c0e7`;
the freeze SHA256 is
`a18e2ba1c9a4b2b31f23b2a49f26f5066c422484a2a1bb6d3023be2289430263`.

Source coverage stays distinct from musical judgments: this source-selected
artist model covers 9,992 exact identities out of 2,999,670 core identities;
2,989,678 remain outside this model. All 1,991 reviewed identities have at least
one native genre assertion, so unlabelled behavior has test coverage but no
empirical support here. Native geographic and language context is disclosed as
source properties with missingness, never musical features or style conclusions.
