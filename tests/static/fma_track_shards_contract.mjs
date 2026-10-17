import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, mkdir, readFile, readdir, rm, writeFile, copyFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

// Synthetic metadata only. No retained catalog or audio is loaded by these contracts.
let root;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const revision = 'fma-track-url-prefix-v1';
const columns = ['track_id','title','artist_id','genre_ids','license_id','metadata_url_suffix','album_id','missing_fields'];
const prefix = 'https://freemusicarchive.org/music/';
const encoded = (id, suffix = 'Fixture_artist/Fixture_album/Track') => ({
  revision, metadata_url_prefix:prefix, columns:[...columns],
  tracks:[[id,'Synthetic track '+id,10,[1],0,suffix,20,[]]],
});

async function codec() {
  const source = await readFile(resolve('src/opennoise/static/fma-track-shards.js'), 'utf8');
  return (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).decodeTrackShard;
}

function freeze(value) {
  if (value && typeof value === 'object') {
    for (const member of Object.values(value)) freeze(member);
    Object.freeze(value);
  }
  return value;
}

test('track prefix codec preserves exact metadata, nulls and legacy rows without mutation', async () => {
  const decode = await codec();
  for (const base of ['http://freemusicarchive.org/music/','https://freemusicarchive.org/music/','http://www.freemusicarchive.org/music/','https://www.freemusicarchive.org/music/']) {
    const shard = encoded(501, 'Artist/%E2%99%AB/Track?x=1&x=2#part');
    shard.metadata_url_prefix = base;
    shard.tracks.push([502,null,null,[],null,null,null,['title','artist_id']]);
    const before = structuredClone(shard);
    freeze(shard);
    const actual = decode(shard);
    const expected = structuredClone(before.tracks);
    expected[0][5] = base + before.tracks[0][5];
    assert.deepEqual(actual,expected);
    assert.deepEqual(shard,before);
    assert.notEqual(actual[0],shard.tracks[0],'decoded URL belongs to a copied row');
    assert.equal(decode(shard)[0][5],expected[0][5],'repeat decode does not double-prefix cached rows');
  }
  const legacy = {tracks:[[1,'Old fixture',10,[1],0,prefix+'Original',null]]};
  assert.deepEqual(decode(freeze(legacy)),legacy.tracks,'older seven-column shards remain supported');
  const currentLegacy = {columns:columns.map(name=>name==='metadata_url_suffix'?'metadata_url':name),tracks:[[1,'Legacy eight columns',10,[1],0,null,null,[]]]};
  assert.deepEqual(decode(freeze(currentLegacy)),currentLegacy.tracks);
  assert.deepEqual(decode(encoded(503,''))[0][5],prefix,'literal empty suffix preserves the source URL');
});

test('track prefix codec rejects unknown and malformed encoded formats', async () => {
  const decode = await codec();
  const invalid = [
    value => {value.revision='fma-track-url-prefix-v999';},
    value => {value.revision=null;},
    value => {delete value.revision;},
    value => {delete value.revision;delete value.metadata_url_prefix;},
    value => {delete value.metadata_url_prefix;},
    value => {value.metadata_url_prefix=null;},
    value => {value.metadata_url_prefix='https://example.org/music/';},
    value => {value.metadata_url_prefix='https://freemusicarchive.org.evil/music/';},
    value => {value.metadata_url_prefix='https://freemusicarchive.org/music';},
    value => {value.metadata_url_prefix='https://freemusicarchive.org/music/\n';},
    value => {value.metadata_url_prefix='HTTPS://freemusicarchive.org/music/';},
    value => {delete value.columns;},
    value => {value.columns[5]='metadata_url';},
    value => {value.columns.reverse();},
    value => {value.columns.push('extra');},
    value => {value.tracks=null;},
    value => {value.tracks[0]=null;},
    value => {value.tracks[0]={track_id:501};},
    value => {value.tracks[0].pop();},
    value => {value.tracks[0].push('extra');},
    value => {value.tracks[0][5]=false;},
    value => {value.tracks[0][5]=123;},
    value => {value.tracks[0][5]={url:'Track'};},
  ];
  for (const change of invalid) {
    const shard = encoded(501);
    change(shard);
    assert.throws(() => decode(shard),Error,JSON.stringify(shard));
  }
});

async function browser(operation, {transform = null, delayed = null} = {}) {
  const exportRoot = resolve(root);
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    const file = resolve(exportRoot, '.' + (path === '/' ? '/index.html' : path));
    if (!file.startsWith(exportRoot + sep)) { response.statusCode = 403; response.end(); return; }
    try {
      if (delayed?.path === path) await delayed.promise;
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
    assert.ok(!requests.some(row => /artist-index|\/tracks\/|\/cohorts\/|\/artists\//.test(row.request.url)), 'initial catalog must not load track shards');
    await operation({evaluate, wait, command, requests, url});
    assert.deepEqual(errors, []); assert.ok(requests.every(row => new URL(row.request.url).origin === new URL(url).origin && row.type !== 'Media'), 'no external provider or audio requests');
  } finally {
    socket?.close(); child.kill('SIGKILL'); await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve)); await rm(profile, {recursive: true, force: true}); await new Promise(resolve => server.close(resolve));
  }
}

