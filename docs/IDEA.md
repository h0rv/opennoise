# Musix

Build an open music map from public metadata and privacy-safe aggregates.

The map is a graph first. A genre can have many taxonomy parents, direct artist
claims, one-hop artist evidence, neighbors, representative albums, and tracks.
Every published relationship has a source, rule, score, version, and hash.

The public model is independent. It currently contains 603 qualified public
genres. The final 6,291 Every Noise entries are a dated historical reference.
They can be preserved and evaluated separately. They never become hidden input
to the public model.

The default product map is semantic: the overview shows umbrella regions.
Zooming keeps context and reveals genres, subgenres, and deeper descendants.
A display parent is a map choice. The full taxonomy DAG remains available as
data. The product also supports simple switching among separately versioned,
evidence-backed visualizations; a historical compatibility view is always
labelled, local-only when required, and never becomes input to the public map.

Selecting a genre shows data: artists, albums, tracks, compact membership
facets, and similarity scores. It does not play samples. Links leave the site
for metadata destinations where available.

No audio, previews, or music files are downloaded, stored, served, embedded,
or used for training. Metadata-only source adapters make new sources easy to
add without changing the model or UI.

The pipeline is: verified source artifact → typed source claim → SQLite
projection → versioned model → production-map artifact → sealed local release.
Every stage can be rebuilt and audited from its manifest.

Keep the stack small: Python 3.13.14, uv, mise, Poe, Litestar, Pydantic,
SQLite, HTMX 4, and vendored Cytoscape.js 3.34. If an ORM becomes necessary,
use SQLModel rather than declarative SQLAlchemy. The graph island handles direct
manipulation. HTML links, forms, and server-rendered fragments handle everything
else.
