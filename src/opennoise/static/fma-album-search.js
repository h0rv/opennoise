/** Lazy native album-title search; equal titles never join album identities. */
export const normalizedAlbumTitle = title => (title ?? '').normalize('NFKC').toLowerCase();

export async function loadAlbumSearch(config, json) {
  const search = config?.search;
  if (search?.revision !== 'fma-native-album-search-v1' ||
      !Number.isSafeInteger(search.row_count) || search.row_count < 0 ||
      search.row_count !== config.album_count ||
      !Number.isSafeInteger(search.bytes) || search.bytes < 0 || search.bytes > 2000000 ||
      !Array.isArray(search.shards) || search.shards.length > 16 ||
      JSON.stringify(search.columns) !== JSON.stringify(['album_id', 'title', 'track_count', 'artist_count']) ||
      search.shards.some((path, index) => path !== `album-search/${index}.json`)) {
    throw Error('Album search is unavailable or invalid in this export.');
  }
  const chunks = await Promise.all(search.shards.map(json));
  if (chunks.some(chunk => !Array.isArray(chunk))) throw Error('Invalid album search shard');
  const rows = chunks.flat();
  if (rows.length !== search.row_count) throw Error('Album search count mismatch');
  let previous = 0;
  for (const row of rows) {
    if (!Array.isArray(row) || row.length !== 4 ||
        !Number.isSafeInteger(row[0]) || row[0] <= previous ||
        (row[1] !== null && typeof row[1] !== 'string') ||
        !Number.isSafeInteger(row[2]) || row[2] <= 0 ||
        !Number.isSafeInteger(row[3]) || row[3] < 0 || row[3] > row[2]) {
      throw Error('Invalid native album search row');
    }
    previous = row[0];
  }
  return rows.sort((left, right) => {
    const a = normalizedAlbumTitle(left[1]), b = normalizedAlbumTitle(right[1]);
    return (a < b ? -1 : a > b ? 1 : 0) || left[0] - right[0];
  });
}

export function albumMatches(rows, query) {
  const normalized = normalizedAlbumTitle(query.trim());
  return rows.filter(row => normalizedAlbumTitle(row[1]).includes(normalized) || String(row[0]) === query.trim());
}
