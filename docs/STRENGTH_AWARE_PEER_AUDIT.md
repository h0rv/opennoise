# Strength-aware peer audit

`audit_strength_aware_peer_graph.py` is a local-only, source-neutral audit of
the direct binary and filtered release-group-support candidate artifacts. It
does not use H3 or historical inputs. The nine predeclared combinations of
shared artists (2, 3, 5) and binary Jaccard (0.005, 0.01, 0.02) are all
reported; no named genre cohort selects a threshold.

Selection is preregistered to require a non-dominated grid point on coverage,
non-giant collapse, deterministic edge-drop coassignment, direct-channel
ablation coassignment, support-channel ablation coassignment, and a bounded
derived-community size. If no unique point satisfies that rule, the audit
abstains. Named cohorts are only qualitative review material.

Strong edges only shape the derived display communities. Communities are
deterministic similarity partitions, not factual genre taxonomy. Weak edges
remain counted as navigation candidates. Cross-channel overlapping pairs are
reported separately, and deterministic edge-drop coassignment is a stability
diagnostic rather than a quality certificate.
