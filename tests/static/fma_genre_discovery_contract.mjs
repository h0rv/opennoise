import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_DISCOVERY_SITE;
async function browser(operation, mutateIndex = null, startupFailure = null) {
  let indexAttempts = 0;
  const root = resolve(process.env.OPENNOISE_FMA_DISCOVERY_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      let body = await readFile(file);
      if (startupFailure && path === '/genre-discovery.json') {
        indexAttempts++;
        if (indexAttempts === 1) {
          if (startupFailure === 'http') {
            response.statusCode = 503;
            response.end();
            return;
          }
          const invalid = JSON.parse(body);
          invalid.revision = 'unsupported';
          body = Buffer.from(JSON.stringify(invalid));
        } else {
          await new Promise(resolve => setTimeout(resolve, 150));
        }
      }
      if (mutateIndex && path === '/genre-discovery.json') { const value=JSON.parse(body); mutateIndex(value); body=Buffer.from(JSON.stringify(value)); }
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    const externalOrigin = process.env.OPENNOISE_FMA_DISCOVERY_ORIGIN;
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
    await wait(mutateIndex || startupFailure ? "document.querySelector('h1')?.textContent === 'Listening index unavailable'" : "document.documentElement?.dataset.discoveryReady === 'true'");
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

test('genre discovery covers every native route and plays both bounded sources without autoplay', {skip, timeout:180000}, async()=>{
  const index=JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE,'genre-discovery.json')));
  const output=process.env.OPENNOISE_FMA_DISCOVERY_EVIDENCE;
  if(output)await mkdir(output,{recursive:true});
  const artistIds=[...new Set(Object.values(index.tracks).map(t=>t.artist_id))].sort((a,b)=>a-b);
  await browser(async({evaluate,wait,command,requests})=>{
    const ready=async(hash)=>wait(`location.hash===${JSON.stringify(hash)}&&document.documentElement?.dataset.discoveryReady==='true'&&document.querySelector('#content')?.getAttribute('aria-busy')==='false'`);
    const route=async(hash)=>{await new Promise(resolve=>setTimeout(resolve,60));await evaluate(`location.hash=${JSON.stringify(hash)}`);await ready(hash);};
    const ids=()=>evaluate("[...document.querySelectorAll('.discovery-excerpt')].map(n=>Number(n.dataset.trackId))");
    const screenshot=async(name)=>{assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth'));if(output)await writeFile(join(output,name+'.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));};
    assert.equal(await evaluate("document.querySelectorAll('.discovery-directory li').length"),index.genres.filter(g=>g.track_ids.length).length);
    await screenshot('discovery-desktop');
    let single=0,missing=0;
    for(const genre of index.genres){
      await route(`#genre=${genre.genre_id}`);
      assert.deepEqual((await ids()).sort((a,b)=>a-b),[...genre.track_ids].sort((a,b)=>a-b));
      const children = index.genres
        .filter(child => child.parent_id === genre.genre_id)
        .sort((a, b) => a.title.localeCompare(b.title) || a.genre_id - b.genre_id);
      const displayedChildren = await evaluate(`
        [...document.querySelectorAll('section[aria-label="Source subgenres"] li')].map(item => ({
          id: Number(item.dataset.genreId),
          href: item.querySelector('a').getAttribute('href'),
          count: item.querySelector('small').textContent,
        }))
      `);
      assert.deepEqual(displayedChildren, children.map(child => ({
        id: child.genre_id,
        href: `#genre=${child.genre_id}`,
        count: child.track_ids.length
          ? `${child.track_ids.length} local excerpt${child.track_ids.length === 1 ? '' : 's'}`
          : 'No local excerpt',
      })));
      const starting=await evaluate("[...document.querySelectorAll('section[aria-label=\"Starting excerpts\"] .discovery-excerpt')].map(n=>Number(n.dataset.trackId))");
      assert.deepEqual(starting,genre.starting_ids);
      assert.equal(new Set(starting.map(id=>index.tracks[id].artist_id)).size,starting.length);
      if(genre.track_ids.length===1){single++;assert.match(await evaluate("document.querySelector('.selection-note').textContent"),/Only one excerpt.*not been judged representative/);assert.equal(await evaluate("document.querySelectorAll('.more-excerpts').length"),0);}
      if(!genre.track_ids.length){missing++;assert.match(await evaluate("document.querySelector('#discovery-rows').textContent"),/No retained excerpt/);assert.equal(await evaluate("document.querySelectorAll('[data-play-id]').length"),0);}
    }
    for(const artist of artistIds){await route(`#artist=${artist}`);assert.deepEqual((await ids()).sort((a,b)=>a-b),Object.values(index.tracks).filter(t=>t.artist_id===artist).map(t=>t.track_id).sort((a,b)=>a-b));}
    assert.equal(await evaluate("document.querySelectorAll('audio').length"),0);
    assert.ok(!requests.some(r=>r.request.url.endsWith('.mp3')));
    await route('#genres');
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'/',code:'Slash'});
    assert.equal(await evaluate('document.activeElement.id'),'discovery-query');
    const target=index.genres.find(g=>g.track_ids.length);
    await evaluate(`document.querySelector('#discovery-query').value=${JSON.stringify(String(target.genre_id))};document.querySelector('#discovery-query').dispatchEvent(new Event('input',{bubbles:true}))`);
    assert.equal(await evaluate("document.querySelectorAll('.discovery-directory li').length"),1);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown'});
    assert.equal(await evaluate("document.activeElement.getAttribute('href')"),`#genre=${target.genre_id}`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});await ready(`#genre=${target.genre_id}`);
    await route('#genres');await evaluate("document.querySelector('#include-unavailable').click()");await wait("document.querySelectorAll('.discovery-directory li').length===164");
    const played=[];
    for(const origin of ['original','expanded']){
      const track=Object.values(index.tracks).find(t=>t.collection===origin);
      await route(`#artist=${track.artist_id}`);
      await evaluate(`document.querySelector('[data-play-id="${track.track_id}"]').click()`);
      await wait(`document.querySelector('#persistent-player')?.dataset.trackId==='${track.track_id}'&&document.querySelector('#persistent-player audio').currentTime>.1&&!document.querySelector('#persistent-player audio').paused`);
      assert.ok((await evaluate("document.querySelector('audio').src")).includes(`/${origin}/audio/${track.track_id}.mp3`));
      assert.equal(await evaluate("[...document.querySelectorAll('audio')].filter(a=>!a.paused).length"),1);
      assert.equal(await evaluate("document.querySelectorAll('audio').length"),1);
      await route(`#genre=${track.genre_ids[0]}`);assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await evaluate('history.back()');await ready(`#artist=${track.artist_id}`);assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await evaluate(`document.querySelector('#persistent-player a[href="#track=${track.track_id}"]').click()`);
      await ready(`#track=${track.track_id}`);
      assert.equal(await evaluate("document.querySelector('h1').textContent"),track.title || `Track #${track.track_id}`);
      assert.deepEqual(await ids(),[track.track_id]);
      assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await route('#track=9007199254740991');
      assert.equal(await evaluate("document.querySelector('h1').textContent"),'Page unavailable');
      assert.equal(await evaluate("document.querySelectorAll('#discovery-rows [data-play-id]').length"),0);
      assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await route(`#artist=${track.artist_id}`);
      played.push({track_id:track.track_id,collection:origin});
    }
    await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    await screenshot('discovery-artist-mobile');
    await route('#genres');await screenshot('discovery-directory-mobile');
    const before=requests.filter(r=>r.request.url.endsWith('.mp3')).length;
    await command('Page.reload');await wait("document.documentElement?.dataset.discoveryReady==='true'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"),0);
    assert.equal(requests.filter(r=>r.request.url.endsWith('.mp3')).length,before);
    if(output)await writeFile(join(output,'discovery-browser.json'),JSON.stringify({revision:'fma-genre-discovery-browser-v1',genres:index.genres.length,playable_genres:index.genres.filter(g=>g.track_ids.length).length,artist_routes:artistIds.length,single_excerpt_genres:single,no_excerpt_genres:missing,played,persistent_navigation:true,persistent_track_link:true,unknown_track_safe_error:true,no_autoplay_reload:true,viewport_widths:[1280,390]},null,2));
  });
});

