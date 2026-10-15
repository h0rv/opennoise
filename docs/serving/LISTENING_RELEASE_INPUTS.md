# Listening release inputs and deployment

Status checked 15 October 2026, after main `14a8d3b`. No release upload, Pages
configuration, cloud storage or deployment was performed by this investigation.

The current explorer is static: 240,026,187 bytes across 7,902 served files,
largest file 1,202,882 bytes. The browser requests catalog shards and audio as
needed; it does not download the whole export on entry. All three collection
trees and coordinates were preserved by the root-map integration in PR40.
The [architecture HTML](architecture.html) explains the 44-feature Gaussian
baseline, component splits, within-collection neighbors and train-fitted PCA.

## Exact candidate release assets

Proposed destination: a new release in `h0rv/opennoise`, tag
`fma-local-inputs-20261015`, targeting `14a8d3ba748bad3717df045ef38bf38f0f05d55d`.
This tag/release does not currently exist as a result of this work. Keep assets
separate from Git source history and give input and output artifacts distinct
names and roles. Hash-pin downloads; never use a mutable `latest` URL.

| Asset already present in workspace | Bytes | SHA-256 | Role |
| --- | ---: | --- | --- |
| `OpenNoise-FMA-native-reconstruction-20261013.tar` | 335,523,840 | `a17e72750e67e560c8130ff4841ef5c37991387899ff222df0b3fe54b7fd99a3` | Retained native metadata/features, baseline and audit inputs. Does not by itself rebuild the latest audio site. |
| `OpenNoise-listening-133-root-map-20261015.zip` | 160,404,277 | `e171df9447d2bc94584cc59780dc760738e08e3d786f7444b3b836e82a91b97d` | Verified finished local output, including launcher and closed inventory. Deployment can consume its exact `OpenNoise/site` only after public promotion review. It is not a raw-input snapshot. |
| `OpenNoise-root-map133-evidence-20261015.tar` | 3,665,920 | `1f8cfd516b0653365fe0b9866c196255227398ab472e3d238938fefc2a65238b` | Source review, browser checks, unchanged-data comparisons and assembly evidence. |

Total for these three assets: **499,594,037 bytes**. They fit GitHub's documented
release limits: each file under 2 GiB, up to 1,000 assets per release; GitHub
documents no total release-size or bandwidth limit. Managing releases requires
repository write access. See [GitHub release documentation](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
This is a fit assessment, not confirmation of account access or successful storage.

## Actual access blocker

The available GitHub connector can create/review/merge source PRs but exposes no
binary release-asset upload action. Read-only shell probes returned:

```text
gh api repos/h0rv/opennoise/releases: Forbidden
gh api repos/h0rv/opennoise/pages: Forbidden
```

No token was requested, inspected or changed, and no alternate upload transport
was attempted. The required next action is an authorized release upload of the
named assets and verification of their returned asset IDs, download URLs, sizes
and hashes. Repository write through a source connector is not proof that the
execution environment can upload a 160–336 MB binary or configure Pages.

## Reproduction is not the same as publishing a snapshot

The native reconstruction archive preserves the original metadata/feature/model
stage. Rebuilding the latest listening site additionally needs the retained audio
capture/export manifests and bytes for all three collections, their frozen
neighbor packs, the descriptor-map artifact and the extension recipes. Those
are in the workspace and separately named evidence/capture archives. The two
large assets above do not claim a complete single-command reconstruction from
raw inputs of all later extensions.

A snapshot deployment can be reproducible without retraining: pin the completed
ZIP's SHA-256 and verify its exact closed inventory before publishing its `site`
directory. A code push must not silently mix newer UI files with an old verified
inventory. To update behavior, rebuild and independently verify a new complete
site artifact, then review the corresponding version/hash change in Git.

Full pipeline reproduction is a separate input-bundle task: enumerate each input
from the declared recipes, close the inventory, verify all hashes and offline
rebuild to a new destination. Do not substitute source receipt timestamps or
re-download mutable third-party data on every main push.

## Proposed CI boundary, not an enabled workflow

1. An authenticated uploader stores the reviewed, versioned release artifacts.
2. A source PR pins an exact release asset URL, byte size and SHA-256.
3. CI runs `poe check`, downloads that immutable asset with hard byte/time limits,
   rejects archive traversal/symlinks/duplicates, and verifies the closed file
   inventory and actual browser contracts. A hash mismatch fails closed.
4. After an explicit reviewed public promotion, a main-only deployment job uses
   narrowly scoped Pages permissions to publish the verified static directory.
   No raw training input or runtime inference service is needed on the host.

The existing bundle and catalog receipts explicitly describe a **local research
export**, and the existing `poe deploy` certifies a different semantic atlas.
Do not silently flip their authorization fields or wire that command to this
bundle. Current source credits and per-track license information must be retained
in any reviewed public promotion. No paid storage or new persistent grant is
needed merely to prepare and review this plan, and none was added.

GitHub Pages permits published sites up to 1 GB with a soft 100 GB/month bandwidth
limit. Cloudflare Pages Free permits 20,000 files with a 25 MiB per-file limit;
static requests are free and unlimited under its published pricing. The current
site fits both size limits. These are platform limits, not a promise of unlimited
GitHub audio traffic or of access from this environment.
[GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) ·
[Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/) ·
[Cloudflare static request pricing](https://developers.cloudflare.com/pages/functions/pricing/).

ccMixter is not an input: its first anonymous API request was denied by the
execution proxy with `Tunnel connection failed: 403 Forbidden`. No metadata or
audio was ingested, and the denial was not retried or bypassed.
