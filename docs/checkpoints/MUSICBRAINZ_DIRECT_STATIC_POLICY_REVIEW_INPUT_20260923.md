# MusicBrainz direct static policy review input

The local policy-review input reads the existing direct custody receipt and
local candidate manifest. It returned a pending review for the pinned direct
receipt output `a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9`
and candidate manifest output
`a8f0059e7c53c802af88f27d473f6fec35b8e2f137218470e9fc3bee1b71ee70`.

The input contains the exact sorted set of 412 placed candidate seed IDs. It
proposes this public source wording: "MusicBrainz proper-genre observation on
this artist record."

Any future quality report must include source coverage, duplicate count,
exclusion count, ambiguous-name rejection count, per-genre row counts, and
manually sampled public source links.

The input fixes its decision to `pending` and all public export, serving,
membership, and release gate fields to `false`. It does not authorize policy,
change `static-direct-discovery-v2`, modify `dist`, or run a deployment.

The create-only local command wrote
`.cache/musicbrainz-direct-static-policy-review-input-v1.json` on 2026-09-23.
Its file SHA-256 is
`015befc92f592bfec0478f0a8903e51a0a96a7d815f177354e51df259ebea676`, and
its embedded logical SHA-256 is
`d64779ef56306cbb97bd2eb9cb3396df38c55b85d11afd4611a9d3ffb0a07d84`.

```sh
.venv/bin/python scripts/write_musicbrainz_direct_static_policy_review_input.py \
  --direct-custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --direct-custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --local-candidate-manifest .cache/musicbrainz-direct-local-static-candidate-v1/manifest.json \
  --output .cache/musicbrainz-direct-static-policy-review-input-v1.json
```
