# Musix

An open reproduction of https://everynoise.com/ built on open data.

## Tech Stack

Minimal, grug-brained stack:

* System dependency management: mise
* Language: Rust
* Web framework: https://github.com/tokio-rs/topcoat - static where possible, HTMX 4.0 for reactivity
* Databse: SQLite (identify the appropiate, FOSS, and up to date plugins/extensions for AI tooling: vector search, etc.)

Strict static analysis:

* Identify the strictest Rust lint and static analysis tools that catch bugs before they happen, so we can work on the interesting bits and ensure the code just works.

---

## Schemas

Let's use open data formats and schemas, that are modern, up to date, and flexible for late 2026.

We should store:

* Genres
* Subgenres
* Artists
* Albums
* Songs

Each of these, should be able to be broken down into individual embeddings and context.

## Machine Learning

This is the interesting part and requires the most research.

Read up on the author of https://everynoise.com/ blog posts and other resources.

## Data

Use open data where appropiate. Understand if we can scrape https://everynoise.com/ as a starting point.

Anna's archive also has exceptional music data and metadata to use.

Identify other resources too.

## MVP

* Visual, 2D mapping of music genres and subgenres, as detailed as possible.
* Be able to plugin artist names, to identify where they land on the map, and see similar artists to them (for example: Aphex Twin, Boards of Canada, and Four Tet should be similar)

