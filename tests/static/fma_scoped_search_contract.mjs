import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, mkdir, readFile, readdir, rm, writeFile, copyFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import test from 'node:test';

// Synthetic native metadata only: no retained corpus, media or judgments.
let root;
const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const skip = !chromium;
async function helpers() {
  const source=await readFile(resolve('src/opennoise/static/fma-scoped-search.js'),'utf8');
  return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}

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
  root=await mkdtemp(join(tmpdir(),'scoped-search-fixture-'));
  const assets=resolve('src/opennoise/static');
  for(const name of await readdir(assets)) if(name.endsWith('.js')||name.endsWith('.css')||name==='fma-catalog.html') await copyFile(join(assets,name),join(root,name==='fma-catalog.html'?'index.html':name));
  const put=async(path,value)=>{const target=join(root,path);await mkdir(resolve(target,'..'),{recursive:true});await writeFile(target,JSON.stringify(value));};
  const ids=Array.from({length:1001},(_,i)=>i+1);
  const tracks=[...ids,1500].map(id=>[id,id===1001?null:[201,1500].includes(id)?'Café 音楽':'Shared title',id===1001?null:id===1?999:10,id===1500?[]:[1],0,'https://freemusicarchive.org/music/Fixture/'+id,id>=201&&id<=450?20:21,[]]);
  await put('catalog.json',{revision:'fma-source-static-v1',page_size:200,profile_shards:128,track_id_span:500,
    counts:{raw_tracks:1002,source_artists:1,missing_artist_records:2,observed_track_genres:1,unannotated_tracks:1},
    genres:[{genre_id:1,title:'Fixture genre',track_count:1001,parent_id:null,connections:[]},{genre_id:2,title:'Empty genre',track_count:0,parent_id:null,connections:[]}],
    licenses:[],albums:{revision:'fma-native-albums-v1',shards:128},
    track_search:{columns:['track_id','title','artist_id'],row_count:1002,shards:['track-search/0.json']}});
  await put('artist-index.json',{artists:[[10,'Known artist',1000,'source'],[999,'Track supplied name',1,'missing_source_artist_record','unanimous_track_artist_name'],[null,'Missing artist ID',1,'missing_source_artist_record']]});
  await put('track-search/0.json',tracks.map(row=>row.slice(0,3)));
  for(let page=0;page<6;page++) await put(`cohorts/genre-1/${page}.json`,{cohort:'genre-1',page,total:1001,track_ids:ids.slice(page*200,(page+1)*200)});
  for(let shard=0;shard<4;shard++) {
    const rows=tracks.filter(row=>Math.floor(row[0]/500)===shard);
    await put(`tracks/${shard}.json`,shard%2?{revision:'fma-track-url-prefix-v1',metadata_url_prefix:'https://freemusicarchive.org/music/',columns:['track_id','title','artist_id','genre_ids','license_id','metadata_url_suffix','album_id','missing_fields'],tracks:rows.map(row=>row.map((value,index)=>index===5?value.replace('https://freemusicarchive.org/music/',''):value))}:{tracks:rows});
  }
  for(const [id,name,members] of [[10,'Known artist',ids.filter(id=>id>1&&id<1001)],[999,'Track supplied name',[1]],[null,'Missing artist ID',[1001]]]) {
    const shard=(id??0)%128;
    await put(`artists/${shard}.json`,{shard,artists:{[id===null?'None':id]:{artist_id:id,name,track_ids:members,track_genre_counts:[],albums:[],status:id===10?'source':'missing_source_artist_record',name_source:id===999?'unanimous_track_artist_name':null}}});
  }
  await put('albums/20.json',{shard:20,albums:{20:{album_id:20,title:'Fixture album',artist_ids:[10],track_ids:ids.filter(id=>id>=201&&id<=450)}}});
}

