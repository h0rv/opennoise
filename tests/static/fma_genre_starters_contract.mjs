import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_STARTERS_SITE;
async function browser(operation, mutateIndex = null) {
  const root = resolve(process.env.OPENNOISE_FMA_STARTERS_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      const overlay = process.env.OPENNOISE_FMA_STARTERS_ASSETS;
      const asset = path === '/index.html' ? 'fma-discovery.html' : path.slice(1);
      const replace = overlay && ['fma-discovery.html', 'fma-discovery.js', 'fma-discovery-search.js', 'fma-playback.js'].includes(asset);
      let body = await readFile(replace ? join(resolve(overlay), asset) : file);
      if (mutateIndex && path === '/genre-discovery.json') { const value=JSON.parse(body); mutateIndex(value); body=Buffer.from(JSON.stringify(value)); }
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    const externalOrigin = process.env.OPENNOISE_FMA_STARTERS_ORIGIN;
    if (externalOrigin && !/^http:\/\/127\.0\.0\.1:\d+$/.test(externalOrigin)) throw Error('External genuine test origin must be localhost.');
    if (!externalOrigin) await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = externalOrigin ?? `http://127.0.0.1:${server.address().port}`;
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
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true, replMode: true}); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
    const wait = async expression => { for (let i = 0; i < 400; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error(`Timed out: ${expression}`); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
    await command('Page.navigate', {url: `${origin}/index.html`});
    await wait(mutateIndex ? "document.querySelector('h1')?.textContent === 'Listening index unavailable'" : "document.documentElement?.dataset.discoveryReady === 'true'");
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

test('real genre starters keep collection audio, credits and sequence through navigation', {skip, timeout:120000}, async () => {
  const root = process.env.OPENNOISE_FMA_STARTERS_SITE;
  const index = JSON.parse(await readFile(join(root, 'genre-discovery.json')));
  const genre = index.genres.find(genre => new Set(genre.starting_ids.map(id => index.tracks[id].collection)).size > 1);
  assert.ok(genre, 'retained source has cross-collection genre starters');
  const manifests = {};
  for (const collection of ['original','expanded']) manifests[collection] = JSON.parse(await readFile(join(root, collection, 'audio/manifest.json')));
  await browser(async ({evaluate, wait, command, requests}) => {
    await evaluate(`location.hash='#genre=${genre.genre_id}'`);
    await wait("document.querySelector('.genre-play-starters')");
    assert.ok(!requests.some(row => row.request.url.includes('/audio/')));
    await evaluate("document.querySelector('.genre-play-starters').click()");
    const check = async position => {
      const id = genre.starting_ids[position], track = index.tracks[id];
      await wait(`document.querySelector('#persistent-player')?.dataset.trackId === '${id}' && document.querySelector('audio').currentTime > .1 && !document.querySelector('audio').paused`);
      assert.ok((await evaluate("document.querySelector('audio').src")).endsWith(`/${track.collection}/audio/${id}.mp3`));
      assert.ok((await evaluate("document.querySelector('#persistent-player').textContent")).includes(manifests[track.collection].tracks[id].attribution));
      assert.equal(await evaluate("document.querySelectorAll('audio').length"), 1);
    };
    await check(0);
    assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, 1);
    await evaluate(`location.hash='#artist=${index.tracks[genre.starting_ids[0]].artist_id}'`);
    await wait("document.querySelector('#content').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate("document.querySelector('audio').paused"), false);
    await evaluate("document.querySelector('audio').pause(); await document.querySelector('audio').play(); document.querySelector('audio').playbackRate=16");
    await check(1);
    await evaluate("document.querySelector('audio').playbackRate=1; document.querySelector('.playback-previous').click()");
    await check(0);
    for (let position=1; position<genre.starting_ids.length; position++) {
      await evaluate("document.querySelector('.playback-next').click()");
      await check(position);
    }
    const output = process.env.OPENNOISE_FMA_STARTERS_EVIDENCE;
    if (output) {
      await mkdir(output, {recursive:true});
      await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
      assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
      await writeFile(join(output,'genre-starters-mobile.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));
      await writeFile(join(output,'genre-starters.json'),JSON.stringify({genre_id:genre.genre_id,starting_ids:genre.starting_ids,collections:genre.starting_ids.map(id=>index.tracks[id].collection),exact_audio_and_credits:true,native_resume_and_natural_end:true,previous_next:true,no_prefetch:true},null,2));
    }
    await evaluate("document.querySelector('.playback-stop').click()");
    assert.equal(await evaluate("document.querySelector('audio').getAttribute('src')"), null);
    await command('Page.reload');
    await wait("document.documentElement?.dataset.discoveryReady === 'true'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
  });
});
