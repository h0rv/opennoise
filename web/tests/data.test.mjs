import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { Catalog } from '../src/data.ts';

test('genre detail resolves an old ID without exposing redirects as catalog entries', async () => {
  const catalog = Object.create(Catalog.prototype);
  catalog.manifest = { genre_redirects: { 'old-garage': 'uk-garage' } };
  catalog.search = [{ kind: 'genre', id: 'uk-garage' }];
  catalog.read = async (path) => path;
  assert.equal(catalog.genreId('old-garage'), 'uk-garage');
  assert.equal(await catalog.genre('old-garage'), 'genres/uk-garage.json');
  assert.equal(catalog.genreId('constructor'), 'constructor');
  catalog.manifest = {};
  assert.equal(catalog.genreId('uk-garage'), 'uk-garage');
});

test('catalog reads plain and gzipped JSON, including empty lists', async (t) => {
  const catalog = { url: new URL('https://example.com/catalog/manifest.json') };
  for (const body of ['[]', gzipSync('[]')]) {
    t.mock.method(globalThis, 'fetch', async () => new Response(body));
    assert.deepEqual(await Catalog.prototype.read.call(catalog, 'genres.json', 'Genres'), []);
  }
});

test('catalog rejects HTTP errors, invalid JSON, corrupt gzip and invalid records', async (t) => {
  const catalog = { url: new URL('https://example.com/catalog/manifest.json') };
  for (const response of [
    new Response('', { status: 404 }),
    new Response('{'),
    new Response(new Uint8Array([0x1f, 0x8b, 0])),
    new Response('[{}]'),
  ]) {
    t.mock.method(globalThis, 'fetch', async () => response);
    await assert.rejects(Catalog.prototype.read.call(catalog, 'genres.json', 'Genres'));
  }
});
