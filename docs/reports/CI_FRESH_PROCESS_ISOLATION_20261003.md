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
