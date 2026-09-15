# Stack and architecture

## Runtime

- Python 3.13.14 is pinned by `.python-version` and mise.
- uv owns the lockfile and virtual environment.
- Poe is the task runner.
- Ruff formats and lints. ty type-checks.
- mise and uv reuse the project environment and hard-linked cache across runs.

## Delivery

- Cloudflare Pages serves one exported directory. There is no application
  server, API, template engine, or runtime database in the delivery path.
- `poe export-semantic-pages` validates one semantic-layout artifact and emits
  HTML, CSS, JavaScript, JSON, and Pages headers into an empty `dist/`.
- `poe dev` is a loopback-only static file server for that exported directory.
- The Canvas renderer owns pan, zoom, selection, search, and semantic LOD from
  the exported JSON. CSS owns light, system, and dark appearances.

## Data

- Pydantic models parse every external boundary and public contract.
- Standard-library `sqlite3` performs persistence. The project does not use an
  ORM today. If persistence grows past direct SQL, SQLModel is the chosen ORM;
  declarative SQLAlchemy is not.
- `adapters/` turns one source into typed records. `clients/` transports bytes.
  `pipeline/` owns manifests, policies, checkpoints, provenance, and release
  sealing. `catalog/` projects normalized entities. `ml/` builds and validates
  model artifacts. Exporters project verified artifacts into static assets.
- The object-store protocol uses validated relative keys and paths. The local
  content-addressed implementation is current. R2 or S3 only needs another
  implementation of the protocol.

## Boundaries

- The public model and the 6,291-entry historical Every Noise reference are
  separate datasets and products.
- The qualified public model currently has 603 genres.
- No audio or music files cross the source boundary.
- Raw listening events and listener identity do not cross the aggregate
  privacy boundary.
- A model, map, and release are immutable artifacts. The exporter reads a
  configured, sealed artifact; Pages does not rebuild or fetch on demand.
