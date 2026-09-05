# Roadmap

## Current product

The certified default is a 603 genre public semantic map with semantic zoom,
dark mode, genre detail, and a local sealed release. Its landscape map works
from the certified production artifact.

The workspace selector exposes three separate views: Public, Open 6,291, and
Historical 6,291. Open uses the committed open construction graph and bounded
landscape responses. Historical remains a dated, local only compatibility view
and is unavailable unless its separate artifact and local display setting are
configured.

The Open graph retains all 6,291 names. It contains 1,059 edges, 5,243
components, 5,173 isolated nodes, 216 factual taxonomy edges, and 843 lexical
review edges. It contains no inferred memberships. Its sparse coverage and
review only edges are known limits, not missing evidence to fill by guessing.

The local MusicBrainz research graph covers 724 matched names. It is not part
of the exportable public model. Its scores and landscape are research output.

## Release gates

- Verify the sealed source cache and provenance manifest.
- Rebuild or verify the public model and its logical hash.
- Build and verify the production map and browser evidence.
- Serve only the certified database and map artifact.
- Keep Open and Historical view boundaries explicit in the selector and API.

The public release bundle is portable and cache only. It carries the sealed
derived cache, release configuration, model, map, and evidence. Raw-source
replay is separate: a fresh checkout can rebuild a selected bounded local vault
from declared, network-verifiable pins or restore a supplied source-cache
receipt. Raw bytes with local-only or non-redistributable policy never enter a
portable store. The full release-manifest source vault and derived database are
not yet reproducible from this workflow.

## Next data work

- Complete the MusicBrainz release and track catalog chain beyond the current
  20 release and 237 track hydration slice.
- Keep metadata candidates separate from published metadata examples.
- Add a reviewed, versioned genre candidate workflow before publishing any new
  generated genre.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate.
- Expand source-cache replay until every selected release-manifest input can
  be acquired or restored, ingested, and replayed into the certified database.

## Later experiments

- Evaluate alternative graph and hierarchy aware layouts against fixed
  evidence, then expose accepted layouts through the versioned public map
  contract.
- Evaluate historical output only after the open model is sealed and the local
  rights and rebuild gates pass.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
