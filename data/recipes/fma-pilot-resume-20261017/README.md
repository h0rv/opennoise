# Resume the local listening pilot

Listeners could export answers, but could not restore them after reloading the
page. The participant form now accepts its own saved response files and shows
how many of the six trials have a choice. This count is not a completeness,
attention or judgment-quality score.

Restore is explicit and local. The file must match the current packet hash and
listener slot, include exactly the six expected trial IDs and retain the exact
response schema. The page validates the entire bounded file before changing any
answer. If the current form contains answers or notes, replacement requires a
separate confirmation. A rejected or canceled restore preserves the form.
Nullable listening/conflict fields preserve the difference between unanswered
and false; optional notes retain their text. Nothing is saved automatically,
transmitted or played by restoration.

This is a participant-interface revision, not a new listening experiment or
model evaluation. The original fixed six queries, candidate identities and order,
A/B assignments, credits and unchanged licensed audio are preserved. Packet
bytes and their SHA256 bindings remain identical to the previous participant
packages, so older saved responses remain compatible. Updated page, instructions,
execution seal and inventory bindings are separately generated in a fresh pack.
The original pack is not overwritten; its original source revision remains the
way to replay its exact interface guard. No inventory validation is weakened to
accept arbitrary old or new pages.

The two participant folders remain separate from each other and from coordinator
files. An ordinary explorer link would expose tags and methods before a listener
participates, so this change does not add such a link. Use the separately packaged
listener folder and its existing loopback-only launcher. No coordinator key,
source-genre annotations or model scores are added to the participant view.

The coordinator already supports zero, one or two strictly validated response
files and retains all missingness and exclusion reasons. Browser test answers
are synthetic test evidence only; they are never submitted to the actual pilot.
The recorded pilot still has zero real responses out of twelve planned responses.
Two slots do not establish two independent people. These previously inspected
recordings are not independent confirmation, and missing tags remain unknown.
The outstanding quality gate is real independent listening participation followed
by a genuinely unexamined evaluation before any broad quality or promotion claim.

No new source acquisition, audio processing, paid service, credentials, model
variation, Library retry or public deployment is part of this change.
