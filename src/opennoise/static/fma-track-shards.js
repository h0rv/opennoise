/** Restore exact source URL strings without changing cached shard data. */
export function decodeTrackShard(shard) {
  if (!shard || !Array.isArray(shard.tracks)) throw new Error('Invalid track shard');
  if (!Object.hasOwn(shard, 'revision') && !Object.hasOwn(shard, 'metadata_url_prefix')) {
    if (shard.columns?.[5] === 'metadata_url_suffix') throw new Error('Missing track URL encoding');
    return shard.tracks;
  }
  const columns = ['track_id', 'title', 'artist_id', 'genre_ids', 'license_id', 'metadata_url_suffix', 'album_id', 'missing_fields'];
  if (shard.revision !== 'fma-track-url-prefix-v1'
      || typeof shard.metadata_url_prefix !== 'string'
      || !['http://freemusicarchive.org/music/', 'https://freemusicarchive.org/music/',
        'http://www.freemusicarchive.org/music/', 'https://www.freemusicarchive.org/music/'].includes(shard.metadata_url_prefix)
      || !Array.isArray(shard.columns) || shard.columns.length !== columns.length
      || shard.columns.some((name, index) => name !== columns[index])) {
    throw new Error('Unsupported track URL encoding');
  }
  return shard.tracks.map(row => {
    if (!Array.isArray(row) || row.length !== columns.length
        || (row[5] !== null && typeof row[5] !== 'string')) throw new Error('Invalid encoded track row');
    return [...row.slice(0, 5), row[5] === null ? null : shard.metadata_url_prefix + row[5], ...row.slice(6)];
  });
}
