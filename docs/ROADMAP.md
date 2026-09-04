# Roadmap

## Current product

One semantic map is the product. It uses a qualified 603-genre public model,
semantic zoom, dark mode, genre detail, and a local sealed release.

The 6,291-entry Every Noise map is a historical reference. It remains separate
from public modeling and can be used for compatibility and evaluation work.

## Release gates

- Verify the sealed source cache and provenance manifest.
- Rebuild or verify the public model and its logical hash.
- Build a production-map artifact with one taxonomy DAG, presentation-parent
  choices, similarity evidence, and monotonic LOD sets.
- Pass geometry, neighbor-quality, label, accessibility, interaction, and
  screenshot checks on desktop and mobile in light, dark, and system themes.
- Serve only the certified database and map artifact.

## Next data work

- Add bounded source adapters without changing the model or UI contract.
- Improve public artist, album, and recording coverage.
- Keep direct claims, one-hop evidence, hierarchy, and similarity separate.
- Add a reviewed, versioned genre-candidate workflow before publishing any new
  generated genre.

## Later experiments

- Evaluate alternative graph and hierarchy-aware layouts against fixed evidence.
- Evaluate historical output only after the open model is sealed.
- Add optional user-reviewed ML experiments in isolated modules. No audio files
  or audio-derived data enter the default pipeline.
