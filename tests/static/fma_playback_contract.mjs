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

async function fixture(root, enabled, trackCount = 2) {
  const explorer = join(root, 'explorer'), audio = join(root, 'audio');
  await mkdir(explorer); await mkdir(audio);
  for (const name of await readdir(assets)) {
    if (/\.(?:html|css|js|mjs)$/.test(name)) await copyFile(join(assets, name), join(explorer, name));
  }
  await copyFile(join(assets, 'fma-catalog.html'), join(explorer, 'index.html'));
  const tone = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-ar', '22050', '-ac', '1', '-codec:a', 'libmp3lame', join(audio, '2.mp3')]);
  assert.equal(tone.status, 0, tone.stderr.toString());
  const fixtureIds = Array.from({length:trackCount}, (_, index) => index + 2);
  for (const id of fixtureIds.slice(1)) await copyFile(join(audio, '2.mp3'), join(audio, `${id}.mp3`));
  const bytes = await readFile(join(audio, '2.mp3'));
  const tracks = Object.fromEntries(fixtureIds.map(id => [id, {
    track_id: id, artist_id: 1, title: `Test-only tone ${id}`, artist_name: 'Test fixture',
    audio_path: `${id}.mp3`, audio_sha256: createHash('sha256').update(bytes).digest('hex'),
    audio_bytes: bytes.length, duration_seconds: 4, license_title: 'CC0 fixture',
    license_url: 'https://creativecommons.org/publicdomain/zero/1.0/', source_url: null,
    attribution: 'Synthetic test fixture; not FMA audio',
  }]));
  const catalog = {counts: {raw_tracks: 2, source_artists: 1, missing_artist_records: 0, tracks_with_missing_artist_records: 0, genre_definitions: 0, observed_track_genres: 0, unannotated_tracks: 2}, genres: [], page_size: 200, profile_shards: 128, track_id_span: 500, licenses: [['CC0 fixture', 'https://creativecommons.org/publicdomain/zero/1.0/']]};
  if (enabled) catalog.playback = {manifest: '../audio/manifest.json', tracks: fixtureIds.map(track_id => ({track_id, artist_id:1, genre_ids:[]}))};
  await writeFile(join(explorer, 'catalog.json'), JSON.stringify(catalog));
  await writeFile(join(audio, 'manifest.json'), JSON.stringify({revision: 'fma-local-playback-v1', test_only: true, tracks}));
  await writeFile(join(explorer, 'artist-index.json'), JSON.stringify({artists: [[1, 'Test fixture', 2, 'source_known']]}));
  await mkdir(join(explorer, 'tracks'));
  await writeFile(join(explorer, 'tracks/0.json'), JSON.stringify({tracks: [2, 3].map(id => [id, `Test-only tone ${id}`, 1, [], 0, null, null, {}])}));
}

async function browser(operation, {enabled = true, trackCount = 2} = {}) {
  const root = resolve(await mkdtemp(join(tmpdir(), 'opennoise-synthetic-playback-')));
  await fixture(root, enabled, trackCount);
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
  await wait("location.hash === '#listen' && document.querySelector('.listening-entry .playback-toggle') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
}

test('persistent synthetic player requires Play, retains credits and survives navigation until Stop', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, command, requests} = state;
    await listen(state);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    assert.ok(!requests.some(row => row.type === 'Media' || row.request.url.endsWith('.mp3')));
    await evaluate("document.querySelector('.listening-entry .playback-toggle').focus()");
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await wait("document.querySelector('#persistent-player audio')?.currentTime > 0.1 && !document.querySelector('#persistent-player audio').paused");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 1);
    assert.match(await evaluate("document.querySelector('#persistent-player').textContent"), /Test-only audio fixture.*Synthetic test fixture/s);
    assert.ok(await evaluate("document.querySelector('#persistent-player a[href=\"https://creativecommons.org/publicdomain/zero/1.0/\"]') !== null"));
    await evaluate("window.originalAudio=document.querySelector('audio'); window.beforeRoute=originalAudio.currentTime; location.hash='genres'");
    await wait("document.querySelector('h1').textContent === 'Genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await wait("document.querySelector('audio') === window.originalAudio && originalAudio.currentTime > window.beforeRoute && !originalAudio.paused");
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    await evaluate("document.querySelector('#persistent-player .playback-toggle').click()");
    await wait("document.querySelector('audio').paused");
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    assert.ok(await evaluate("document.querySelector('#persistent-player').hidden && originalAudio.paused && !originalAudio.hasAttribute('src')"));
    await command('Page.reload');
    await wait("document.documentElement?.dataset.fmaReady === 'true'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
  });
});

