# Public layout lenses

This report covers the frozen seven-day public run on 2026-08-31. The build used Wikidata P136 and
P279 facts plus privacy safe ListenBrainz pair counts. It did not use Every Noise data, audio,
music files, or audio-derived features.

## Inputs

The job jointly scanned seven verified ListenBrainz increments dated 2026-08-24 through
2026-08-30. The compressed inputs total 1,514,835,361 bytes. It read 30,469,708 listens and found
993,589 usable listens with an artist MusicBrainz ID. It formed 30,903 artist pairs from 40,782
listener-day windows at a privacy floor of five. One malformed record was quarantined. Listener
identities were discarded before any aggregate left the bounded job.

The public catalog contained 294 direct Wikidata P136 observations, 247 distinct direct
memberships, and 174 P279 hierarchy edges. The final input had 1,525 artists and 168 genre
identities. It produced 10,400 propagated memberships, 7,610 directed neighbor rows, and 315
representative metadata rows.

The model input SHA-256 is
`93f79d72a03346f65572096b8efcad86cf21a1e51665774dc51865fc438da4ee`. The settings SHA-256 is
`d3dac19868e04b09f6fd24dacbe0c570da91f7c39979c8a029829be12bfed43a`. The logical model output
SHA-256 is `40ebb3ace12c47aca88d2c527d70a48e4bc64801cabd51bd9aca35298754f8d1`.

## Results

| Lens | Input | Placed | Unplaced | Input edges | Layout edges | Top-10 preservation | One-hop reference | Output SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `public` | one-hop similarity | 104 | 64 | 1,520 | 1,520 | 0.5173 | 0.5173 | `80398907a67765ea65573e21a187702b886a673e9995e7310bb7d14e7afa574d` |
| `public-direct` | direct similarity | 104 | 64 | 670 | 670 | 0.5090 | 0.4077 | `d26646857b3ee058251d0d477cc2fb566d343f698c53df2137a8d2aa7e1a0149` |
| `public-community` | one-hop communities | 104 | 64 | 1,520 | 892 | 0.5510 | 0.5510 | `898f38f260bdadb815664b3c64852b4db17371c41c499b0cce3e57d7fbd2db16` |
| `public-taxonomy` | P279 hierarchy | 167 | 1 | 174 | 174 | 0.3894 | not applicable | `9ac75b1e19ed0ee279061b8eb0f6cb8e02af3d43244fa129a50522825f7846d5` |

The one-hop lens remains the default because it preserves more of the learned graph than the
direct lens does when both are judged against the same reference. The direct lens remains useful
because every edge can be traced to direct membership evidence.

The community lens found eight groups in six iterations. It converged with modularity 0.5634. Its
coordinates differ from the default for all 104 placed genres, and its top-10 preservation is
higher. It is therefore useful as a separate view. It does not replace the default because the
group boundaries are learned and have no source-provided names.

The taxonomy lens placed 167 genres, including genres that lacked enough artist evidence for the
similarity lenses. It remains separate because subclass links do not mean that listeners or
artists are similar.

Every lens reproduced exactly, with aligned coordinate RMS 0.0. The final five-day, six-day, and
seven-day one-hop models had neighbor Jaccard values of 0.8658 and 0.8766 across successive
cutoffs. Their aligned coordinate RMS values were 0.0130 and 0.0055. The three-seed community
agreement was 0.8162. Independent source holdout was unavailable because Wikidata P136 was the
only direct facet with public embedding permission.

## Resources and artifacts

Joint aggregation took 208.772 seconds and reached 453,701,632 bytes of peak resident memory. The
final four-lens build took 996 milliseconds. Individual layout times were 29 milliseconds for the
default, 19 for direct, 22 for community, and 32 for taxonomy. The validation stage took 4.325
seconds after aggregation.

The model artifact is 24,156,646 bytes with file SHA-256
`06af8c607ec8eac881b8afb20c1667cc4b6455145a55f7bfd618ddea738800e6`. The validation report is
43,638 bytes with file SHA-256
`fb403c7a65e8fca7408c24d27d808bf3ea6d905c753117e21993f244f2d8f015`. Its logical output SHA-256
is `ecae909850c6ae2cac821ccfe488505f44ec2750e0d82397d04fbaecffe3efcb`.

The measured output is a bounded audit artifact, not a claim that the graph is complete. Sixty-four
genres had no usable similarity placement. Public serving keeps their reason keys so the interface
can distinguish missing evidence from a rendering failure.
