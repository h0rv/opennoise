# MusicBrainz credit portable static local gate

The portable credit custody package can now supply the candidate database and
report to the existing strict artist-detail static-export gate without reading
`.cache`. The local wrapper restores those two bytes into a temporary directory
from `config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json`,
then passes them to the unchanged gate.

This is not a fresh-checkout public build path. The other two gate inputs are
not tracked portable inputs:

- `data/public.sqlite` is ignored by `/data/*.sqlite`; its required SHA-256 is
  `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.
- The v2 discovery asset is ignored under `dist/`; its required SHA-256 is
  `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`.

The tracked custody scope is deliberately `custody_only` and cannot replace
the gate's separate `CreditMetadataPublicationApproval`. A local caller must
provide that approval, the exact public database, and the exact discovery
asset. The wrapper does not choose `dist` or deploy; the caller supplies its
explicit output path.

The fixture test verifies that a restored candidate still requires and passes
the existing public-input, exact-MBID, policy, and approval checks. Once the
two public inputs and a real release approval have portable custody, the local
command is:

```sh
uv run python scripts/export_portable_musicbrainz_credit_static_metadata.py \
  --credit-receipt config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json \
  --credit-object-store data/release/musicbrainz-credit-catalog-v1/objects \
  --public-database /path/to/public.sqlite \
  --static-discovery /path/to/static-discovery.json \
  --approval /path/to/credit-approval.json \
  --output /tmp/musicbrainz-credit-metadata.json
```

Browser-certified artist-detail integration and deployment remain separate.
