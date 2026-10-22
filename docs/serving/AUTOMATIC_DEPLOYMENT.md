# Default-branch production deployment

The `Checks and production deployment` workflow retains the existing required
`Clean-checkout poe check` job for every push, PR and manual check. Its deployment
job runs only after that job succeeds, on a push to `main` in `h0rv/opennoise`,
while `main` is the repository default branch. A merged PR creates that push.
PRs, forks, other branches and manual checks never run the deployment job.

Every main push is eligible. GitHub concurrency permits one running and one pending
deployment; a newer eligible run replaces an older pending run. Intermediate commits
may therefore be skipped during a burst of merges while the newest eligible build
waits for the active upload. This avoids overlapping production uploads.

The job also requires the separate public-input candidate build/browser check.
That job uses no secrets and publishes no generated artifact; see
[the candidate contract](PUBLIC_CATALOG_CANDIDATE.md). Passing it does not promote
the candidate or change the canonical production input selection.

The job checks out the exact triggering SHA, serializes production uploads, installs
Python 3.13, locked project dependencies and a pinned Wrangler, and invokes only
`poe deploy`. This preserves canonical input paths, SHA-256 pins, promotion replay,
static export and real browser certification before uploading `dist` to the existing
Cloudflare Pages project `opennoise` (`https://opennoise.horv.co`, also
`https://opennoise.pages.dev`). It creates no service, credential or paid resource.
Only the final deployment step receives existing `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` repository secrets. Missing inputs or secrets fail closed.

## Current activation boundary

On October 22, the existing Pages project was a Direct Upload project with no Git
source, and production deployment `6275accd-8077-47ac-add3-0b2990017f68` reported
commit `2721688dbef0e7f258eec9a073e9a6eeaf8ee851`. The current source checkout and
the clean CI checkout lack both sealed inputs:

| Input | Required SHA-256 |
| --- | --- |
| `data/public.sqlite` | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| `.cache/semantic-map-layout-v3/artifact.json` | `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972` |

Neither file is tracked, and no approved immutable CI retrieval location is
configured. The workflow deliberately reports this missing custody before it can
upload anything. Enabling the trigger alone therefore does **not** establish a
working deployment. The exact approved inputs must become available to the job
through a separately verified release-custody integration. No arbitrary URL,
mutable workspace directory or research export is accepted as a fallback.

GitHub CLI reads of branch, Actions secret and variable metadata returned
`Forbidden` during this task and were stopped. Secret availability is unknown;
the workflow checks it without printing values or acquiring credentials.
The authenticated Cloudflare app connection is distinct from CI credentials.

The retained-catalog demonstration, research annotations, private benchmark
aggregates and listening/research exports remain outside this deployment payload.
Publishing code does not select those artifacts for release. The prior semantic
atlas remains the approved deployment target, and its safeguards are unchanged.

After a deployment succeeds, verify its Pages trigger commit equals the merged
commit and its stage is `success`, then read the live
`opennoise-static-manifest.json` and check the reported input and asset hashes.
Do not describe an attempted workflow run or an unchanged live site as a new build.
