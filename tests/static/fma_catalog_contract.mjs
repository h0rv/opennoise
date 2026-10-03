import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
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
