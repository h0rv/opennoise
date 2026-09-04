# Roadmap

## Current product

The certified default is a 603-genre public semantic map with semantic zoom,
dark mode, genre detail, and a local sealed release. A separately retained
final-integration release has passed the current browser and data acceptance
gate; see `reports/PRODUCTION_MAP_QA_20260831.md`.

The product still needs simple, clearly labelled visualization switching.
Independent public visualizations must remain derived from the same public
model, with their own coordinate and evidence hashes. A historical
compatibility visualization is a separate, local-only option: it must never
blend Every Noise observations into the public graph.

The 6,291-entry Every Noise map remains a dated historical reference. Its H2
geometry is retained, and measured H3 membership coverage is available only
under a local-display policy. It is not yet an eligible integrated product
view because the source-data licence is unspecified and the full-map handoff
has not passed the integration gates in `HISTORICAL_COMPATIBILITY.md`.

## Release gates

- Verify the sealed source cache and provenance manifest.
- Rebuild or verify the public model and its logical hash.
- Build a production-map artifact with one taxonomy DAG, presentation-parent
  choices, similarity evidence, and monotonic LOD sets.
- Pass geometry, neighbor-quality, label, accessibility, interaction, and
  screenshot checks on desktop and mobile in light, dark, and system themes.
- Serve only the certified database and map artifact.
- Certify each selectable visualization and its switch behavior, including the
  public/default and any local-only historical compatibility view.

## Next data work

- Add bounded source adapters without changing the model or UI contract.
- Improve public artist, album, and recording coverage.
- Keep direct claims, one-hop evidence, hierarchy, and similarity separate.
- Add a reviewed, versioned genre-candidate workflow before publishing any new
  generated genre.
- Retain or distribute the sealed source-cache database needed to regenerate a
  certified release from a fresh checkout; a manifest alone cannot do this.

## Later experiments

- Evaluate alternative graph and hierarchy-aware layouts against fixed evidence,
  then expose accepted ones through a minimal, truthful visualization switcher.
- Evaluate historical output only after the open model is sealed.
- Add optional user-reviewed ML experiments in isolated modules. No audio files
  or audio-derived data enter the default pipeline.
