import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_SEARCH_SITE;
async function browser(operation, mutateIndex = null) {
  const root = resolve(process.env.OPENNOISE_FMA_SEARCH_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      const overlay = process.env.OPENNOISE_FMA_SEARCH_ASSETS;
      const asset = path === '/index.html' ? 'fma-discovery.html' : path.slice(1);
      const replace = overlay && ['fma-discovery.html', 'fma-discovery.js', 'fma-discovery-search.js'].includes(asset);
      let body = await readFile(replace ? join(resolve(overlay), asset) : file);
      if (mutateIndex && path === '/genre-discovery.json') { const value=JSON.parse(body); mutateIndex(value); body=Buffer.from(JSON.stringify(value)); }
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    const externalOrigin = process.env.OPENNOISE_FMA_SEARCH_ORIGIN;
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

test('retained search reaches every title with keyboard, history, direct playback and mobile', {skip, timeout:120000}, async () => {
  const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_SEARCH_SITE, 'genre-discovery.json')));
  const output = process.env.OPENNOISE_FMA_SEARCH_EVIDENCE;
  if (output) await mkdir(output, {recursive:true});
  await browser(async ({evaluate, wait, command, requests}) => {
    const ready = async hash => wait(`location.hash === ${JSON.stringify(hash)} && document.querySelector('#content').getAttribute('aria-busy') === 'false'`);
    const search = async text => {
      const hash = '#search&q=' + encodeURIComponent(text);
      await evaluate(`location.hash=${JSON.stringify(hash)}`);
      await ready(hash);
    };
    await evaluate("document.querySelector('nav a[href=\"#search\"]').click()");
    await ready('#search');
    assert.match(await evaluate("document.querySelector('#discovery-status').textContent"), /genres, artists or attached tracks/);
    assert.equal(await evaluate("document.querySelector('#availability-label').hidden"), true);
    await command('Input.dispatchKeyEvent', {type:'keyDown',key:'/',code:'Slash'});
    assert.equal(await evaluate('document.activeElement.id'), 'discovery-query');
    for (const track of Object.values(index.tracks)) {
      await search(track.title || `Track #${track.track_id}`);
      assert.ok(await evaluate(`document.querySelector('[data-search-kind="tracks"] li[data-native-id="${track.track_id}"]') !== null`));
    }
    const track = Object.values(index.tracks).find(row => row.title);
    await search(String(track.track_id));
    assert.ok(await evaluate(`document.querySelector('[data-search-kind="tracks"] li[data-native-id="${track.track_id}"]') !== null`));
    await evaluate(`document.querySelector('#discovery-query').value=${JSON.stringify(track.title + ' & missing')};document.querySelector('#discovery-query').dispatchEvent(new Event('input',{bubbles:true}))`);
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).get('q')"), track.title + ' & missing');
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).has('search')"), true);

    await search(track.artist_name);
    assert.ok(await evaluate(`document.querySelector('[data-search-kind="artists"] a[href="#artist=${track.artist_id}"]') !== null`));
    const missing = index.genres.find(genre => !genre.track_ids.length);
    if (missing) {
      await search(missing.title);
      assert.match(await evaluate(`document.querySelector('[data-search-kind="genres"] li[data-native-id="${missing.genre_id}"]').textContent`), /No local excerpt/);
      assert.equal(await evaluate(`document.querySelector('[data-search-kind="genres"] li[data-native-id="${missing.genre_id}"] button')`), null);
    }
    assert.ok(!requests.some(row => row.request.url.endsWith('.mp3')));
    await search(track.title);
    await evaluate(`document.querySelector('[data-search-kind="tracks"] button[data-play-id="${track.track_id}"]').click()`);
    await wait(`document.querySelector('#persistent-player')?.dataset.trackId === '${track.track_id}' && document.querySelector('audio').currentTime > .1 && !document.querySelector('audio').paused`);
    await evaluate(`document.querySelector('[data-search-kind="tracks"] a[href="#track=${track.track_id}"]').click()`);
    await ready(`#track=${track.track_id}`);
    assert.equal(await evaluate("document.querySelector('audio').paused"), false);
    await evaluate('history.back()');
    await ready('#search&q=' + encodeURIComponent(track.title));
    assert.equal(await evaluate("document.querySelector('#discovery-query').value"), track.title);
    assert.equal(await evaluate("document.querySelector('audio').paused"), false);
    await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
    await command('Page.reload');
    await wait("document.documentElement?.dataset.discoveryReady === 'true'");
    assert.equal(await evaluate("document.querySelector('#discovery-query').value"), track.title);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await evaluate("document.querySelector('#discovery-query').focus()");
    await command('Input.dispatchKeyEvent', {type:'keyDown',key:'ArrowDown',code:'ArrowDown'});
    assert.equal(await evaluate('document.activeElement.tagName'), 'A');
    const target = await evaluate('document.activeElement.hash');
    await command('Input.dispatchKeyEvent', {type:'keyDown',key:'Enter',code:'Enter'});
    await ready(target);
    await search('<script>missing-query</script>');
    assert.match(await evaluate("document.querySelector('#discovery-status').textContent"), /No matching/);
    assert.equal(await evaluate("document.querySelectorAll('#discovery-rows script').length"), 0);
    await search(track.artist_name);
    for (const [width, height, name] of [[1280,900,'search-desktop'],[390,844,'search-mobile']]) {
      await command('Emulation.setDeviceMetricsOverride', {width,height,deviceScaleFactor:1,mobile:width===390});
      assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
      if (output) await writeFile(join(output,name+'.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));
    }
    if (output) await writeFile(join(output,'search-browser.json'),JSON.stringify({revision:'fma-retained-search-browser-v1',all_track_titles_reachable:Object.keys(index.tracks).length,artist_query:track.artist_name,played_track:track.track_id,history_reload:true,keyboard:true,mobile_no_overflow:true},null,2));
  });
});

