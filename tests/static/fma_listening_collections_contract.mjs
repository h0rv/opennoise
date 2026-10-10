import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_COLLECTION_SITE;
async function browser(operation) {
  const root = resolve(process.env.OPENNOISE_FMA_COLLECTION_SITE);
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
    const externalOrigin = process.env.OPENNOISE_FMA_COLLECTION_ORIGIN;
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
    const evaluate = async expression => { const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true}); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
    const wait = async expression => { for (let i = 0; i < 400; i++) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 20)); } throw new Error(`Timed out: ${expression}`); };
    await command('Network.enable'); await command('Runtime.enable'); await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
    await command('Page.navigate', {url: `${origin}/index.html`});
    await wait("document.querySelector('h1')?.textContent === 'OpenNoise · listen'");
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

test('bounded listening collections link native genre cohorts and switch without autoplay', {skip, timeout: 180000}, async () => {
  const root = process.env.OPENNOISE_FMA_COLLECTION_SITE;
  const receipt = JSON.parse(await readFile(join(root, 'collections.json')));
  const catalog = JSON.parse(await readFile(join(root, 'expanded/explorer/catalog.json')));
  const output = process.env.OPENNOISE_FMA_COLLECTION_EVIDENCE;
  if (output) await mkdir(output, {recursive:true});
  await browser(async ({evaluate, wait, command, requests}) => {
    const snapshot = async name => {
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
      if (output) await writeFile(join(output, `${name}.png`), Buffer.from((await command('Page.captureScreenshot', {format:'png'})).data, 'base64'));
    };
    const ready = async hash => wait(`location.hash === ${JSON.stringify(hash)} && document.documentElement?.dataset.fmaReady === 'true' && document.querySelector('main')?.getAttribute('aria-busy') === 'false'`);
    const links = await evaluate("[...document.querySelectorAll('.genres a')].map(a=>a.getAttribute('href'))");
    assert.deepEqual(links, receipt.new_direct_genre_ids.map(id => `expanded/explorer/index.html#listen&genre=${id}`));
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await snapshot('collections-desktop');
    await command('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});
    await snapshot('collections-mobile');
    await evaluate("document.querySelector('a[href^=\"original/explorer\"]').click()");
    await ready('#listen');
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await evaluate("document.querySelector('.listening-entry .playback-toggle').click()");
    await wait("document.querySelector('#persistent-player audio')?.currentTime > .1 && !document.querySelector('#persistent-player audio').paused");
    const active = await evaluate("document.querySelector('#persistent-player').dataset.trackId");
    await evaluate(`location.hash='track=${active}'`);
    await ready(`#track=${active}`);
    assert.equal(await evaluate("document.querySelector('#persistent-player audio').paused"), false);
    await evaluate("document.querySelector('[data-collection-home]').click()");
    await wait("document.querySelector('h1')?.textContent === 'OpenNoise · listen'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    const mediaBefore = requests.filter(row => row.request.url.endsWith('.mp3')).length;
    await evaluate("document.querySelector('a[href^=\"expanded/explorer\"]').click()");
    await ready('#listen');
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, mediaBefore);
    const checked = [];
    for (const id of receipt.new_direct_genre_ids) {
      await evaluate(`location.hash='listen&genre=${id}'`);
      await ready(`#listen&genre=${id}`);
      const expected = catalog.playback.tracks.filter(row => row.genre_ids.includes(id)).map(row => row.track_id).sort((a,b)=>a-b);
      const actual = await evaluate("[...document.querySelectorAll('#rows .playback[data-track-id]')].map(row=>Number(row.dataset.trackId)).sort((a,b)=>a-b)");
      assert.ok(expected.length > 0);
      assert.deepEqual(actual, expected);
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
      checked.push({genre_id:id,track_ids:actual});
    }
    await snapshot('expanded-genre-mobile');
    await command('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
    await snapshot('expanded-genre-desktop');
    assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, mediaBefore);
    if (output) await writeFile(join(output,'collections-browser.json'), JSON.stringify({revision:'fma-collections-browser-v1',distinct_clips:receipt.distinct_clips,new_genre_routes:checked,persistence_track_id:Number(active),cross_collection_autoplay:false,viewport_widths:[1280,390],media_requests:mediaBefore},null,2));
  });
});
