import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
import {copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {dirname, join, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const ffmpeg = spawnSync('ffmpeg', ['-version'], {stdio: 'ignore'}).status === 0;
const skip = !chromium || !ffmpeg;
const assets = resolve(dirname(fileURLToPath(import.meta.url)), '../../src/opennoise/static');

async function fixture(root, enabled) {
  const explorer = join(root, 'explorer'), audio = join(root, 'audio');
  await mkdir(explorer); await mkdir(audio);
  for (const name of await readdir(assets)) {
    if (/\.(?:html|css|js|mjs)$/.test(name)) await copyFile(join(assets, name), join(explorer, name));
  }
  await copyFile(join(assets, 'fma-catalog.html'), join(explorer, 'index.html'));
  const tone = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-ar', '22050', '-ac', '1', '-codec:a', 'libmp3lame', join(audio, '2.mp3')]);
  assert.equal(tone.status, 0, tone.stderr.toString());
  await copyFile(join(audio, '2.mp3'), join(audio, '3.mp3'));
  const bytes = await readFile(join(audio, '2.mp3'));
  const tracks = Object.fromEntries([2, 3].map(id => [id, {
    track_id: id, artist_id: 1, title: `Test-only tone ${id}`, artist_name: 'Test fixture',
    audio_path: `${id}.mp3`, audio_sha256: createHash('sha256').update(bytes).digest('hex'),
    audio_bytes: bytes.length, duration_seconds: 4, license_title: 'CC0 fixture',
    license_url: 'https://creativecommons.org/publicdomain/zero/1.0/', source_url: null,
    attribution: 'Synthetic test fixture; not FMA audio',
  }]));
  const catalog = {counts: {raw_tracks: 2, source_artists: 1, missing_artist_records: 0, tracks_with_missing_artist_records: 0, genre_definitions: 0, observed_track_genres: 0, unannotated_tracks: 2}, genres: [], page_size: 200, profile_shards: 128, track_id_span: 500, licenses: [['CC0 fixture', 'https://creativecommons.org/publicdomain/zero/1.0/']]};
  if (enabled) catalog.playback = {manifest: '../audio/manifest.json'};
  await writeFile(join(explorer, 'catalog.json'), JSON.stringify(catalog));
  await writeFile(join(audio, 'manifest.json'), JSON.stringify({revision: 'fma-local-playback-v1', test_only: true, tracks}));
  await writeFile(join(explorer, 'artist-index.json'), JSON.stringify({artists: [[1, 'Test fixture', 2, 'source_known']]}));
  await mkdir(join(explorer, 'tracks'));
  await writeFile(join(explorer, 'tracks/0.json'), JSON.stringify({tracks: [2, 3].map(id => [id, `Test-only tone ${id}`, 1, [], 0, null, null, {}])}));
}

async function browser(operation, {enabled = true} = {}) {
  const root = resolve(await mkdtemp(join(tmpdir(), 'opennoise-synthetic-playback-')));
  await fixture(root, enabled);
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
    child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${join(root, 'profile')}`, 'about:blank']);
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
    await rm(root, {recursive: true, force: true});
  }
}

async function listen({evaluate, wait}) {
  await evaluate("document.querySelector('nav [data-playback]').click()");
  await wait("location.hash === '#listen' && document.querySelector('.playback audio') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
}

test('synthetic-only playback is explicit, attributed, keyboard usable and stops on navigation', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, command, requests} = state;
    assert.equal(await evaluate("document.querySelector('nav [data-playback]').hidden"), false);
    await listen(state);
    assert.match(await evaluate("document.querySelector('main').textContent"), /Test-only audio fixture/);
    assert.match(await evaluate("document.querySelector('.playback').textContent"), /Synthetic test fixture; not FMA audio/);
    assert.ok(await evaluate("document.querySelector('.playback a[href=\"https://creativecommons.org/publicdomain/zero/1.0/\"]') !== null"));
    assert.ok(await evaluate("[...document.querySelectorAll('audio')].every(a => a.controls && a.preload === 'none' && !a.autoplay && a.paused && a.currentTime === 0)"));
    assert.ok(!requests.some(row => row.type === 'Media' || row.request.url.endsWith('.mp3')), 'opening listen does not download media');
    if (process.env.OPENNOISE_FMA_PLAYBACK_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_PLAYBACK_SCREENSHOTS, 'synthetic-playback-desktop.png'), Buffer.from(shot.data, 'base64'));
    }
    await evaluate("document.querySelector('.playback-toggle').focus()");
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await wait("document.querySelector('audio').currentTime > 0.1 && !document.querySelector('audio').paused");
    await evaluate("document.querySelector('.playback-toggle').click()");
    await wait("document.querySelector('audio').paused");
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    if (process.env.OPENNOISE_FMA_PLAYBACK_SCREENSHOTS) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_PLAYBACK_SCREENSHOTS, 'synthetic-playback-mobile.png'), Buffer.from(shot.data, 'base64'));
    }
    await evaluate("document.querySelector('.playback-toggle').click()");
    await wait("!document.querySelector('audio').paused");
    assert.equal(await evaluate("document.querySelectorAll('.playback audio').length"), 2);
    await evaluate("document.querySelectorAll('.playback-toggle')[1].click()");
    await wait("document.querySelectorAll('audio')[0].paused && !document.querySelectorAll('audio')[1].paused && document.querySelectorAll('audio')[1].currentTime > 0.1");
    assert.equal(await evaluate("[...document.querySelectorAll('audio')].filter(a => !a.paused).length"), 1);
    await evaluate("window.retainedAudio = [...document.querySelectorAll('audio')]; location.hash='genres'");
    await wait("document.querySelector('h1').textContent === 'Genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.ok(await evaluate("window.retainedAudio.every(a => a.paused)"), 'route change stops even detached audio');
  });
});

test('synthetic-only missing audio reports failure and offers retry', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, failAudio} = state;
    failAudio(true); await listen(state);
    await evaluate("document.querySelector('.playback-toggle').click()");
    await wait("document.querySelector('.playback-retry') !== null && !document.querySelector('.playback-retry').hidden");
    assert.match(await evaluate("document.querySelector('.playback-status').textContent"), /unavailable|failed|error|could not/i);
    assert.equal(await evaluate("document.querySelector('.playback-status').getAttribute('role')"), 'status');
    assert.match(await evaluate("document.querySelector('.playback').textContent"), /Synthetic test fixture; not FMA audio/);
    failAudio(false);
    await evaluate("document.querySelector('.playback-retry').click()");
    await wait("document.querySelector('audio').currentTime > 0.1 && !document.querySelector('audio').paused");
  });
});

test('catalog without approved playback configuration keeps listen hidden and makes no audio request', {skip, timeout: 60000}, async () => {
  await browser(async ({evaluate, requests}) => {
    assert.equal(await evaluate("document.querySelector('nav [data-playback]').hidden"), true);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));
  }, {enabled: false});
});