for (const [name, mutate] of [
  ['duplicate genre', value=>value.genres.push(value.genres[0])],
  ['incomplete genre membership', value=>{ const genre=value.genres.find(g=>g.track_ids.length>1);genre.track_ids=genre.track_ids.slice(1);genre.starting_ids=genre.starting_ids.filter(id=>genre.track_ids.includes(id)); }],
  ['external collection path', value=>{value.collections.original.manifest='https://invalid.example/audio/manifest.json';}],
  ['external descriptor map path', value => { value.collections.original.descriptor_map = {href: 'https://invalid.example/map'}; }],
]) test(`malformed discovery index rejects ${name} without fetching audio`,{skip,timeout:30000},async()=>{
  await browser(async({evaluate,requests})=>{
    assert.equal(await evaluate("document.querySelectorAll('[data-play-id],audio').length"),0);
    assert.equal(await evaluate("document.querySelector('#discovery-rows a').getAttribute('href')"),'collections.html');
    assert.ok(!requests.some(row=>/\/audio\//.test(row.request.url)));
  },mutate);
});

const pairProposal = process.env.OPENNOISE_FMA_PAIR_PROPOSAL;

test('approved artist additions expose and play both independent examples on all twelve genre routes', {
  skip: skip || !pairProposal,
  timeout: 120000,
}, async () => {
  const proposal = JSON.parse(await readFile(pairProposal));
  const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE, 'genre-discovery.json')));
  const pairs = proposal.tracks.flatMap(track => track.second_independent_artist_genres.map(genreId => ({genreId, addedId: track.track_id})));
  assert.equal(pairs.length, 12);
  assert.equal(new Set(pairs.map(pair => pair.genreId)).size, 12);
  await browser(async ({evaluate, wait}) => {
    for (const {genreId, addedId} of pairs) {
      const genre = index.genres.find(row => row.genre_id === genreId);
      assert.equal(genre.track_ids.length, 2);
      assert.ok(genre.track_ids.includes(addedId));
      assert.equal(new Set(genre.track_ids.map(id => index.tracks[id].artist_id)).size, 2);
      await evaluate(`location.hash='#genre=${genreId}'`);
      await wait(`location.hash==='#genre=${genreId}' && document.documentElement.dataset.discoveryReady==='true' && document.querySelector('#content').getAttribute('aria-busy')==='false'`);
      const displayed = await evaluate("[...document.querySelectorAll('.discovery-excerpt')].map(row => Number(row.dataset.trackId))");
      assert.deepEqual(displayed.sort((a, b) => a - b), [...genre.track_ids].sort((a, b) => a - b));
      for (const trackId of genre.track_ids) {
        await evaluate(`document.querySelector('[data-play-id="${trackId}"]').click()`);
        await wait(`document.querySelector('#persistent-player').dataset.trackId==='${trackId}' && document.querySelector('#persistent-player audio').currentTime>.1 && !document.querySelector('#persistent-player audio').paused`);
        assert.equal(await evaluate("[...document.querySelectorAll('audio')].filter(audio => !audio.paused).length"), 1);
        await evaluate("document.querySelector('#persistent-player .playback-stop').click()");
      }
    }
  });
});


