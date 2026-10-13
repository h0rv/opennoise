import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium || !process.env.OPENNOISE_FMA_INLINE_SITE;
async function browser(operation, options = {}) {
  const root = resolve(process.env.OPENNOISE_FMA_INLINE_SITE);
  const profile = resolve(await mkdtemp(join(tmpdir(), 'opennoise-genuine-playback-')));
  const held = [];
  const release = () => { for (const resolve of held.splice(0)) resolve(); };
  const requests = [], errors = []; let failAudio = false, socket, child;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + sep) || (failAudio && path.endsWith('.mp3'))) { response.statusCode = 404; response.end(); return; }
    try {
      let body = await readFile(file);
      if (path.endsWith('/playable-neighbors/manifest.json')) {
        if (options.missing) throw Error('Fixture missing pack');
        if (options.hold) await new Promise(resolve=>held.push(resolve));
        if (options.mutate) { const value=JSON.parse(body); options.mutate(value); body=Buffer.from(JSON.stringify(value)); }
      }
      response.setHeader('Content-Type', file.endsWith('.mp3') ? 'audio/mpeg' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/json');
      response.setHeader('Cache-Control', 'no-store'); response.setHeader('Content-Length', body.length); response.end(body);
    } catch { response.statusCode = 404; response.end(); }
  });
  try {
    const externalOrigin = process.env.OPENNOISE_FMA_INLINE_ORIGIN;
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
    await wait("document.documentElement?.dataset.discoveryReady === 'true'");
    assert.ok(!requests.some(row => /\/audio\//.test(row.request.url)), 'landing does not fetch audio or its manifest');
    await operation({evaluate, wait, command, requests, release, failAudio: value => { failAudio = value; }});
    assert.deepEqual(errors, []);
    assert.ok(requests.every(row => new URL(row.request.url).origin === origin || (row.type === 'Image' && row.request.url.startsWith('data:image/'))), 'network requests stay local; native controls may use embedded image icons');
  } finally {
    release();
    socket?.close(); if (child) { child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); }
    if (server.listening) await new Promise(resolve => server.close(resolve));
    await rm(profile, {recursive: true, force: true});
  }
}

async function inputs(){
  const root=process.env.OPENNOISE_FMA_INLINE_SITE;
  const index=JSON.parse(await readFile(join(root,'genre-discovery.json')));
  const packs=Object.fromEntries(await Promise.all(['original','expanded'].map(async key=>[key,JSON.parse(await readFile(join(root,key,'explorer/playable-neighbors/manifest.json')))])));
  return {index,packs};
}
async function route(state,hash){await state.evaluate(`location.hash=${JSON.stringify(hash)}`);await state.wait(`location.hash===${JSON.stringify(hash)}&&document.querySelector('#content').getAttribute('aria-busy')==='false'`);}
const neighborIds=state=>state.evaluate("[...document.querySelectorAll('.playable-neighbor-track')].map(a=>Number(a.hash.slice(7)))");
async function playing(state,id,collection){await state.wait(`document.querySelector('#persistent-player')?.dataset.trackId==='${id}'&&document.querySelector('audio').currentTime>.1&&!document.querySelector('audio').paused`);assert.ok((await state.evaluate("document.querySelector('audio').src")).includes(`/${collection}/audio/${id}.mp3`));assert.equal(await state.evaluate("document.querySelectorAll('audio').length"),1);}

