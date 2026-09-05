# Musix

Build an open music map from public metadata and privacy safe aggregates.

The default public map is a 603 genre semantic map. It has a working
landscape view, semantic zoom, genre detail, and a local sealed release. The
workspace selector also exposes an Open 6,291 view and a Historical 6,291
view. Open is a public navigation graph. Historical is a dated, local only
compatibility view when its separately configured artifact is available.

The Open graph contains all 6,291 retained names, 1,059 edges, 5,243
components, and 5,173 isolated nodes. It has 216 factual taxonomy edges and
843 lexical review edges. It has 0 inferred memberships. Most names remain
isolated because the public catalog resolved only a bounded set of identities.
Lexical review edges are review candidates. They are not taxonomy, membership,
similarity, or artist evidence.

The local MusicBrainz research graph contains 724 matched names. It is a
calibration and research artifact with local research scope. It is not part of
the exportable public model.

Selecting a genre shows artists, albums, tracks, membership facets, and
similarity scores. Album and track entries are metadata examples selected from
bounded candidates. They are not claims about defining, popular, or
quintessential works. The current hydration slice contains 20 releases and
237 track listings. Every hydrated track is metadata only and is marked
non-playable.

No audio, previews, or music files are downloaded, stored, served, embedded,
or used for training. Source adapters use metadata only.

Artist membership evaluation is calibration only until an independent public
gold set exists. A calibration report cannot establish production quality.

The pipeline is: verified source artifact, typed source claim, SQLite
projection, versioned model, production map artifact, and sealed local release.
The portable release bundle contains the sealed derived cache and evidence. It
does not contain raw sources and does not close the raw source re-ingestion
gap.

Keep the stack small: Python 3.13.14, uv, mise, Poe, Litestar, Pydantic,
SQLite, HTMX 4, and vendored Cytoscape.js 3.34. The graph island handles
direct manipulation. HTML links, forms, and server rendered fragments handle
everything else.
