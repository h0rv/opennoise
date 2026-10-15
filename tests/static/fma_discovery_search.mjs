import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../../src/opennoise/static/fma-discovery-search.js', import.meta.url), 'utf8');
const {normalizeQuery, searchDiscovery} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const index = {
  genres: [
    {genre_id: 2, title: 'Jazz', track_ids: [12], starting_ids: [12]},
    {genre_id: 3, title: 'Jazz vocals', track_ids: [], starting_ids: []}
  ],
  tracks: {
    12: {track_id: 12, title: 'Été bleu', artist_id: 2, artist_name: 'Björk'},
    13: {track_id: 13, title: null, artist_id: 2, artist_name: 'Björk'}
  }
};
const artists = new Map([[2, {id: 2, name: 'Björk', track_ids: [12, 13]}]]);

test('cross-entity names, source IDs and track artist context remain separate', () => {
  const matches = searchDiscovery(index, artists, '2');
  assert.deepEqual(matches.genres.map(row => row.id), [2]);
  assert.deepEqual(matches.artists.map(row => row.id), [2]);
  assert.deepEqual(matches.tracks, []);
  assert.deepEqual(searchDiscovery(index, artists, 'bjork').tracks.map(row => row.id), [12, 13]);
  assert.deepEqual(searchDiscovery(index, artists, '13').tracks.map(row => row.id), [13]);
});

test('accent and Unicode normalization, token order, missing titles and exact-first order', () => {
  assert.equal(normalizeQuery('  E\u0301TE\t BLEU  '), 'ete bleu');
  assert.deepEqual(searchDiscovery(index, artists, 'bjork bleu').tracks.map(row => row.id), [12]);
  assert.deepEqual(searchDiscovery(index, artists, 'JAZZ').genres.map(row => row.id), [2, 3]);
  assert.equal(searchDiscovery(index, artists, 'vocals').genres[0].playId, undefined);
  assert.equal(searchDiscovery(index, artists, '13').tracks[0].name, 'Track #13');
});

test('blank and unmatched queries never manufacture matches or change source objects', () => {
  const before = JSON.stringify(index);
  assert.deepEqual(searchDiscovery(index, artists, '  '), {genres: [], artists: [], tracks: []});
  assert.deepEqual(searchDiscovery(index, artists, '<script>'), {genres: [], artists: [], tracks: []});
  assert.equal(JSON.stringify(index), before);
});