async function fixture() {
  root = await mkdtemp(join(tmpdir(),'track-codec-fixture-'));
  const assets=resolve('src/opennoise/static');
  for (const name of await readdir(assets)) {
    if (name.endsWith('.js') || name.endsWith('.css') || name === 'fma-catalog.html') {
      await copyFile(join(assets,name),join(root,name === 'fma-catalog.html' ? 'index.html' : name));
    }
  }
  const put=async (path,value) => {
    const file=join(root,path);
    await mkdir(resolve(file,'..'),{recursive:true});
    await writeFile(file,JSON.stringify(value));
  };
  await put('catalog.json',{
    revision:'fma-source-static-v1',page_size:200,profile_shards:128,track_id_span:500,
    genres:[{genre_id:1,title:'Synthetic genre',track_count:5,parent_id:null,connections:[]}],
    counts:{raw_tracks:5,source_artists:1,missing_artist_records:0,observed_track_genres:1,unannotated_tracks:0},
    licenses:[['Synthetic license','https://example.org/license']],
  });
  await put('artist-index.json',{artists:[[10,'Synthetic artist',5,'source']]});
  await put('tracks/0.json',{tracks:[[1,'Legacy track',10,[1],0,prefix+'Legacy',null,[]]]});
  const mixed=encoded(501,'Encoded%20artist/Track?test=1#part');
  mixed.tracks.push([502,'No metadata URL',10,[1],0,null,null,[]]);
  await put('tracks/1.json',mixed);
  await put('tracks/2.json',encoded(1001));
  await put('tracks/3.json',encoded(1501));
}

test('synthetic catalog mixes shards, retries malformed content and discards stale routes', {skip:!chromium,timeout:60000}, async () => {
  await fixture();
  let release;
  const delayed={path:'/tracks/3.json',promise:new Promise(resolve=>{release=resolve;})};
  let broken=true;
  try {
    await browser(async ({evaluate,wait,command,requests}) => {
      const visit=async id => {
        await evaluate(`location.hash='track=${id}'`);
        await wait(`document.querySelector('.track')?.dataset.trackId==='${id}' && document.querySelector('main').getAttribute('aria-busy')==='false'`);
      };
      for (const id of [1,501,502,501,1,501]) {
        await visit(id);
        const actual=await evaluate("document.querySelector('.track .metadata a')?.getAttribute('href') ?? null");
        const expected=id===502?null:prefix+(id===1?'Legacy':'Encoded%20artist/Track?test=1#part');
        assert.equal(actual,expected);
        assert.equal(await evaluate("document.querySelectorAll('.track').length"),1);
      }
      assert.equal(requests.filter(row=>row.request.url.endsWith('/tracks/1.json')).length,1,'valid encoded shards stay cached without mutation');
      await evaluate("location.hash='track=1001'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
      assert.equal(await evaluate("document.querySelectorAll('.track').length"),0);
      broken=false;
      await evaluate("[...document.querySelectorAll('#rows button')].find(button=>button.textContent==='Retry').click()");
      await wait("document.querySelector('.track')?.dataset.trackId==='1001'");
      assert.equal(requests.filter(row=>row.request.url.endsWith('/tracks/2.json')).length,2,'malformed decoded content must be evicted for Retry');
      await evaluate("location.hash='track=1501'");
      // Wait for the actual delayed request, not a timing-dependent sleep.
      for (let attempt=0; !requests.some(row=>row.request.url.endsWith('/tracks/3.json')); attempt++) {
        assert.ok(attempt<250,'delayed shard requested');
        await new Promise(resolve=>setTimeout(resolve,20));
      }
      await visit(1);
      release();
      await wait("performance.getEntriesByType('resource').some(entry=>entry.name.endsWith('/tracks/3.json'))");
      await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
      assert.equal(await evaluate("location.hash + ':' + document.querySelector('.track')?.dataset.trackId"),'#track=1:1','late encoded shard must not replace the current route');
      assert.equal(await evaluate("document.querySelector('h1').textContent"),'Legacy track');
      // Revisit the delayed shard to ensure its settled response is available before checking history.
      await visit(1501);
      await evaluate('history.back()');
      await wait("location.hash==='#track=1' && document.querySelector('.track')?.dataset.trackId==='1'");
      await command('Page.reload');
      await wait("document.querySelector('.track')?.dataset.trackId==='1'");
      assert.equal(await evaluate("document.querySelector('.track .metadata a').getAttribute('href')"),prefix+'Legacy');
      assert.equal(await evaluate("document.querySelectorAll('audio,[data-playback]:not([hidden])').length"),0);
    },{delayed,transform:(path,value)=>{
      if(path==='/tracks/2.json'&&broken)value.columns[5]='wrong';
      return value;
    }});
  } finally {
    release();
    await rm(root,{recursive:true,force:true});
  }
});
