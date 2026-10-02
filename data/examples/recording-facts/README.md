# Exact recording credits

This portable MusicBrainz CC0 pack contains 36 native recording lookup responses
captured on 2026-10-02. All ten benchmark artists have three exact credited
recordings; Aphex Twin and Four Tet have six each. Every requested identity is
retained in `selection.json`, including any missing results. This capture has
zero missing results and 16,511 response bytes.

Replay the raw bytes and compare the entire projection without network access:

```sh
.venv/bin/python scripts/capture_cc0_recording_facts.py \
  --output data/examples/recording-facts --verify-only
```

`verify_recording_fact_pack` checks the selection, exact source URLs, raw byte
hashes, permitted native fields, recording identities and explicit artist
credits. It reconstructs every projected row. Unexpected supplementary or media
fields fail verification. The capture command refuses existing outputs, freezes
selection before requests, permits at most 50 requests and 1 MB of response
bytes, follows no redirects and performs no retries.

These are fresh recording facts, selected from the existing bounded credit
examples. They do not replay historical search rankings or release editions.
They establish recording credits, with source durations and missing durations;
they do not establish genre membership, representative musical quality,
popularity, release-group credits or provider listening availability.

The older recording-search captures contain supplementary tags. Those original
mixed responses remain optional research inputs and are not copied into this
core-only pack. Native source fields here are restricted to recording identifiers,
titles, duration, video flag, disambiguation, first release date and artist credits,
with core artist identity/name/type/country fields. Source license:
<https://musicbrainz.org/doc/About/Data_License>.
