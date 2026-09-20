# Source-neutral reconstruction checkpoint

`certify-reconstruction-checkpoint` writes one small, deterministic manifest
over the sealed open signals. It binds the evidence graph database and receipt,
the construction certificate, full-graph membership signal, cold-label identity
alignment, co-listen neighborhoods, hierarchy fusion, and semantic layout by
both file bytes and logical output hash. Every construction artifact must cover
the same 6,291 stable seeds and declare that historical input was not read.
The review-only co-listen membership-transfer artifact and receipt are also
required construction inputs. Its candidates remain separate from observed
membership support.

Run from any checkout or linked worktree:

```sh
uv run poe certify-reconstruction-checkpoint
```

The default output is `.cache/reconstruction-checkpoint-v1.json` in the shared
repository cache. The command uses the full-vocabulary cold alignment by
default, binds its release-group vocabulary artifact and receipt, and writes no
model data. A historical report may be supplied explicitly with
`--historical-evaluation`; it is bound under `evaluation_inputs`, never under
`inputs`, and is terminal evaluation-only. Construction certification does not
read historical data unless that optional argument is supplied. The hierarchy
artifact receipt is optional while the hierarchy producer has not emitted one;
when supplied with `--hierarchy-receipt`, its bytes and logical hash are bound.

The manifest reports five axes separately: identities, memberships,
neighborhoods, hierarchy, and coordinates. Membership and neighborhood axes
remain `not_evaluable` even when the optional historical report is bound,
because that legacy report does not hash-bind the current full-graph and
co-listen candidates. Identity, hierarchy, and coordinate axes likewise remain
`not_evaluable` until an independent held-out reference binds the exact
candidate lineage. Missing historical positives are unknown, not negatives,
and no axis is converted into an Every Noise parity claim.

The separate `membership_transfer` section reports 402 review candidates, 60
eligible cold artists, 6 abstentions, and positive-only held-out recall beside
the train-only popularity baseline. These are review diagnostics, not factual
membership counts.
