import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

const root = process.env.OPENNOISE_FMA_STATIC_ROOT;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !root || !chromium;
async function browser(operation) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try { response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json'); response.end(await readFile(file)); }
    catch { response.statusCode = 404; response.end(); }
  });
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-fma-contract-'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
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
    const wait = async expression => { for (let index = 0; index < 400; index++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error('Timed out: ' + expression); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false}); await command('Page.navigate', {url});
    await wait("document.documentElement?.dataset.fmaReady === 'true' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(!requests.some(row => /artist-index|\/tracks\/|\/cohorts\/|\/artists\//.test(row.request.url)), 'initial genre catalog stays lazy');
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'), 'no external provider or audio requests');
  } finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}
async function idle({wait}) { await wait("document.querySelector('main').getAttribute('aria-busy') === 'false'"); }

test('actual raw FMA catalog preserves complete counts, source annotations, history and reload', {skip, timeout: 60000}, async () => {
  const catalog = JSON.parse(await readFile(join(root, 'catalog.json')));
  const biggest = catalog.genres.reduce((a, b) => a.track_count > b.track_count ? a : b);
  await browser(async state => {
    const {evaluate, wait, command} = state;
    if (!catalog.source_genres) assert.ok(await evaluate("[...document.querySelectorAll('[data-source-genres]')].every(element => element.hidden)"), 'optional source genre controls stay hidden without a pack');
    assert.deepEqual(catalog.counts, {raw_tracks: 109727, source_artists: 16916, missing_artist_records: 250, tracks_with_missing_artist_records: 974, genre_definitions: 164, observed_track_genres: 162, unannotated_tracks: 2609});
    assert.match(await evaluate("document.querySelector('#status').textContent"), /164 genre definitions.*162/);
    assert.equal(await evaluate("document.querySelectorAll('.directory li').length"), 100);
    await evaluate("[...document.querySelectorAll('#pages button')].find(row => row.textContent === 'Last').click()"); await idle(state);
    assert.equal(await evaluate("document.querySelectorAll('.directory li').length"), 64);
    await evaluate(`location.hash='genre=${biggest.genre_id}'`); await wait("document.querySelectorAll('.track').length === 200 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    const first = await evaluate("document.querySelector('.track').dataset.trackId");
    assert.ok(await evaluate("[...document.querySelectorAll('.track')].every(row => row.querySelector('.annotations').textContent.includes('Track genres:'))"));
    assert.match(await evaluate("document.querySelector('#status').textContent"), /No parent annotations are inherited/);
    await evaluate("[...document.querySelectorAll('#pages button')].find(row => row.textContent === 'Next').click()"); await wait(`document.querySelector('.track')?.dataset.trackId !== '${first}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await evaluate('history.back()'); await wait(`document.querySelector('.track')?.dataset.trackId === '${first}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await evaluate("document.querySelector('.track p a').click()"); await wait("location.hash.startsWith('#artist=') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    const heading = await evaluate("document.querySelector('h1').textContent");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /Genre annotations below belong to each track/);
    await command('Page.reload'); await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(heading)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await evaluate("location.hash='tracks&page=548'"); await wait("document.querySelectorAll('.track').length === 127 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /109,727/);
  });
});

test('actual FMA search, missing records and unannotated tracks work on mobile and keyboard', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, command} = state;
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await evaluate("location.hash='artists'"); await wait("document.querySelector('#status').textContent.includes('16,916') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('#query').value='AWOL'; document.querySelector('#query').dispatchEvent(new Event('input')); document.querySelector('#query').focus()"); await idle(state);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40});
    assert.equal(await evaluate("document.activeElement.closest('.directory') !== null"), true);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await wait("location.hash.startsWith('#artist=') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    await evaluate("location.hash='artists&missing=1'"); await wait("document.querySelector('#status').textContent.includes('250 matching') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('.directory a').click()"); await wait("document.querySelector('#status').textContent.includes('Artist record is missing') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("document.querySelectorAll('.track').length > 0"));
    await evaluate("location.hash='unannotated'"); await wait("document.querySelectorAll('.track').length === 200 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("[...document.querySelectorAll('.annotations')].every(row => row.textContent.includes('No source genre annotations'))"));
    assert.match(await evaluate("document.querySelector('#status').textContent"), /2,609/);
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    assert.equal(await evaluate("document.querySelectorAll('audio,video,iframe').length"), 0);
  });
});

