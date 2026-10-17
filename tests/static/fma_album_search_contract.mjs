import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, mkdir, readFile, readdir, rm, writeFile, copyFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

let root;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium;
async function browser(operation, {transform = null, delay = null} = {}) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try {
      if (delay?.(path)) await new Promise(resolve => setTimeout(resolve, 250));
      let body = await readFile(file);
      if (transform && path === '/album-search/0.json' && transform(path, null) === false) { response.statusCode = 503; response.end(); return; }
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


async function fixture() {
  root = await mkdtemp(join(tmpdir(), 'cotag-fixture-'));
  const assets = resolve('src/opennoise/static');
  for (const name of await readdir(assets)) {
    if (name.endsWith('.js') || name.endsWith('.css') || name === 'fma-catalog.html') {
      await copyFile(join(assets, name), join(root, name === 'fma-catalog.html' ? 'index.html' : name));
    }
  }
  const put = async (path, value) => {
    const target = join(root, path);
    await mkdir(resolve(target, '..'), {recursive: true});
    await writeFile(target, JSON.stringify(value));
  };
  await put('catalog.json', {
    revision:'fma-source-static-v1', page_size:200, profile_shards:128, track_id_span:500,
    genres:[1,2,3].map(id => ({genre_id:id,title:id===2?'ExperimentalVeryLongUnbrokenSourceGenreNameForMobileCoverage':'Genre '+id,track_count:201,parent_id:null,connections:[]})),
    counts:{raw_tracks:201,source_artists:1,missing_artist_records:0,observed_track_genres:3,unannotated_tracks:0},
    cotags:{revision:'fma-direct-cotags-v1'}, licenses:[]
  });
  await put('artist-index.json',{artists:[[10,'Fixture artist',201,'source']]});
  await put('connections/1.json',{genre_id:1,connections:[{genre_id:2,shared_tracks:201,known_artist_count:100,unresolved_artist_tracks:100}]});
  await put('connections/3.json',{genre_id:3,connections:[]});
  await put('cohorts/pair-1-2/0.json',{cohort:'pair-1-2',page:0,total:201,track_ids:Array.from({length:200},(_,i)=>i+1)});
  await put('cohorts/pair-1-2/1.json',{cohort:'pair-1-2',page:1,total:201,track_ids:[201]});
  await put('tracks/0.json',{tracks:Array.from({length:201},(_,i)=>[i+1,'Track '+(i+1),10,[1,2],null,null,null])});
}

async function albumsFixture() {
  await fixture();
  const path = join(root,'catalog.json');
  const catalog = JSON.parse(await readFile(path));
  catalog.albums = {revision:'fma-native-albums-v1',shards:128,album_count:202,search:{
    revision:'fma-native-album-search-v1',columns:['album_id','title','track_count','artist_count'],row_count:202,shards:['album-search/0.json'],bytes:10000
  }};
  await writeFile(path,JSON.stringify(catalog));
  await mkdir(join(root,'album-search'));
  await writeFile(join(root,'album-search/0.json'),JSON.stringify(Array.from({length:202},(_,i)=>[i+1,i<2?'Café & Same':`Title ${String(i).padStart(3,'0')}`,1,1])));
  await mkdir(join(root,'albums'));
  await writeFile(join(root,'albums/1.json'),JSON.stringify({shard:1,albums:{'1':{album_id:1,title:'Café & Same',track_ids:[1],artist_ids:[10]}}}));
  await writeFile(join(root,'tracks/0.json'),JSON.stringify({tracks:[[1,'Recording',10,[1],null,null,1]]}));
}

test('synthetic lazy album discovery preserves IDs, pages, history, failures and old exports', {skip,timeout:60000}, async()=>{
  await albumsFixture();
  try {
    await browser(async({evaluate,wait,requests,command})=>{
      assert.ok(!requests.some(row=>row.request.url.includes('/album-search/')));
      await evaluate("location.hash='albums'");
      await wait("document.querySelectorAll('.album-search-results li').length===100");
      assert.ok(!requests.some(row=>row.request.url.includes('/artist-index.json')));
      await evaluate("[...document.querySelectorAll('#pages button')].find(b=>b.textContent==='Last').click()");
      await wait("document.querySelectorAll('.album-search-results li').length===2");
      await evaluate("location.hash='albums&q='+encodeURIComponent('CAFÉ & SAME')");
      await wait("document.querySelectorAll('.album-search-results li').length===2 && document.querySelector('[data-album-id=\"1\"]')");
      assert.deepEqual(await evaluate("[...document.querySelectorAll('.album-search-results li')].map(row=>row.dataset.albumId)"),['1','2']);
      for(const width of [390,320]){
        await command('Emulation.setDeviceMetricsOverride',{width,height:700,deviceScaleFactor:1,mobile:true});
        assert.equal(await evaluate('innerWidth'),width);
      }
      await evaluate("document.querySelector('.album-search-results a').click()");
      await wait("document.querySelector('.album-contributors') && document.querySelectorAll('.track').length===1");
      await evaluate('history.back()');
      await wait("document.querySelectorAll('.album-search-results li').length===2");
      await command('Page.reload');
      await wait("document.querySelectorAll('.album-search-results li').length===2");
      await evaluate("location.hash='albums&q=202'");
      await wait("document.querySelector('[data-album-id=\"202\"]') && document.querySelectorAll('.album-search-results li').length===1");
    });
    let failed=false;
    await browser(async({evaluate,wait})=>{
      await evaluate("location.hash='albums'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
      await evaluate("[...document.querySelectorAll('#rows button')].find(b=>b.textContent==='Retry').click()");
      await wait("document.querySelectorAll('.album-search-results li').length===100");
    },{transform:(path,value)=>{if(path==='/album-search/0.json'&&!failed){failed=true;return false;}return value;}});
    await browser(async({evaluate,wait})=>{
      await evaluate("location.hash='albums'");
      await new Promise(resolve=>setTimeout(resolve,50));
      await evaluate("location.hash='genres'");
      await wait("document.querySelector('h1').textContent==='Genres' && document.querySelector('#content').getAttribute('aria-busy')==='false'");
      await new Promise(resolve=>setTimeout(resolve,350));
      assert.equal(await evaluate("document.querySelectorAll('.album-search-results').length"),0);
    },{delay:path=>path.startsWith('/album-search/')});
    await browser(async({evaluate,wait,requests})=>{
      assert.ok(await evaluate("[...document.querySelectorAll('[data-album-search]')].every(node=>node.hidden)"));
      await evaluate("location.hash='albums'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
      assert.ok(!requests.some(row=>row.request.url.includes('/album-search/')));
    },{transform:(path,value)=>{if(path==='/catalog.json')delete value.albums.search;return value;}});
  } finally {await rm(root,{recursive:true,force:true});}
});

test('album index validates IDs and searches normalized titles without merging collisions',async()=>{
  const source=await readFile(resolve('src/opennoise/static/fma-album-search.js'),'utf8');
  const {loadAlbumSearch,albumMatches}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const config={album_count:3,search:{revision:'fma-native-album-search-v1',columns:['album_id','title','track_count','artist_count'],row_count:3,shards:['album-search/0.json'],bytes:100}};
  const rows=await loadAlbumSearch(config,async()=>[[1,'Café',2,2],[2,'Cafe\u0301',1,1],[3,null,1,0]]);
  assert.deepEqual(albumMatches(rows,'CAFÉ').map(row=>row[0]),[1,2]);
  assert.deepEqual(albumMatches(rows,'3').map(row=>row[0]),[3]);
  assert.deepEqual(albumMatches(rows,'03'),[]);
  await assert.rejects(loadAlbumSearch(config,async()=>[[1,'A',1,1],[1,'B',1,1],[3,null,1,0]]));
  await assert.rejects(loadAlbumSearch({...config,search:{...config.search,shards:['https://invalid.example/index.json']}},async()=>{throw Error('must not fetch');}));
});