const currentIds=evaluate=>evaluate("[...document.querySelectorAll('.track')].map(row=>Number(row.dataset.trackId))");
async function visit(state,hash,heading) {
  await state.evaluate(`location.hash=${JSON.stringify(hash)}`);
  await state.wait(`location.hash===${JSON.stringify('#'+hash)} && document.querySelector('main').getAttribute('aria-busy')==='false' && document.querySelector('h1').textContent.includes(${JSON.stringify(heading)})`);
}

 test('synthetic context search preserves source scopes, pagination, Unicode and native missing IDs', {skip,timeout:60000},async()=>{
  await fixture();
  try {await browser(async state=>{
    const {evaluate,wait,requests,command}=state;
    await visit(state,'genre=1','Fixture genre');
    assert.equal(await evaluate("document.querySelector('#scope').value"),'context');
    assert.equal(requests.some(row=>row.request.url.includes('/track-search/')),false,'blank context keeps index lazy');
    assert.equal(requests.filter(row=>row.request.url.includes('/cohorts/genre-1/')).length,1,'blank context browses just one page');
    await evaluate("document.querySelector('#query').value='Ｃａｆé 音楽';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))");
    await wait("document.querySelector('#status').textContent.startsWith('1 matching of 1,001')");
    assert.deepEqual(await currentIds(evaluate),[201],'same title outside this genre is excluded');
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).get('genre')"),'1');
    await evaluate("document.querySelector('#query').focus()");
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown'});
    assert.equal(await evaluate("document.activeElement.getAttribute('href')"),'#track=201');
    await evaluate("document.querySelector('#search-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");
    await wait("location.hash==='#track=201' && document.querySelector('main').getAttribute('aria-busy')==='false'");
    assert.equal(await evaluate("document.querySelector('#scope').value"),'tracks');
    assert.equal(await evaluate("document.querySelector('#query').value"),'');
    await evaluate('history.back()');
    await wait("document.querySelector('#scope').value==='context' && document.querySelector('#status').textContent.startsWith('1 matching of')");
    await command('Page.reload');
    await wait("document.querySelector('#status')?.textContent.startsWith('1 matching of')");
    assert.deepEqual(await currentIds(evaluate),[201]);
    await visit(state,'genre=1&q=Shared&page=4','Fixture genre');
    await wait("document.querySelectorAll('.track').length===199");
    assert.equal((await currentIds(evaluate)).at(-1),1000);
    await evaluate("document.querySelector('#query').value='#1001';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))");
    await wait("document.querySelector('.track')?.dataset.trackId==='1001'");
    assert.equal(await evaluate("new URLSearchParams(location.hash.slice(1)).has('page')"),false);
    await visit(state,'genre=1&q=%231500','Fixture genre');
    assert.deepEqual(await currentIds(evaluate),[]);
    await visit(state,'genre=2&q=Shared','Empty genre');
    assert.ok(await evaluate("document.querySelector('#status').textContent.startsWith('0 matching of 0')"));
    await visit(state,'artist=999&q=Track%20supplied','Track supplied name');
    assert.deepEqual(await currentIds(evaluate),[1]);
    assert.ok(await evaluate("document.querySelector('#status').textContent.includes('Artist record is missing')"));
    await visit(state,'artist=null&q=%231001','Missing artist ID');
    assert.deepEqual(await currentIds(evaluate),[1001]);
    await visit(state,'album=20&q=Shared&page=1','Fixture album');
    assert.equal((await currentIds(evaluate)).length,49);
    assert.equal((await currentIds(evaluate)).at(-1),450);
    assert.ok(await evaluate("document.querySelector('#status').textContent.includes('not album ownership')"));
    await evaluate("document.querySelector('#query').focus();document.querySelector('#query').value='';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))");
    await wait("location.hash==='#album=20' && document.querySelector('.album-contributors')");
    assert.equal((await currentIds(evaluate)).length,200);
    assert.equal(await evaluate('document.activeElement.id'),'query','clearing context query preserves focus for the next search');
    await command('Input.insertText',{text:'Café'});
    await wait("document.querySelector('#status').textContent.startsWith('1 matching of 250')");
    await evaluate("document.querySelector('#scope').value='tracks';document.querySelector('#scope').dispatchEvent(new Event('change'))");
    await wait("location.hash.startsWith('#tracks') && document.querySelectorAll('.track').length===2");
    assert.deepEqual(await currentIds(evaluate),[201,1500],'explicit global scope includes the previously excluded title');
    for(const hash of ['genre=999&q=Shared','artist=777&q=Shared','album=999&q=Shared']) {
      await visit(state,hash,'Catalog unavailable');
    }
    for (const [context,name] of [['genre=1','Fixture genre'],['artist=999','Track supplied name'],['album=20','Fixture album']]) {
      await visit(state,context+'&q=Shared',name);
      await evaluate("document.querySelector('#query').focus();document.querySelector('#query').value='';document.querySelector('#query').dispatchEvent(new Event('input',{bubbles:true}))");
      await wait(`location.hash==='#${context}' && document.querySelector('main').getAttribute('aria-busy')==='false'`);
      assert.equal(await evaluate('document.activeElement.id'),'query',context+' keeps focus when cleared');
      await command('Input.insertText',{text:'Shared'});
      await wait("document.querySelector('#status').textContent.includes('matching of') && document.querySelector('main').getAttribute('aria-busy')==='false'");
      assert.equal(await evaluate('document.activeElement.id'),'query');
    }
    await visit(state,'genre=1&q=%23501','Fixture genre');
    assert.deepEqual(await currentIds(evaluate),[501]);
    assert.equal(await evaluate("document.querySelector('.metadata a').getAttribute('href')"),'https://freemusicarchive.org/music/Fixture/501');
    await command('Emulation.setDeviceMetricsOverride',{width:320,height:740,deviceScaleFactor:1,mobile:true});
    assert.equal(await evaluate('innerWidth'),320);
    assert.ok(await evaluate('document.documentElement.scrollWidth<=320'));
  });} finally {await rm(root,{recursive:true,force:true});}
});

