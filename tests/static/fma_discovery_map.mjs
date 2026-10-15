import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const playback = await readFile(new URL('../../src/opennoise/static/fma-playback.js', import.meta.url), 'utf8');
const queueSource = playback.slice(playback.indexOf('export async function requestDescriptorQueue'), playback.indexOf('/** Call only from an explicit user Play action'));

function queueHarness() {
  const calls = [];
  const context = {
    requestVersion: 0, pendingRequest: null, queueEntries: [], queueIndex: -1,
    entryPacks: new Map(),
    beginRequest(retry) { context.retry = retry; return ++context.requestVersion; },
    async loadPlayback(config, json) { calls.push(config.manifest); return {manifest: await json(config.manifest)}; },
    async startCurrent() { context.started = true; return true; },
    failPlayback() { context.failed = true; },
  };
  const request = runInNewContext(`(${queueSource.replace('export ', '')})`, context);
  return {request, context, calls};
}

function entries(count) {
  const keys = ['original', 'expanded', 'coverage'];
  return Array.from({length: count}, (_, i) => ({id: i + 1, config: {manifest: `${keys[i % 3]}/audio/manifest.json`}}));
}

function manifest(path) {
  return {tracks: Object.fromEntries(entries(64).filter(row => row.config.manifest === path).map(row => [String(row.id), {track_id: row.id, artist_id: 7}]))};
}

test('descriptor queue accepts 64 exact IDs across three sources including repeated artists', async () => {
  const {request, context, calls} = queueHarness();
  assert.equal(await request({entries: entries(64), json: async path => manifest(path)}), true);
  assert.equal(context.queueEntries.length, 64);
  assert.deepEqual([...context.queueEntries].map(row => row.track_id), entries(64).map(row => row.id));
  assert.equal(calls.length, 3);
  assert.equal(context.started, true);
});

test('descriptor queue rejects 65, duplicates, unknown source and absent native IDs', async () => {
  for (const selected of [entries(65), [entries(1)[0], entries(1)[0]], [{id: 1, config: {manifest: 'fourth/audio/manifest.json'}}], [{id: 2, config: entries(1)[0].config}]]) {
    const {request, context} = queueHarness();
    assert.equal(await request({entries: selected, json: async path => manifest(path)}), false);
    assert.equal(context.started, undefined);
    assert.equal(context.failed, true);
  }
});

test('interrupted descriptor load never starts audio and retry snapshots the selection', async () => {
  const {request, context} = queueHarness();
  let release;
  const selected = entries(1);
  const pending = request({entries: selected, json: () => new Promise(resolve => { release = resolve; })});
  selected[0].id = 999;
  context.requestVersion++;
  release(manifest('original/audio/manifest.json'));
  assert.equal(await pending, false);
  assert.equal(context.started, undefined);
  assert.equal(context.failed, undefined);
});

test('root map adapter is silent, prefixes only coordinate paths and preserves exact full catalog fallback', async () => {
  const source = await readFile(new URL('../../src/opennoise/static/fma-discovery-map.js', import.meta.url), 'utf8');
  const calls = [], plays = [];
  let options;
  const context = {
    renderDescriptorMap: async value => { options = value; },
    requestDescriptorQueue: value => plays.push(value), requestPlay: value => plays.push(value),
    URLSearchParams, history: {replaceState() {}},
  };
  const render = runInNewContext(source.replace(/^import .*;\n/gm, '').replaceAll('export ', '') + '\nrenderDiscoveryMap', context);
  const index = {collections: {original: {}, expanded: {descriptor_map: {}, manifest: 'expanded/audio/manifest.json'}, coverage: {manifest: 'coverage/audio/manifest.json'}}, tracks: {2: {track_id: 2, artist_id: 7, genre_ids: [1], collection: 'coverage'}}};
  let current = true;
  await render({index, artists: new Map([[7, {}]]), current: () => current, json: async path => { calls.push(path); return {artists: [[7, 'Retained'], [8, 'Full catalog']]}; }});
  assert.deepEqual(calls, ['expanded/explorer/artist-index.json']);
  assert.equal(plays.length, 0);
  assert.equal(options.artists.length, 2);
  assert.equal(options.detailHref('artist', 7), '#artist=7');
  assert.equal(options.detailHref('artist', 8), 'expanded/explorer/index.html#artist=8');
  assert.throws(() => options.json('../audio/manifest.json'));
  await options.json('descriptor-map/artists-0.json');
  assert.equal(calls.at(-1), 'expanded/explorer/descriptor-map/artists-0.json');
  options.onPlay(2);
  assert.equal(plays[0].config.manifest, 'coverage/audio/manifest.json');
  current = false;
  options.onPlay(2, [2]);
  assert.equal(plays.length, 1);
});
