# Frozen musical review packet

Use this packet to collect independent judgments against the selected 150-artist open-build denominator. `declaration.json` freezes scope, seed, sample rules and interpretation limits; `cohort.json` preserves sampled exact identities and available credited recording refs. Source genre IDs, source tags, and evidence-volume strata are in the sibling coordinator-only `musical-review-packet-coordinator/selected150-source-key.json`; hide that key until judgments are collected. Candidate labels and neighbor pairs remain blank until the selected candidate outputs are frozen. The CSV files contain two blank reviewer rows per item and are not results.

Before distribution, a coordinator must freeze candidate outputs, populate displayed labels and A/B pairs, and store method-to-letter assignments in the sibling coordinator directory. Do not infer listening permission from MusicBrainz links: the separate exact-recording roster carries literal provider destinations for 9 of 36 examples, with availability and permission still unchecked. Check the provider for the reviewer and region, then record exact-match and access status.

Each item needs two independent reviewers. Retain both rows, uncertainty, unsupported judgments and access failures. Record adjudication separately. Region, language and era are unknown in the source roster; this packet cannot establish global coverage.

Rebuild with `python scripts/build_musical_review_packet.py --source PATH --provider-destinations PATH --output docs/foundation/musical-review-packet`. Input SHA-256 values are frozen in `declaration.json`; changing the source, selection rule or thresholds requires a new revision.
