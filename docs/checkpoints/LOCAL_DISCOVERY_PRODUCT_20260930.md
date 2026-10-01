# Local discovery product checkpoint · 2026-09-30

The complete local product is `.cache/opennoise-discovery-bulk-20260930-v2/`.
Its root is the named-style atlas; `communities/index.html` opens inferred music
communities; `communities/source-explorer.html` preserves the exact direct-source
genre explorer, artist pages, and genre maps. Each page links to all three
explorers. The root atlas retains its separate artist maps and complete paginated
style cohorts.

The product adds navigation and working composition-provenance links. It does
not refit a model, change source features, add native memberships, or map inferred
communities onto named styles. Source observations, credited release context,
inferred style proposals, and inferred community memberships retain their parent
roles. Composition does not establish model quality; see the
[independent bulk review](INDEPENDENT_BULK_DISCOVERY_REVIEW_20260930.md).

## Exact lineage

| Binding | SHA-256 |
| --- | --- |
| Product logical receipt identity | `50d5d8e1d0f3a8ca84308aa06afa7556d2154de754d83472c7e189cd33d22216` |
| Product receipt bytes | `7d6127ef5a19ac38bc367f5527881cb4e8ab2b1e0690a5e837e1963d1bda3716` |
| Atlas logical receipt identity | `7f91c5db7198716c9fd4f2ccdfb14d3497becf74c02ffb4b7e1d03f8a94fdb95` |
| Community logical receipt identity | `3ca8632e4837ad8a01c08d9a8da0fdebf60eedba06f388ec23d1b997e4146c86` |
| Shared primary-v4 feature bytes | `2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252` |
| Shared primary-v4 feature receipt bytes | `281a0cdcf87498bad50f6e2fe9b145cf0e010c1ed7c3b48a832ae0b8a094f6d7` |
| Shared source preview logical identity | `0deaa234b5637ca734b6558022ad3e1fab1573ee45f7547e37b144deff1d84a9` |
| Atlas enrichment prediction logical identity | `70ea84650de3f95054f5fda34c4bcbb286365bfa5fc8d4f69b8b4bb54d3c4d13` |
| Atlas enrichment model identity | `650cc9dbead293cea81d214e7cdd0ddf6b99639ac9b503ddca4a68727fd45877` |
| Community model logical identity | `8bc5488c8861aaa89e88ea05513b9a9b6beb94b0ba63969ddb04d70d861d9556` |
| Composition builder bytes | `96b8c757327be7db529196b2bb30a3f8b08ed5e154d323000c5859978444092a` |

The verified atlas parent is `.cache/named-style-atlas-bulk-20260930-final/`.
The verified community parent is `.cache/community-explorer-bulk-20260930-v1/`.
The latter includes no enrichment prediction overlay, so its enrichment identity
remains null. It still shares the exact feature file, feature receipt, and source
preview identities with the atlas. Explicit conflicting enrichment identities
are rejected when a community overlay is present.

The product binds **97,472 files and 3,301,239,214 bytes**. Its parent artifacts
total 97,470 files; **97,467 retain exactly the parent SHA-256 and byte count**.
Only `index.html`, `communities/index.html`, and
`communities/source-explorer.html` change, and the receipt records each prior
and resulting byte binding. The two additional bound files preserve the raw
parent receipts at `provenance/atlas-receipt.json` and
`provenance/communities-receipt.json`. The product's `receipt.json` supplies the
current composition identity and complete file bindings.

The atlas parent contains 31,864 source musical values and 3,505 bounded artist
maps. Its final display recipe shows 3,920 dictionary or repeated candidates by
default. Reviewed biographical roles and cause-of-death labels remain available
as raw source candidates. This display filter preserves all source, cohort,
profile, geometry, prediction, and artist-map bytes from the initial bulk atlas.

## Construction and checks

The builder verifies both parent receipt identities and every declared file's
hash, byte count, and path before composition. It rejects unsupported scopes,
public or serving authorization, native-membership additions, lineage
mismatches, destination collisions, symlinked artifact directories, and output
outside the project cache. It refuses to overwrite any existing destination.

Unchanged files use hardlinks on this filesystem, preserving space. The builder
falls back to copying only across filesystem boundaries. Navigation HTML is
written to fresh temporary files and atomically replaces the product links;
the parent inodes remain unchanged. A final pass hashes every output artifact
and requires all differences to be one of the three declared navigation pages.
Every local HTML href and src must resolve to a bound product file, including
the generated receipt. Source explorer provenance links now reach the current
composition receipt instead of the absent original preview receipt.
Each navigation page also declares an inline empty favicon, avoiding an implicit
request for an absent favicon file. This adds no network request or artifact.

The ten focused tests cover receipt and artifact tampering, path escape, exact
feature/receipt/source lineage, enrichment conflicts, unsafe parent scope,
existing and out-of-cache destinations, dead HTML targets, complete crosslinks,
unchanged hardlinked data, and separate navigation inodes. Scoped Ruff formatting,
linting, and type checking passed with those tests.

The final product passed actual Chromium certification at the local preview:
18 screenshots and 80 requests, with zero HTTP errors, external requests,
media requests, or runtime errors. The browser followed the atlas → communities
→ source explorer → atlas path and exercised real artist maps, complete cohorts,
name and ID search, evidence roles, history, reload, mobile layouts, and the
final default-display filter. Evidence is
`.cache/opennoise-discovery-bulk-browser-20260930-v3/browser-report.json`.

Build a separate fresh destination from the sealed parents:

```sh
poe sync
.venv/bin/python scripts/build_local_discovery_product.py \
  --atlas .cache/named-style-atlas-bulk-20260930-final \
  --communities .cache/community-explorer-bulk-20260930-v1 \
  --output .cache/research-discovery-product
.venv/bin/python -m http.server 8890 --bind 127.0.0.1 \
  --directory .cache/research-discovery-product
```

The result is static metadata for local research. The receipt retains
`scope=local_research_only`, `public_export_authorized=false`,
`serving_authorized=false`, and `native_genre_memberships_added=0`.
MusicBrainz core metadata remains CC0-1.0; open tags remain CC-BY-NC-SA-3.0,
with both parents' attribution, noncommercial, and share-alike obligations
preserved. No deployment or sealed-source/model change occurs in composition.
