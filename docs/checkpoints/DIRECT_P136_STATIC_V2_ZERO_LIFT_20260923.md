# Direct P136 static v2 zero lift audit

The deployed v2 discovery asset represents 3,859 of the public catalog's 4,948
direct Wikidata P136 observations. The remaining 1,089 observations do not
have an automatically eligible, positioned catalog map binding.

The audit read the pinned public database, deployed v2 discovery asset, and
canonical semantic layout. Their SHA-256 values are:

| Input | SHA-256 |
| --- | --- |
| Public database | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| Deployed v2 discovery asset | `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c` |
| Canonical semantic layout | `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972` |

The 1,089 observations partition as follows:

| Reason | Observations | Genres | Artists |
| --- | ---: | ---: | ---: |
| The public label is ambiguous | 551 | 22 | 405 |
| The QID has multiple positioned seeds | 55 | 4 | 50 |
| The exact QID label resolves only to an unplaced seed | 20 | 7 | 16 |
| No unique exact public label to seed link exists | 463 | 134 | 303 |

The sealed QID map has 355 one to one positioned bindings. Of those, 311 have
direct P136 evidence, with 3,544 observations, and all 311 are already in the
deployed v2 asset. The other 44 bindings have no direct P136 evidence.
Therefore the safe, non-ambiguous, positioned frontier has zero genre, artist,
and observation lift.

The existing graph identity audit lists two `safe_exact` candidates that are not currently static
with two observations: Belgian hip hop to Stromae and humppa to Korpiklaani.
Both corresponding map nodes, `item688` and `item4405`, are unplaced in the
canonical layout. They are pending human review and are not positioned
candidates for static publication.

The audit changed no catalog row, static asset, publication receipt, build, or
deployment.