test('source families support keyboard descent, Back and mobile deep-link reload without audio', {
  skip,
  timeout: 30000,
}, async () => {
  const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE, 'genre-discovery.json')));
  const parent = index.genres.find(genre => index.genres.some(child => child.parent_id === genre.genre_id));
  assert.ok(parent, 'retained source has a genre family');
  const child = index.genres
    .filter(genre => genre.parent_id === parent.genre_id)
    .sort((a, b) => a.title.localeCompare(b.title) || a.genre_id - b.genre_id)[0];

  await browser(async ({evaluate, wait, command, requests}) => {
    const ready = id => wait(`
      location.hash === '#genre=${id}' &&
      document.querySelector('h1').textContent === ${JSON.stringify(index.genres.find(genre => genre.genre_id === id).title)} &&
      document.querySelector('#content').getAttribute('aria-busy') === 'false'
    `);
    await evaluate(`location.hash = '#genre=${parent.genre_id}'`);
    await ready(parent.genre_id);
    const output = process.env.OPENNOISE_FMA_DISCOVERY_EVIDENCE;
    const screenshot = async name => {
      if (!output) return;
      await mkdir(output, {recursive: true});
      const image = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(output, name + '.png'), Buffer.from(image.data, 'base64'));
    };
    await screenshot('genre-family-desktop');
    await evaluate(`document.querySelector('section[aria-label="Source subgenres"] a').focus()`);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter'});
    await ready(child.genre_id);
    assert.equal(await evaluate('document.activeElement.tagName'), 'H1');
    assert.ok(await evaluate(`!!document.querySelector('#discovery-rows a[href="#genre=${parent.genre_id}"]')`));

    await evaluate('history.back()');
    await ready(parent.genre_id);
    await evaluate('history.forward()');
    await ready(child.genre_id);
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await command('Page.reload');
    await ready(child.genre_id);
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
    await evaluate(`document.querySelector('#discovery-rows a[href="#genre=${parent.genre_id}"]').click()`);
    await ready(parent.genre_id);
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
    await evaluate(`document.querySelector('section[aria-label="Source subgenres"]').scrollIntoView()`);
    await screenshot('genre-family-mobile');
    assert.equal(await evaluate('document.querySelectorAll("audio").length'), 0);
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));
  });
});

