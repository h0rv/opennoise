import type { ArtistDetail, Genre } from './catalog';

export const genrePriority = (score: number, count: number) =>
  (score * Math.sqrt(count)) / (count + 10000);

export const similarPriority = (score: number, listeners: number | null) =>
  score / Math.max(listeners ?? 1, 1) ** 0.1;

export function artistGenres(data: ArtistDetail, genres: ReadonlyMap<string, Genre>) {
  return [...(data.genres || [])].sort(
    (a, b) =>
      genrePriority(b.score, genres.get(b.id)?.member_count || 0) -
        genrePriority(a.score, genres.get(a.id)?.member_count || 0) || a.id.localeCompare(b.id),
  );
}
