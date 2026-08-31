# Data bootstrap plan

Verified on 2026-08-30.

The first local map can start with 6,291 historical Every Noise genre names and display coordinates. The pinned HTML copy is small, stable, and more complete than the other name lists checked for this project. The importer must remove all preview URLs, Spotify identifiers, Spotify links, and sample track text. The remaining names, pixel positions, colors, and font sizes stay local under the user's authorization.

Wikidata should provide the first open hierarchy and alias layer. MusicBrainz should then provide stable artist identities and relationships. ListenBrainz should wait until the static metadata import works, because even its sample is 247 MB and the current full archive is 205 GB.

The machine readable source list is [data_sources.toml](../config/data_sources.toml). It pins each tested artifact, expected byte count, checksum, format, rights policy, and adapter order. No source file or secret is stored in the repository.

## Adapter order

The adapters should run in the following order:

1. `enao_html_map_v1` reads the pinned 6,291 point HTML copy. It creates local genre records and a separate legacy display layout. It must not import audio preview data or Spotify identifiers.
2. `enao_watch_csv_v1` checks 5,453 older names and coordinates against the first source. It should record differences as separate claims rather than overwrite the first source.
3. `enao_names_json_v1` adds a 6,043 name comparison set. It has no coordinates and is not the canonical count.
4. `wikidata_sparql_genres_v1` adds CC0 labels, aliases, parent relations, origins, inception dates, MusicBrainz genre IDs, and Every Noise IDs.
5. `musicbrainz_artist_json_dump_v1` adds artist identities, aliases, and relationships after a streaming archive reader has passed its limits and replay tests.
6. The MusicBrainz PostgreSQL adapters are the complete fallback. The core archive is CC0, while the derived archive contains the user tags needed for genre associations under CC BY-NC-SA 3.0.
7. The ListenBrainz sample validates listen parsing and privacy thresholds. The full and incremental adapters remain disabled until the sample graph has passed evaluation.

The priority number in the manifest controls execution order. It does not control claim authority. Each source keeps its own provenance, and claim selection uses an explicit rule.

## Every Noise inputs

The best first source is the pinned `quint-t` HTML snapshot. The repository has no license file and gives no separate data license. The snapshot contains 6,291 genre elements and is 3,789,046 bytes. Its SHA256 is `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`.

The HTML includes Spotify preview URLs, track IDs, links, and sample track descriptions. The adapter must discard those fields before it creates any catalog record. The accepted local fields are the item number, genre name, `left` and `top` pixel positions, text color, and font size. The positions must be stored as `legacy_display_coordinate`, because they are display output rather than a disclosed semantic embedding.

EveryNoise-Watch is the only reviewed Every Noise artifact with an explicit data license. Its `datapackage.json` names `genre_attrs.csv` as a resource and declares CC BY-SA 4.0 for the package. The repository's MIT code license is separate. The CSV contains 5,453 records and is 178,804 bytes. Its SHA256 is `21d9e576fd3f0ae0ec2db46f72d20043f3aafd1ec84d8c14da35e58ecc5ca367`.

The license statement is usable evidence for that CSV, although it does not establish that the publisher had authority to relicense every upstream value. The default project policy is therefore still local only. A later export review can consider attribution and share alike requirements.

The Scottsdale JSON list has 6,043 values, despite the repository's claim of 6,044. The file is 120,730 bytes and has SHA256 `9e9834811bdadfa90f19653a4ad522a4e8b5ac1a3321c1d1ac6b7e2738a73712`. The repository has no license file and no separate data license.

The reviewed Geeoon output has no separate data license. Its repository level CC0 file does not say that the upstream genre data is CC0. The official public mirror also gives no data license. The mirror was visible in a browser during this review, but it returned HTTP 403 to an ordinary `curl` request. Musix must not work around that block.

The default Every Noise policy is `user_authorized_local`. It permits local normalization, search, display, embedding, and training. It denies raw export, metadata export, and redistribution. The user can review later model work before any local training runs.

## MusicBrainz inputs