test('persistent queue preserves its snapshot through search and navigation, advances and pauses', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait} = state;
    await listen(state);
    await evaluate("document.querySelector('#listen-query').value='tone 3'; document.querySelector('#listen-query').dispatchEvent(new Event('input'))");
    assert.equal(await evaluate("document.querySelectorAll('.listening-entry:not([hidden])').length"), 1);
    await evaluate("document.querySelector('#listen-query').value='TEST FIXTURE'; document.querySelector('#listen-query').dispatchEvent(new Event('input'))");
    assert.equal(await evaluate("document.querySelectorAll('.listening-entry:not([hidden])').length"), 2);
    await evaluate("document.querySelector('.playback-queue').click()");
    await wait("document.querySelector('audio')?.currentTime > 0.1 && !document.querySelector('audio').paused");
    await evaluate("document.querySelector('#listen-query').value='not present'; document.querySelector('#listen-query').dispatchEvent(new Event('input'))");
    assert.match(await evaluate("document.querySelector('.listening-status').textContent"), /No matching excerpts/);
    assert.equal(await evaluate("document.querySelector('audio').paused"), false);
    await evaluate("document.querySelector('#persistent-player .playback-next').click()");
    await wait("document.querySelector('#persistent-player').dataset.trackId === '3' && document.querySelector('audio').currentTime > 0.1");
    await evaluate("document.querySelector('#persistent-player .playback-previous').click()");
    await wait("document.querySelector('#persistent-player').dataset.trackId === '2' && !document.querySelector('audio').paused");
    await evaluate("location.hash='genres'");
    await wait("document.querySelector('h1').textContent === 'Genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('audio').currentTime=document.querySelector('audio').duration-0.1");
    await wait("document.querySelector('#persistent-player').dataset.trackId === '3' && !document.querySelector('audio').paused && document.querySelector('audio').currentTime > 0.1");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 1);
    await evaluate("document.querySelector('#persistent-player .playback-toggle').click()");
    await wait("document.querySelector('audio').paused");
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
  });
});

test('persistent synthetic missing audio preserves attribution and retries after recovery', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, failAudio} = state;
    failAudio(true); await listen(state);
    await evaluate("document.querySelector('.listening-entry .playback-toggle').click()");
    await wait("document.querySelector('#persistent-player .playback-retry')?.hidden === false");
    assert.match(await evaluate("document.querySelector('#persistent-player .playback-status').textContent"), /unavailable/i);
    assert.match(await evaluate("document.querySelector('#persistent-player').textContent"), /Synthetic test fixture; not FMA audio/);
    failAudio(false); await evaluate("document.querySelector('#persistent-player .playback-retry').click()");
    await wait("document.querySelector('audio').currentTime > 0.1 && !document.querySelector('audio').paused");
  });
});

