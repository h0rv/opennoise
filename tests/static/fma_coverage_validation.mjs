import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../../src/opennoise/static/fma-discovery.js', import.meta.url), 'utf8');
const validation = source.slice(source.indexOf('function validate(value)'), source.indexOf('\nfunction play('));
const validate = runInNewContext(`(${validation})`);

function fixture(coverageCount = 1) {
  const keys = ['original', 'expanded', 'coverage'];
  const tracks = Object.fromEntries(Array.from({length: coverageCount + 2}, (_, i) => {
    const id = i + 1;
    const collection = keys[Math.min(i, 2)];
    return [String(id), {track_id: id, artist_id: id, genre_ids: [1], collection, origins: [collection]}];
  }));
  const ids = Object.values(tracks).map(track => track.track_id);
  return {
    revision: 'fma-genre-discovery-v1', musical_quality_validated: false,
    collections: Object.fromEntries(keys.map(key => [key, {manifest: `${key}/audio/manifest.json`} ])),
    tracks,
    genres: [{genre_id: 1, track_ids: ids, starting_ids: ids.slice(0, 3), artist_ids: ids}],
    counts: {genres: 1, clips: ids.length, playable_genres: 1, artists: ids.length}
  };
}

test('fixed coverage collection accepts twelve exact single-origin identities', () => {
  const value = fixture(12);
  assert.equal(validate(value), value);
});

test('coverage rejects unknown collection, changed URL, mixed origins and thirteenth clip', () => {
  const mutations = [
    value => { value.collections.fourth = {manifest: 'fourth/audio/manifest.json'}; },
    value => { value.collections.coverage.manifest = 'elsewhere/audio/manifest.json'; },
    value => { value.tracks['3'].origins = ['coverage', 'original']; },
    value => { value.tracks['1'].origins.push('coverage'); },
    value => { value.tracks['3'].origins = ['unknown']; },
    value => { delete value.collections.expanded; }
  ];
  for (const mutate of mutations) {
    const value = fixture();
    mutate(value);
    assert.throws(() => validate(value));
  }
  assert.throws(() => validate(fixture(13)));
  assert.throws(() => validate(fixture(127)));
});
