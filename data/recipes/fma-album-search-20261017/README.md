# Native album directory and search

The retained catalog already had detail pages for 15,713 native albums but no
album-title search or album directory. This increment adds an optional lazy
Albums entry and title/native-ID search with 100-result pages, linking the
existing album, track and contributor pages. Search uses normalized title
substrings or an exact native ID; a numeric query can also match a title.

The albums cover 108,686 tracks; 1,041 tracks without album IDs remain accessible
through the track catalog. There are 1,126 multiartist albums. Exactly 356
case-sensitive title-collision groups contain 933 separate album IDs; normalized
case-insensitive search produces 390 nonempty collision groups. Titles never
join identities. Counts describe distinct nonnull native artist IDs on source
tracks, including unresolved IDs, not album ownership or independent musicians.
No album genre classifications, dates or release sequence are inferred.

## Source and boundaries

Only the same verified 2017 FMA track projection is used. Metadata is CC BY 4.0;
dataset-author attribution, source link and derivation notice remain in Sources.
The source/corpus pins are the same as the
[display-name recipe](../fma-track-artist-names-20261017/README.md).
New index rows contain only native album ID, existing title, track count and
artist-ID count. No acquisition, audio, model fitting or public deployment.

Four lazy index shards contain all 15,713 rows in 607,938 bytes. Each shard stays
under the existing 200 KB writer limit; the index additionally caps total bytes
at 2 MB and shard count at 16 before any index write. Browser and producer use
the same caps. The complete export remains within the unchanged 40 MB guard:
36,048,308 receipt bytes and 6,975 manifest files. The full build used 16.12 seconds
and 367,165,440 bytes peak RSS under 120-second CPU/wall and 1 GiB address-space
limits. After aligning the edge-case shard cap, regenerating the actual four
shards reproduced identical bytes and manifest metadata.

The existing static builder reproduces the export from retained source and
projected directories as documented in the preceding recipes. Older exports
without the optional index hide Albums controls and report that search is not
attached when directly routed there. Album details continue to work.

Independent replay checked every index row/count/collision, all inventory hashes,
and byte equality of 6,936 prior data files. Browser checks cover first/last
pagination, title/native-ID search, multiartist links, missing-album tracks,
history/reload, keyboard, 320/390px layouts, Retry, stale requests and old-export
fallback. This improves access to retained source evidence, not catalog freshness
or musical recommendation quality.