for (const failure of ['http', 'invalid-index']) {
  test(`listening index recovers from ${failure} without losing the current route or fetching audio`, {
    skip,
    timeout: 30000,
  }, async () => {
    const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE, 'genre-discovery.json')));
    const target = index.genres.find(genre => genre.track_ids.length);
    await browser(async ({evaluate, wait, requests}) => {
      assert.equal(await evaluate('document.querySelectorAll("[data-retry-index]").length'), 1);
      await evaluate(`location.hash = '#genre=${target.genre_id}'`);
      await wait(`location.hash === '#genre=${target.genre_id}'`);
      assert.equal(await evaluate('document.querySelector("h1").textContent'), 'Listening index unavailable');
      assert.equal(await evaluate('document.querySelector("#discovery-search").hidden'), true);
      await evaluate(`
        const retry = document.querySelector('[data-retry-index]');
        retry.click();
        retry.click();
      `);
      await wait('document.querySelector("#content").getAttribute("aria-busy") === "true"');
      await evaluate(`location.hash = '#genre=${target.genre_id}&from=retry'`);
      await evaluate('document.querySelector("#discovery-query").dispatchEvent(new Event("input", {bubbles: true}))');
      await wait(`document.querySelector('h1').textContent === ${JSON.stringify(target.title)} && document.querySelector('#content').getAttribute('aria-busy') === 'false'`);
      assert.equal(await evaluate('location.hash'), `#genre=${target.genre_id}&from=retry`);
      assert.equal(await evaluate('document.querySelectorAll("[data-retry-index]").length'), 0);
      assert.deepEqual(await evaluate('[...document.querySelectorAll(".discovery-excerpt")].map(row => Number(row.dataset.trackId)).sort((a, b) => a - b)'), [...target.track_ids].sort((a, b) => a - b));
      assert.equal(requests.filter(row => row.request.url.endsWith('/genre-discovery.json')).length, 2);
      assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));
      assert.equal(await evaluate('document.querySelectorAll("audio").length'), 0);
    }, null, failure);
  });
}