test('rejected play disarms the queue and Stop cancels a pending manifest request', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait} = state;
    await listen(state);
    await evaluate("window.realPlay=HTMLMediaElement.prototype.play; HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('Blocked fixture','NotAllowedError'))}; document.querySelector('.playback-queue').click()");
    await wait("document.querySelector('#persistent-player .playback-retry')?.hidden === false");
    assert.equal(await evaluate("document.querySelector('.playback-queue').textContent"), 'Play queue');
    assert.equal(await evaluate("document.querySelector('audio').paused"), true);
    await evaluate("HTMLMediaElement.prototype.play=window.realPlay");
    await evaluate(`(async () => {
      const api=await import('./fma-playback.js'); api.stopPlayback();
      window.fixtureManifest=await fetch('../audio/manifest.json').then(r=>r.json());
      window.delayedPlay=api.requestPlay({config:{manifest:'../audio/manifest.json'},id:2,json:()=>new Promise(resolve=>{window.resolveManifest=resolve})});
      document.querySelector('#persistent-player .playback-stop').click(); window.resolveManifest(window.fixtureManifest); window.delayedResult=await window.delayedPlay;
    })()`);
    assert.equal(await evaluate('window.delayedResult'), false);
    assert.ok(await evaluate("document.querySelector('#persistent-player').hidden && document.querySelector('audio').paused && !document.querySelector('audio').hasAttribute('src')"));
  });
});

test('catalog without playback stays silent and shared-annotation links create no players', {skip, timeout: 60000}, async () => {
  await browser(async ({evaluate, requests}) => {
    assert.equal(await evaluate("document.querySelector('nav [data-playback]').hidden"), true);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));
  }, {enabled:false});
  await browser(async ({evaluate}) => {
    await evaluate(`(async()=>{ const {renderPlayback}=await import('./fma-playback.js'); await renderPlayback({config:{manifest:'../audio/manifest.json'},id:2,relatedIds:[2,3,3,999999],json:path=>fetch(path).then(r=>r.json()),rows:document.querySelector('#rows'),heading:document.querySelector('h1'),status:document.querySelector('#status'),current:()=>true}); })()`);
    assert.equal(await evaluate("document.querySelectorAll('.playback-related li').length"), 1);
    assert.equal(await evaluate("document.querySelector('.playback-related a').getAttribute('href')"), '#track=3');
    assert.match(await evaluate("document.querySelector('.playback-related').textContent"), /Shared source annotations; not a musical-similarity ranking/);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
  });
});

test('editable queue shares ordered native IDs and saves/restores without autoplay', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait, command} = state;
    await listen(state);
    await evaluate("document.querySelector('.queue-options').open=true; document.querySelector('.queue-clear').click()");
    assert.equal(await evaluate("document.querySelector('.playback-queue').disabled"), true);
    await evaluate("document.querySelector('.queue-include[value=\"3\"]').click(); document.querySelector('.queue-include[value=\"2\"]').click(); document.querySelector('.queue-share').click()");
    const shared = await evaluate("document.querySelector('.journey-url').value");
    assert.equal(new URL(shared).hash, '#listen&queue=3,2');
    assert.equal(await evaluate("document.querySelector('.journey-url').readOnly"), true);
    await evaluate("document.querySelector('.queue-save').click()");
    assert.deepEqual(await evaluate("JSON.parse(localStorage.getItem('opennoise.fma-listening-journey.v1'))"), {revision:'fma-native-listening-journey-v1', track_ids:[3,2]});
    await evaluate("document.querySelector('.queue-clear').click(); document.querySelector('.queue-restore').click()");
    await wait("location.hash === '#listen&queue=3,2' && document.querySelector('.queue-include')?.value === '3' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await command('Page.reload');
    await wait("document.querySelector('.queue-include')?.value === '3' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.queue-include')].map(input=>Number(input.value))"), [3,2]);
    await evaluate("document.querySelector('.queue-options').open=true; document.querySelector('.queue-select-visible').click(); document.querySelector('.queue-share').click()");
    assert.equal(await evaluate("new URL(document.querySelector('.journey-url').value).hash"), '#listen&queue=3,2');
    await evaluate("localStorage.setItem('opennoise.fma-listening-journey.v1', JSON.stringify({revision:'fma-native-listening-journey-v1',track_ids:[3,'https://evil.invalid/clip']}))");
    await command('Page.reload');
    await wait("document.querySelector('.queue-restore') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('.queue-restore').disabled"), true);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
  });
});

