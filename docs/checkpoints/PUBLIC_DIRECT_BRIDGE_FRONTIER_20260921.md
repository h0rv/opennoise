# Public direct bridge frontier checkpoint

The local-only candidate at `/tmp/public-direct-bridge-candidate.json` has
file SHA-256 `ce9f66e9af973291a2cbc0d8e1a8e636265b29581cc8504815892e035bfa97c6`
and canonical output SHA-256
`78d1a3589b39dfa6322efbc0ee0e1f7bef4d3c836c0b2b7471550f88f2246dc4`.

It is pinned to sealed `data/public.sqlite`
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`,
static discovery `b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8`,
reconciliation `a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`
(logical `ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0`),
and layout `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`
(logical `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`).

Fail-closed counts: 441 resolved reconciliations and 409 positioned seed links.
Twenty-five DB genres map to multiple positioned seed IDs and are deliberately
excluded rather than lexically choosing a seed. The resulting unambiguous
frontier has 355 DB genres, 311 genres with authorized direct evidence, 227
already in static discovery, 84 newly positioned direct genres, 959 exact
direct rows, 536 artists, and 118 net-new artists with exactly one authorized
MBID.

This is a review candidate only. It writes no static/public artifact, promotes
nothing, includes no one-hop claims, and reads neither a local v3 model nor
historical reference data. It is not a publication or certification decision.