test('complete genre membership rejects bad pages and stops obsolete batches',async()=>{
  const {scopeMembership,trackMatcher,validateScopedTracks}=await helpers();
  const state={kind:'genre',id:1};
  const catalog={counts:{raw_tracks:12},page_size:2};
  const genres=new Map([[1,{genre_id:1,title:'Synthetic',track_count:12}]]);
  const valid=path=>{const page=Number(path.split('/').at(-1).split('.')[0]);return {cohort:'genre-1',page,total:12,track_ids:[page*2+1,page*2+2]};};
  let active=0,peak=0,calls=0;
  const result=await scopeMembership({state,catalog,genres,current:()=>true,evict:()=>{},json:async path=>{calls++;active++;peak=Math.max(peak,active);await Promise.resolve();active--;return valid(path);}});
  assert.equal(peak,4);assert.equal(calls,6);assert.deepEqual(result.ids,Array.from({length:12},(_,i)=>i+1));
  calls=0;
  assert.equal(await scopeMembership({state,catalog,genres,current:()=>calls<4,evict:()=>{},json:async path=>{calls++;return valid(path);}}),null);
  assert.equal(calls,4,'obsolete work never launches the second batch');
  for(const mutate of [v=>v.track_ids.reverse(),v=>v.track_ids.pop(),v=>v.track_ids=[1,2],v=>v.total=11,v=>v.page=0,v=>v.cohort='genre-2',v=>v.track_ids=[0,4]]) {
    const evicted=[];
    await assert.rejects(scopeMembership({state,catalog,genres,current:()=>true,evict:path=>evicted.push(path),json:async path=>{const value=valid(path);if(value.page===1)mutate(value);return value;}}));
    assert.ok(evicted.includes('cohorts/genre-1/1.json'));
  }
  assert.equal(trackMatcher('#12',new Map())([12,null,null]),true);
  assert.equal(trackMatcher('Ｃａｆé',new Map())([12,'Café',1]),true);
  assert.throws(()=>validateScopedTracks([[12,'x',1,[2],null,null,4]],state,{ids:[12]}));
});

