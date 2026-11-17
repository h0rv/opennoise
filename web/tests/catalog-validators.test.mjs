import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';
import Ajv from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import * as validators from '../src/catalog-validators.js';

const read = async (path) => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const schema = await read('../../src/opennoise/catalog.schema.json');
const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
ajv.addSchema(schema);
const fixtures = '../../tests/fixtures/catalog/';
const cases = [
  ['Manifest', await read(`${fixtures}manifest.json`)],
  ['Genres', await read(`${fixtures}genres.json`)],
  ['Search', await read(`${fixtures}search.json`)],
];
for (const [directory, definition] of [
  ['genres', 'GenreDetail'],
  ['artists', 'ArtistDetail'],
])
  for (const file of await readdir(new URL(`${fixtures}${directory}/`, import.meta.url)))
    cases.push([definition, await read(`${fixtures}${directory}/${file}`)]);

for (const [definition, data] of cases) {
  test(`precompiled ${definition} accepts fixture and rejects missing fields`, () => {
    const validate = validators[definition];
    const runtime = ajv.getSchema(`${schema.$id}#/$defs/${definition}`);
    assert.equal(validate(data), true, JSON.stringify(validate.errors));
    const object = Array.isArray(data) ? data[0] : data;
    for (const key of Object.keys(object)) {
      const invalid = structuredClone(data);
      delete (Array.isArray(invalid) ? invalid[0] : invalid)[key];
      assert.equal(runtime(invalid), false, key);
      assert.equal(validate(invalid), false, key);
    }
  });
}

test('precompiled checks keep ID, range, alias, URL and extra-field rules', () => {
  const genres = cases.find(([definition]) => definition === 'Genres')[1];
  const search = cases.find(([definition]) => definition === 'Search')[1];
  const artist = cases.find(([definition]) => definition === 'ArtistDetail')[1];
  const checks = [
    ['Genres', genres, (data) => (data[0].id = '../bad')],
    ['Genres', genres, (data) => (data[0].positions.axes = { x: 2, y: 0 })],
    ['Genres', genres, (data) => (data[0].aliases = ['duplicate', 'duplicate'])],
    ['Genres', genres, (data) => (data[0].extra = true)],
    ['Search', search, (data) => Object.assign(data[0], { kind: 'artist', id: 'bad' })],
    ['ArtistDetail', artist, (data) => (data.links = [{ label: 'bad', url: 'https://bad url' }])],
  ];
  for (const [definition, original, mutate] of checks) {
    const data = structuredClone(original);
    mutate(data);
    assert.equal(ajv.getSchema(`${schema.$id}#/$defs/${definition}`)(data), false);
    assert.equal(validators[definition](data), false);
  }
});
