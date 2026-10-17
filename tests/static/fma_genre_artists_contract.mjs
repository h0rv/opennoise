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
      if (transform && path === '/genre-artists/1/0.json' && transform(path, null) === false) { response.statusCode = 503; response.end(); return; }
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

async function genreArtistFixture() {
  await fixture();
  const path=join(root,'catalog.json');
  const catalog=JSON.parse(await readFile(path));
  catalog.counts.raw_tracks=202;
  catalog.genres[0].track_count=202;
  catalog.genres[1].track_count=0;
  catalog.genre_artists={revision:'fma-genre-track-artists-v1',page_size:100,genres:[[1,2,202],[2,0,0]],pair_count:2};
  await writeFile(path,JSON.stringify(catalog));
  await mkdir(join(root,'genre-artists/1'),{recursive:true});
  await mkdir(join(root,'genre-artists/2'),{recursive:true});
  await writeFile(join(root,'genre-artists/1/0.json'),JSON.stringify({genre_id:1,page:0,total:2,artists:[[999,201],[null,1]]}));
  await writeFile(join(root,'genre-artists/2/0.json'),JSON.stringify({genre_id:2,page:0,total:0,artists:[]}));
  await writeFile(join(root,'artist-index.json'),JSON.stringify({artists:[[null,'Missing artist ID',1,'missing_source_artist_record'],[999,'LongUnbrokenTrackSuppliedArtistNameForNarrowViewportTesting',201,'missing_source_artist_record','unanimous_track_artist_name']]}));
  await mkdir(join(root,'artists'),{recursive:true});
  await writeFile(join(root,'artists/103.json'),JSON.stringify({shard:103,artists:{'999':{artist_id:999,name:'Track supplied',name_source:'unanimous_track_artist_name',status:'missing_source_artist_record',track_ids:Array.from({length:201},(_,i)=>i+1),track_genre_counts:[{genre_id:1,track_count:201}],albums:[]}}}));
  await writeFile(join(root,'artists/0.json'),JSON.stringify({shard:0,artists:{'None':{artist_id:null,name:'Missing artist ID',status:'missing_source_artist_record',track_ids:[202],track_genre_counts:[{genre_id:1,track_count:1}],albums:[]}}}));
  await writeFile(join(root,'tracks/0.json'),JSON.stringify({tracks:Array.from({length:202},(_,i)=>[i+1,'Recording '+i,i===201?null:999,[1,1],null,null,null])}));
}

test('synthetic genre artist discovery preserves exact intersections, null identity and navigation', {skip,timeout:60000}, async()=>{
  await genreArtistFixture();
  try{
    await browser(async({evaluate,wait,requests,command})=>{
      assert.ok(!requests.some(row=>row.request.url.includes('/genre-artists/')));
      await evaluate("location.hash='genre-artists=1'");
      await wait("document.querySelectorAll('.genre-artist-results li').length===2");
      assert.equal(await evaluate("document.querySelector('.genre-artist-results li').dataset.artistId"),'999');
      assert.match(await evaluate("document.querySelector('.genre-artist-results small').textContent"),/201.*Track-supplied/);
      for(const width of [390,320]){
        await command('Emulation.setDeviceMetricsOverride',{width,height:700,deviceScaleFactor:1,mobile:true});
        assert.equal(await evaluate('innerWidth'),width);
      }
      await evaluate("document.querySelector('.genre-artist-results a').click()");
      await wait("document.querySelectorAll('.track').length===200");
      assert.match(await evaluate("document.querySelector('#status').textContent"),/201 recordings.*Track-supplied name/);
      await evaluate("[...document.querySelectorAll('#pages button')].find(b=>b.textContent==='Next').click()");
      await wait("document.querySelectorAll('.track').length===1 && document.querySelector('.track').dataset.trackId==='201'");
      await evaluate('history.back()');
      await wait("document.querySelectorAll('.track').length===200");
      await command('Page.reload');
      await wait("document.querySelectorAll('.track').length===200");
      await evaluate("location.hash='artist=null&genre=1'");
      await wait("document.querySelectorAll('.track').length===1 && document.querySelector('.track').dataset.trackId==='202'");
      await evaluate("location.hash='artist=999&genre=2'");
      await wait("document.querySelector('#status').textContent.startsWith('0 recordings')");
      await evaluate("location.hash='genre-artists=2'");
      await wait("document.querySelector('#status').textContent.startsWith('0 source artist groups')");
      await evaluate("location.hash='artist=&genre=1'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
    });
    let failed=false;
    await browser(async({evaluate,wait})=>{
      await evaluate("location.hash='genre-artists=1'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
      await evaluate("[...document.querySelectorAll('#rows button')].find(b=>b.textContent==='Retry').click()");
      await wait("document.querySelectorAll('.genre-artist-results li').length===2");
    },{transform:(path,value)=>{if(path==='/genre-artists/1/0.json'&&!failed){failed=true;return false;}return value;}});
    await browser(async({evaluate,wait})=>{
      await evaluate("location.hash='artist=999&genre=1'");
      await new Promise(resolve=>setTimeout(resolve,50));
      await evaluate("location.hash='genres'");
      await wait("document.querySelector('h1').textContent==='Genres'");
      await new Promise(resolve=>setTimeout(resolve,350));
      assert.equal(await evaluate("document.querySelectorAll('.track').length"),0);
    },{delay:path=>path.startsWith('/tracks/')});
    await browser(async({evaluate,wait})=>{
      await evaluate("location.hash='genre-artists=1'");
      await wait("document.querySelector('h1').textContent==='Catalog unavailable'");
      assert.match(await evaluate("document.querySelector('#status').textContent"),/not attached/);
    },{transform:(path,value)=>{if(path==='/catalog.json')delete value.genre_artists;return value;}});
  }finally{await rm(root,{recursive:true,force:true});}
});

test('profile scan checks every recording, limits batches, abstains stale work and rejects false counts', async()=>{
  const source=await readFile(resolve('src/opennoise/static/fma-genre-artists.js'),'utf8');
  const {artistGenreTracks,genreArtistRoute}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  const profile={artist_id:1,track_ids:Array.from({length:41},(_,i)=>i+1),track_genre_counts:[{genre_id:2,track_count:41}]};
  const batches=[];
  const args={profile,artist:1,genre:2,rawTrackCount:41,current:()=>true,tracksFor:async ids=>{batches.push(ids.length);return ids.map(id=>[id,'Title',1,[2,2]]);}};
  assert.equal((await artistGenreTracks(args)).length,41);
  assert.deepEqual(batches,[20,20,1]);
  await assert.rejects(artistGenreTracks({...args,profile:{...profile,track_genre_counts:[{genre_id:2,track_count:40}]}}),/count mismatch/);
  await assert.rejects(artistGenreTracks({...args,tracksFor:async ids=>ids.map(id=>[id,'Title',9,[2]])}),/identity mismatch/);
  let calls=0,current=true;
  assert.equal(await artistGenreTracks({...args,current:()=>current,tracksFor:async ids=>{calls++;current=false;return ids.map(id=>[id,'T',1,[2]]);}}),null);
  assert.equal(calls,1);
  assert.deepEqual(genreArtistRoute(new URLSearchParams('artist=null&genre=2')),{kind:'artist-genre',id:2,artist:null,page:0});
  for(const query of ['artist=&genre=2','artist=00&genre=2','genre-artists=1&artist=1','genre-artists=2&page=-1'])assert.equal(genreArtistRoute(new URLSearchParams(query)).kind,'invalid');
});
