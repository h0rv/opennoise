# ListenBrainz aggregate-count source and rights review

**Status: private research only.** The response, request body, native provider
source snapshots, and complete receipts live under the ignored local path
`.cache/private/listenbrainz-counts/`. No aggregate values or provider source
code are committed. The private receipt explicitly sets `export_allowed`,
`serving_allowed`, and `model_input_allowed` to false. Do not copy this cache
into a public pack until redistribution rights for every contributing source
are established.

## Bounded probe

On 2026-10-03 UTC, one POST went to
`https://api.listenbrainz.org/1/popularity/recording` with the 36 canonical
recording MBIDs from the already verified
`data/examples/recording-facts/recording-facts.json` roster. It returned HTTP
200 and a response of 3,905 bytes. The local receipt records exact request and
response hashes, the UTC capture time, and all unavailable IDs. The request did
not query usernames, user listens, timestamps, genres, artist popularity, or
playback providers. No retry was sent. Raw response values remain private.

The official endpoint source documents the response as a recording MBID plus
`total_listen_count` and `total_user_count`, with paired null counts when no
statistics exist. It does not return listener identities or event rows. The
API is public, but small aggregates can still reveal information about a small
group. A public display gate of at least five distinct listeners is implemented
for future eligible use; this is not differential privacy and does not make
small-group values safe to publish.

## Data provenance and rights

The provider references below were checked on 2026-10-03. The private cache
retains exact response bytes and SHA-256 values for the relevant official pages
and pinned server sources.

- [ListenBrainz server README](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/README.md) calls ListenBrainz open data and says all its data is available for commercial use.
- [ListenBrainz data-dump guide](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/docs/users/listenbrainz-dumps.rst) distinguishes the public database dump, whose contents include statistics derived from submitted ListenBrainz listens, from the listens dump.
- [ListenBrainz dump-license note](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/listenbrainz/db/licenses/README.md) says the license file is included in data dumps and explicitly says the CC0 license does not apply to repository code. It does not name this API response or its combined inputs.
- [Popularity API implementation](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/listenbrainz/webserver/views/popularity_api.py) delegates recording counts to the provider's `get_counts` routine.
- [Popularity data implementation](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/listenbrainz/db/popularity.py) sums the ListenBrainz popularity table and the distinct `mlhd_` popularity table. The provider's [MLHD+ dataset page](https://metabrainz.org/datasets/derived-dumps#mhld) identifies that dataset separately and describes its Last.fm listening-history source. The [MetaBrainz datasets page](https://metabrainz.org/datasets) likewise lists ListenBrainz and MLHD+ as separate datasets.
- The API's combined output is therefore not proven to consist solely of ListenBrainz contributions covered by the CC0 dump notice. “Available for commercial use” is useful provider evidence, but it does not alone establish a specific CC0 grant or redistribution rights in the MLHD+ component. No explicit provider statement was found that licenses this blended endpoint result under CC0 or otherwise grants redistribution of all its source components.

Consequently this repository does not assign a public-data license to the
captured response. It remains a local probe artifact with all outward-use
permissions disabled. A future pure ListenBrainz dataset adapter can reuse the
bounded request, strict parser, receipt structure, and offline validation only
after the selected endpoint's source population and redistribution grant are
explicitly established.

## Privacy and use limits

The ListenBrainz [Terms of Service source](https://github.com/metabrainz/listenbrainz-server/blob/274281aee17dfe96d8278318d47483528dcc3c7f/frontend/js/src/about/terms-of-service/TermsOfService.tsx)
points to MetaBrainz's [privacy policy](https://metabrainz.org/privacy), which
says access logs include IP address, user agent, endpoint, and parameters. The
[GDPR statement](https://metabrainz.org/gdpr) says ListenBrainz listens are
personally identifying data and made public. This probe sent only a bounded set
of public recording IDs; it requested and retained no user identity, listen
event, or timestamp. The response is still local because aggregated counts can
support inference about small listener groups.

Even if rights are later resolved, these counts measure submitted listening
activity for this provider's bounded examples. They are not genre labels,
acoustic or cultural similarity, music-fit judgments, proof that an item is
music, global popularity, playback availability, or Spotify availability.
`bounded_example_rank` only orders eligible members of this exact closed roster
and is not a confidence or probability.