test('connected genres lead to tracks and an artist’s track-genre summary', {skip, timeout: 60000}, async () => {
  const catalog = JSON.parse(await readFile(join(root, 'catalog.json')));
  const genre = catalog.genres.find(row => row.title === 'Jazz' && row.connections?.length);
  assert.ok(genre, 'Jazz has source annotation connections');
  await browser(async state => {
    const {evaluate, wait, command} = state;
    await evaluate(`location.hash='genre=${genre.genre_id}'`);
    await wait("document.querySelector('.connections h2')?.textContent === 'Connected genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelectorAll('.connections li').length"), genre.connections.length);
    assert.equal(await evaluate("document.querySelector('.connections').dataset.evidenceRole"), 'source_track_annotation_overlap');
    const connection = await evaluate("document.querySelector('.connections .directory a').getAttribute('href')");
    await evaluate("document.querySelector('.connections .directory a').focus()");
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await wait(`location.hash === ${JSON.stringify(connection)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(await evaluate("document.querySelectorAll('.track').length > 0"));
    await evaluate("document.querySelector('.track p a').click()");
    await wait("location.hash.startsWith('#artist=') && document.querySelector('.connections h2')?.textContent === 'Explore track genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('.connections p').textContent"), /this artist’s tracks; not an artist classification/);
    const artistHash = await evaluate('location.hash');
    const summary = await evaluate("document.querySelector('.connections').textContent");
    await command('Page.reload');
    await wait(`document.querySelector('.connections')?.textContent === ${JSON.stringify(summary)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    await evaluate("document.querySelector('.connections .directory a').click()");
    await wait("document.querySelector('.connections h2')?.textContent === 'Connected genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate('history.back()');
    await wait(`location.hash === ${JSON.stringify(artistHash)} && document.querySelector('.connections h2')?.textContent === 'Explore track genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
  });
});

test('complete track search supports names, exact IDs, track links and empty results', {skip, timeout: 60000}, async () => {
  const catalog = JSON.parse(await readFile(join(root, 'catalog.json')));
  assert.equal(catalog.track_search.row_count, 109727);
  await browser(async state => {
    const {evaluate, wait, command, requests} = state;
    assert.ok(!requests.some(row => row.request.url.includes('/track-search/')), 'track search stays lazy');
    await evaluate("location.hash='tracks&q=AWOL'");
    await wait("document.querySelector('h1').textContent === 'Tracks' && document.querySelectorAll('.track').length > 0 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('.track p').textContent"), /AWOL/i);
    const trackId = await evaluate("document.querySelector('.track').dataset.trackId");
    await evaluate(`location.hash='tracks&q=${trackId}'`);
    await wait("document.querySelectorAll('.track').length === 1 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /^1 matching tracks/);
    await evaluate("document.querySelector('.track h2 a').click()");
    await wait(`location.hash === '#track=${trackId}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    const heading = await evaluate("document.querySelector('h1').textContent");
    await command('Page.reload');
    await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(heading)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(await evaluate("document.querySelector('.metadata a').href.startsWith('http')"));
    await evaluate("document.querySelector('.annotations a').click()");
    await wait("document.querySelector('.connections details') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('.connections details').open = true");
    assert.ok(await evaluate("document.querySelectorAll('.fma-genre-map svg a').length > 0"));
    if (process.env.OPENNOISE_FMA_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_SCREENSHOTS, 'explorer-desktop.png'), Buffer.from(shot.data, 'base64'));
    }
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    if (process.env.OPENNOISE_FMA_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_SCREENSHOTS, 'explorer-mobile.png'), Buffer.from(shot.data, 'base64'));
    }
    await evaluate("document.querySelector('.fma-genre-map svg a').focus()");
    assert.equal(await evaluate("document.activeElement.closest('svg') !== null"), true);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await idle(state);
    await evaluate("location.hash='tracks&q=no-such-track-zzzzxxxx'");
    await wait("document.querySelector('#status').textContent.startsWith('0 matching') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('#rows').textContent"), /No matching tracks/);
  });
});

