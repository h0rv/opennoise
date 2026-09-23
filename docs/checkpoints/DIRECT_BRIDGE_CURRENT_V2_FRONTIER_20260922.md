# Direct bridge current v2 frontier

The direct bridge audit now accepts the certified v2 static discovery asset.
It verifies the v2 payload before reading its genre bindings. Verification
replays the payload hash, source accounting, reciprocal memberships, related
artist references, coverage, and the public database binding.

The current audit reads these inputs:

| Input | SHA-256 |
| --- | --- |
| Open construction graph v2 | `16a7387f1edeb1b7bf0dcc7689984944363f60841a7f03b23a3065c537fec8b1` |
| Certified v2 static discovery | `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c` |
| Public database | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

The fresh audit has logical SHA-256
`98011b222ad1a767b712ac7529fae07c06463a31fe3cf57030ea4cca90267f53`.
It contains 441 identity edges. The classifications are 245 `safe_exact`, 101
`review_only`, and 95 `conflicting_or_ambiguous`. Of the 441 edges, 328 already
have a static catalog bridge. The total remaining potential direct observation
lift is 561.

There are 29 `safe_exact` edges without a current static bridge. Their combined
potential direct observation lift is 2. The 245 `safe_exact` count is the full
classification count and is not the number of remaining review targets.

The regenerated packet and empty ledger are local cache artifacts. The packet
is bound to the same audit hash. The ledger has 441 pending rows, zero review
decisions, zero ready rows, and false catalog, static discovery, and publication
flags. No reviewer decision, catalog change, static asset change, publication,
build, or deployment occurred.

The next step is independent human review. Each proposed edge needs the two
independent approvals required by the ledger policy before it can become
`ready_for_separate_publication`. That state still requires a separate
publication process.
