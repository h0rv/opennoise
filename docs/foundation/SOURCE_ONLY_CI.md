# Source-only clean-checkout checks

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
The current acceptance dossier remains one recorded engineering rebuild pass and
eleven unmet gates, with automatic semantic pass false. This workflow does not
change the dossier, sealed exports or dated acceptance evidence.
