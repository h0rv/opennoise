# Open listening and playlist source research

This is a read-only source check on 2026-09-23. It does not change source
policy, the model, static assets, or deployment.

## Decision

Keep the existing qualified ListenBrainz aggregate as the only listening
source that may supply production similarity where the map contract permits
it. Its local-only holdout already outperforms the direct-IDF peer baseline at
Recall@20, 188 of 1,453 versus 74 of 1,453, although the cohort is
endpoint-conditioned and the arms have different candidate capacities. No
newly researched source is ready for ingestion. Public playlist access does
not establish that a person selected the tracks, and playlist membership does
not establish a genre claim.

The co-listen result is the practical source-priority finding. The aggregate
uses a five-distinct-user privacy floor and does not access raw listens or
listener identifiers. It is a retrieval result, not a precision estimate,
musical-similarity claim, factual membership claim, or production approval.
See the [source-isolated holdout](MUSICBRAINZ_DIRECT_CUSTODY_COLISTEN_HOLDOUT_20260923.md).

## New source findings

| Source | Access and fields | Decision |
| --- | --- | --- |
| Million Song Dataset Taste Profile | The official MSD project identifies Taste Profile as its user-data contribution. It has user ID, MSD song ID, and play count, rather than timestamped events or MusicBrainz IDs. MSD warns that song-to-track matching errors affect Taste Profile-linked song and artist metadata. [MSD](https://millionsongdataset.com/), [matching caveat](https://millionsongdataset.com/blog/12-2-12-fixing-matching-errors). | It needs the same aggregate privacy boundary as ListenBrainz, but an exact no-name-match MusicBrainz bridge is unproven. MSD tags and tagtraum labels cannot independently evaluate an MSD listening result. Do not acquire or use it as an exact-ID, independent-gold, or production source. |
| Spotify Million Playlist Dataset | The historical corpus contains one million public playlists from United States Spotify users between 2010 and 2017, with more than two million tracks and nearly 300,000 artists. Its fields include title, ordered Spotify tracks, edit time, and edit count. The official page now says it is not downloadable and directs requesters to Spotify Research. The sample was manually filtered, dithered, and given fictitious tracks, so Spotify says it is nonrepresentative. [Access status](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge). | "User-created" describes the collection origin, not manual or expert curation for each playlist. Spotify IDs have no verified exact MusicBrainz bridge. In addition to non-commercial, no-redistribution, and no-reidentification terms, the rules prohibit reverse engineering Spotify technology or intellectual property. The dataset is unsuitable for OpenNoise's reproduction work even if Spotify Research grants access. [Terms](https://rails-aws.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge/challenge_rules). |
| MusicBrainz collections | Public collections can contain exact recording, release, release-group, or artist MBIDs. The API can list a user's public collections and browse their contents, with the usual one-call-per-second ceiling. [API](https://musicbrainz.org/doc/MusicBrainz_API), [collections](https://musicbrainz.org/doc/Collections). | A collection can be personal holdings, a community project, or an arbitrary list. It is not a playlist and has no automatic thematic or human-curation meaning. Keep it as a low-priority, local-context possibility only. |

## Human and algorithmic playlist distinction

Classify a playlist only from source evidence retained with the receipt. Use
`editorial_or_human_attributed` only when the provider identifies a named
human or editorial organization and the evidence supports that reading. Use
`provider_or_algorithmic` when the provider calls it generated,
recommendation-based, radio, or personalized. Use `user_created_unverified`
when a provider says a user created it but does not establish manual selection.
Use `unknown` for all other public playlists. Playlist title, description,
creator handle, order, popularity, and genre words do not change the class.

## Method and bounded pilot

Spotify's MUSIG research used playlist co-occurrence alongside private Spotify
data, audio features, and genre prediction. It supports a simple sparse-count
co-occurrence baseline as a method, but it does not make private data, audio,
or genre labels available to this project. [MUSIG](https://research.atspotify.com/2021/10/multi-task-learning-of-graph-based-inductive-representations-of-music-content/).

The only laptop-sized pilot presently justified is a second ListenBrainz
account cohort. The existing neutral search route cannot currently produce a
selection because the public API returns a JavaScript browser-verification page
to a command-line request, rather than the documented JSON. The earlier
sandboxed request could not resolve the host. The one external retry on
2026-09-23 timed out, and a further external retry reached the host but
returned that verification page. It did not return a playlist-search response,
so there is no auditable account, playlist UUID, or selection manifest to use.
See the [cross-account feasibility
checkpoint](LISTENBRAINZ_CROSS_ACCOUNT_PLAYLIST_FEASIBILITY_20260923.md).

The official playlist API has no global, popular, recent, or other
username-free public listing. Its public listing route requires a known
username, and its exact-playlist route requires a known playlist MBID. The
import routes require authorization. Thus a second-account probe cannot use an
alternate public discovery call until the search endpoint returns its
documented JSON or an account or playlist ID is supplied independently.

When the documented route returns JSON, fetch at most ten playlists per
account and 200 unique recording MBIDs per playlist through the existing
bounded API adapter. Retain response receipts, playlist and recording MBIDs,
source-order membership, and unknown curator state. Do not retain a public
account name in the derived aggregate, serve it, or infer a person's identity.
Source-claimed JSPF artist URIs remain claims. Only a separate exact
MusicBrainz recording lookup can establish an artist credit.

The pilot should report only exact recording coverage, playlist-size
distribution, per-account normalized pair support, cross-account pair overlap,
and the count of exact verified credit bridges. It must not use title or
description text, merge into the ListenBrainz aggregate, assert curator type,
or produce genre, membership, ranking, model, evaluation, or public output.

The pilot is a coverage and independence check for the already stronger
aggregate signal. It is not an attempt to use playlist text or playlist
co-occurrence to replace the privacy-filtered listening result.

## Next safe work

Do not acquire a new corpus. Preserve ListenBrainz's privacy-filtered
aggregate boundary, and only consider a new source after a source-specific
approval records terms, the exact identifier bridge, a privacy design, and a
declared local-only signal role. A curated-playlist study would need receipts
from multiple independently attributed curator organizations and an
independent held-out evaluation. It must keep playlist text out of labels and
must not promote playlist co-occurrence into factual membership.
