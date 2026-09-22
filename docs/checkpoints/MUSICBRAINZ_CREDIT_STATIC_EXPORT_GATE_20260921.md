# MusicBrainz credit static export gate

The local gate builds an optional artist-detail-only asset from the retained
credit candidate. It verifies candidate/report/public/v2-discovery hashes,
semantic v2 discovery invariants, report integrity, exact MBID joins, and
active non-local display/export policy. It rejects an empty result.

Local smoke inputs: candidate `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`,
report `f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00`,
public DB `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`,
and v2 discovery `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`.
It produced 961 rows: 82 releases and 879 recordings, for 116 artists with
credit rows out of 1,126 visible artists. The temporary output hash was
`13da60e6767bab1c3c1168e5a4a93d0add1695c012152512163d8d7269505d7c`.

It remains local-only. Production requires release-custody of the candidate,
a tracked purpose approval, then browser-certified artist-detail integration.
