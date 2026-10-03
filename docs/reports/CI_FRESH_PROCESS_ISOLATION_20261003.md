# Resource-sensitive fixture isolation: original failure and pending correction

The actual clean CI run at published commit
1997d45f12491e51638330f6c00889dc1a4c6e05 executed 1,771 tests and reported
three failures and four errors in [run 37117125200](https://github.com/h0rv/opennoise/actions/runs/37117125200). Formatting, source type checking and Node checks
had passed. The long unittest discovery process had already reached approximately
558 MB VmHWM before the native catalog and source-recovery fixtures ran. Their
unchanged 40 MB catalog and 35 MiB source-model native guards correctly refused
work. Catalog capture returned budget-aborted or partial outcomes, causing
assertions against projected custody to fail; source-model fixtures failed
before fitting. This original CI outcome remains a failure.

The correction changes only the test execution boundary for
SourceRecoveryCalibrationTests, WorkerTests and RecoveryTests. Each exact method
executes in a clean actual Python 3.13 process. Parent method accounting and
failure, error, skip, expected-failure, unexpected-success and subtest identities
are retained. Native memory guards, source receipts and fixture assertions remain
active. No production cap, Poe command, workflow, gate or expectation is weakened.

The helper bounds captured output, protocol bytes and elapsed time. It binds each
protocol to the actual spawned PID, Python-attested original argv, exact method
identity and one method start/stop. Boolean values cannot satisfy integer test
counts. Linux VmHWM is explicitly recorded before final protocol serialization;
this field is not claimed to be retained kernel cmdline or final-exit memory.
Method cleanup runs in the child. Deliberately failing transport probes live
outside discovery and are checked through private TestResult objects; real
resource-sensitive cases are not skipped. The three adopted classes have no
class/module fixtures; this helper currently isolates their method fixtures.

The local runtime stalled during the first patch and source-presence probe.
Those local tool outcomes remain unknown. Corrected source was prepared through
GitHub from the exact published parent for an independently reviewable draft.
No local test, formatting, type or CI pass is claimed. Reconcile workspace and
remote source after runtime recovery. Report actual new remote CI outcomes
separately before describing this correction as validated.

## Coordinated integration after executor recovery

The repair executor fetched draft PR #1 at
`20fa336abfafbce57b66410a20bad96148555fff` and reproduced all 12 `ty`
diagnostics. Its `ExceptionInfo` allowed a missing traceback with a non-null
exception, but unittest's callback contract accepts either a complete exception
tuple or the all-null tuple. The override also promised a narrower `run()`
return than the inherited contract. The follow-up uses `sys.exc_info()` with
real caught exceptions, accepts the all-null callback tuple, safely classifies
it, and matches the inherited optional return. No type suppressions were added.

The PR's bounded transport, outcome/subtest forwarding, seven transport tests,
three original commits and class-level isolation are preserved. A separately
validated minimal decorator implementation was not layered over this helper.
Three guard-rejection regressions were integrated from that repair: both catalog
workers must stop after headers without compression, custody or projected facts
when the actual process peak reaches the cap, and calibration preparation must
reject above-budget memory. Existing provenance and transport assertions remain.

All 31 focused tests (transport plus the three affected classes) pass locally.
The aggregate source-only check and the exact published SHA's GitHub Actions
result must be reported separately in the PR; this focused result is not a claim
that CI has passed. Existing optional source-only skips require sealed public
inputs, historical custody, retained discovery/layout artifacts, or actual
FMA/foundation/taxonomy/listening exports. No recovery archive or new skip is
needed for this repair; native limits and acceptance criteria are unchanged.
