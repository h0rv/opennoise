import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, readdir, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

const root = process.env.OPENNOISE_FMA_ALBUM_ROOT;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !root || !chromium;
async function browser(operation, {transform = null, delay = null} = {}) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try {
      if (delay?.(path)) await new Promise(resolve => setTimeout(resolve, 250));
      let body = await readFile(file);
      if (transform && path.endsWith('.json')) body = Buffer.from(JSON.stringify(transform(path, JSON.parse(body))));
      response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json'); response.end(body); }
    catch { response.statusCode = 404; response.end(); }
  });
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-fma-contract-'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const child = spawn(chromium, ['--headless=new', '--no-first-run', '--no-default-browser-check', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket;
  const requests = [], errors = [];
  try {
    const endpoint = await new Promise((resolve, reject) => {
      // Cold browser launch has its own allowance; application readiness remains unchanged.
      let output = ''; const timeout = setTimeout(() => reject(new Error('Chromium startup timed out')), 30000);
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

async function albumFixtures() {
  const catalog = JSON.parse(await readFile(join(root, 'catalog.json')));
  const albums = [];
  for (let shard = 0; shard < catalog.albums.shards; shard++) {
    const value = JSON.parse(await readFile(join(root, `albums/${shard}.json`)));
    albums.push(...Object.values(value.albums));
  }
  const compilation = albums.find(album => album.artist_ids.length > 1
    && album.artist_ids.every(id => id !== null) && album.track_ids.length < catalog.page_size);
  const paginated = albums.find(album => album.track_ids.length > catalog.page_size);
  const named = albums.find(album => album.album_id === 2216);
  let missing;
  for (const path of await readdir(join(root, 'tracks'))) {
    const tracks = JSON.parse(await readFile(join(root, 'tracks', path))).tracks;
    missing = tracks.find(track => track[6] === null);
    if (missing) break;
  }
  return {catalog, albums, compilation, paginated, named, missing};
}

test('native albums expose exact compilation artists, ordered pages and history without audio', {skip, timeout:60000}, async () => {
  const {catalog, compilation, paginated, named, missing} = await albumFixtures();
  assert.ok(compilation && paginated && named && missing);
  await browser(async state => {
    const {evaluate, wait, command, requests} = state;
    const visit = async id => {
      await evaluate(`location.hash='#album=${id}'`);
      await wait(`document.querySelector('h1').textContent.endsWith(' · #${id}') && document.querySelector('main').getAttribute('aria-busy') === 'false'`);
    };
    assert.ok(!requests.some(row => row.request.url.includes('/albums/')));
    await evaluate("location.hash='#track=4074'");
    await wait("document.querySelector('.track a[href=\"#album=2216\"]')");
    await evaluate("document.querySelector('.track a[href=\"#album=2216\"]').click()");
    await wait("document.querySelector('h1').textContent.endsWith(' · #2216')");
    assert.match(await evaluate("document.querySelector('h1').textContent"), /Pistolera Live at Barbes/);
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.track')].map(row=>Number(row.dataset.trackId))"), named.track_ids);
    assert.match(await evaluate("document.querySelector('#status').textContent"), /not release sequence/);
    await evaluate('history.back()');
    await wait("location.hash === '#track=4074' && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await visit(compilation.album_id);
    const expected = compilation.artist_ids.map(id => `#artist=${id}`);
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.album-contributors a')].map(link=>link.hash)"), expected);
    await evaluate("document.querySelector('.album-contributors a').click()");
    await wait(`document.querySelector('.artist-albums a[href="#album=${compilation.album_id}"]')`);
    assert.ok((await evaluate(`document.querySelector('.artist-albums a[href="#album=${compilation.album_id}"]').textContent`)).includes(compilation.title));
    await evaluate('history.back()');
    await wait(`location.hash === '#album=${compilation.album_id}' && document.querySelector('.album-contributors')`);
    await command('Page.reload');
    await wait(`document.querySelector('h1')?.textContent.endsWith(' · #${compilation.album_id}')`);
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.track')].map(row=>Number(row.dataset.trackId))"), compilation.track_ids);
    await visit(paginated.album_id);
    assert.equal(await evaluate("document.querySelectorAll('.track').length"), catalog.page_size);
    await evaluate("[...document.querySelectorAll('#pages button')].find(button=>button.textContent==='Next').click()");
    await wait("location.hash.includes('page=1') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.track')].map(row=>Number(row.dataset.trackId))"), paginated.track_ids.slice(catalog.page_size,2*catalog.page_size));
    await evaluate(`location.hash='#track=${missing[0]}'`);
    await wait(`document.querySelector('.track[data-track-id="${missing[0]}"]')`);
    assert.match(await evaluate("document.querySelector('.track small').textContent"), /Album ID: missing/);
    assert.equal(await evaluate("document.querySelector('.track a[href^=\"#album=\"]')"), null);
    await visit(compilation.album_id);
    const output = process.env.OPENNOISE_FMA_ALBUM_EVIDENCE;
    for (const [width,height,name] of [[1280,900,'albums-desktop'],[390,844,'albums-mobile']]) {
      await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width===390});
      assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
      if (output) await writeFile(join(output,name+'.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));
    }
    await evaluate("document.querySelector('.album-contributors a').focus()");
    const target = await evaluate('document.activeElement.hash');
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
    await wait(`location.hash === ${JSON.stringify(target)} && document.querySelector('.artist-albums')`);
    await evaluate("location.hash='#album=999999999'");
    await wait("document.querySelector('h1').textContent === 'Catalog unavailable'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"), 0);
    if (output) await writeFile(join(output,'albums-browser.json'),JSON.stringify({native_named_album:named.album_id,compilation:compilation.album_id,compilation_artists:compilation.artist_ids,paginated_album:paginated.album_id,missing_album_track:missing[0],history_reload:true,keyboard_mobile:true,no_audio:true},null,2));
  });
});

test('older catalog exports keep tracks readable and album requests explicitly unavailable', {skip, timeout:60000}, async () => {
  await browser(async ({evaluate, wait}) => {
    await evaluate("location.hash='#track=4074'");
    await wait("document.querySelector('.track[data-track-id=\"4074\"]')");
    assert.match(await evaluate("document.querySelector('.track small').textContent"), /Album ID: 2216/);
    assert.equal(await evaluate("document.querySelector('.track a[href^=\"#album=\"]')"), null);
    await evaluate("location.hash='#album=2216'");
    await wait("document.querySelector('#status').textContent.includes('unavailable in this export')");
  }, {transform:(path,value)=>{if(path==='/catalog.json')delete value.albums;return value;}});
});

test('late album response cannot replace another route and mismatched membership fails closed', {skip, timeout:60000}, async () => {
  await browser(async ({evaluate, wait, requests}) => {
    await evaluate("location.hash='#album=2216'");
    await wait("document.querySelector('main').getAttribute('aria-busy') === 'true'");
    await evaluate("location.hash='#genre=21'");
    await wait("document.querySelector('h1').textContent.includes('Hip-Hop') && document.querySelector('main').getAttribute('aria-busy') === 'false'");
    await new Promise(resolve=>setTimeout(resolve,350));
    assert.ok(!await evaluate("document.querySelector('.album-contributors')"));
    assert.ok(requests.some(row=>row.request.url.includes('/albums/')));
  }, {delay:path=>path.startsWith('/albums/')});
  await browser(async ({evaluate, wait}) => {
    await evaluate("location.hash='#album=2216'");
    await wait("document.querySelector('h1').textContent === 'Catalog unavailable'");
    assert.match(await evaluate("document.querySelector('#status').textContent"), /membership differs/);
    assert.equal(await evaluate("document.querySelectorAll('.track').length"),0);
  }, {transform:(path,value)=>{if(path.startsWith('/albums/') && value.albums['2216'])value.albums['2216'].track_ids=[2];return value;}});
});