MusicBrainz publishes complete PostgreSQL snapshots twice a week. The core `mbdump.tar.bz2` archive contains artists, releases, recordings, works, areas, aliases, identifiers, genres, and relationships. MusicBrainz licenses the core archive as CC0. The `mbdump-derived.tar.bz2` archive contains annotations, ratings, tags, and search data under CC BY-NC-SA 3.0. Genre associations need the derived archive because MusicBrainz represents them through user tags. The official [download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download) lists both the contents and the separate licenses.

The snapshot verified for this manifest is `20260829-002439`:

| Archive | Bytes | SHA256 |
| --- | ---: | --- |
| `mbdump.tar.bz2` | 7,480,013,679 | `6e6bae8db4f8be39cc29c510b0e55d44cf923fbbb09393024655789b66a76a85` |
| `mbdump-derived.tar.bz2` | 513,721,489 | `646d6edadb0ec0bc7fdcb530b8092ab9510c2ad2ec32825849e01a55f7e8cc78` |

MusicBrainz also publishes entity centered JSON archives. The verified artist archive is `artist.tar.xz` from snapshot `20260829-001001`. It is 1,695,597,804 bytes and has SHA256 `396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d`. The server returns `application/octet-stream` for all three archives.

The JSON adapter must apply the MusicBrainz license by field. Core identity fields are CC0. User tags and other supplementary fields remain CC BY-NC-SA 3.0 even when the JSON serializer puts both classes in one record. The importer must create separate claims and policies when a record contains both classes.

The `LATEST` files contain the current snapshot directory name. A resolver should read `LATEST`, validate that it matches `^[0-9]{8}-[0-9]{6}$`, then build archive and checksum URLs. Production imports should store the resolved directory, exact archive URL, checksum file, byte count, response headers, acquisition time, and archive SHA256.

