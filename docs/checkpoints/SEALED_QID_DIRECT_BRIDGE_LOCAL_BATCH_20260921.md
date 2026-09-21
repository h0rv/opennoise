# Sealed QID direct bridge local batch

The clean local chain uses QID map hash
`dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449` and
sealed bridge output hash
`c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b`.
It contains 84 positioned genres, 862 grouped memberships, 959 direct P136
observations, 536 artists, and 118 net new artists. A terminal comparison
found exact membership equality with the older bridge.

The clean sidecar has hash
`dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73` and
records the same 84 genres, 862 grouped memberships, and 959 direct P136
observations. The merged local v2 candidate has 344 genres, 1,126 artists,
and 3,859 bound observations, with hash
`9ee2a464de74e0b681ea347163fda94afa6eb28e3189a4fa4e6d0ee3d708232b`.
The sidecar and merged candidate no longer consume the old v3 bridge or
reconciliation. The base v1 asset is unchanged.

Nothing here approves a release or deployment. A tracked promotion receipt,
public v2 schema, certifier, and browser gates are still missing. The nested
static v1 compatibility payload is not a release schema.