test('skip to music preserves deep routes, history and the current player', {skip, timeout: 30000}, async () => {
  const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE, 'genre-discovery.json')));
  const genre = index.genres.find(row => row.track_ids.length);
  const trackId = genre.track_ids[0];
  await browser(async ({evaluate, wait, command, requests}) => {
    for (const hash of [`#genre=${genre.genre_id}`, `#track=${trackId}`, '#search&q=music']) {
      await evaluate(`location.hash = ${JSON.stringify(hash)}`);
      await wait(`location.hash === ${JSON.stringify(hash)} && document.querySelector('#content').getAttribute('aria-busy') === 'false'`);
      if (hash.startsWith('#genre=')) {
        await evaluate("document.querySelector('[data-play-id]').click()");
        await wait("document.querySelector('audio')?.currentTime > .1 && !document.querySelector('audio').paused");
        await evaluate("window.skipAudio = document.querySelector('audio')");
      }
      const historyLength = await evaluate('history.length');
      const mediaRequests = requests.filter(row => row.request.url.endsWith('.mp3')).length;
      await evaluate("document.querySelector('.skip').focus()");
      await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
      await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
      await wait("document.activeElement === document.querySelector('#content')");
      assert.equal(await evaluate('location.hash'), hash);
      assert.equal(await evaluate('history.length'), historyLength);
      assert.ok(await evaluate("document.querySelector('audio') === window.skipAudio && !window.skipAudio.paused"));
      assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, mediaRequests);
    }
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await evaluate("document.querySelector('.skip').click()");
    assert.equal(await evaluate('location.hash'), '#search&q=music');
    assert.ok(await evaluate("document.activeElement === document.querySelector('#content')"));
    await evaluate('history.back()');
    await wait(`location.hash === '#track=${trackId}' && document.querySelector('#content').getAttribute('aria-busy') === 'false'`);
  });
});


