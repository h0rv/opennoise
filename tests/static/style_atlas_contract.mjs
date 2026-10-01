import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const styleId = 'style-' + 'a'.repeat(24), sparseId = 'style-' + 'b'.repeat(24);
const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333'];
const sourceRoles = ['observed_artist_feature', 'credited_release_context'];
const names = ['Source Artist A', 'Source Artist B', 'Unplaced Artist'];
const cohortIds = [...ids, ...Array.from({length: 100}, (_, index) => `${(index + 4).toString(16).padStart(8, '0')}-4444-4444-8444-444444444444`)];
const cohortRows = cohortIds.map((artist_mbid, index) => ({artist_mbid, name: names[index] || `Additional Source Artist ${index}`, score: null, profile_path: `artists/${artist_mbid.slice(0, 3)}.json`}));
const style = id => ({id, name: id === styleId ? 'ambient' : 'sparse source', aliases: [], x: .5, y: .5, layout_status: 'positioned_source_musical_cooccurrence', role: 'candidate_named_style', native_fact: false, evidence_tier: 'dictionary_named_style', default_visible: true, source_artist_support: 103, native_genre_ids: [], counts: {observed_artist_feature: 103, credited_release_context: 0, inferred_feature_proposal: 0}, detail_path: `styles/${id}.json`, artist_map_path: `style-artist-maps/${id}.json`});
const catalog = {role: 'candidate_named_styles', scope: 'local_research_only', public_export_authorized: false, native_fact: false, artist_shard_prefix_length: 3, page_size: 100, coverage: {artists: 103}, styles: [style(styleId), style(sparseId)]};
const map = id => ({style_id: id, role: 'inferred_source_artist_profile_map', native_fact: false, quality_evaluated: false, total_count: 103, selected_count: 3, positioned_count: id === styleId ? 2 : 0, abstained_count: id === styleId ? 1 : 3, omitted_count: 100, truncated: true, method: 'source_musical_value_idf_cosine_spectral_rectangular_atlas', candidate_selection: 'informative_source_music_degree_descending_then_exact_mbid', world_width: 16 / 9, world_height: 1, cohort_roles: sourceRoles, artists: ids.map((artist_mbid, index) => {
  const placed = id === styleId && index < 2;
  return {artist_mbid, name: names[index], name_status: 'source_name', x: placed ? [.3, 1.3][index] : null, y: placed ? [.3, .7][index] : null, layout_status: placed ? 'positioned' : 'abstained', abstention_reason: placed ? null : 'identical_usable_source_music_profile', profile_path: `artists/${artist_mbid.slice(0, 3)}.json`, membership_roles: [sourceRoles[0]], source_music_value_count: 3, supported_neighbor_count: placed ? 1 : 0, neighbors: placed ? [{artist_mbid: ids[1 - index], score: .7, shared_music_value_count: 2, shared_music_values: ['ambient', 'drone']}] : []};
})});

