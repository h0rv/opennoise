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
    const externalOrigin = process.env.OPENNOISE_FMA_GENUINE_ORIGIN;
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

test('genuine retained FMA excerpts play locally with attribution and persistent navigation', {skip, timeout: 180000}, async () => {
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
    await evaluate("document.querySelector('.fma-atlas-playable').click()");
    assert.ok(await evaluate("location.hash.includes('playable=1')"));
    assert.equal(await evaluate("document.querySelectorAll('.fma-atlas-listen').length"), new Set(catalog.playback.tracks.flatMap(row => row.genre_ids)).size);
    if (catalog.descriptor_map) {
      await evaluate("location.hash='descriptor-map'");
      await wait("document.querySelector('#status').textContent.includes('164 matching genres') && document.querySelector('.descriptor-canvas') !== null");
      await evaluate("document.querySelector('.descriptor-canvas').focus()");
      await command('Input.dispatchKeyEvent', {type:'keyDown',key:'+',code:'Equal'});
      await command('Input.dispatchKeyEvent', {type:'keyDown',key:'Home',code:'Home'});
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
      await evaluate("const s=document.querySelector('.descriptor-controls select');s.value='artists';s.dispatchEvent(new Event('change',{bubbles:true}))");
      await wait("document.querySelector('#status').textContent.includes('16916 matching artists')");
      assert.ok(await evaluate("document.querySelector('#status').textContent.includes('16109 with coordinates')"));
      await evaluate(`const q=document.querySelector('#descriptor-query');q.value=${JSON.stringify(String(entries[0].artist_id))};q.dispatchEvent(new Event('input',{bubbles:true}))`);
      await wait("document.querySelectorAll('.descriptor-list li').length === 1");
      await evaluate("document.querySelector('.descriptor-list button').click()");
      assert.ok(await evaluate(`document.querySelector('.descriptor-selection a').getAttribute('href') === '#artist=${entries[0].artist_id}'`));
      assert.ok(!requests.some(row => row.type === 'Media' || row.request.url.endsWith('.mp3')), 'map selection does not autoplay');
      await evaluate("document.querySelector('.descriptor-excerpts li button').click()");
      await wait("document.querySelector('#persistent-player audio').currentTime > 0.1 && !document.querySelector('#persistent-player audio').paused");
      await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
      const mapQueue = catalog.playback.tracks.filter(row => row.artist_id === entries[0].artist_id).map(row => row.track_id);
      await evaluate("document.querySelector('.descriptor-play-selection').click()");
      await wait(`document.querySelector('#persistent-player').dataset.trackId === '${mapQueue[0]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
      assert.equal(await evaluate("document.querySelector('.playback-order').textContent"), `1 of ${mapQueue.length} · ${mapQueue.map(id => manifest.tracks[String(id)].title || `Track #${id}`).join(' → ')}`);
      await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
      await command('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
      await wait("document.querySelector('.descriptor-canvas').width > 600");
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);

    }
    const genre = catalog.playback.tracks.find(row => row.genre_ids.length).genre_ids[0];
    const cohort = catalog.playback.tracks.filter(row => row.genre_ids.includes(genre));
    await evaluate(`location.hash='genre=${genre}'`);
    await wait("document.querySelector('#rows a[href^=\"#listen\"]') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await evaluate("document.querySelector('#rows a[href^=\"#listen\"]').click()");
    await wait(`document.querySelectorAll('#rows .playback[data-track-id]').length === ${cohort.length} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.deepEqual((await evaluate("[...document.querySelectorAll('#rows .playback[data-track-id]')].map(row => Number(row.dataset.trackId))")).sort((a,b)=>a-b), cohort.map(row => row.track_id).sort((a,b)=>a-b));
    await evaluate("location.hash='listen'");
    await wait(`document.querySelectorAll('#rows .playback[data-track-id]').length === ${entries.length} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    assert.ok(requests.filter(row => row.type === 'Media').every(row => row.request.url.endsWith('.mp3')), 'only local MP3 media requests');
    const played = [];
    for (const entry of entries) {
      const selector = `#rows .playback[data-track-id="${entry.track_id}"]`;
      assert.ok(await evaluate(`document.querySelector(${JSON.stringify(selector)}).textContent.includes(${JSON.stringify(entry.attribution)})`));
      assert.ok(await evaluate(`document.querySelector(${JSON.stringify(selector)}).querySelector('a[href=${JSON.stringify(entry.license_url)}]') !== null`));
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).querySelector('.playback-toggle').click()`);
      await wait(`(() => {const a=document.querySelector('#persistent-player audio'); return document.querySelector('#persistent-player').dataset.trackId === '${entry.track_id}' && !a.paused && a.currentTime > 0.1 && a.readyState >= 2 && !a.error;})()`);
      assert.equal(await evaluate("[...document.querySelectorAll('audio')].filter(a => !a.paused).length"), 1);
      played.push(entry.track_id);
    }
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    if (process.env.OPENNOISE_FMA_GENUINE_EVIDENCE) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(process.env.OPENNOISE_FMA_GENUINE_EVIDENCE, 'genuine-listening-mobile.png'), Buffer.from(shot.data, 'base64'));
      await writeFile(join(process.env.OPENNOISE_FMA_GENUINE_EVIDENCE, 'browser-playback.json'), JSON.stringify({test_only: false, played_track_ids: played, clips_started: played.length, one_active_player: true, local_requests_only: true, persistent_navigation: true}, null, 2));
    }
    await evaluate("window.retainedAudio=document.querySelector('#persistent-player audio'); window.retainedTime=window.retainedAudio.currentTime; location.hash='genres'");
    await wait("document.querySelector('h1').textContent === 'Genres' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await wait('window.retainedAudio.currentTime > window.retainedTime && !window.retainedAudio.paused');
    assert.equal(await evaluate('document.querySelectorAll("audio").length'), 1);
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    assert.ok(await evaluate('window.retainedAudio.paused && !window.retainedAudio.hasAttribute("src")'));
    await evaluate("location.hash='tracks&playable=1'");
    await wait(`document.querySelectorAll('#rows .track').length === ${entries.length} && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    await evaluate("document.querySelector('#rows .track button').click()");
    await wait("document.querySelector('#persistent-player audio').currentTime > 0.1 && !document.querySelector('#persistent-player audio').paused");
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    await evaluate(`location.hash='track=${entries[0].track_id}'`);
    await wait("document.querySelector('#rows .playback-toggle') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    const expectedRelated = catalog.playback.tracks.filter(row => row.track_id !== entries[0].track_id && row.artist_id !== entries[0].artist_id && row.genre_ids.some(id => catalog.playback.tracks.find(other => other.track_id === entries[0].track_id).genre_ids.includes(id)));
    if (expectedRelated.length) assert.ok(await evaluate("document.querySelector('.playback-related a') !== null"));
    await evaluate("document.querySelector('#rows .playback-toggle').focus()");
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await wait("document.querySelector('#persistent-player audio').currentTime > 0.1 && !document.querySelector('#persistent-player audio').paused");
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    if (catalog.playable_neighbors) {
      const neighbors = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_GENUINE_SITE, 'explorer', catalog.playable_neighbors.manifest_path)));
      assert.equal(neighbors.audio_manifest_sha256, catalog.playback.manifest_sha256);
      for (const entry of neighbors.rows) {
        await evaluate(`location.hash='track=${entry.track_id}'`);
        await wait(`location.hash === '#track=${entry.track_id}' && document.querySelector('#rows .track')?.dataset.trackId === '${entry.track_id}' && document.querySelector('main').getAttribute('aria-busy') === 'false' && document.querySelector('.playable-neighbors') !== null`);
        assert.deepEqual(await evaluate("[...document.querySelectorAll('.playable-neighbor-track')].map(a=>Number(a.hash.slice(7)))"), entry.neighbor_ids);
        assert.ok(entry.neighbor_ids.every(id => neighbors.components[id] !== neighbors.components[entry.track_id]));
        if (catalog.related_music) assert.ok(await evaluate("document.querySelector('.related-music') !== null"), 'original training-pool suggestions remain separate');
      }
      const selected = neighbors.rows.find(row => row.neighbor_ids.length >= 2);
      assert.ok(selected);
      await evaluate(`location.hash='track=${selected.track_id}'`);
      await wait(`document.querySelector('#rows .track')?.dataset.trackId === '${selected.track_id}' && document.querySelector('.playable-neighbors-queue') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
      await evaluate("document.querySelector('.playable-neighbor-play').click()");
      await wait(`document.querySelector('#persistent-player').dataset.trackId === '${selected.neighbor_ids[0]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
      await evaluate("document.querySelector('.playable-neighbors-queue').click()");
      await wait(`document.querySelector('#persistent-player .playback-order').textContent === ${JSON.stringify('1 of ' + selected.neighbor_ids.length + ' · ' + selected.neighbor_ids.map(id => manifest.tracks[id].title).join(' → '))}`);
      await evaluate("window.playableAudio=document.querySelector('#persistent-player audio'); document.querySelector('.playable-neighbor-track').click()");
      await wait(`location.hash === '#track=${selected.neighbor_ids[0]}' && document.querySelector('#rows .track')?.dataset.trackId === '${selected.neighbor_ids[0]}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
      assert.equal(await evaluate("window.playableAudio === document.querySelector('#persistent-player audio') && !window.playableAudio.paused"), true);
      await evaluate('history.back()');
      await wait(`location.hash === '#track=${selected.track_id}' && document.querySelector('#rows .track')?.dataset.trackId === '${selected.track_id}' && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
      assert.deepEqual(await evaluate("[...document.querySelectorAll('.playable-neighbor-track')].map(a=>Number(a.hash.slice(7)))"), selected.neighbor_ids);
      await evaluate("document.querySelector('#persistent-player audio').playbackRate=16");
      await wait(`document.querySelector('#persistent-player').dataset.trackId === '${selected.neighbor_ids[1]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
      await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
      await command('Page.reload');
      await wait("document.documentElement?.dataset.fmaReady === 'true' && document.querySelector('.playable-neighbors-queue') !== null && document.querySelector('main').getAttribute('aria-busy') === 'false'");
      assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0, 'descriptor journey reload never autoplays');
    }
    const journey = [entries[1].track_id, entries[0].track_id];
    await evaluate(`location.hash='listen&queue=${journey.join(',')}'`);
    await wait("document.querySelectorAll('#rows .playback[data-track-id]').length === 2 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.deepEqual(await evaluate("[...document.querySelectorAll('#rows .playback[data-track-id]')].map(row=>Number(row.dataset.trackId))"), journey);
    await evaluate("document.querySelector('.queue-options').open=true;document.querySelector('.queue-share').click();document.querySelector('.queue-save').click()");
    assert.equal(await evaluate("new URL(document.querySelector('.journey-url').value).hash"), '#listen&queue='+journey.join(','));
    await evaluate('window.beforeJourneyReload=true');
    await command('Page.reload');
    await wait("window.beforeJourneyReload === undefined && document.querySelectorAll('#rows .playback[data-track-id]').length === 2 && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.equal(await evaluate('document.querySelectorAll(\"audio\").length'), 0, 'restored journey is silent until explicit Play');
    await evaluate("document.querySelector('.playback-queue').click()");
    await wait(`document.querySelector('#persistent-player').dataset.trackId === '${journey[0]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
    // Natural completion also works on the deliverable's ordinary non-range HTTP server.
    await evaluate("document.querySelector('#persistent-player audio').playbackRate=16");
    await wait(`document.querySelector('#persistent-player').dataset.trackId === '${journey[1]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
    await evaluate("document.querySelector('#persistent-player .playback-repeat').click();document.querySelector('#persistent-player audio').playbackRate=16");
    await wait(`document.querySelector('#persistent-player').dataset.trackId === '${journey[0]}' && document.querySelector('#persistent-player audio').currentTime > 0.1`);
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
  });
});