test('listening families retain all source IDs, direct counts, filter history and the active player', {
  skip,
  timeout: 30000,
}, async () => {
  const index = JSON.parse(await readFile(join(process.env.OPENNOISE_FMA_DISCOVERY_SITE, 'genre-discovery.json')));
  const track = Object.values(index.tracks)[0];
  const genre = index.genres.find(row => row.genre_id === track.genre_ids[0]);
  await browser(async ({evaluate, wait, command, requests}) => {
    assert.ok(!requests.some(row => row.request.url.endsWith('/fma-genre-map.js')), 'atlas JavaScript is lazy');
    await evaluate(`location.hash = '#families'`);
    await wait('document.querySelectorAll(".fma-atlas-name a, .fma-atlas-family h2 a").length === 164');
    const displayed = await evaluate(`
      [...document.querySelectorAll('.fma-genre-atlas [data-genre-id]')].map(anchor => {
        const counts = anchor.closest('.fma-atlas-row, .fma-atlas-family').querySelector('.fma-atlas-counts');
        return {
          id: Number(anchor.dataset.genreId),
          tracks: counts.querySelector('.fma-atlas-count').textContent,
          excerpts: counts.querySelector('.fma-atlas-listen')?.textContent ?? null,
          href: counts.querySelector('.fma-atlas-listen')?.getAttribute('href') ?? null,
        };
      }).sort((a, b) => a.id - b.id)
    `);
    assert.deepEqual(displayed, index.genres.map(row => ({
      id: row.genre_id,
      tracks: `${new Intl.NumberFormat('en').format(row.track_count)} tracks`,
      excerpts: row.track_ids.length ? `Listen · ${row.track_ids.length} excerpt${row.track_ids.length === 1 ? '' : 's'}` : null,
      href: row.track_ids.length ? `#genre=${row.genre_id}` : null,
    })).sort((a, b) => a.id - b.id));
    const output = process.env.OPENNOISE_FMA_DISCOVERY_EVIDENCE;
    const screenshot = async name => {
      if (!output) return;
      await mkdir(output, {recursive: true});
      const image = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(output, name + '.png'), Buffer.from(image.data, 'base64'));
    };
    await screenshot('listening-families-desktop');
    assert.match(await evaluate('document.querySelector("#discovery-status").textContent'), /not musical similarity/);
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));

    await evaluate(`location.hash = '#genre=${genre.genre_id}'`);
    await wait(`!!document.querySelector('[data-play-id="${track.track_id}"]')`);
    await evaluate(`document.querySelector('[data-play-id="${track.track_id}"]').click()`);
    await wait('document.querySelector("audio")?.currentTime > .1 && !document.querySelector("audio").paused');
    await evaluate('window.originalPlayer = document.querySelector("audio"); location.hash = "#families"');
    await wait('!!document.querySelector(".fma-atlas-search")');
    assert.ok(await evaluate('document.querySelector("audio") === window.originalPlayer && !window.originalPlayer.paused'));
    await evaluate(`
      const search = document.querySelector('.fma-atlas-search');
      search.focus();
      search.value = '${genre.genre_id}';
      search.dispatchEvent(new Event('input', {bubbles: true}));
      document.querySelector('.fma-atlas-playable').click();
    `);
    const filteredHash = await evaluate('location.hash');
    assert.ok(filteredHash.includes('q=' + genre.genre_id) && filteredHash.includes('playable=1'));
    assert.match(await evaluate('document.querySelector(".fma-atlas-status").textContent'), /^1 of 164 genres with local excerpts/);
    await evaluate(`document.querySelector('.fma-genre-atlas [data-genre-id="${genre.genre_id}"]').focus()`);
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter'});
    await wait(`location.hash === '#genre=${genre.genre_id}' && !document.querySelector('.fma-genre-atlas')`);
    await evaluate('history.back()');
    await wait(`location.hash === ${JSON.stringify(filteredHash)} && !!document.querySelector('.fma-atlas-search')`);
    assert.equal(await evaluate('document.querySelector(".fma-atlas-search").value'), String(genre.genre_id));
    assert.equal(await evaluate('document.querySelector(".fma-atlas-playable").checked'), true);
    assert.ok(await evaluate('document.querySelector("audio") === window.originalPlayer && !window.originalPlayer.paused'));

    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
    const before = requests.filter(row => /\/audio\//.test(row.request.url)).length;
    await command('Page.reload');
    await wait('!!document.querySelector(".fma-atlas-search")');
    assert.equal(await evaluate('location.hash'), filteredHash);
    assert.equal(await evaluate('document.querySelector(".fma-atlas-search").value'), String(genre.genre_id));
    assert.equal(await evaluate('document.querySelectorAll("audio").length'), 0);
    assert.equal(requests.filter(row => /\/audio\//.test(row.request.url)).length, before);
    await evaluate('document.querySelector(".fma-atlas-filters button").click()');
    await screenshot('listening-families-mobile');
    assert.equal(await evaluate('document.querySelectorAll(".fma-genre-atlas [data-genre-id]").length'), 164);
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
  });
});


