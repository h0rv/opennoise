import * as validators from './catalog-validators.js';
import type { Manifest, Genres, Search, GenreDetail, ArtistDetail } from './catalog';

export class Catalog {
  manifest!: Manifest;
  genres!: Genres;
  search!: Search;
  private searching?: Promise<Search>;
  readonly url = new URL(
    import.meta.env.VITE_CATALOG_URL || '/catalog/manifest.json',
    location.href,
  );

  async read<T>(
    path: string,
    definition: keyof typeof validators,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await fetch(new URL(path, this.url), { signal });
    if (!response.ok) throw new Error(`Catalog request failed (${response.status}).`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    const body = new Blob([bytes]);
    const data: unknown = JSON.parse(
      await new Response(
        bytes[0] === 0x1f && bytes[1] === 0x8b
          ? body.stream().pipeThrough(new DecompressionStream('gzip'))
          : body,
      ).text(),
    );
    const validate = validators[definition];
    if (!validate(data))
      throw new Error(
        `This release has invalid ${definition} data. ${validate.errors
          ?.map((error) => `data${error.instancePath} ${error.message}`)
          .join(', ')}`,
      );
    return data as T;
  }

  async load() {
    this.manifest = await this.read(this.url.href, 'Manifest');
    this.genres = await this.read<Genres>(this.manifest.genres, 'Genres');
    this.search = this.genres.map(({ id, name, aliases }) => ({
      kind: 'genre',
      id,
      name,
      aliases,
    }));
    return this;
  }

  loadSearch(): Promise<Search> {
    this.searching ??= this.read<Search>(this.manifest.search, 'Search')
      .then((entries) => {
        this.search = entries;
        return entries;
      })
      .catch((error) => {
        this.searching = undefined;
        throw error;
      });
    return this.searching;
  }

  genreId(id: string) {
    const redirects = this.manifest.genre_redirects;
    return redirects && Object.hasOwn(redirects, id) ? redirects[id] : id;
  }

  genre(id: string, signal: AbortSignal) {
    return this.read<GenreDetail>(
      `genres/${encodeURIComponent(this.genreId(id))}.json`,
      'GenreDetail',
      signal,
    );
  }

  artist(id: string, signal: AbortSignal) {
    return this.read<ArtistDetail>(
      `artists/${encodeURIComponent(id)}.json`,
      'ArtistDetail',
      signal,
    );
  }
}
