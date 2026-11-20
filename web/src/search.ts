import type { SearchEntry } from './catalog';
import { isArtistCluster } from './label-grid';

export const searchableEntry = (entry: Pick<SearchEntry, 'kind' | 'name'>) =>
  entry.kind !== 'genre' || !isArtistCluster(entry.name);

export function searchMatches<T extends { kind?: string; listeners?: number | null }>(
  index: { entry: T; terms: string[]; topLevel?: boolean }[],
  query: string,
): T[] {
  if (!query) return [];
  const buckets: T[][] = [[], [], [], [], []];
  for (const { entry, terms, topLevel } of index) {
    const rank =
      terms[0] === query
        ? 0
        : terms.includes(query)
          ? topLevel
            ? 1
            : 2
          : terms.some((term) => term.startsWith(query))
            ? 3
            : terms.some((term) => term.includes(query))
              ? 4
              : -1;
    if (rank !== -1) buckets[rank].push(entry);
  }
  return buckets
    .flatMap((bucket) => {
      const artists = bucket
        .filter((entry) => entry.kind === 'artist')
        .sort((a, b) => (b.listeners ?? 0) - (a.listeners ?? 0));
      let i = 0;
      return bucket.map((entry) => (entry.kind === 'artist' ? artists[i++] : entry));
    })
    .slice(0, 12);
}
