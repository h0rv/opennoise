# Musix

Musix is a local map of 6,291 music microgenres. It reproduces a pinned Every Noise layout and keeps source rights and provenance with each normalized record.

## Run the demo

Install [mise](https://mise.jdx.dev/), then run:

```sh
mise install
mise run bootstrap
mise run dev
```

Open <http://127.0.0.1:3001>. The first bootstrap downloads about 3.8 MB from a pinned source URL, verifies its byte count and SHA256, and loads the map. Later runs use the local content addressed vault and do not create duplicates.

## Development

Poe is the project task runner. uv installs the locked environment and runs each task.

```sh
uv sync --locked
uv run poe format
uv run poe check
```

Useful tasks are `format`, `format-check`, `lint`, `typecheck`, `test`, `schema`, `import`, `bootstrap`, `dev`, and `check`.

The app uses Python 3.13 or newer, Litestar, Jinja, Pydantic, standard library SQLite, and a self-hosted copy of htmx 4.0.0. It uses no ORM, Alpine, or custom JavaScript. The SVG map is rendered on the server, and htmx replaces search and map fragments.

The default database is `data/musix.sqlite`. Raw and normalized source artifacts stay in the ignored `data/vault` directory. The repository docs describe the reproduction method and local data policy.
