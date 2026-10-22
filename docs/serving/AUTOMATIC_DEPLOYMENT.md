# Default-branch production deployment

The `Checks and production deployment` workflow runs source checks on pushes,
PRs and manual checks. A push to `main` in `h0rv/opennoise`, while `main` is its
repository default, deploys after both source checks and the reproducible public
build/browser job pass. PRs, forks, other branches and manual checks never receive
deployment credentials. A merged PR creates the eligible main push.

Every main push is eligible. GitHub concurrency permits one running and one pending
deployment; a newer eligible run replaces an older pending run. Intermediate commits
may therefore be skipped during a burst of merges. Uploads never overlap.

## Reproducible production input

`poe build` and `poe deploy` now select the audited retained public catalog,
not the unavailable historical semantic-atlas inputs. The candidate builder uses
only 174 tracked, byte-pinned public source files. The production certifier repeats
its independent reconstruction, requires the separate promotion receipt's exact
source contract, counts and 701-file public data inventory, then runs real desktop
and mobile browser acceptance before atomically installing `dist`.

The approved scope contains 433 metadata artists / 1,031 recordings. A separate
acoustic source has 17 artists / 55 descriptor-bearing recordings, of which
13 artists / 34 recordings share the strict feature contract; 6 artists / 11
held-out queries emit unvalidated suggestions. The union is 440 artists / 1,086
recordings. Coverage is shown in the UI. Source genre links, map layout and
acoustic suggestions do not establish musical relevance or EveryNoise parity.
No audio, private annotation or private benchmark result is published.

See [the source/payload contract](PUBLIC_CATALOG_CANDIDATE.md) and
`config/releases/retained-public-catalog-promotion-v1.json`. Code assets follow
reviewed main commits; public data facts remain pinned. Changing that data scope
requires a separate audited promotion. Environment input/output overrides are
rejected. The old certifier and its unavailable database/layout pins are preserved,
but no longer block the current public build. This is a replacement scope, not a
reconstruction of the old atlas.

## Upload and verification

The production job checks out the exact triggering SHA, installs Python 3.13.14,
Node 24.19.0, locked dependencies and Wrangler 4.102.0, then runs `poe build` without credentials. The next step invokes only the pinned
Wrangler uploader on that certified `dist`.
The PR build job exercises `poe build` without credentials or uploading artifacts.
Only the final upload step receives the existing `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` secrets. Their absence fails closed without printing values
or creating credentials. The Cloudflare app connection is distinct from CI auth.

The upload target remains the existing Direct Upload Pages project `opennoise`,
production branch `main`, custom domain `https://opennoise.horv.co` (also
`https://opennoise.pages.dev`). No service, credential or paid resource is created.
After upload, CI reads the new commit-bound `opennoise-release.json`, requires an
exact match to the locally certified marker and merged SHA, then verifies the
every served member against its byte hash, with the same 800-file / 12 MB bounds
and at most eight concurrent requests. No per-asset retry is performed. Only
old-commit propagation or 404 permits a bounded wait; access denial stops at once.
This does not recover or retry the old live-manifest route.

A successful upload alone is not reported as a verified new site. Require the
normal verification step and Pages deployment stage to succeed for the merged
commit. If ordinary workflow logs show missing credentials, stop there and report
that concrete integration blocker; do not inspect secret metadata or create keys.
