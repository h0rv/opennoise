import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_GENUINE_SITE;
async function browser(operation) {
  const root = resolve(process.env.OPENNOISE_FMA_GENUINE_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      const body = await readFile(file);
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
    const endpoint = await new Promise((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('Chromium startup timed out')), 10000);
      child.on('error', reject); child.stderr.on('data', bytes => { output += bytes; const match = output.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//); if (match) { clearTimeout(timer); resolve(`http://127.0.0.1:${match[1]}`); } });
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, {method: 'PUT'}).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
    let sequence = 0; const pending = new Map();
    socket.addEventListener('message', ({data}) => { const result = JSON.parse(data); if (result.method === 'Network.requestWillBeSent') requests.push(result.params); if (result.method === 'Runtime.exceptionThrown') errors.push(result.params.exceptionDetails); pending.get(result.id)?.(result); });
    const command = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence, timer = setTimeout(() => reject(new Error(`${method} timed out`)), 10000); pending.set(id, result => { clearTimeout(timer); pending.delete(id); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); }); socket.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true}); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
    const wait = async expression => { for (let i = 0; i < 400; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error(`Timed out: ${expression}`); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
    await command('Page.navigate', {url: `${origin}/explorer/index.html`});
    await wait("document.documentElement?.dataset.fmaReady === 'true' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)), 'landing does not fetch audio or its manifest');
    await operation({evaluate, wait, command, requests, failAudio: value => { failAudio = value; }});
    assert.deepEqual(errors, []);
    assert.ok(requests.every(row => new URL(row.request.url).origin === origin || (row.type === 'Image' && row.request.url.startsWith('data:image/'))), 'network requests stay local; native controls may use embedded image icons');
  } finally {
    socket?.close(); if (child) { child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); }
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await rm(profile, {recursive: true, force: true});
  }
}

test('genuine retained FMA excerpts play locally with attribution and navigation isolation', {skip, timeout: 180000}, async () => {
  const manifest = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_GENUINE_SITE, 'audio/manifest.json')));
  assert.equal(manifest.test_only, false);
  assert.equal(manifest.public_deployment_authorized, false);
  const entries = Object.values(manifest.tracks);
  assert.ok(entries.length > 0 && entries.length <= 64);
  await browser(async ({evaluate, wait, command, requests}) => {
    await evaluate("location.hash='listen&genre=invalid'");
    await wait("document.querySelector('h1').textContent === 'Catalog unavailable'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await evaluate("location.hash='genre-map'");
    await wait("document.querySelector('h1').textContent === 'Genre families' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    const catalog = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_GENUINE_SITE, 'explorer/catalog.json')));
    assert.equal(await evaluate("document.querySelectorAll('#rows a[href^=\"#genre=\"]').length"), catalog.genres.length);
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    const genre = catalog.playback.tracks.find(row => row.genre_ids.length).genre_ids[0];
    const cohort = catalog.playback.tracks.filter(row => row.genre_ids.includes(genre));
    await evaluate(`location.hash='genre=${genre}'`);
    await wait("document.querySelector('#rows a[href^=\"#listen\"]') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('#rows a[href^=\"#listen\"]').click()");
    await wait(`document.querySelectorAll('.playback audio').length === ${cohort.length} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.deepEqual((await evaluate("[...document.querySelectorAll('.playback')].map(row => Number(row.dataset.trackId))")).sort((a,b)=>a-b), cohort.map(row => row.track_id).sort((a,b)=>a-b));
    await evaluate("location.hash='listen'");
    await wait(`document.querySelectorAll('.playback audio').length === ${entries.length} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(!requests.some(row => row.type === 'Media' || row.request.url.endsWith('.mp3')), 'no MP3 request before playback gesture');
    const played = [];
    for (const entry of entries) {
      const selector = `.playback[data-track-id="${entry.track_id}"]`;
      assert.ok(await evaluate(`document.querySelector(${JSON.stringify(selector)}).textContent.includes(${JSON.stringify(entry.attribution)})`));
      assert.ok(await evaluate(`document.querySelector(${JSON.stringify(selector)}).querySelector('a[href=${JSON.stringify(entry.license_url)}]') !== null`));
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).querySelector('.playback-toggle').click()`);
      await wait(`(() => {const a=document.querySelector(${JSON.stringify(selector)}).querySelector('audio'); return !a.paused && a.currentTime > 0.1 && a.readyState >= 2 && !a.error;})()`);
      assert.equal(await evaluate("[...document.querySelectorAll('audio')].filter(a => !a.paused).length"), 1);
      played.push(entry.track_id);
    }
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    if (process.env.OPENNOISE_FMA_GENUINE_EVIDENCE) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_GENUINE_EVIDENCE, 'genuine-listening-mobile.png'), Buffer.from(shot.data, 'base64'));
      await writeFile(join(process.env.OPENNOISE_FMA_GENUINE_EVIDENCE, 'browser-playback.json'), JSON.stringify({test_only: false, played_track_ids: played, clips_started: played.length, one_active_player: true, local_requests_only: true}, null, 2));
    }
    await evaluate("window.retainedAudio=[...document.querySelectorAll('audio')]; location.hash='genres'");
    await wait("document.querySelector('h1').textContent === 'Genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate('window.retainedAudio.every(a => a.paused && !a.hasAttribute("src"))'));
    await evaluate(`location.hash='track=${entries[0].track_id}'`);
    await wait("document.querySelector('.playback audio') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    const expectedRelated = catalog.playback.tracks.filter(row => row.track_id !== entries[0].track_id && row.artist_id !== entries[0].artist_id && row.genre_ids.some(id => catalog.playback.tracks.find(other => other.track_id === entries[0].track_id).genre_ids.includes(id)));
    if (expectedRelated.length) assert.ok(await evaluate("document.querySelector('.playback-related a') !== null"));
    await evaluate("document.querySelector('.playback-toggle').focus()");
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await wait("document.querySelector('audio').currentTime > 0.1 && !document.querySelector('audio').paused");
  });
});
