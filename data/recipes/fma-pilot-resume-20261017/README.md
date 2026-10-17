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

## Verified result

Implementation: `8fc3ff8add5e532b5bd85f4853bf2e81d3f587bc`.
Independent source checks passed (7 Python and 5 Chromium contracts). Independent
actual-package checks passed for both slots: all 15 recordings per slot play
with preserved credits; blank answers survive download, reload, restoration and
re-export exactly; wrong-slot/hash imports leave the form unchanged; no external
requests, automatic playback or coordinator access occurred. Mobile 390px and
keyboard checks passed; synthetic contracts additionally cover 320px, nonblank
round trips, Unicode limits, cancellation and asynchronous races.

The fresh execution seal is
`054f7f3a7911698946f1239f3bb2aa9b27446c77adb3f4c75f9618065d67b9a7`.
The new coordinator mapping hash is
`ad1114852ea4a6e5b94cd34fdf1675bff324736a3568478359f722638cc6c36b`.
Independent closed-inventory checks confirm byte-identical packets and audio,
unchanged assignments and an untouched historical pack. Each listener ZIP has
20 files, excludes coordinator files and responses, and passed byte-for-byte
archive round-trip validation:

- Slot 1: 14,464,977 bytes; SHA256
  `9e447fc45a45b8dca5ba51da09e4b52148080f18662dcff26e5df1626cd049f9`.
- Slot 2: 14,464,977 bytes; SHA256
  `aba3c2ea73909800be7eece35a3e837572b69bc775dcd82b4dbea44006a4bd0d`.

## Local reproduction

Use the existing reviewed candidate at
`/workspace/opennoise-candidate-navigation-20261016/site55` and baseline at
`/workspace/opennoise-evaluation-run-20261016/pack-final`. The older candidate
page correctly fails the current validator; no guard was weakened. Both
candidate versions retain the same reviewed manifest and audio.

Run `scripts/build_fma_listening_pilot.py freeze` with those inputs, baseline
inventory pin `0f4f380428f5d5961dca818824ab6f38702dff2facc90309fa002ed556ffbd14`,
and `data/recipes/fma-waveform55-evaluation-20261016/listening-protocol.json`.
Review the resulting seal, then run `build` with its exact SHA256 into a fresh
directory. Run `summarize` with the new mapping SHA256 and no response arguments
to reproduce the zero-response summary. Do not confirm distinct participants
without actual evidence. Existing wrapper resource guards remain unchanged.

Actual run: `/workspace/opennoise-pilot-resume-run-20261017`.
Independent artifact/browser evidence:
`/workspace/opennoise-pilot-resume-independent-20261017`.
Source and methodology reviews:
`/workspace/opennoise-pilot-resume-review-20261017`.

Extract each participant ZIP separately and run `python3 serve.py` inside that
listener folder. Follow the printed loopback URL. Download answers before
closing, then use **Restore saved answers** in the same listener slot to resume.
Keep the coordinator archive away from participant folders and HTTP roots.