test('synthetic malformed genre pages retry atomically and late context reads cannot replace navigation', {skip,timeout:60000},async()=>{
  await fixture();
  let broken=true,release;
  const delayed={path:'/cohorts/genre-1/0.json',promise:new Promise(resolve=>{release=resolve;})};
  try {
    await browser(async state=>{
      const {evaluate,wait,requests}=state;
      await evaluate("location.hash='genre=1&q=Shared'");
      for(let attempt=0;!requests.some(row=>row.request.url.includes('/cohorts/genre-1/3.json'));attempt++) {assert.ok(attempt<250);await new Promise(resolve=>setTimeout(resolve,20));}
      await visit(state,'artist=999&q=Shared','Track supplied name');
      release();
      await wait("performance.getEntriesByType('resource').some(row=>row.name.endsWith('/cohorts/genre-1/0.json'))");
      await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
      assert.deepEqual(await currentIds(evaluate),[1]);
      assert.equal(requests.some(row=>/cohorts\/genre-1\/[45]\.json/.test(row.request.url)),false);
      await visit(state,'genre=1&q=Shared','Catalog unavailable');
      assert.deepEqual(await currentIds(evaluate),[]);
      broken=false;
      await evaluate("[...document.querySelectorAll('#rows button')].find(row=>row.textContent==='Retry').click()");
      await wait("document.querySelector('#status').textContent.startsWith('999 matching of 1,001') && document.querySelectorAll('.track').length===200");
      assert.ok(requests.filter(row=>row.request.url.endsWith('/cohorts/genre-1/1.json')).length>=2);
    },{delayed,transform:(path,value)=>{if(broken&&path==='/cohorts/genre-1/1.json')value.total=1000;return value;}});
  } finally {release();await rm(root,{recursive:true,force:true});}
});

test('synthetic scoped Retry clears invalid memberships and incomplete track shards', {skip,timeout:60000},async()=>{
  await fixture();
  let wrongMember=true,missingTrack=true;
  try {
    await browser(async state=>{
      const {evaluate,wait,requests}=state;
      await visit(state,'genre=2&q=Shared','Empty genre');
      assert.equal(requests.some(row=>row.request.url.includes('/track-search/')),false,'empty source cohort never loads the full search index');
      await visit(state,'artist=999&q=Shared','Catalog unavailable');
      assert.deepEqual(await currentIds(evaluate),[]);
      assert.ok(await evaluate("document.querySelector('#status').textContent.includes('omits source membership')"));
      wrongMember=false;
      await evaluate("[...document.querySelectorAll('#rows button')].find(row=>row.textContent==='Retry').click()");
      await wait("document.querySelector('.track')?.dataset.trackId==='1'");
      assert.equal(requests.filter(row=>row.request.url.endsWith('/artists/103.json')).length,2,'Retry rereads a corrected valid-shaped membership');
      await visit(state,'genre=1&q=%23501','Catalog unavailable');
      assert.deepEqual(await currentIds(evaluate),[]);
      assert.ok(await evaluate("document.querySelector('#status').textContent.includes('Track shard is incomplete')"));
      missingTrack=false;
      await evaluate("[...document.querySelectorAll('#rows button')].find(row=>row.textContent==='Retry').click()");
      await wait("document.querySelector('.track')?.dataset.trackId==='501'");
      assert.equal(requests.filter(row=>row.request.url.endsWith('/tracks/1.json')).length,2,'Retry rereads a corrected missing selected track');
    },{transform:(path,value)=>{
      if(wrongMember&&path==='/artists/103.json')value.artists['999'].track_ids=[9999];
      if(missingTrack&&path==='/tracks/1.json')value.tracks=value.tracks.filter(row=>row[0]!==501);
      return value;
    }});
  } finally {await rm(root,{recursive:true,force:true});}
});