test('attached descriptor map preserves native scope, missing contexts, playback and silent reload', {
  skip: skip || !process.env.OPENNOISE_FMA_DESCRIPTOR_ATTACHED,
  timeout: 60000,
}, async () => {
  const root = process.env.OPENNOISE_FMA_DISCOVERY_SITE;
  const catalog = JSON.parse(await readFile(join(root, 'expanded/explorer/catalog.json')));
  const map = JSON.parse(await readFile(join(root, 'expanded/explorer/descriptor-map/manifest.json')));
  const missingGenre = map.genres.find(row => row.position === null).id;
  const track = catalog.playback.tracks[0];
  await browser(async ({evaluate, wait, command, requests}) => {
    await evaluate("location.hash = '#families'");
    await wait('!!document.querySelector(".fma-genre-atlas")');
    const link = 'a[href="expanded/explorer/index.html#descriptor-map"]';
    assert.equal(await evaluate(`document.querySelectorAll('${link}').length`), 1);
    await evaluate(`document.querySelector('${link}').click()`);
    await wait('document.querySelector("#status")?.textContent.includes("164 matching genres")');
    assert.match(await evaluate('document.querySelector("#status").textContent'), /158 with coordinates.*6 without coordinates/);
    const output = process.env.OPENNOISE_FMA_DISCOVERY_EVIDENCE;
    const screenshot = async name => {
      if (!output) return;
      await mkdir(output, {recursive: true});
      const image = await command('Page.captureScreenshot', {format: 'png'});
      await writeFile(join(output, name + '.png'), Buffer.from(image.data, 'base64'));
    };
    await screenshot('restored-descriptor-map-desktop');
    assert.match(await evaluate('document.querySelector(".fma-descriptor-map").textContent'), /PC1 and PC2 are mathematical/);
    assert.ok(!requests.some(row => row.request.url.includes('/descriptor-map/artists-')));
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)));
    const genreIds = [];
    for (let page = 0; page < 4; page++) {
      genreIds.push(...await evaluate('[...document.querySelectorAll(".descriptor-list a")].map(a => Number(a.hash.split("=")[1]))'));
      if (page < 3) await evaluate('document.querySelector(".descriptor-pages button:last-child").click()');
    }
    assert.deepEqual(genreIds.sort((a, b) => a - b), map.genres.map(row => row.id).sort((a, b) => a - b));
    await evaluate(`location.hash = '#descriptor-map&q=${missingGenre}&selected=${missingGenre}'`);
    await wait('document.querySelector(".descriptor-selection")?.textContent.includes("no supported coordinates")');
    assert.equal(await evaluate('document.querySelector(".descriptor-selection a").hash'), `#genre=${missingGenre}`);
    await evaluate("location.hash = '#descriptor-map&entity=artists'");
    await wait('document.querySelector("#status")?.textContent.includes("16916 matching artists")');
    assert.match(await evaluate('document.querySelector("#status").textContent'), /16109 with coordinates.*807 without coordinates/);
    assert.equal(new Set(requests.filter(row => row.request.url.includes('/descriptor-map/artists-')).map(row => row.request.url)).size, map.artist_shards.length);
    await evaluate(`location.hash = '#descriptor-map&selected=${track.genre_ids[0]}'`);
    await wait('!!document.querySelector(".descriptor-play-selection")');
    assert.equal(await evaluate('document.querySelectorAll("audio").length'), 0);
    await evaluate('document.querySelector(".descriptor-play-selection").click()');
    await wait('document.querySelector("audio")?.currentTime > .1 && !document.querySelector("audio").paused');
    const playedId = await evaluate('Number(document.querySelector("#persistent-player").dataset.trackId)');
    assert.ok(catalog.playback.tracks.some(row => row.track_id === playedId && row.genre_ids.includes(track.genre_ids[0])));
    await evaluate(`location.hash = '#descriptor-map&entity=artists&selected=${track.artist_id}'`);
    await wait(`document.querySelector('.descriptor-selection a')?.hash === '#artist=${track.artist_id}'`);
    assert.equal(await evaluate('document.querySelector("audio").paused'), false);
    await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await wait('document.querySelector(".descriptor-canvas").width < 500');
    await screenshot('restored-descriptor-map-mobile');
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: '/', code: 'Slash'});
    assert.equal(await evaluate('document.activeElement.id'), 'descriptor-query');
    const before = requests.filter(row => row.request.url.endsWith('.mp3')).length;
    await command('Page.reload');
    await wait(`document.querySelector('.descriptor-selection a')?.hash === '#artist=${track.artist_id}'`);
    assert.equal(await evaluate('document.querySelectorAll("audio").length'), 0);
    assert.equal(requests.filter(row => row.request.url.endsWith('.mp3')).length, before);
  });
});
