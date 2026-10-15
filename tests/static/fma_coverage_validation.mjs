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

test('extended root requires the exact coverage protocol and retains old limits', () => {
  const value = fixture(17);
  value.revision = 'fma-genre-discovery-v2';
  value.collections.coverage.audio_revision = 'fma-local-coverage-extension-v2';
  assert.equal(validate(value), value);
  for (const revision of [undefined, 'unknown', 'fma-local-coverage-v1']) {
    const changed = structuredClone(value);
    changed.collections.coverage.audio_revision = revision;
    assert.throws(() => validate(changed));
  }
  value.revision = 'fma-genre-discovery-v1';
  assert.throws(() => validate(value));
  const old = fixture();
  old.collections.coverage.audio_revision = 'unknown';
  assert.throws(() => validate(old));
  const oversized = fixture(18);
  oversized.revision = 'fma-genre-discovery-v2';
  oversized.collections.coverage.audio_revision = 'fma-local-coverage-extension-v2';
  assert.throws(() => validate(oversized));
});

test('playback rejects an index declaring a different coverage manifest protocol', async () => {
  const playback = await readFile(new URL('../../src/opennoise/static/fma-playback.js', import.meta.url), 'utf8');
  const body = playback.slice(playback.indexOf('async function loadPlayback('), playback.indexOf('\nlet persistent'));
  const load = runInNewContext(`(${body})`, {URL, location: new URL('http://localhost/')});
  const config = {manifest: 'coverage/audio/manifest.json', audio_revision: 'fma-local-coverage-extension-v2'};
  const manifest = {revision: 'fma-local-coverage-v1', test_only: true, tracks: {}};
  await assert.rejects(load(config, async () => manifest), /protocol differs/);
  manifest.revision = config.audio_revision;
  assert.equal((await load(config, async () => manifest)).manifest, manifest);
});