async function sourceGenreFixture(context) {
  const catalog = JSON.parse(await readFile(join(root, 'catalog.json')));
  if (!catalog.source_genres) { context.skip('optional Wikidata genre export is absent'); return null; }
  const index = JSON.parse(await readFile(join(root, catalog.source_genres.index)));
  const details = Object.assign({}, ...(await Promise.all(Array.from({length: index.detail_shards}, async (_, shard) => JSON.parse(await readFile(join(root, `source-genres/${shard}.json`))).genres))));
  return {index, details};
}

test('optional Wikidata directory is lazy, complete, searchable and keyboard accessible', {skip, timeout: 60000}, async context => {
  const fixture = await sourceGenreFixture(context); if (!fixture) return;
  const {index} = fixture;
  assert.equal(index.genres.length, 1000);
  const missing = index.genres.find(row => row[2]);
  assert.ok(missing, 'selection includes a missing English label');
  await browser(async state => {
    const {evaluate, wait, command, requests} = state;
    assert.ok(!requests.some(row => row.request.url.includes('/source-genres/')), 'source genres stay lazy on FMA landing');
    assert.equal(await evaluate("document.querySelector('nav [data-source-genres]').hidden"), false);
    assert.equal(await evaluate("document.querySelector('#scope [data-source-genres]').hidden"), false);
    await evaluate("document.querySelector('nav [data-source-genres]').click()");
    await wait("location.hash === '#wikidata' && document.querySelectorAll('.directory li').length === 100 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /1,000/);
    const ids = [];
    for (let page = 0; page < 10; page++) {
      if (page) {
        await evaluate("[...document.querySelectorAll('#pages button')].find(row => row.textContent === 'Next').click()");
        await wait(`new URLSearchParams(location.hash.slice(1)).get('page') === '${page}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
      }
      ids.push(...await evaluate("[...document.querySelectorAll('.directory a')].map(row => row.getAttribute('href').split('=')[1])"));
    }
    assert.deepEqual([...ids].sort(), index.genres.map(row => row[0]).sort());
    assert.equal(new Set(ids).size, 1000);
    await evaluate(`location.hash='wikidata&q=${missing[0]}'`);
    await wait("document.querySelectorAll('.directory li').length === 1 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok((await evaluate("document.querySelector('.directory').textContent")).includes(missing[0]), 'missing label remains searchable by QID');
    assert.doesNotMatch(await evaluate("document.querySelector('.directory').textContent"), /undefined|null/);
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await evaluate("document.querySelector('#query').value='ska'; document.querySelector('#query').dispatchEvent(new Event('input')); document.querySelector('#query').focus()");
    await wait("document.querySelectorAll('.directory li').length > 0 && document.querySelector('#query').value === 'ska' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("[...document.querySelectorAll('.directory a')].every(row => /ska/i.test(row.textContent))"));
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    if (process.env.OPENNOISE_FMA_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_SCREENSHOTS, 'source-genres-mobile.png'), Buffer.from(shot.data, 'base64'));
    }
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40});
    assert.equal(await evaluate("document.activeElement.closest('.directory') !== null"), true);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await wait("location.hash.startsWith('#wdgenre=') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelectorAll('.track,audio,video,iframe').length"), 0);
  });
});

test('optional Wikidata direct hierarchy preserves boundaries, history, reload and invalid IDs', {skip, timeout: 60000}, async context => {
  const fixture = await sourceGenreFixture(context); if (!fixture) return;
  const {details} = fixture;
  const twoTone = details.Q209498;
  assert.ok(twoTone);
  const ska = twoTone.parents.find(row => row[1].toLowerCase() === 'ska' && row[2]);
  assert.ok(ska, '2 tone has its direct retained ska parent');
  const outsideEntry = Object.entries(details).find(([, row]) => row.parents.some(parent => !parent[2]));
  assert.ok(outsideEntry, 'selection retains external direct parents');
  const [outsideSource, outsideDetail] = outsideEntry;
  const outside = outsideDetail.parents.find(row => !row[2]);
  await browser(async state => {
    const {evaluate, wait, command} = state;
    await evaluate("location.hash='wdgenre=Q209498'");
    await wait("document.querySelector('h1').textContent.includes('2 tone') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelectorAll('.track').length"), 0);
    assert.ok(await evaluate("document.querySelector('[data-evidence-role=wikidata_direct_subclass_claim]') !== null"));
    if (process.env.OPENNOISE_FMA_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_SCREENSHOTS, 'source-genres-desktop.png'), Buffer.from(shot.data, 'base64'));
    }
    await evaluate(`document.querySelector('#rows a[href="#wdgenre=${ska[0]}"]').click()`);
    await wait(`location.hash === '#wdgenre=${ska[0]}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(await evaluate("document.querySelector('#rows a[href=\"#wdgenre=Q209498\"]') !== null"), 'parent exposes retained direct child');
    await evaluate('history.back()');
    await wait("location.hash === '#wdgenre=Q209498' && document.querySelector('h1').textContent.includes('2 tone') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await command('Page.reload');
    await wait("document.querySelector('h1')?.textContent.includes('2 tone') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate(`location.hash='wdgenre=${outsideSource}'`);
    await wait(`document.querySelector('#rows a[href="https://www.wikidata.org/wiki/${outside[0]}"]') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(await evaluate(`document.querySelector('#rows a[href="https://www.wikidata.org/wiki/${outside[0]}"]').parentElement.textContent.includes('Outside this selection')`));
    assert.equal(await evaluate(`document.querySelector('#rows a[href="#wdgenre=${outside[0]}"]')`), null);
    assert.equal(await evaluate("document.querySelectorAll('.track').length"), 0);
    await evaluate("location.hash='wdgenre=not-a-qid'");
    await wait("document.querySelector('h1').textContent === 'Catalog unavailable' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /invalid/i);
    assert.equal(await evaluate("document.querySelectorAll('.track').length"), 0);
  });
});

test('optional Wikidata artist examples retain native identities and direct genre navigation', {skip, timeout: 60000}, async context => {
  const fixture = await sourceGenreFixture(context); if (!fixture) return;
  const [genreId, detail] = Object.entries(fixture.details).find(([, row]) => row.artists?.length);
  const artistId = detail.artists[0];
  const artist = JSON.parse(await readFile(join(root, 'source-genres/artists.json'))).artists[artistId];
  await browser(async state => {
    const {evaluate, wait, command} = state;
    await evaluate(`location.hash='wdgenre=${genreId}'`);
    await wait("document.querySelector('.source-artists a') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('.source-artists').dataset.evidenceRole"), 'wikidata_direct_artist_genre_claim');
    await evaluate(`document.querySelector('.source-artists a[href="#wdartist=${artistId}"]').click()`);
    await wait(`location.hash === '#wdartist=${artistId}' && document.querySelector('h1').textContent === ${JSON.stringify(artist.name)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.match(await evaluate("document.querySelector('#status').textContent"), /separate from FMA/i);
    assert.equal(await evaluate("document.querySelectorAll('.track,audio,video,iframe').length"), 0);
    assert.ok(await evaluate(`document.querySelector('#rows a[href="https://musicbrainz.org/artist/${artistId}"]') !== null`));
    if (artist.wikidata_id) assert.ok(await evaluate(`document.querySelector('#rows a[href="https://www.wikidata.org/wiki/${artist.wikidata_id}"]') !== null`));
    assert.deepEqual((await evaluate("[...document.querySelectorAll('#rows a[href^=\"#wdgenre=\"]')].map(row => row.getAttribute('href').split('=')[1])")).sort(), [...artist.direct_genres].sort());
    await command('Page.reload');
    await wait(`document.querySelector('h1')?.textContent === ${JSON.stringify(artist.name)} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await evaluate(`document.querySelector('#rows a[href="#wdgenre=${genreId}"]').click()`);
    await wait(`location.hash === '#wdgenre=${genreId}' && document.querySelector('.source-artists a') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
  });
});
