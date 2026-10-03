# Source-only clean-checkout checks

Clean-checkout [run 37102709523](https://github.com/h0rv/opennoise/actions/runs/37102709523)
passed on exact public commit `e863150cf2adb4509be1509874996c2fdcb37f7b`:
whole formatting, lint and typing; 43 passing Node tests with nine optional
export/input skips; 1,708 Python tests with 36 skips and no failures.
The [receipt](evidence/source-only-ci-e863150-20261003.json) binds this source
commit, tree, job and actual tool versions. It includes saved-model reconstruction
from the public text recipe. These results do not certify the current full-input
v8 website: its separate browser evidence remains unpassed and is now deferred by the
user's pipeline/modeling priority.

`.github/workflows/check.yml` runs the existing required `poe check` on a fresh
Ubuntu checkout for pushes, pull requests and manual dispatch. It installs Node
24 and Python 3.13, invokes `poe sync` to install the locked dependencies, then
uses the project's installed `.venv/bin/poe check`. The workflow has read-only
repository permissions, needs no secrets and restores no ignored source inputs.
It adds no task aliases, builds or deployment steps.

Static test files run serially through `node --test --test-concurrency=1` in
the existing Poe check. Clean-checkout run `37096763792` passed whole formatting,
lint and typing, then concurrent Chromium starts timed out in three browser
cases. Serial execution bounds competing browser processes; it removes no
assertions and does not turn missing-export skips into current-export evidence.

Every contract honors `CHROMIUM_PATH`. CI verifies and uses its installed Google
Chrome binary explicitly, avoiding incidental Chromium launcher selection;
startup failures retain bounded stderr and process exit details. Neither browser
timeouts nor behavioral assertions were relaxed.

The existing check runs formatting, lint, full typing, all static Node contracts
and Python unittest discovery. Tests that already require unavailable retained
inputs or an explicitly supplied browser/export keep their existing behavior;
the workflow adds no skips or relaxed criteria. Such skipped integration tasks
do not establish full source reconstruction, actual-export browser acceptance or
musical parity. The public UTF-8 FMA recipe supplies the exact portable example
bytes where its tests require them.

This workflow is a place to obtain an actual clean-checkout check result outside
the nearly full development sandbox. Adding it is not a passing CI result;
publication permissions and the actual GitHub run must be checked separately.
The freshly checked acceptance dossier has three recorded engineering passes and
nine unmet original gates, with automatic semantic pass false. This workflow does not
change the dossier, sealed exports or dated acceptance evidence.