async function withBrowser(operation, mutate = payload => payload, withMaps = true) {
  const assets = await Promise.all(['html', 'css', 'js'].map(suffix => readFile(new URL(`../../src/opennoise/static/style-atlas.${suffix}`, import.meta.url))));
  const current = structuredClone(catalog);
  if (!withMaps) for (const row of current.styles) delete row.artist_map_path;
  const server = createServer((request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    let payload;
    if (path === '/') { response.setHeader('Content-Type', 'text/html'); response.end(assets[0]); return; }
    if (path === '/style-atlas.css' || path === '/style-atlas.js') { response.setHeader('Content-Type', path.endsWith('.js') ? 'text/javascript' : 'text/css'); response.end(assets[path.endsWith('.js') ? 2 : 1]); return; }
    if (path === '/data.json') payload = current;
    if (path === '/artist-search.json') payload = {artists: ids.map((id, index) => [id, names[index], 'source_name'])};
    const row = current.styles.find(row => path === '/' + row.detail_path);
    if (row) payload = {...row, cohorts: Object.fromEntries(Object.keys(row.counts).map(role => [role, {artist_count: row.counts[role], pages: Array.from({length: Math.ceil(row.counts[role] / 100)}, (_, page) => `cohorts/${row.id}/${role}/${page}.json`)}]))};
    const mapId = [styleId, sparseId].find(id => path === `/style-artist-maps/${id}.json`);
    if (mapId) payload = mutate(map(mapId));
    const cohortId = [styleId, sparseId].find(id => path.startsWith(`/cohorts/${id}/observed_artist_feature/`));
    if (cohortId) { const page = Number(path.split('/').at(-1).split('.')[0]); payload = {style_id: cohortId, role: sourceRoles[0], native_fact: false, page, artist_count: 103, artists: cohortRows.slice(page * 100, (page + 1) * 100)}; }
    const artistId = ids.find(id => path === `/artists/${id.slice(0, 3)}.json`);
    if (artistId) payload = {artists: {[artistId]: {artist_mbid: artistId, name: names[ids.indexOf(artistId)], genre_ids: [], style_memberships: [{style_id: styleId, value: 'ambient', role: sourceRoles[0], native_fact: false, source_features: [{namespace: 'artist_tag', value: 'ambient', weight: 1, evidence_refs: ['retained-source:ambient']}]}]}}};
    if (!payload) { response.statusCode = 404; response.end(); return; }
    response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(payload));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-artist-map-contract-'));
  const child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket;
  const requests = [], errors = [];
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let output = ''; const timeout = setTimeout(() => reject(new Error('Chromium startup timed out')), 10000);
      child.on('error', reject); child.stderr.on('data', bytes => { output += bytes; const match = output.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//); if (match) { clearTimeout(timeout); resolve(`http://127.0.0.1:${match[1]}`); } });
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, {method: 'PUT'}).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
    let sequence = 0; const pending = new Map();
    socket.addEventListener('message', ({data}) => { const result = JSON.parse(data); if (result.method === 'Network.requestWillBeSent') requests.push(result.params); if (result.method === 'Runtime.exceptionThrown') errors.push(result.params.exceptionDetails); pending.get(result.id)?.(result); });
    const command = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence, timeout = setTimeout(() => reject(new Error(`${method} timed out`)), 10000); pending.set(id, result => { clearTimeout(timeout); pending.delete(id); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); }); socket.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text); return result.result.value; };
    const wait = async expression => { for (let index = 0; index < 300; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false}); await command('Page.navigate', {url});
    await wait("document.documentElement?.dataset.styleAtlasReady === 'true'");
    assert.ok(!requests.some(row => /style-artist-maps|\/artists\//.test(row.request.url)), 'initial atlas stays lazy');
    await operation({evaluate, wait, command, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'));
  } finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}

async function openMap(browser, id = styleId) {
  await browser.evaluate(`location.hash='style=${id}'`);
  await browser.wait("Boolean(document.querySelector('.artist-map-toggle')) && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
  await browser.evaluate("document.querySelector('.artist-map-toggle').click()");
}

test('artist map preserves source-only identities, full cohorts, abstentions, and history', {skip: !chromium, timeout: 60000}, async () => {
  await withBrowser(async browser => {
    const {evaluate, wait, command} = browser;
    await openMap(browser); await wait("document.querySelector('canvas').dataset.artistMapReady === 'true' && document.querySelectorAll('.artist-map-label').length === 2");
    assert.equal(await evaluate("document.querySelector('canvas').dataset.evidenceRole"), 'inferred_source_artist_profile_map');
    assert.ok(await evaluate("document.querySelector('.map-legend').textContent.includes('not sonic distance')"));
    assert.equal(await evaluate("document.querySelectorAll('.cohort-content .artist-row').length"), 100);
    assert.ok(await evaluate("document.querySelector('.map-sample-counts').textContent.includes('3 sampled of 103') && document.querySelector('.map-sample-counts').textContent.includes('100 outside this sample')"));
    await evaluate("[...document.querySelectorAll('.cohort-content .pagination button')].find(row => row.textContent === 'Last').click()");
    await wait("document.querySelectorAll('.cohort-content .artist-row').length === 3 && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('.cohort-content .artist-row').dataset.artistId"), cohortIds[100]);
    await evaluate('history.back()'); await wait("document.querySelectorAll('.cohort-content .artist-row').length === 100 && document.querySelector('canvas').dataset.artistMapReady === 'true'");
    await evaluate("document.querySelector('.artist-map-label').click()"); await wait("Boolean(document.querySelector('.artist-evidence')) && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("location.hash.includes('atlas=artists') && location.hash.includes('artist=')"));
    assert.equal(await evaluate("document.querySelectorAll('.evidence-card.observed_artist_feature').length"), 1);
    assert.equal(await evaluate("document.querySelectorAll('.evidence-card.inferred_feature_proposal').length"), 0);
    await command('Page.reload'); await wait("document.querySelector('canvas')?.dataset.artistMapReady === 'true' && Boolean(document.querySelector('.artist-evidence'))");
    await evaluate("document.querySelector('.back-button').click();document.querySelector('#list-view').click()");
    assert.equal(await evaluate("document.querySelectorAll('#artist-map-directory .artist-row').length"), 3);
    assert.ok(await evaluate("document.querySelector('#artist-map-directory').textContent.includes('Unplaced')"));
    await evaluate("document.querySelector('#artist-map-search').value='absent artist';document.querySelector('#artist-map-search').dispatchEvent(new Event('input'))");
    assert.ok(await evaluate("document.querySelector('#artist-map-directory').textContent.includes('No sampled artists match')"));
    await evaluate("document.querySelector('#artist-map-search').value='';document.querySelector('#artist-map-search').dispatchEvent(new Event('input'));document.querySelector('#artist-map-back').click()");
    assert.ok(await evaluate("!location.hash.includes('atlas=artists') && document.querySelector('#artist-map-toolbar').hidden"));
    await evaluate('history.back()'); await wait("document.querySelector('.atlas').dataset.scene === 'artists' && document.querySelector('canvas').dataset.artistMapReady === 'true'");
    await evaluate('history.forward()'); await wait("document.querySelector('.atlas').dataset.scene === 'styles'");
    await openMap(browser, sparseId); await wait("document.querySelector('canvas').dataset.artistMapStyleId === '" + sparseId + "' && document.querySelector('canvas').dataset.artistMapReady === 'true'");
    assert.equal(await evaluate("document.querySelectorAll('#artist-map-directory .artist-row').length"), 3);
    assert.ok(await evaluate("document.querySelector('#map-view').disabled && document.querySelectorAll('.artist-map-label').length === 0"));
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true}); await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
    assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
    assert.ok(await evaluate("document.querySelector('#atlas-status').getBoundingClientRect().top >= document.querySelector('#artist-map-toolbar').getBoundingClientRect().bottom"));
  });
});

test('artist map rejects native claims and unsupported coordinates without hiding source cohorts', {skip: !chromium, timeout: 60000}, async () => {
  for (const mutate of [payload => ({...payload, native_fact: true}), payload => ({...payload, artists: payload.artists.map((row, index) => index === 0 ? {...row, neighbors: [{...row.neighbors[0], artist_mbid: row.artist_mbid}]} : row)}), payload => ({...payload, artists: payload.artists.map((row, index) => index === 2 ? {...row, x: .5, y: .5} : row)}), payload => ({...payload, artists: payload.artists.map((row, index) => index === 0 ? {...row, membership_roles: ['inferred_feature_proposal']} : row)})]) {
    await withBrowser(async browser => { await openMap(browser); await browser.wait("document.querySelector('#atlas-status').textContent.includes('Artist map unavailable')"); assert.equal(await browser.evaluate("document.querySelectorAll('.cohort-content .artist-row').length"), 100); assert.equal(await browser.evaluate("document.querySelectorAll('.artist-map-label').length"), 0); }, mutate);
  }
});

test('older atlas payloads retain style navigation without offering missing artist maps', {skip: !chromium, timeout: 60000}, async () => {
  await withBrowser(async browser => { await browser.evaluate(`location.hash='style=${styleId}'`); await browser.wait("document.querySelector('#detail').getAttribute('aria-busy') === 'false' && document.querySelectorAll('.cohort-content .artist-row').length === 100"); assert.equal(await browser.evaluate("document.querySelectorAll('.artist-map-toggle').length"), 0); }, payload => payload, false);
});


test('actual Python artist-map producer loads in Chromium without consumer contract drift', {skip: !chromium, timeout: 60000}, async () => {
  const python = new URL('../../.venv/bin/python', import.meta.url).pathname;
  const producer = `
import json, sqlite3, sys, tempfile
from pathlib import Path
import numpy as np
from scipy import sparse
from opennoise.deployment.style_artist_maps import map_context
from opennoise.deployment.style_atlas import _artist_maps
payload = json.load(sys.stdin)
rows, styles = payload["artists"], payload["styles"]
ids = tuple(row["artist_mbid"] for row in rows)
matrix = np.zeros((len(ids), 4), dtype=np.int8)
matrix[:4] = [[1,1,1,0], [1,1,0,1], [1,0,1,0], [0,1,0,1]]
context = map_context(ids, ["ambient", "drone", "noise", "dub"], sparse.csr_matrix(matrix))
db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE artist_names(mbid TEXT, name TEXT, status TEXT)")
db.execute("CREATE TABLE members(style TEXT, artist TEXT, role TEXT)")
db.executemany("INSERT INTO artist_names VALUES(?,?,?)", [(row["artist_mbid"], row["name"], "source_name") for row in rows])
db.executemany("INSERT INTO members VALUES(?,?,?)", [(style["id"], artist, "observed_artist_feature") for style in styles for artist in ids])
with tempfile.TemporaryDirectory() as temporary:
    output = Path(temporary)
    (output / "styles").mkdir()
    for style in styles:
        (output / style["detail_path"]).write_text(json.dumps(style))
    _artist_maps(output, db, styles, context, {})
    print(json.dumps({style["id"]: json.loads((output / style["artist_map_path"]).read_text()) for style in styles}))
`;
  const produced = JSON.parse(execFileSync(python, ['-c', producer], {input: JSON.stringify({artists: cohortRows, styles: catalog.styles}), encoding: 'utf8'}));
  assert.equal(produced[styleId].selected_count, 103);
  assert.ok(produced[styleId].positioned_count > 0);
  assert.ok(produced[styleId].abstained_count > 0);
  await withBrowser(async browser => {
    await openMap(browser);
    await browser.wait("document.querySelector('canvas').dataset.artistMapReady === 'true' && document.querySelectorAll('.artist-map-label').length > 0");
    assert.equal(await browser.evaluate("document.querySelectorAll('.cohort-content .artist-row').length"), 100);
    assert.equal(await browser.evaluate("document.querySelectorAll('#detail .error-state').length"), 0);
    await browser.evaluate("document.querySelector('#list-view').click()");
    assert.equal(await browser.evaluate("document.querySelectorAll('#artist-map-directory .artist-row').length"), 103);
    assert.ok(await browser.evaluate("document.querySelector('#artist-map-directory').textContent.includes('indistinguishable source profile')"));
    await browser.evaluate(`document.querySelector('#artist-map-directory [data-artist-id="${ids[0]}"]').click()`);
    await browser.wait("Boolean(document.querySelector('.artist-evidence')) && document.querySelector('#detail').getAttribute('aria-busy') === 'false'");
    assert.equal(await browser.evaluate("document.querySelector('#detail h2').textContent"), names[0]);
    assert.ok(await browser.evaluate("document.querySelector('.artist-map-summary').textContent.includes('Shared source values:')"));
  }, payload => produced[payload.style_id]);
});