test('all retained root queries preserve exact bounded neighbor order and explicit playback queues',{skip,timeout:180000},async()=>{
  const {index,packs}=await inputs(), audited=[];
  const output=process.env.OPENNOISE_FMA_INLINE_EVIDENCE;if(output)await mkdir(output,{recursive:true});
  await browser(async state=>{
    const {evaluate,wait,command,requests}=state;
    assert.ok(!requests.some(r=>r.request.url.endsWith('/playable-neighbors/manifest.json')));
    for(const track of Object.values(index.tracks)){
      await route(state,`#track=${track.track_id}`);
      const pack=packs[track.collection], expected=pack.rows.find(r=>r.track_id===track.track_id).neighbor_ids;
      if(pack.revision==='fma-playable-component-neighbors-v2') assert.equal(new Set(expected.map(id=>pack.components[id])).size,expected.length,'v2 suggestions span distinct source components');
      assert.deepEqual(await neighborIds(state),expected);
      assert.match(await evaluate("document.querySelector('.playable-neighbors').textContent"),/Musical similarity has not been validated/);
      audited.push({track_id:track.track_id,collection:track.collection,neighbor_ids:expected});
    }
    assert.equal(await evaluate("document.querySelectorAll('audio').length"),0);
    assert.ok(!requests.some(r=>r.request.url.endsWith('.mp3')));
    for(const collection of ['original','expanded']){
      const track=Object.values(index.tracks).find(t=>t.collection===collection);
      const ids=packs[collection].rows.find(r=>r.track_id===track.track_id).neighbor_ids;
      await route(state,`#track=${track.track_id}`);
      await evaluate("document.querySelector('.playable-neighbor-play').click()");await playing(state,ids[0],collection);
      await route(state,`#genre=${track.genre_ids[0]}`);assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await route(state,`#artist=${index.tracks[ids[0]].artist_id}`);assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await evaluate('history.back()');await wait(`location.hash==='#genre=${track.genre_ids[0]}'`);assert.equal(await evaluate("document.querySelector('audio').paused"),false);
      await route(state,`#track=${track.track_id}`);
      await evaluate("document.querySelector('.playable-neighbors-queue').click()");await playing(state,ids[0],collection);
      assert.equal(await evaluate("document.querySelector('.playback-order').textContent"),`1 of ${ids.length} · ${ids.map(id=>index.tracks[id].title||`Track #${id}`).join(' → ')}`);
      await evaluate("document.querySelector('.playback-next').click()");await playing(state,ids[1],collection);
      await evaluate("document.querySelector('.playback-previous').click()");await playing(state,ids[0],collection);
      await evaluate("document.querySelector('audio').playbackRate=16");await playing(state,ids[1],collection);
      await evaluate("document.querySelector('audio').playbackRate=1");
      await evaluate("document.querySelector('.playback-stop').click()");
    }
    await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    assert.ok(await evaluate('document.documentElement.scrollWidth<=innerWidth'));
    if(output)await writeFile(join(output,'inline-mobile.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));
    await command('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
    if(output)await writeFile(join(output,'inline-desktop.png'),Buffer.from((await command('Page.captureScreenshot',{format:'png'})).data,'base64'));
    await evaluate("document.querySelector('.playable-neighbor-play').click()");await wait("document.querySelector('audio').currentTime>.1&&!document.querySelector('audio').paused");
    const media=requests.filter(r=>r.request.url.endsWith('.mp3')).length;
    await command('Page.reload');await wait("document.documentElement?.dataset.discoveryReady==='true'&&document.querySelector('#content').getAttribute('aria-busy')==='false'");
    assert.equal(await evaluate("document.querySelectorAll('audio').length"),0);assert.equal(requests.filter(r=>r.request.url.endsWith('.mp3')).length,media);
    if(output)await writeFile(join(output,'inline-browser.json'),JSON.stringify({revision:'fma-inline-discovery-browser-v1',queries:audited,edges:audited.reduce((sum,q)=>sum+q.neighbor_ids.length,0),queue_natural_end:true,explicit_query_collection:true,reload_silent:true},null,2));
  });
});

test('late suggestion response cannot attach to another route',{skip,timeout:30000},async()=>{
  const {index}=await inputs(),track=Object.values(index.tracks)[0];
  await browser(async state=>{
    await state.evaluate(`location.hash='#track=${track.track_id}'`);
    for(let i=0;i<100&&!state.requests.some(r=>r.request.url.endsWith('/playable-neighbors/manifest.json'));i++)await new Promise(resolve=>setTimeout(resolve,20));
    assert.ok(state.requests.some(r=>r.request.url.endsWith('/playable-neighbors/manifest.json')));
    await route(state,`#artist=${track.artist_id}`);state.release();await new Promise(resolve=>setTimeout(resolve,150));
    assert.equal(await state.evaluate("document.querySelectorAll('.playable-neighbors').length"),0);
    assert.equal(await state.evaluate("document.querySelectorAll('audio').length"),0);
  },{hold:true});
});

for(const [name,options] of [
  ['missing pack',{missing:true}],
  ['repeated v2 component',{mutate:p=>{p.revision='fma-playable-component-neighbors-v2';const [a,b]=p.rows[0].neighbor_ids;p.components[b]=p.components[a];}}],
  ['wrong binding',{mutate:p=>{p.audio_manifest_sha256='0'.repeat(64);}}],
  ['self candidate',{mutate:p=>{p.rows[0].neighbor_ids[0]=p.rows[0].track_id;}}],
  ['unsupported candidate',{mutate:p=>{const id=p.rows[0].neighbor_ids[0],candidate=p.rows.find(r=>r.track_id===id);candidate.reason='outside_training_support';candidate.neighbor_ids=[];}}],
])test(`bad suggestions isolate ${name} and preserve ordinary playback`,{skip,timeout:30000},async()=>{
  const {index}=await inputs(),track=Object.values(index.tracks)[0];
  await browser(async state=>{
    await route(state,`#track=${track.track_id}`);
    assert.match(await state.evaluate("document.querySelector('.playable-neighbors').textContent"),/unavailable/);
    assert.equal(await state.evaluate("document.querySelectorAll('.playable-neighbors button').length"),0);
    assert.ok(!state.requests.some(r=>r.request.url.endsWith('.mp3')));
    await state.evaluate("document.querySelector('.discovery-excerpt [data-play-id]').click()");await playing(state,track.track_id,track.collection);
  },options);
});
