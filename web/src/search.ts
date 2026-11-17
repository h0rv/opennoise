export function searchMatches<T>(index: { entry: T; terms: string[] }[], query: string): T[] {
  if (!query) return [];
  const buckets: T[][] = [[], [], [], []];
  for (const { entry, terms } of index) {
    const rank =
      terms[0] === query
        ? 0
        : terms.includes(query)
          ? 1
          : terms.some((term) => term.startsWith(query))
            ? 2
            : terms.some((term) => term.includes(query))
              ? 3
              : -1;
    if (rank !== -1 && buckets[rank].length < 12) buckets[rank].push(entry);
  }
  return buckets.flat().slice(0, 12);
}