test('full source handoff finds an unattached title, carries queries and leaves playback stopped', {skip, timeout:120000}, async () => {
  const root = process.env.OPENNOISE_FMA_SEARCH_SITE;
  const index = JSON.parse(await readFile(join(root, 'genre-discovery.json')));
  const catalog = JSON.parse(await readFile(join(root, 'expanded/explorer/catalog.json')));
  const firstShard = JSON.parse(await readFile(join(root, 'expanded/explorer', catalog.track_search.shards[0])));
  const source = await readFile(new URL('../../src/opennoise/static/fma-discovery-search.js', import.meta.url), 'utf8');
  const {searchDiscovery} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const artists = new Map(Object.values(index.tracks).map(track => [track.artist_id, {
    id:track.artist_id, name:track.artist_name, track_ids:[track.track_id]
  }]));
  const fixture = firstShard.find(([id, title]) => title?.includes('&') && !index.tracks[id]
    && Object.values(searchDiscovery(index, artists, title)).every(rows => !rows.length));
  assert.ok(fixture, 'authentic unattached title containing an encoded ampersand exists');
  const [id, title] = fixture;
  await browser(async ({evaluate, wait, command, requests}) => {
    const retained = Object.values(index.tracks)[0];
    await evaluate(`location.hash='#search&q=${retained.track_id}'`);
    await wait(`document.querySelector('[data-search-kind="tracks"] button[data-play-id="${retained.track_id}"]')`);
    await evaluate(`document.querySelector('[data-search-kind="tracks"] button[data-play-id="${retained.track_id}"]').click()`);
    await wait("document.querySelector('audio')?.currentTime > .1 && !document.querySelector('audio').paused");
    const hash = '#search&q=' + encodeURIComponent(title);
    await evaluate(`location.hash=${JSON.stringify(hash)}`);
    await wait("document.querySelector('.catalog-search-handoff') && document.querySelector('#discovery-status').textContent.includes('No matching')");
    assert.match(await evaluate("document.querySelector('.catalog-search-handoff').textContent"), /Leaving this page stops the current player/);
    assert.ok(!requests.some(row => row.request.url.includes('/track-search/')), 'front page does not load full search shards');
    assert.equal(await evaluate("document.querySelector('audio').paused"), false);
    await evaluate("document.querySelector('[data-catalog-search=tracks]').click()");
    await wait(`location.pathname === '/expanded/explorer/index.html' && document.querySelector('#rows a[href="#track=${id}"]')`);
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).get('q')"), title);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await evaluate('history.back()');
    await wait(`location.pathname === '/index.html' && location.hash === ${JSON.stringify(hash)} && document.querySelector('.catalog-search-handoff')`);
    assert.ok(await evaluate("[...document.querySelectorAll('audio')].every(audio => audio.paused)"));
    await evaluate("document.querySelector('[data-catalog-search=artists]').click()");
    await wait("location.pathname === '/expanded/explorer/index.html' && document.querySelector('h1')?.textContent === 'Artists'");
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).get('q')"), title);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    await command('Page.reload');
    await wait("document.querySelector('h1')?.textContent === 'Artists'");
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).get('q')"), title);
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    const output = process.env.OPENNOISE_FMA_SEARCH_EVIDENCE;
    if (output) await writeFile(join(output, 'catalog-handoff.json'), JSON.stringify({
      revision:'fma-catalog-search-handoff-browser-v1', source_track_id:id, source_title:title,
      absent_retained_selection:true, source_result_found:true, encoded_query:true,
      history_preserved:true, playback_stopped:true, no_autoplay:true
    }, null, 2));
  });
});
