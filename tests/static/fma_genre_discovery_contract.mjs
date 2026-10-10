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
async function browser(operation, mutateIndex = null) {
  const root = resolve(process.env.OPENNOISE_FMA_DISCOVERY_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      let body = await readFile(file);
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
]) test(`malformed discovery index rejects ${name} without fetching audio`,{skip,timeout:30000},async()=>{
  await browser(async({evaluate,requests})=>{
    assert.equal(await evaluate("document.querySelectorAll('[data-play-id],audio').length"),0);
    assert.equal(await evaluate("document.querySelector('#discovery-rows a').getAttribute('href')"),'collections.html');
    assert.ok(!requests.some(row=>/\/audio\//.test(row.request.url)));
  },mutate);
});