Replication packets are not part of the bootstrap. They update a complete MusicBrainz server each hour, require a feed token, and use CC BY-NC-SA 3.0. A twice weekly immutable snapshot is simpler for the first local build. Sources: [MusicBrainz database](https://musicbrainz.org/doc/MusicBrainz_Database) and [Live Data Feed](https://musicbrainz.org/doc/Live_Data_Feed).

## Wikidata inputs

Wikidata structured data in its main, property, and lexeme namespaces is CC0. The [official licensing page](https://www.wikidata.org/wiki/Wikidata:Licensing) is the license basis.

The first adapter should use the Wikidata Query Service and store its response as an immutable local snapshot. The query in the manifest selects music genres through `instance of` and `subclass of`, then gets aliases, parent genres, country of origin, inception date, MusicBrainz genre ID `P8052`, and Every Noise at Once ID `P9881`. The adapter should send a clear user agent, request SPARQL JSON, use a bounded timeout, and retry only `429` and transient `5xx` responses. It should split the query by QID or property when the public service times out. For a known, bounded set of QIDs, `https://www.wikidata.org/wiki/Special:EntityData/{qid}.json` is a second strategy that avoids a broad SPARQL query and still returns labels, aliases, statements, ranks, qualifiers, and references.

The complete dump is an offline fallback, not an MVP download. The verified dated JSON dump is `wikidata-20260824-all.json.bz2`. It is 102,835,325,297 bytes and its official SHA1 is `d951e647609249d1dc2e351ac5590d631d78008e`. The JSON file is one large array, so the adapter must stream array elements instead of loading the file into memory.

The verified truthy RDF alternative is `wikidata-20260826-truthy-BETA.nt.bz2`. It is 43,329,477,419 bytes and its official SHA1 is `84766f420cf03af0e307fc48ed466f9a0c25bae9`. Truthy RDF omits deprecated statements and keeps the best ranked value, so it is smaller but loses qualifiers, references, and competing claims. Musix should use the JSON dump when statement detail is required.

Wikidata finishes different formats on different dates. A resolver must select the dated directory that actually contains the chosen file and its checksum. It must not assume that every `latest-*` link belongs to the same snapshot date. The official [entity dump index](https://dumps.wikimedia.org/wikidatawiki/entities/) shows the current files and sizes.

## ListenBrainz inputs

ListenBrainz makes public listen data and user supplied text available under CC0 in its [terms of service](https://listenbrainz.org/terms-of-service/). Full dumps are normally created on the 1st and 15th of each month, and incremental dumps are created daily. Incremental dumps do not remove deleted listens, so an exact refresh needs a later full import. Sources: [dump documentation](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html) and [update intervals](https://listenbrainz.readthedocs.io/en/latest/general/data-update-intervals.html).

The current mirror does not exactly match the general documentation. As checked on 2026-08-30, the newest full directory is dated 2026-07-12 and contains one 205,073,162,240 byte uncompressed tar file intended for Spark. The newest incremental archive is a 191,259,244 byte `tar.zst` from 2026-08-30. The official data page also reported current statistics instability. A resolver must inspect the mirror instead of predicting a path from the nominal schedule.

The documentation also describes a `listenbrainz-public-dump.tar.zst` with users and derived artist, recording, and release statistics. No current public database archive was visible in the official mirror index during this review. The bootstrap must therefore compute its own privacy thresholded aggregates from the sample and must not invent a URL for the documented archive. The public statistics API is useful for spot checks, but it is a live API rather than a reproducible bulk snapshot.

| Archive | Format | Bytes | SHA256 |
| --- | --- | ---: | --- |
| Sample from 2025-06-10 | `tar.zst` | 246,734,240 | `509282544c50b324db8dfb4e33a5af4012f514c153da077a0fb07f093956168b` |
| Full Spark dump 2593 | `tar` | 205,073,162,240 | `17cf9ec7e528265d84d536bf89a8e58aa01dda2b8834a3a515e54130be8ba52a` |
| Incremental dump 2644 | `tar.zst` | 191,259,244 | `d98da81fd4552521ecda22d8242ddd0b9359afb8c302e2f7b4b24c31a2f41789` |

The sample is the only ListenBrainz input recommended for the initial implementation. The adapter should use MusicBrainz identifiers when present, hash or drop user identifiers before graph materialization, and enforce minimum support before it writes a co-listen or transition edge. Raw listens stay in the corpus store, and the catalog receives only thresholded aggregate edges.

## Retrieval and verification

The source resolver must create `data/source-cache` and `data/staging` as ignored local directories before it downloads anything. It must refuse a download when a source is disabled, a policy is missing, free disk is below twice the expected compressed size, the server's byte count differs from the manifest, or the checksum fails.

The following commands fetch the three small Every Noise inputs. They are the only downloads needed for the initial genre map:

```sh
mkdir -p data/source-cache/enao

curl --fail --location --continue-at - \
  --output data/source-cache/enao/quint-index.html \
  https://raw.githubusercontent.com/quint-t/Every-Noise-at-Once/e80265defc743b307586ac0a7a5c72d2dacdf409/index.html

curl --fail --location --continue-at - \
  --output data/source-cache/enao/genre_attrs.csv \
  https://raw.githubusercontent.com/AyrtonB/EveryNoise-Watch/4d3febe3762a555ac197524eea97a0f2825652de/data/genre_attrs.csv

curl --fail --location --continue-at - \
  --output data/source-cache/enao/genres.json \
  https://raw.githubusercontent.com/Scottsdaaale/List-of-All-Spotify-Genres/e604552252dbebb83a99a3d5a608c72e2886dc49/formats/genres.json
```

Verify exact bytes and checksums before parsing:

```sh
wc -c data/source-cache/enao/quint-index.html \
  data/source-cache/enao/genre_attrs.csv \
  data/source-cache/enao/genres.json

sha256sum data/source-cache/enao/quint-index.html \
  data/source-cache/enao/genre_attrs.csv \
  data/source-cache/enao/genres.json

rg -o 'class="genre scanme"' data/source-cache/enao/quint-index.html | wc -l
```

The expected count from the final command is `6291`. The CSV must have 5,454 lines including its header. The JSON array must contain 6,043 strings.

The MVP provides one verified bootstrap command for the pinned Every Noise source:

```sh
uv run poe bootstrap
```

The command downloads the pinned source when it is absent, checks its exact byte count and SHA256, stores the bytes in the content addressed vault, adapts them to typed records, imports them, and publishes the layout. Repeating the command reuses the same import attempt and does not create duplicate entities. Future large source adapters should expose separate resolve, fetch, verify, and adapt steps before they are enabled.

The Every Noise adapter should emit the current importer boundary as one object per line:

```json
{"type":"genre","external_id":"enao-legacy:item1","name":"pop","slug":"pop","aliases":[],"identifiers":[{"type":"source_id","namespace":"enao-legacy","value":"item1"}]}
```

The adapter should write layout data to a separate local file until the catalog importer supports typed layout observations:

```json
{"external_id":"enao-legacy:item1","x_px":783,"y_px":4997,"color_hex":"#ad8907","font_size_percent":160,"source_sha256":"1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180"}
```

Every adapter run must record the source ID, snapshot, original URL, resolved URL, response content type, response byte count, checksum, acquisition time, adapter version, policy version, accepted count, rejected count, and output checksum. A parser should fail when a required field changes shape. It should quarantine a record when a name is empty, a coordinate is outside the observed map bounds, a color is invalid, or the same source ID has conflicting content.

## Evaluation corpus

The evaluation corpus must cover genre family, region, era, evidence volume, language, and script. The manifest sets a minimum of 240 canonical genres and fixed seed `20260830`. The sample includes at least 12 genres from each of 16 broad genre families, 10 from each of 13 region groups, and 20 from each era bucket. One genre can satisfy more than one quota.

Selection should follow a fixed process:

1. Build candidates from Wikidata and MusicBrainz, then attach the local Every Noise crosswalk. Keep an explicit `unknown` value instead of guessing a region or era from a genre name.
2. Group the canonical genre and all of its aliases before splitting. Put the whole group in train, validation, or test so an alias cannot leak across splits.
3. Use deterministic stratified sampling over the axes in the manifest. Within each cell, sample high, medium, and low evidence genres so popular genres do not dominate.
4. Freeze the selected QIDs, MBIDs, source snapshots, labels, strata, and split in a versioned JSON Lines file. A source update creates a new evaluation version rather than silently changing the old one.

The held out set is 20 percent of canonical genres. Regional scenes, non-English labels, non-Latin scripts, older genres, current internet genres, and disconnected graph components must all appear in the held out set. No one artist should supply more than one percent of evaluation examples, and no one source should define the expected answer by itself.

Search evaluation uses aliases and spelling variants from sources that were not used to construct the query index. Neighborhood evaluation needs agreement from at least two approved sources or a user reviewed judgment. Every Noise neighbors and coordinates can be one local historical benchmark, but they cannot be the only ground truth. Layout evaluation measures local neighborhood preservation, disconnected component coverage, and stability across fixed seeds. It does not score visual resemblance to one old map as correctness.

The first review packet should contain 80 genres selected evenly across family, region, era, and evidence volume. For each genre, show the ten baseline neighbors with their supporting shared artists, tags, hierarchy edges, or co-listen counts. The user reviews the questionable pairs and the proposed strata before any learned representation is trained. The reviewed packet becomes a versioned evaluation artifact, not training data by default.

## Pipeline acceptance checks

The source and adapter work is ready when all of the following checks pass:

- The manifest parses, source IDs and priorities are unique, and every source has an explicit decision for all eight uses.
- Each enabled source resolves to the expected content type and byte count, then passes its pinned checksum.
- The first adapter emits exactly 6,291 unique source IDs and no preview URL, Spotify ID, Spotify URL, or sample track field.
- Repeating an adapter with the same bytes and version produces byte identical JSON Lines and layout output.
- The rights gate denies both raw and normalized export for all four Every Noise sources.
- The evaluation sampler meets every quota, keeps alias groups in one split, and produces the same result from seed `20260830`.

Large imports should also pass archive path checks, decompression limits, record size limits, checkpoint recovery, and low disk tests. A ListenBrainz graph must prove that its aggregation threshold prevents a rare individual listen pattern from reaching the catalog.
