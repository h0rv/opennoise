# MusicBrainz release-group native observation checkpoint

The local-only observation pass verified the retained source cache receipt and
the exact 1,159,485,640 byte release-group archive before parsing. It then read
the first 10,000 valid release groups in archive order and stopped. The pass
took 6.2 seconds on the local archive. It does not estimate full-corpus
coverage, prevalence, or quality because archive order can bias the sample.

The report is stored only in
`.cache/musicbrainz-release-group-native-observation-v1/report.json`. It
retains each sampled release-group MBID, its exact LF-stripped record content
hash and byte length, plus native proper genre UUID, name, and signed source
vote count. Positive-count tags are separate facts. Zero and missing tag counts
are excluded. The pass reads no artist credits and cannot create artist facts
or memberships.

The report binds these local inputs and outputs:

- Source archive SHA-256: `6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`
- Source archive bytes: `1159485640`
- Source-cache receipt SHA-256: `2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`
- Member: `mbdump/release-group`
- Sampled member-record hash: `9032a5c5a93582f3a0b9e701fbcf36c418e2dea3b2a525fc84c8b7721e4b8b38`
- Sample receipt hash: `af12a42a044d485d888d31f077c97abf22e2b2e0b380b5b1bc4cec6f639beb08`
- Report logical SHA-256: `b479fc9742375c2447b475a380e6afb2247febb649683d18fcff7fc63268f3c9`

The sampled member-record hash binds the 10,000 retained record hashes and
byte lengths. It is not a hash of the full expanded archive member, because
the bounded pass deliberately stops after its fixed sample.

The report contains 10,000 sampled records and one malformed record before the
sample completed. Of the sampled records, 6,582 contain at least one proper
genre. The report retains 21,913 proper genre observations and 27,751 positive
tag observations. These counts describe only the fixed archive-order sample.
