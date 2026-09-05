# Roadmap

## Current product

The default map uses the versioned open construction graph. It retains all
6,291 historical names and adds 746 public catalog anchors. The map has one
landscape surface with stable neighborhoods, semantic zoom, genre detail,
search, pan, zoom, and dark mode.

The historical Every Noise result is a separate local reference. It preserves
dated observed output for evaluation and does not provide inputs to the open
model.

The open graph contains 7,037 nodes and 3,317 edges. It has 441 exact identity
edges, 853 factual taxonomy edges, 1,940 compositional review edges, and 83
ambiguous review edges. It has no inferred artist memberships. Review edges
remain review candidates until a later evidence or human review run promotes
them.

## Release gates

- Verify the sealed source cache and provenance manifest.
- Rebuild or verify the public model and its logical hash.
- Build and verify the production map and browser evidence.
- Serve only the certified database and map artifact.
- Keep historical reference data separate from open model inputs.

The public release bundle is portable and cache only. It carries the sealed
derived cache, release configuration, model, map, and evidence. Raw source
replay is separate. A fresh checkout can rebuild a selected bounded local vault
from declared, network verifiable pins or restore a supplied source cache
receipt. Raw bytes with local only or non redistributable policy never enter a
portable store. The full release manifest source vault and derived database
are not yet reproducible from this workflow.

## Next data work

- Enrich the 6,291 immutable name seeds with public identities, hierarchy,
  overlapping communities, artist membership, and similarity while preserving
  each source claim.
- Complete the MusicBrainz release and track catalog chain beyond the current
  bounded 51 release and 491 track metadata slice.
- Keep metadata candidates separate from published metadata examples.
- Add a reviewed, versioned genre candidate workflow before publishing any new
  generated genre.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate.
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.

## Later experiments

- Evaluate alternative graph and hierarchy aware layouts against fixed
  evidence, then expose accepted layouts through the versioned public map
  contract.
- Evaluate historical output only after the open model is sealed and the local
  rights and rebuild gates pass.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
