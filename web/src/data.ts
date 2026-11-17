import Ajv from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import schema from '../../src/opennoise/catalog.schema.json';
import type { Manifest, Genres, Search, GenreDetail, ArtistDetail } from './catalog';

const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
ajv.addSchema(schema);
const validators = new Map<string, ReturnType<typeof ajv.compile>>();

export class Catalog {
  manifest!: Manifest;
  genres!: Genres;
  search!: Search;
  readonly url = new URL(
    import.meta.env.VITE_CATALOG_URL || '/catalog/manifest.json',
    location.href,
  );

  async read<T>(path: string, definition: string, signal?: AbortSignal): Promise<T> {
    const response = await fetch(new URL(path, this.url), { signal });
    if (!response.ok) throw new Error(`Catalog request failed (${response.status}).`);
    const data: unknown = await response.json();
    let validate = validators.get(definition);
    if (!validate) {
      validate = ajv.compile({ $ref: `${schema.$id}#/$defs/${definition}` });
      validators.set(definition, validate);
    }
    if (!validate(data))
      throw new Error(
        `This release has invalid ${definition} data. ${ajv.errorsText(validate.errors)}`,
      );
    return data as T;
  }

  async load() {
    this.manifest = await this.read(this.url.href, 'Manifest');
    [this.genres, this.search] = await Promise.all([
      this.read<Genres>(this.manifest.genres, 'Genres'),
      this.read<Search>(this.manifest.search, 'Search'),
    ]);
    return this;
  }

  genre(id: string, signal: AbortSignal) {
    return this.read<GenreDetail>(`genres/${encodeURIComponent(id)}.json`, 'GenreDetail', signal);
  }

  artist(id: string, signal: AbortSignal) {
    return this.read<ArtistDetail>(
      `artists/${encodeURIComponent(id)}.json`,
      'ArtistDetail',
      signal,
    );
  }
}