test('shuffle preserves current track and queue membership; repeat only advances an armed queue', {skip, timeout: 60000}, async () => {
  await browser(async state => {
    const {evaluate, wait} = state;
    await listen(state);
    await evaluate("document.querySelector('.playback-queue').click()");
    await wait("document.querySelector('audio')?.currentTime > 0.1 && !document.querySelector('audio').paused");
    await evaluate("window.originalRandom=Math.random; Math.random=()=>0; document.querySelector('.playback-shuffle').click(); Math.random=window.originalRandom");
    assert.equal(await evaluate("document.querySelector('#persistent-player').dataset.trackId"), '2');
    const order = await evaluate("document.querySelector('.playback-order').textContent");
    const titles = [...order.matchAll(/Test-only tone ([0-9]+)/g)].map(match => Number(match[1]));
    assert.equal(titles[0], 2);
    assert.deepEqual([...titles].sort(), [2,3,4,5]);
    assert.equal(new Set(titles).size, 4);
    assert.notDeepEqual(titles, [2,3,4,5]);
    await evaluate("document.querySelector('.playback-repeat').click()");
    assert.equal(await evaluate("document.querySelector('.playback-repeat').getAttribute('aria-pressed')"), 'true');
    for (const id of titles.slice(1)) {
      await evaluate("document.querySelector('.playback-next').click()");
      await wait(`document.querySelector('#persistent-player').dataset.trackId === '${id}' && !document.querySelector('audio').paused && document.querySelector('audio').readyState >= 1`);
    }
    await evaluate("document.querySelector('audio').currentTime=document.querySelector('audio').duration-0.1");
    await wait("document.querySelector('#persistent-player').dataset.trackId === '2' && !document.querySelector('audio').paused");
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    assert.equal(await evaluate("document.querySelector('.playback-repeat').getAttribute('aria-pressed')"), 'false');
    assert.ok(await evaluate("document.querySelector('audio').paused && document.querySelector('#persistent-player').hidden"));
    await evaluate("document.querySelector('audio').dispatchEvent(new Event('ended'))");
    assert.equal(await evaluate("document.querySelector('#persistent-player').hidden"), true);
  }, {trackCount:4});
});

test('explicit collection revision plays synthetic audio while unknown revisions and oversized pools fail closed', {skip, timeout: 60000}, async () => {
  await browser(async ({evaluate, wait, requests}) => {
    await evaluate(`(async()=>{
      window.collectionApi=await import('./fma-playback.js');
      window.collectionFixture=await fetch('../audio/manifest.json').then(response=>response.json());
      window.collectionFixture.revision='fma-local-playback-collection-v1';
      window.collectionResult=await window.collectionApi.requestPlay({config:{manifest:'../audio/manifest.json'},id:2,json:async()=>window.collectionFixture});
    })()`);
    assert.equal(await evaluate('window.collectionResult'), true);
    await wait("document.querySelector('audio').currentTime > 0.1 && !document.querySelector('audio').paused");
    assert.match(await evaluate("document.querySelector('#persistent-player').textContent"), /Test-only audio fixture/);
    await evaluate('window.collectionApi.stopPlayback()');
    const before = requests.filter(row => row.request.url.endsWith('.mp3')).length;
    for (const mutation of [
      "pack.revision='fma-local-playback-collection-v2'",
      "pack.tracks=Object.fromEntries(Array.from({length:65},(_,i)=>[i+2,{...pack.tracks[2],track_id:i+2,audio_path:`${i+2}.mp3`}]))",
      "pack.tracks[2].audio_path='../other.mp3'",
    ]) {
      const accepted = await evaluate(`(async()=>{ const pack=structuredClone(window.collectionFixture); ${mutation}; return window.collectionApi.requestPlay({config:{manifest:'../audio/manifest.json'},id:2,json:async()=>pack}); })()`);
      assert.equal(accepted, false);
      assert.equal(await evaluate("document.querySelector('audio').paused && !document.querySelector('audio').hasAttribute('src')"), true);
      await evaluate('window.collectionApi.stopPlayback()');
    }
    assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, before);
  });
});
